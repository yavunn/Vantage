"""Ingest testleri: kirli veriye dayanıklılık + idempotentlik."""
from __future__ import annotations

from sqlalchemy import select

from tests.conftest import days_ago


def test_kimliksiz_commit_sistemi_cokertmez(session):
    from app.adapters.base import NormalizedCommit
    from app.models import Commit, Developer
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    n = ing.ingest_commits([
        NormalizedCommit(repo_name="r1", sha="abc", author_key=None,
                         committed_at=None, message=None, changed_files=None),
        NormalizedCommit(repo_name="r1", sha="def", author_key="a@x",
                         author_name="A", committed_at=days_ago(1)),
        NormalizedCommit(repo_name="r1", sha="", author_key="a@x"),  # kimliksiz → atlanır
    ])
    session.commit()
    assert n == 2
    rows = session.scalars(select(Commit)).all()
    assert len(rows) == 2
    # Kimliği belirsiz yazar için sahte developer üretilmez
    assert session.scalars(select(Developer)).all()[0].display_name == "A"
    assert rows[0].author_id is None


def test_ingest_idempotent(session):
    from app.adapters.base import NormalizedCommit
    from app.models import Commit
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    batch = [NormalizedCommit(repo_name="r1", sha="abc", committed_at=days_ago(2))]
    ing.ingest_commits(batch)
    ing.ingest_commits(batch)  # tekrar senkron
    session.commit()
    assert len(session.scalars(select(Commit)).all()) == 1


def test_ayni_kisi_farkli_kaynaklarda_tek_kayit(session):
    from app.adapters.base import NormalizedCommit, NormalizedTask
    from app.models import Developer
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    ing.ingest_commits([NormalizedCommit(repo_name="r1", sha="s1",
                                         author_key="ali@x", author_name="Ali")])
    # Farklı kaynak anahtarı → önce ayrı kayıt açılır (otomatik eşleme iddiası yok)
    ing.ingest_tasks([NormalizedTask(source="jira", external_id="J-1",
                                     assignee_key="ali.jira", assignee_name="Ali")])
    session.commit()
    devs = session.scalars(select(Developer)).all()
    assert len(devs) == 2  # kimlik eşleme bilinçli/manuel yapılır, uydurulmaz


def test_task_katman2_alanlari_bos_kalabilir(session):
    from app.adapters.base import NormalizedTask
    from app.models import Task
    from app.services.ingest import Ingestor

    ing = Ingestor(session)
    ing.ingest_tasks([NormalizedTask(source="fixture", external_id="T-1",
                                     team_name="A", status="To Do")])
    session.commit()
    task = session.scalars(select(Task)).one()
    assert task.estimate_hours is None
    assert task.due_date is None
    assert task.story_points is None


# --- İŞ-18: kaynakta kaybolan kayıt -------------------------------------------
# Ingest yalnız upsert yapıyordu. Canlı ölçüm: board'da 21 kart varken DB'de 26
# task vardı; 5'i artık çekilmeyen bir board'dan kalmıştı ve her senkronda
# "hiçbir takıma bağlı değil" uyarısı üretip metrik paydalarına giriyordu.

class _Kaynak:
    """Uyarı sözleşmesini uygulayan sahte task sağlayıcısı."""

    def __init__(self, tasks, warnings=None):
        self._tasks = tasks
        self.warnings = list(warnings or [])

    def fetch_tasks(self, since=None):
        return self._tasks

    def fetch_team_members(self):
        return []


def _task(ext_id, baslik="iş"):
    from app.adapters.base import NormalizedTask

    return NormalizedTask(source="trello", external_id=ext_id, title=baslik,
                          team_name="T", status="DEVELOPMENT")


def test_kaynakta_olmayan_kayit_kayip_damgalanir(session):
    from sqlalchemy import select

    from app.models import Task
    from app.services.ingest import run_ingest

    run_ingest(session, None, _Kaynak([_task("a"), _task("b")]))
    assert session.scalars(select(Task)).all().__len__() == 2

    # İkinci senkronda "b" kaynakta yok.
    stats = run_ingest(session, None, _Kaynak([_task("a")]))

    kayitlar = {t.external_id: t for t in session.scalars(select(Task))}
    assert kayitlar["b"].missing_since is not None, "kayıp kayıt damgalanmadı"
    assert kayitlar["a"].missing_since is None
    # KALICI SİLME YOK: kayıt duruyor.
    assert len(kayitlar) == 2
    assert stats["tasks_missing"] == 1
    assert any("kaynakta bulunamadı" in w for w in stats["warnings"])


