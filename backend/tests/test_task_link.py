"""Task ↔ commit bağı ve iş bazlı süreç analizi.

Bu dosyanın iki testi ötekilerden önemli:

1. `test_insan_karari_senkronda_ezilmez` — motor her senkronda öneri üretir.
   Kullanıcının reddettiği bağ geri gelirse onay mekanizması anlamsızlaşır ve
   kullanıcı aynı yanlışı sonsuza kadar reddeder.

2. `test_onaysiz_baglantida_llm_hic_cagrilmaz` — eşleştirme TAHMİNdir (~%50
   isabet). Tahmin üstüne analiz yazmak, sistemin yanlış commit'e bakıp
   kendinden emin konuşması demektir. RAG'daki aynı kuralın karşılığı.

Testler ağa çıkmaz: embedding için HashEmbedding, LLM için sahte advisor.
"""
from __future__ import annotations

import pytest

from tests.conftest import days_ago


class _FakeAdvisor:
    def __init__(self, reply: str = "Analiz [1]"):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def advise(self, team_name: str, metrics_block: str) -> str:
        return self.reply

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


def _cfg():
    from app.core.config import get_config
    return get_config()


def _enable_rag() -> None:
    """RAG bloğunu ağsız (hash) sağlayıcıyla açar — eşik düşük, eşleşme olsun."""
    import yaml

    from app.core.config import active_config_path, reset_config_cache

    path = active_config_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw["rag"] = {
        "enabled": True,
        "embedding": {"provider": "hash"},
        "chunk": {"words": 400, "overlap": 60},
        "retrieval": {"top_k": 5, "min_score": 0.05},
        "index": "auto",
    }
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    reset_config_cache()


def _seed(session):
    """Bir takım + iki commit + iki task. Başlıklar bilerek ayrık kelimeler
    taşır ki hash-embedding sözcük örtüşmesinden doğru eşleşmeyi bulabilsin."""
    from app.models import Commit, Repo, Task, TaskStatusTransition, Team

    team = Team(name="Takım A")
    session.add(team)
    session.flush()
    repo = Repo(name="repo-a", team_id=team.id)
    session.add(repo)
    session.flush()

    anket = Commit(
        repo_id=repo.id, sha="a" * 40, committed_at=days_ago(5),
        message="anket modulu eklendi", changed_files=["survey.py"],
        additions=100, deletions=2,
    )
    izin = Commit(
        repo_id=repo.id, sha="b" * 40, committed_at=days_ago(4),
        message="izin onay akisi duzeltildi", changed_files=["leaves.py"],
        additions=30, deletions=5,
    )
    session.add_all([anket, izin])

    t_anket = Task(source="trello", external_id="T1", team_id=team.id,
                   title="anket modulu", status="DONE", created_at=days_ago(7))
    t_izin = Task(source="trello", external_id="T2", team_id=team.id,
                  title="izin onay akisi", status="DONE", created_at=days_ago(7))
    session.add_all([t_anket, t_izin])
    session.flush()
    session.add_all([
        TaskStatusTransition(task_id=t_anket.id, to_status="DONE",
                             changed_at=days_ago(5)),
        TaskStatusTransition(task_id=t_izin.id, to_status="DONE",
                             changed_at=days_ago(4)),
    ])
    session.commit()
    return team, t_anket, t_izin, anket, izin


def _provider():
    from app.services.rag.embedding import HashEmbedding
    return HashEmbedding()


# --- eşleştirme ---------------------------------------------------------------

def test_motor_dogru_commiti_ust_siraya_koyar(session):
    _enable_rag()
    _team, t_anket, _t_izin, c_anket, _c_izin = _seed(session)
    from app.services.task_link import link_tasks

    groups = {g.task_id: g for g in link_tasks(session, _cfg(), provider=_provider())}
    top = groups[t_anket.id].links[0]
    assert top.commit_id == c_anket.id


