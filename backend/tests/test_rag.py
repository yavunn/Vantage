"""RAG katmanı: chunking, retrieval, yetki ve "bilmiyorum" davranışı.

Buradaki asıl risk halüsinasyondur: zayıf ya da boş bağlamla LLM'e gidilirse
model boşluğu kendi genel bilgisiyle doldurur ve sistem, kaynağı olmayan bir
cevabı kaynaklıymış gibi sunar. O yüzden "LLM ÇAĞRILMIYOR" testi bu dosyanın
en önemli testidir.

İkinci risk takım sızıntısı: bir takımın ham kaydı başka takımın cevabında
görünmemeli. Üçüncüsü kişi sızıntısı: chunk metnine isim girmemeli.

Testler ağa çıkmaz — HashEmbedding + InMemoryIndex ile uçtan uca çalışır.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import days_ago

# --- yardımcılar --------------------------------------------------------------

class _FakeAdvisor:
    """Çağrıldı mı diye sayar; içerik üretmez."""

    def __init__(self, reply: str = "Cevap [1]"):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def advise(self, team_name: str, metrics_block: str) -> str:
        return self.reply

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


def _enable_rag(**overrides) -> None:
    """Test config'ine rag bloğu yazar (embedding: hash → ağsız)."""
    from app.core.config import active_config_path, reset_config_cache

    path = active_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rag = {
        "enabled": True,
        "embedding": {"provider": "hash"},
        "chunk": {"words": 400, "overlap": 60},
        "retrieval": {"top_k": 8, "min_score": 0.05},
        "index": "auto",
    }
    rag.update(overrides)
    raw["rag"] = rag
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    reset_config_cache()


def _seed(session, team_name="Takım A", repo_name="repo-a"):
    from app.models import Repo, Team

    team = Team(name=team_name)
    session.add(team)
    session.flush()
    repo = Repo(name=repo_name, team_id=team.id)
    session.add(repo)
    session.flush()
    return team, repo


def _index(session, cfg):
    from app.services.rag.embedding import HashEmbedding
    from app.services.rag.indexer import reindex

    return reindex(session, cfg, HashEmbedding())


# --- chunking -----------------------------------------------------------------

def test_commit_chunku_mesaj_ve_dosyalari_tasir_ismi_tasimaz(session):
    from app.core.config import get_config
    from app.models import Commit, Developer
    from app.services.rag.chunker import build_chunks

    _enable_rag()
    team, repo = _seed(session)
    dev = Developer(external_ids={"git": "ayse@x.com"}, display_name="Ayşe Yılmaz")
    session.add(dev)
    session.flush()
    session.add(Commit(
        repo_id=repo.id, sha="abc", author_id=dev.id, committed_at=days_ago(2),
        message="fix(auth): token yenileme hatasi",
        changed_files=["app/auth.py", "tests/test_auth.py"],
    ))
    session.commit()

    chunks = build_chunks(session, get_config())

    assert len(chunks) == 1
    content = chunks[0].content
    assert "token yenileme" in content
    assert "app/auth.py" in content
    # İlke E: kişi adı chunk'a GİRMEZ
    assert "Ayşe" not in content and "ayse@x.com" not in content
    assert chunks[0].team_id == team.id


def test_task_chunku_gecis_zincirini_tasir(session):
    from app.core.config import get_config
    from app.models import Task, TaskStatusTransition
    from app.services.rag.chunker import build_chunks

    _enable_rag()
    team, _ = _seed(session)
    task = Task(source="trello", external_id="c1", team_id=team.id,
                title="Trello entegrasyonu", status="DONE", created_at=days_ago(10))
    session.add(task)
    session.flush()
    session.add_all([
        TaskStatusTransition(task_id=task.id, from_status=None,
                             to_status="BACKLOG", changed_at=days_ago(10)),
        TaskStatusTransition(task_id=task.id, from_status="BACKLOG",
                             to_status="DONE", changed_at=days_ago(4)),
    ])
    session.commit()

    content = next(c.content for c in build_chunks(session, get_config())
                   if c.source_kind == "task")

    assert "Trello entegrasyonu" in content
    assert "BACKLOG" in content and "DONE" in content
    assert "6 gün" in content


