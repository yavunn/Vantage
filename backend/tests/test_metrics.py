"""Metrik motoru testleri.

Her metrik iki koşulda test edilir (spec Bölüm 6):
1. Tam veri → doğru değer üretir.
2. Eksik/kirli veri → metrik GİZLENİR (value None), sistem çökmez,
   completeness dürüstçe raporlanır.
"""
from __future__ import annotations

from tests.conftest import NOW, days_ago, make_team


def _team_data(session, team, window_days=30):
    from datetime import timedelta

    from app.metrics.engine import load_team_data

    return load_team_data(session, team, NOW - timedelta(days=window_days), NOW)


def _cfg():
    from app.core.config import get_config

    return get_config()


def add_pr(session, repo, author, opened_d, review_d=None, merged_d=None, ext=None):
    from app.models import PullRequest

    pr = PullRequest(
        repo_id=repo.id,
        external_id=ext or f"pr-{opened_d}-{id(object())}",
        author_id=author.id if author else None,
        opened_at=days_ago(opened_d) if opened_d is not None else None,
        first_review_at=days_ago(review_d) if review_d is not None else None,
        merged_at=days_ago(merged_d) if merged_d is not None else None,
    )
    session.add(pr)
    session.commit()
    return pr


class TestPRReviewTime:
    def test_tam_veri(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)  # 4 gün
        add_pr(session, repo, devs[1], opened_d=8, merged_d=6)   # 2 gün
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value == 3.0
        assert out.completeness == 1.0
        assert out.source_layer == "git"

    def test_veri_yoksa_gizlenir(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value is None  # asla 0 uydurulmaz

    def test_kirli_tarih_dusuk_completeness(self, session):
        from app.metrics.engine import pr_review_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)
        add_pr(session, repo, devs[0], opened_d=None, merged_d=5)  # açılış tarihi yok
        out = pr_review_time(_team_data(session, team), _cfg())
        assert out.value == 4.0          # hesap sadece sağlam kayıtla
        assert out.completeness == 0.5   # eksiklik raporlanır, cezalandırılmaz


class TestCycleTimeFallback:
    def test_task_yoksa_pr_merge_fallback(self, session):
        """İlke B: birincil katman (jira_status) boşsa Katman 0'a düşer."""
        from app.metrics.engine import cycle_time

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=9, merged_d=4)  # 5 gün
        out = cycle_time(_team_data(session, team), _cfg())
        assert out.source_layer == "pr_merge"
        assert out.value == 5.0

    def test_status_gecisi_varsa_katman1(self, session):
        from app.metrics.engine import cycle_time
        from app.models import Task, TaskStatusTransition

        team, repo, devs, _ = make_team(session)
        task = Task(source="fixture", external_id="T-1", team_id=team.id,
                    assignee_id=devs[0].id, status="Done", created_at=days_ago(10))
        session.add(task)
        session.flush()
        session.add_all([
            TaskStatusTransition(task_id=task.id, from_status="To Do",
                                 to_status="In Progress", changed_at=days_ago(8)),
            TaskStatusTransition(task_id=task.id, from_status="In Progress",
                                 to_status="Done", changed_at=days_ago(2)),
        ])
        session.commit()
        out = cycle_time(_team_data(session, team), _cfg())
        assert out.source_layer == "jira_status"
        assert abs(out.value - 6.0) < 0.01  # In Progress → Done = 6 gün


class TestWIP:
    def test_task_statusu_yoksa_pr_fallback(self, session):
        from app.metrics.engine import wip

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=5)  # açık PR
        out = wip(_team_data(session, team), _cfg())
        assert out.source_layer == "pr_open"
        assert out.value == 0.5  # 1 açık PR / 2 üye (yönetici sayılmaz)

    def test_hic_veri_yoksa_gizli(self, session):
        from app.metrics.engine import wip

        team, repo, devs, _ = make_team(session)
        out = wip(_team_data(session, team), _cfg())
        assert out.value is None


class TestRework:
    def test_ayni_dosyaya_tekrar_dokunma(self, session):
        from app.metrics.engine import rework_rate
        from app.models import Commit

        team, repo, devs, _ = make_team(session)
        session.add_all([
            Commit(repo_id=repo.id, sha="a1", author_id=devs[0].id,
                   committed_at=days_ago(10), changed_files=["x.py"]),
            Commit(repo_id=repo.id, sha="a2", author_id=devs[1].id,
                   committed_at=days_ago(5), changed_files=["x.py", "y.py"]),
        ])
        session.commit()
        out = rework_rate(_team_data(session, team), _cfg())
        # 3 dokunuş, 1'i rework (x.py 5 gün sonra tekrar)
        assert abs(out.value - 1 / 3) < 0.01
        assert out.sample == 3


class TestProcessHygiene:
    def test_eksik_veri_metrige_donusur(self, session):
        """İlke A: 'bu takım hiç estimate girmiyor' bilgisi bir metriktir."""
        from app.metrics.engine import process_hygiene
        from app.models import Task

        team, repo, devs, _ = make_team(session)
        for i in range(4):
            session.add(Task(source="fixture", external_id=f"T-{i}", team_id=team.id,
                             status="To Do", estimate_hours=8.0 if i == 0 else None))
        session.commit()
        out = process_hygiene(_team_data(session, team), _cfg())
        assert out.value is not None
        # bileşen1: estimate doluluk 0.25; bileşen2: transition doluluk 0.0
        assert abs(out.value - (0.25 + 0.0) / 2) < 0.01


class TestConfigKapatma:
    def test_kapali_metrik_hesaplanmaz(self, session, app_env):
        from app.core.config import get_config
        from app.metrics.engine import compute_all
        from app.models import MetricResult
        from sqlalchemy import select

        team, repo, devs, _ = make_team(session)
        add_pr(session, repo, devs[0], opened_d=10, merged_d=6)
        compute_all(session, get_config())
        keys = {r.metric_key for r in session.scalars(select(MetricResult))}
        assert "estimate_accuracy" not in keys  # config'te enabled: false
        assert "pr_review_time" in keys