def test_oneriler_kaydedilir_ve_tekrar_calistirmak_cogaltmaz(session):
    _enable_rag()
    _seed(session)
    from sqlalchemy import func, select

    from app.models import TaskCommitLink
    from app.services.task_link import refresh_suggestions

    first = refresh_suggestions(session, _cfg())
    total = session.scalar(select(func.count()).select_from(TaskCommitLink))
    assert first["suggested"] == total > 0

    second = refresh_suggestions(session, _cfg())
    assert second["suggested"] == 0
    assert session.scalar(select(func.count()).select_from(TaskCommitLink)) == total


def test_insan_karari_senkronda_ezilmez(session):
    """EN ÖNEMLİ TEST: reddedilen bağ senkronda geri gelmemeli."""
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.services.task_link import decide, list_links, refresh_suggestions

    refresh_suggestions(session, _cfg())
    decide(session, t_anket.id, c_anket.id, "rejected")

    refresh_suggestions(session, _cfg())

    row = next(x for x in list_links(session, t_anket.id)
               if x["commit_id"] == c_anket.id)
    assert row["status"] == "rejected"


def test_elle_baglama_motor_onermese_de_calisir(session):
    _enable_rag()
    _team, t_anket, _t2, _c1, c_izin = _seed(session)
    from app.services.task_link import confirmed_commits, decide

    # Motorun önermediği bir commit elle bağlanabilmeli.
    decide(session, t_anket.id, c_izin.id, "confirmed")
    assert [c.id for c in confirmed_commits(session, t_anket.id)] == [c_izin.id]


def test_gecersiz_karar_reddedilir(session):
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.services.task_link import decide

    with pytest.raises(ValueError):
        decide(session, t_anket.id, c_anket.id, "belki")


def test_zaman_penceresi_sert_filtre_degil(session):
    """Pencere dışındaki commit ELENMEZ, yalnız primi alamaz."""
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.models import Commit
    from app.services.task_link import link_tasks

    # Commit'i penceresinin çok dışına taşı (bir yıl önce).
    session.get(Commit, c_anket.id).committed_at = days_ago(400)
    session.commit()

    groups = {g.task_id: g for g in link_tasks(session, _cfg(), provider=_provider())}
    found = [x for x in groups[t_anket.id].links if x.commit_id == c_anket.id]
    assert found, "pencere dışı commit elenmemeli"
    assert found[0].in_window is False


# --- analiz -------------------------------------------------------------------

def test_onaysiz_baglantida_llm_hic_cagrilmaz(session):
    """EN ÖNEMLİ TEST: analiz tahmine dayanmaz."""
    _enable_rag()
    _team, t_anket, _t2, _c1, _c2 = _seed(session)
    from app.services.task_analysis import analyze_task
    from app.services.task_link import refresh_suggestions

    refresh_suggestions(session, _cfg())  # öneriler var ama onay YOK
    advisor = _FakeAdvisor()
    result = analyze_task(session, _cfg(), t_anket.id, advisor=advisor)

    assert result.status == "no_confirmed_links"
    assert advisor.calls == []


def test_onayli_baglantida_analiz_uretilir(session):
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.services.task_analysis import analyze_task
    from app.services.task_link import decide

    decide(session, t_anket.id, c_anket.id, "confirmed")
    advisor = _FakeAdvisor()
    result = analyze_task(session, _cfg(), t_anket.id, advisor=advisor)

    assert result.status == "ok"
    assert len(advisor.calls) == 1
    _system, user_msg = advisor.calls[0]
    assert "anket modulu eklendi" in user_msg
    # Onaylanmamış commit bağlama GİRMEZ.
    assert "izin onay akisi duzeltildi" not in user_msg