def test_uzun_metin_ortusmeli_bolunur():
    from app.services.rag.chunker import split_words

    text = " ".join(str(i) for i in range(100))

    parts = split_words(text, words=40, overlap=10)

    assert len(parts) > 1
    # Örtüşme: bir parçanın kuyruğu sonrakinin başında olmalı — sert kesim
    # bir cümlenin anlamını ikiye bölerdi.
    tail = parts[0].split()[-10:]
    assert tail == parts[1].split()[:10]


# --- indeksleme ---------------------------------------------------------------

def test_degismeyen_kayit_yeniden_gomulmez(session):
    from app.core.config import get_config
    from app.models import Commit

    _enable_rag()
    _, repo = _seed(session)
    session.add(Commit(repo_id=repo.id, sha="abc", committed_at=days_ago(1),
                       message="ilk commit", changed_files=["a.py"]))
    session.commit()
    cfg = get_config()

    first = _index(session, cfg)
    second = _index(session, cfg)

    assert first["embedded"] == 1 and first["skipped"] == 0
    assert second["embedded"] == 0 and second["skipped"] == 1


def test_kaynaktan_silinen_kayit_indeksten_dusulur(session):
    from app.core.config import get_config
    from app.models import Commit, DocChunk

    _enable_rag()
    _, repo = _seed(session)
    commit = Commit(repo_id=repo.id, sha="abc", committed_at=days_ago(1),
                    message="silinecek commit", changed_files=["a.py"])
    session.add(commit)
    session.commit()
    cfg = get_config()
    _index(session, cfg)
    assert len(session.scalars(select(DocChunk)).all()) == 1

    session.delete(commit)
    session.commit()
    stats = _index(session, cfg)

    # Silinmiş kaydın metni cevaba kaynak gösterilirse sistem yalan söylemiş olur.
    assert stats["removed"] == 1
    assert session.scalars(select(DocChunk)).all() == []


def test_rag_kapaliyken_indeksleme_calismaz(session):
    from app.core.config import get_config
    from app.models import Commit, DocChunk

    _enable_rag(enabled=False)
    _, repo = _seed(session)
    session.add(Commit(repo_id=repo.id, sha="abc", committed_at=days_ago(1),
                       message="commit", changed_files=["a.py"]))
    session.commit()

    stats = _index(session, get_config())

    assert stats["chunks"] == 0
    assert session.scalars(select(DocChunk)).all() == []


# --- retrieval ----------------------------------------------------------------

def test_retrieval_ilgili_kaydi_getirir(session):
    from app.core.config import get_config
    from app.models import Commit
    from app.services.rag.embedding import HashEmbedding
    from app.services.rag.query import answer

    _enable_rag()
    team, repo = _seed(session)
    session.add_all([
        Commit(repo_id=repo.id, sha="a1", committed_at=days_ago(3),
               message="review sureci yavas, PR bekliyor", changed_files=["a.py"]),
        Commit(repo_id=repo.id, sha="b2", committed_at=days_ago(2),
               message="dokuman guncelleme", changed_files=["README.md"]),
    ])
    session.commit()
    cfg = get_config()
    _index(session, cfg)
    advisor = _FakeAdvisor()

    result = answer(session, cfg, "review sureci neden yavas",
                    team.id, HashEmbedding(), advisor)

    assert result.status == "ok"
    assert result.sources, "cevap kaynaksız dönmemeli"
    assert advisor.calls, "bağlam varken LLM çağrılmalı"
    # En yüksek skorlu kaynak ilgili commit olmalı
    assert "review" in advisor.calls[0][1]


def test_bos_retrievalda_llm_hic_cagrilmaz(session):
    """Bu dosyanın en önemli testi: bağlam yoksa model konuşmaz."""
    from app.core.config import get_config
    from app.services.rag.embedding import HashEmbedding
    from app.services.rag.query import answer

    _enable_rag()
    team, _ = _seed(session)
    session.commit()
    cfg = get_config()
    _index(session, cfg)  # hiç kayıt yok → indeks boş
    advisor = _FakeAdvisor()

    result = answer(session, cfg, "cycle time neden yukseldi",
                    team.id, HashEmbedding(), advisor)

    assert result.status == "insufficient_context"
    assert result.answer is None
    assert advisor.calls == [], "bağlam yokken LLM'e GİDİLMEMELİ"