def test_hatali_cekimde_damgalama_yapilmaz(session):
    """EN KRİTİK GÜVENLİK: kaynak hata verdiyse gelmeyen kayıt 'silinmiş' değil
    'okunamamış'tır. Damgalamak gerçek veri kaybı olurdu."""
    from sqlalchemy import select

    from app.models import Task
    from app.services.ingest import run_ingest

    run_ingest(session, None, _Kaynak([_task("a"), _task("b")]))
    run_ingest(session, None, _Kaynak([], warnings=["Trello board okunamadı (429)"]))

    kayitlar = {t.external_id: t for t in session.scalars(select(Task))}
    assert all(t.missing_since is None for t in kayitlar.values())


def test_geri_gelen_kayit_damgasi_temizlenir(session):
    from sqlalchemy import select

    from app.models import Task
    from app.services.ingest import run_ingest

    run_ingest(session, None, _Kaynak([_task("a"), _task("b")]))
    run_ingest(session, None, _Kaynak([_task("a")]))
    run_ingest(session, None, _Kaynak([_task("a"), _task("b")]))

    kayitlar = {t.external_id: t for t in session.scalars(select(Task))}
    assert kayitlar["b"].missing_since is None
    assert kayitlar["b"].last_seen_at is not None


def test_kayip_kayit_metrige_girmez(session):
    from datetime import timedelta

    from app.metrics.engine import load_team_data
    from app.services.ingest import run_ingest
    from tests.conftest import NOW

    run_ingest(session, None, _Kaynak([_task("a"), _task("b")]))
    run_ingest(session, None, _Kaynak([_task("a")]))

    from sqlalchemy import select

    from app.models import Team
    team = session.scalar(select(Team).where(Team.name == "T"))
    data = load_team_data(session, team, NOW - timedelta(days=30), NOW)

    assert [t.external_id for t in data.tasks] == ["a"]


# --- İŞ-20: artımlı senkron ---------------------------------------------------
# Adaptörlerin hepsi `since` destekliyordu ama ingest hepsini PARAMETRESİZ
# çağırıyordu (kod tabanında `since` üreten tek satır yoktu) → her saat tam
# çekim. GitHub'da repo başına ~350 istek/saat; 5000/saat sınırında ~13 repo.

class _GitKaynak:
    def __init__(self, warnings=None):
        self.warnings = list(warnings or [])
        self.since_cagrilari: list = []

    def fetch_commits(self, since=None):
        self.since_cagrilari.append(since)
        return []

    def fetch_pull_requests(self, since=None):
        return []


def test_ilk_senkron_tam_sonraki_artimli(session):
    from app.services.ingest import run_ingest

    g1 = _GitKaynak()
    run_ingest(session, g1, None)
    assert g1.since_cagrilari == [None], "ilk senkron TAM olmalı"

    g2 = _GitKaynak()
    run_ingest(session, g2, None)
    assert g2.since_cagrilari[0] is not None, "ikinci senkron artımlı olmalı"


def test_hatali_senkron_damgayi_ilerletmez(session):
    """EN KRİTİK: kısmi başarıda damga ilerlerse alınamayan commit'ler kalıcı
    olarak atlanır — sessiz ve kalıcı veri kaybı."""
    from app.services.ingest import run_ingest

    run_ingest(session, _GitKaynak(), None)          # damga kuruldu
    from sqlalchemy import select

    from app.models import SyncState
    ilk = session.scalar(select(SyncState).where(SyncState.source_kind == "git")).last_success_at

    run_ingest(session, _GitKaynak(warnings=["Repo okunamadı (403)"]), None)
    session.expire_all()
    sonra = session.scalar(select(SyncState).where(SyncState.source_kind == "git")).last_success_at

    assert ilk == sonra, "hatalı çekimden sonra damga ilerledi"


def test_tam_senkron_damgayi_yok_sayar(session):
    from app.services.ingest import run_ingest

    run_ingest(session, _GitKaynak(), None)
    g = _GitKaynak()
    run_ingest(session, g, None, incremental=False)
    assert g.since_cagrilari == [None]


def test_gorev_kaynagi_her_zaman_tam_cekilir(session):
    """Görevlerde artımlı çekim YAPILMAZ: tam görüntü olmadan 'kaynakta yok'
    tespiti (mark_missing_tasks) yanlış kayıtları kayıp sayardı."""
    from app.services.ingest import run_ingest

    class _T(_Kaynak):
        def __init__(self):
            super().__init__([_task("a")])
            self.since_cagrilari: list = []

        def fetch_tasks(self, since=None):
            self.since_cagrilari.append(since)
            return self._tasks

    run_ingest(session, None, _T())
    t = _T()
    run_ingest(session, None, t)
    assert t.since_cagrilari == [None]