def test_uyum_yargisi_ayiklanir_ve_metinden_cikarilir(session):
    """Kartta tarif edilen iş ile yapılan iş örtüşüyor mu — yargı ayrı alanda
    döner ki arayüz rozet gösterebilsin, anlatı metni de yargı satırını
    tekrarlamasın."""
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.services.task_analysis import analyze_task
    from app.services.task_link import decide

    decide(session, t_anket.id, c_anket.id, "confirmed")
    advisor = _FakeAdvisor("UYUM: sapma\n\nCommit'ler başka bir modüle dokunuyor [1].")
    result = analyze_task(session, _cfg(), t_anket.id, advisor=advisor)

    assert result.status == "ok"
    assert result.alignment == "sapma"
    assert result.alignment_label == "Karttan sapmış"
    assert result.text == "Commit'ler başka bir modüle dokunuyor [1]."
    assert "UYUM:" not in result.text


def test_uyum_biciminde_gelmezse_yargi_UYDURULMAZ(session):
    """Model biçimi tutturamazsa alignment None kalır. Varsayılan bir 'uyuyor'
    üretmek, hiç kontrol edilmemiş bir işi onaylanmış gibi gösterirdi."""
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.services.task_analysis import analyze_task
    from app.services.task_link import decide

    decide(session, t_anket.id, c_anket.id, "confirmed")
    result = analyze_task(session, _cfg(), t_anket.id,
                          advisor=_FakeAdvisor("Serbest metin, biçim yok [1]."))

    assert result.status == "ok"
    assert result.alignment is None and result.alignment_label is None
    assert result.text == "Serbest metin, biçim yok [1]."


def test_analiz_baglami_kisi_adi_tasimaz(session):
    """İlke E: analiz 'kim yaptı'yı değil 'süreç nasıl işledi'yi anlatır."""
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.models import Commit, Developer
    from app.services.task_analysis import build_context
    from app.services.task_link import confirmed_commits, decide

    dev = Developer(display_name="Ayşe Yılmaz", external_ids={}, anonymizable=True)
    session.add(dev)
    session.flush()
    session.get(Commit, c_anket.id).author_id = dev.id
    from app.models import Task
    session.get(Task, t_anket.id).assignee_id = dev.id
    session.commit()

    decide(session, t_anket.id, c_anket.id, "confirmed")
    block, _ = build_context(session.get(Task, t_anket.id),
                            confirmed_commits(session, t_anket.id))
    assert "Ayşe" not in block and "Yılmaz" not in block


# --- HTTP uçları ---------------------------------------------------------------

@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def _token(client, session, email="admin@x.com", role="admin"):
    from datetime import datetime, timezone

    from app.core.security import hash_password
    from app.models import User

    now = datetime.now(timezone.utc)
    session.add(User(
        email=email, password_hash=hash_password("parola1"), role=role,
        is_active=True, must_change_password=False, created_at=now, updated_at=now,
    ))
    session.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "parola1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_uc_takimin_bagli_islerini_doner(client, session):
    _enable_rag()
    team, t_anket, _t2, _c1, _c2 = _seed(session)
    from app.services.task_link import refresh_suggestions

    refresh_suggestions(session, _cfg())
    r = client.get(f"/api/teams/{team.id}/task-links", headers=_token(client, session))

    assert r.status_code == 200, r.text
    ids = [t["task_id"] for t in r.json()["tasks"]]
    assert t_anket.id in ids


def test_uc_baska_takimin_isini_vermez(client, session):
    """Takım erişimi olsa bile URL'deki task_id başka takımınsa 404."""
    _enable_rag()
    team_a, t_a, _t2, _c1, _c2 = _seed(session)
    from app.models import Team

    other = Team(name="Takım B")
    session.add(other)
    session.commit()
    h = _token(client, session)

    r = client.get(f"/api/teams/{other.id}/tasks/{t_a.id}/links", headers=h)

    assert r.status_code == 404


