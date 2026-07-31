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