def test_takim_filtresi_baska_takimin_kaydini_getirmez(session):
    from app.core.config import get_config
    from app.models import Commit
    from app.services.rag.embedding import HashEmbedding
    from app.services.rag.index import InMemoryIndex

    _enable_rag()
    team_a, repo_a = _seed(session, "Takım A", "repo-a")
    team_b, repo_b = _seed(session, "Takım B", "repo-b")
    session.add_all([
        Commit(repo_id=repo_a.id, sha="a1", committed_at=days_ago(2),
               message="gizli konu alfa", changed_files=["a.py"]),
        Commit(repo_id=repo_b.id, sha="b1", committed_at=days_ago(2),
               message="gizli konu alfa", changed_files=["b.py"]),
    ])
    session.commit()
    cfg = get_config()
    provider = HashEmbedding()
    _index(session, cfg)

    vec = provider.embed(["gizli konu alfa"])[0]
    hits = InMemoryIndex(session, provider.model).search(vec, 10, team_a.id)

    assert hits, "kendi takımının kaydı gelmeli"
    ids = {h.chunk_id for h in hits}
    from app.models import DocChunk
    b_ids = {
        row.id for row in session.scalars(
            select(DocChunk).where(DocChunk.team_id == team_b.id)
        )
    }
    assert ids.isdisjoint(b_ids), "başka takımın kaydı sızmamalı"


def test_farkli_modelle_gomulen_chunk_kiyaslanmaz(session):
    from app.core.config import get_config
    from app.models import Commit, DocChunk
    from app.services.rag.embedding import HashEmbedding
    from app.services.rag.index import InMemoryIndex

    _enable_rag()
    team, repo = _seed(session)
    session.add(Commit(repo_id=repo.id, sha="a1", committed_at=days_ago(1),
                       message="review sureci", changed_files=["a.py"]))
    session.commit()
    cfg = get_config()
    _index(session, cfg)
    # Model adı elle değiştirilir: sağlayıcı değişmiş gibi
    for row in session.scalars(select(DocChunk)):
        row.model = "baska-model"
    session.commit()

    provider = HashEmbedding()
    vec = provider.embed(["review sureci"])[0]
    hits = InMemoryIndex(session, provider.model).search(vec, 10, team.id)

    assert hits == [], "farklı modelin vektörü aynı uzayda değildir, kıyaslanmamalı"


# --- API uçları ---------------------------------------------------------------

@pytest.fixture()
def client(app_env):
    from app.main import app

    return TestClient(app)