def test_uc_karar_icin_admin_ister(client, session):
    _enable_rag()
    team, t_anket, _t2, c_anket, _c2 = _seed(session)
    h = _token(client, session, email="calisan@x.com", role="user")

    r = client.post(
        f"/api/teams/{team.id}/tasks/{t_anket.id}/links/{c_anket.id}",
        json={"status": "confirmed"}, headers=h,
    )

    assert r.status_code == 403


def test_uc_onaysiz_analizde_200_ve_dural_cevap(client, session):
    """Onaylı bağ yoksa hata değil, dürüst 'analiz edilecek veri yok' döner."""
    _enable_rag()
    team, t_anket, _t2, _c1, _c2 = _seed(session)

    r = client.post(f"/api/teams/{team.id}/tasks/{t_anket.id}/analysis",
                    headers=_token(client, session))

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "no_confirmed_links"


def test_uc_tokensiz_401(client, session):
    _enable_rag()
    team, t_anket, _t2, _c1, _c2 = _seed(session)

    r = client.get(f"/api/teams/{team.id}/tasks/{t_anket.id}/links")

    assert r.status_code == 401


def test_analiz_baglami_sureyi_ve_akisi_tasir(session):
    _enable_rag()
    _team, t_anket, _t2, c_anket, _c2 = _seed(session)
    from app.models import Task
    from app.services.task_analysis import build_context
    from app.services.task_link import confirmed_commits, decide

    decide(session, t_anket.id, c_anket.id, "confirmed")
    block, _ = build_context(session.get(Task, t_anket.id),
                             confirmed_commits(session, t_anket.id))
    assert "DONE" in block          # statü akışı
    assert "+100/-2" in block       # değişiklik hacmi
    assert "survey.py" in block     # dokunulan alan


# --- konvansiyon: commit mesajı kartın numarasını söylüyorsa -------------------
#
# Bu blok, eşleştirmenin TAHMİN olmaktan çıktığı tek yolu korur. Kırılırsa
# sistem sessizce ~%50 isabetli tahmine geri döner ve kimse fark etmez.

def _seed_konvansiyon(session):
    """Kart numarası taşıyan bir task + onu anan bir commit + ilgisiz bir commit."""
    from app.models import Commit, Repo, Task, TaskStatusTransition, Team

    team = Team(name="Takım K")
    session.add(team)
    session.flush()
    repo = Repo(name="repo-k", team_id=team.id)
    session.add(repo)
    session.flush()

    anan = Commit(repo_id=repo.id, sha="c" * 40, committed_at=days_ago(3),
                  message="feat: rapor ekrani\n\nRefs [#42]", changed_files=["r.py"])
    ilgisiz = Commit(repo_id=repo.id, sha="d" * 40, committed_at=days_ago(3),
                     message="chore: bagimlilik guncellendi", changed_files=["req.txt"])
    session.add_all([anan, ilgisiz])
    task = Task(source="trello", external_id="opak-hash-6a607d67", task_key="42",
                team_id=team.id, title="rapor ekrani", status="DONE",
                created_at=days_ago(6))
    session.add(task)
    session.flush()
    session.add(TaskStatusTransition(task_id=task.id, to_status="DONE",
                                     changed_at=days_ago(3)))
    session.commit()
    return team, task, anan, ilgisiz


def test_konvansiyon_bagi_kesindir_onay_beklemez(session):
    _enable_rag()
    _team, task, anan, _ilgisiz = _seed_konvansiyon(session)
    from app.services.task_link import list_links, refresh_suggestions

    stats = refresh_suggestions(session, _cfg())

    assert stats["convention"] == 1
    row = next(x for x in list_links(session, task.id) if x["commit_id"] == anan.id)
    assert row["status"] == "confirmed"
    assert row["matched_by"] == "convention"
    # Skor YOK: benzerlik hiç hesaplanmadı, 1.0 yazmak ölçüm uydurmak olurdu.
    assert row["score"] is None


def test_konvansiyon_varken_o_is_icin_tahmin_uretilmez(session):
    """Kesin bilginin yanına tahmin koymak ekranı kirletir, kullanıcıyı
    'acaba bu mu?' diye düşündürür. Konvansiyonla çözülen iş listeden çıkar."""
    _enable_rag()
    _team, task, anan, _ilgisiz = _seed_konvansiyon(session)
    from app.services.task_link import list_links, refresh_suggestions

    refresh_suggestions(session, _cfg())

    links = list_links(session, task.id)
    assert [x["commit_id"] for x in links] == [anan.id]
    assert all(x["matched_by"] == "convention" for x in links)


def test_ciplak_diyez_github_issue_sayilir_bag_kurmaz(session):
    """`#42` git dünyasında GitHub issue/PR'dır. Kabul etmek 'fix #5' yazan bir
    commit'i 5 numaralı karta KESİN bağ diye işaretlerdi — uydurulmuş kesinlik."""
    _enable_rag()
    _team, task, anan, _ilgisiz = _seed_konvansiyon(session)
    anan.message = "feat: rapor ekrani (fix #42)"   # köşeli parantez YOK
    session.commit()
    from app.services.task_link import refresh_suggestions

    stats = refresh_suggestions(session, _cfg())

    assert stats["convention"] == 0
    from sqlalchemy import select

    from app.models import TaskCommitLink
    rows = session.scalars(select(TaskCommitLink).where(
        TaskCommitLink.task_id == task.id)).all()
    assert all(r.status == "suggested" for r in rows)


def test_ayni_numara_iki_iste_ise_bag_kurulmaz_ve_uyarilir(session):
    """Trello'da idShort board BAŞINA benzersiz: iki board'da da 42 olabilir.
    Hangisi olduğu bilinmiyorken birini seçmek kura çekmektir."""
    _enable_rag()
    _team, task, _anan, _ilgisiz = _seed_konvansiyon(session)
    from app.models import Task
    session.add(Task(source="trello", external_id="baska-board", task_key="42",
                     team_id=task.team_id, title="baska kart", status="DONE",
                     created_at=days_ago(6)))
    session.commit()
    from app.services.task_link import refresh_suggestions

    stats = refresh_suggestions(session, _cfg())

    assert stats["convention"] == 0
    assert any("42" in w for w in stats["warnings"])


def test_insan_reddi_konvansiyonu_da_ezer(session):
    """Kart numarası yanlış yazılmış olabilir; son söz insanındır."""
    _enable_rag()
    _team, task, anan, _ilgisiz = _seed_konvansiyon(session)
    from app.services.task_link import decide, list_links, refresh_suggestions

    refresh_suggestions(session, _cfg())
    decide(session, task.id, anan.id, "rejected")
    refresh_suggestions(session, _cfg())

    row = next(x for x in list_links(session, task.id) if x["commit_id"] == anan.id)
    assert row["status"] == "rejected"


def test_konvansiyon_embedding_olmadan_da_calisir(session):
    """Kesin bağ, yerel embedding ucu kapalıyken de kurulmalı: tahmin adımının
    başarısızlığı tahmin GEREKTİRMEYEN bağı geri almamalı."""
    _enable_rag()
    _team, task, anan, _ilgisiz = _seed_konvansiyon(session)
    from app.services.task_link import list_links, refresh_suggestions

    class _Patlayan:
        model = "patlayan"

        def embed(self, texts):
            raise RuntimeError("embedding ucu kapalı")

    stats = refresh_suggestions(session, _cfg(), provider=_Patlayan())

    assert stats["convention"] == 1
    assert stats["suggested"] == 0
    row = next(x for x in list_links(session, task.id) if x["commit_id"] == anan.id)
    assert row["status"] == "confirmed"