def _user_token(client, session, email="calisan@x.com", role="user", developer_id=None):
    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email=email, password_hash=hash_password("parola1"), role=role,
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
        developer_id=developer_id,
    ))
    session.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "parola1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_ask_ucu_rag_kapaliyken_503(client, session):
    _enable_rag(enabled=False)
    team, _ = _seed(session)
    session.commit()
    token = _user_token(client, session, role="admin")

    r = client.post(f"/api/teams/{team.id}/ask", json={"question": "durum nedir"},
                    headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 503
    assert "rag.enabled" in r.json()["detail"]


def test_ask_ucu_baska_takima_403(client, session):
    from app.models import Developer, TeamMembership

    _enable_rag()
    team_a, _ = _seed(session, "Takım A", "repo-a")
    team_b, _ = _seed(session, "Takım B", "repo-b")
    dev = Developer(external_ids={"git": "x@x.com"}, display_name="X")
    session.add(dev)
    session.flush()
    session.add(TeamMembership(team_id=team_a.id, developer_id=dev.id, role="member"))
    session.commit()
    token = _user_token(client, session, developer_id=dev.id)
    h = {"Authorization": f"Bearer {token}"}

    r_b = client.post(f"/api/teams/{team_b.id}/ask", json={"question": "durum nedir"}, headers=h)

    assert r_b.status_code == 403


def test_ask_ucu_tokensiz_401(client, session):
    _enable_rag()
    team, _ = _seed(session)
    session.commit()

    r = client.post(f"/api/teams/{team.id}/ask", json={"question": "durum nedir"})

    assert r.status_code == 401


# --- takımsız kayıt: indekste ölü ağırlık olmamalı ---------------------------

def test_takimsiz_kayit_indekslenmez_ve_uyarilir(session):
    """Arama takım filtresini SQL'de uygular ve tek sorgu ucu her zaman gerçek
    bir takım id'si geçirir → team_id'si NULL olan chunk HİÇBİR sorguda
    getirilemez. Gömmek onu erişilebilir yapmaz, sadece maliyet ödetir ve
    'kayıtlar indekste var' yanılgısı üretir."""
    from app.core.config import get_config
    from app.models import Task

    _enable_rag()
    team, _repo = _seed(session)
    session.add_all([
        Task(source="trello", external_id="t1", team_id=team.id,
             title="takimli kart", status="DONE", created_at=days_ago(3)),
        Task(source="trello", external_id="t2", team_id=None,
             title="musvedde kart", status="Yapilacaklar", created_at=days_ago(3)),
    ])
    session.commit()

    stats = _index(session, get_config())

    assert stats["orphan_chunks"] == 1
    assert stats["chunks"] == 1
    assert any("hiçbir takıma bağlı" in w for w in stats["warnings"])


def test_indekste_kalmis_takimsiz_chunk_temizlenir(session):
    """Eski senkronlardan kalan takımsız chunk'lar bir sonraki indekslemede
    silinir — erişilemeyen kayıt indekste durmaya devam etmemeli."""
    from sqlalchemy import func, select

    from app.core.config import get_config
    from app.models import DocChunk, Task

    _enable_rag()
    team, _repo = _seed(session)
    session.add(Task(source="trello", external_id="t2", team_id=None,
                     title="musvedde", status="Yapilacaklar",
                     created_at=days_ago(3)))
    session.add(DocChunk(source_kind="task", source_id=999, chunk_index=0,
                         team_id=None, content="eski takimsiz chunk",
                         content_hash="x", model="hash", embedding=[0.1, 0.2]))
    session.commit()

    _index(session, get_config())

    kalan = session.scalar(
        select(func.count()).select_from(DocChunk).where(DocChunk.team_id.is_(None))
    )
    assert kalan == 0


# --- İŞ-24: bellek indeksinin ölçek davranışı ---------------------------------
# index.py'nin tasarım notu ölçeği yalnız yorumda ("birkaç yüz chunk")
# varsayıyordu; aşıldığında sistem hata vermiyor, SESSİZCE yavaşlıyordu.
# Sınır artık ölçüme dayanıyor (scripts/rag_scale_test.py).

def _chunk_ekle(session, team_id, n, model="test", boyut=8, ofset=0):
    from app.models import DocChunk

    for i in range(ofset, ofset + n):
        session.add(DocChunk(
            source_kind="task", source_id=i, chunk_index=0, team_id=team_id,
            content=f"kayıt {i}", content_hash=f"h{i}", model=model,
            embedding=[0.1 * ((i + j) % 5) for j in range(boyut)],
        ))
    session.commit()


def test_olcek_sinirini_asinca_uyari_uretilir(session, monkeypatch):
    from app.models import Team
    from app.services.rag import index as index_mod

    monkeypatch.setattr(index_mod, "MAX_MEMORY_CHUNKS", 5)
    index_mod.invalidate_cache()
    team = Team(name="T")
    session.add(team)
    session.commit()
    _chunk_ekle(session, team.id, 8)

    idx = index_mod.InMemoryIndex(session, model="test")
    hits = idx.search([0.1] * 8, 3, team.id)

    assert len(hits) == 3            # cevap YİNE üretilir
    assert idx.warnings              # ama sessiz kalmaz
    assert "pgvector" in idx.warnings[0]


def test_sinir_altinda_uyari_yok(session, monkeypatch):
    from app.models import Team
    from app.services.rag import index as index_mod

    monkeypatch.setattr(index_mod, "MAX_MEMORY_CHUNKS", 100)
    index_mod.invalidate_cache()
    team = Team(name="T")
    session.add(team)
    session.commit()
    _chunk_ekle(session, team.id, 8)

    idx = index_mod.InMemoryIndex(session, model="test")
    idx.search([0.1] * 8, 3, team.id)
    assert idx.warnings == []


def test_onbellek_indeks_tazelenince_gecersiz_olur(session):
    """Bayat vektörle cevap üretmek, silinmiş bir kaydı kaynak göstermektir."""
    from app.models import Team
    from app.services.rag import index as index_mod

    index_mod.invalidate_cache()
    team = Team(name="T")
    session.add(team)
    session.commit()
    _chunk_ekle(session, team.id, 3)

    idx = index_mod.InMemoryIndex(session, model="test")
    assert len(idx.search([0.1] * 8, 10, team.id)) == 3

    _chunk_ekle(session, team.id, 2, ofset=3)  # indeks büyüdü
    # Önbellek geçersiz kılınmazsa yeni kayıtlar görünmez.
    assert len(idx.search([0.1] * 8, 10, team.id)) == 3
    index_mod.invalidate_cache()
    assert len(idx.search([0.1] * 8, 10, team.id)) == 5