def test_jira_anahtari_paranteZsiz_de_taninir(session):
    """PROJ-123 biçimi kendi kendini tanımlar; başka bir şeyle karışmaz."""
    from app.services.task_link import referenced_keys

    assert referenced_keys("VAN-12 rapor ekrani duzeltildi") == {"VAN-12"}
    assert referenced_keys("bkz [#7] ve VAN-3") == {"7", "VAN-3"}
    assert referenced_keys("fix #7") == set()
    assert referenced_keys(None) == set()


# --- Kişi sinyali -------------------------------------------------------------
#
# Kartın atananı ile commit'in yazarı aynı insan mı? Bu ancak hesaplar hem
# Trello üyeliğine hem git e-postasına bağlıysa bilinebilir.
#
# SIRALAMAYA GİRMEZ (PERSON_BONUS = 0.0) ve bu bir ihmal değil ÖLÇÜM SONUCUDUR:
# tek yazarlı bir depoda prim adayların HEPSİNE gittiği için hiçbir şeyi yeniden
# sıralayamıyor (bkz. scripts/task_link_eval.py). Ölçülmemiş bir fayda için
# sıralamayı oynatmak, bu sistemin kaçındığı "uydurulmuş kesinlik" olurdu.

def test_kisi_sinyali_iki_atanan_alanini_da_okur(session):
    """Kart iki kişiye atanmışsa ikincisi de "atanan"dır: yalnız birincil alana
    bakmak, çok atananlı kartta ikinci kişiyi hiç göstermezdi."""
    from app.models import Developer, Task, TaskAssignee
    from app.services.task_link import task_developer_ids

    a = Developer(display_name="A", external_ids={"trello": "m1"})
    b = Developer(display_name="B", external_ids={"trello": "m2"})
    task = Task(source="trello", external_id="c1", title="iş")
    session.add_all([a, b, task])
    session.flush()
    task.assignee_id = a.id
    session.add(TaskAssignee(task_id=task.id, developer_id=b.id))
    session.commit()

    assert task_developer_ids(task) == {a.id, b.id}


def test_ayni_kisi_rozeti_bagda_gosterilir(session):
    """`same_person` SAKLANMAZ, okunurken türetilir: kimlik eşlemesi sonradan
    yapıldığında eski bağlar da doğru rozeti gösterir."""
    from datetime import datetime, timezone

    from app.models import Commit, Developer, Repo, Task, TaskCommitLink
    from app.services.task_link import list_links

    dev = Developer(display_name="Ayşe", external_ids={"git": "a@x.com"})
    baskasi = Developer(display_name="Mehmet", external_ids={"git": "m@x.com"})
    repo = Repo(name="r1")
    session.add_all([dev, baskasi, repo])
    session.flush()
    task = Task(source="trello", external_id="c1", title="iş", assignee_id=dev.id)
    c_ayni = Commit(repo_id=repo.id, sha="a1", author_id=dev.id, message="benim işim")
    c_baska = Commit(repo_id=repo.id, sha="b2", author_id=baskasi.id, message="başkasının")
    session.add_all([task, c_ayni, c_baska])
    session.flush()
    now = datetime.now(timezone.utc)
    session.add_all([
        TaskCommitLink(task_id=task.id, commit_id=c_ayni.id, status="suggested",
                       matched_by="semantic", score=0.5, created_at=now),
        TaskCommitLink(task_id=task.id, commit_id=c_baska.id, status="suggested",
                       matched_by="semantic", score=0.6, created_at=now),
    ])
    session.commit()

    baglar = {x["commit_id"]: x for x in list_links(session, task.id)}

    assert baglar[c_ayni.id]["same_person"] is True
    assert baglar[c_baska.id]["same_person"] is False


def test_kisi_primi_varsayilan_olarak_siralamayi_degistirmez():
    """Ölçüm fayda göstermedi → prim eklenmedi. Bu sabit büyütülecekse ÖNCE
    scripts/task_link_eval.py ile ilk sıra isabetinin arttığı gösterilmeli."""
    from app.services import task_link

    assert task_link.PERSON_BONUS == 0.0
