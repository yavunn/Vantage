"""Kural motoru testleri: her kuralın tetiklendiği senaryo (spec Bölüm 6)."""
from __future__ import annotations

from datetime import timedelta

from tests.conftest import NOW, days_ago, make_team


def _data(session, team):
    from app.metrics.engine import load_team_data

    return load_team_data(session, team, NOW - timedelta(days=30), NOW)


def _cfg():
    from app.core.config import get_config

    return get_config()


def test_review_bottleneck_tetiklenir(session):
    from app.models import PullRequest
    from app.rules.engine import rule_review_bottleneck

    team, repo, devs, _ = make_team(session)
    for i in range(3):
        session.add(PullRequest(
            repo_id=repo.id, external_id=f"p{i}", author_id=devs[0].id,
            opened_at=days_ago(15), first_review_at=days_ago(15 - 5),  # 5 gün bekleme
        ))
    session.commit()
    finding = rule_review_bottleneck(_data(session, team), _cfg())
    assert finding is not None
    assert "review" in finding.message.lower()
    # Destek dili: suçlama içermez
    assert "tembel" not in finding.message.lower()


def test_hotspot_files_tetiklenir(session):
    from app.models import Commit
    from app.rules.engine import rule_hotspot_files

    team, repo, devs, _ = make_team(session)
    for i in range(4):
        session.add(Commit(
            repo_id=repo.id, sha=f"f{i}", author_id=devs[0].id,
            committed_at=days_ago(i * 3 + 1),
            message=f"fix: hata {i}", changed_files=["src/legacy/core.py"],
        ))
    session.commit()
    finding = rule_hotspot_files(_data(session, team), _cfg())
    assert finding is not None
    # Metin ŞABLON, dosya listesi params'ta: öneri okuma anında çevrildiği için
    # hazır cümle saklanmıyor (bkz. services/report.recommendation_payload).
    assert "src/legacy/core.py" in finding.params["dosyalar"]
    assert "refactor" in finding.message.lower()


def test_wip_overload_tetiklenir(session):
    from app.models import Task
    from app.rules.engine import rule_wip_overload

    team, repo, devs, _ = make_team(session)  # 2 üye
    for i in range(12):  # kişi başı 6 açık iş > eşik 5
        session.add(Task(source="fixture", external_id=f"W-{i}",
                         team_id=team.id, status="In Progress"))
    session.commit()
    finding = rule_wip_overload(_data(session, team), _cfg())
    assert finding is not None
    assert "WIP" in finding.message


def test_low_process_hygiene_tetiklenir(session):
    from app.models import Task
    from app.rules.engine import rule_low_process_hygiene

    team, repo, devs, _ = make_team(session)
    for i in range(10):  # %80'inde estimate yok > eşik %70
        session.add(Task(source="fixture", external_id=f"H-{i}", team_id=team.id,
                         status="To Do", estimate_hours=8.0 if i < 2 else None))
    session.commit()
    finding = rule_low_process_hygiene(_data(session, team), _cfg())
    assert finding is not None
    # Ceza dili yok: eksiklik "kusur" değil görünürlük kaybı olarak anlatılır
    assert "kusur değil" in finding.message


def test_risky_deploy_window_tetiklenir(session):
    from app.models import Commit
    from app.rules.engine import rule_risky_deploy_window

    team, repo, devs, _ = make_team(session)
    # Son 2 cuma 17:00 deploy + cumartesi hotfix
    friday = NOW - timedelta(days=(NOW.weekday() - 4) % 7)
    for w in (1, 2):
        d = (friday - timedelta(weeks=w)).replace(hour=17, minute=0)
        session.add(Commit(repo_id=repo.id, sha=f"d{w}", committed_at=d,
                           message="Merge branch 'release'", changed_files=["a.py"]))
        session.add(Commit(repo_id=repo.id, sha=f"x{w}",
                           committed_at=d + timedelta(hours=20),
                           message="hotfix: hafta sonu", changed_files=["a.py"]))
    session.commit()
    finding = rule_risky_deploy_window(_data(session, team), _cfg())
    assert finding is not None
    assert "freeze" in finding.message.lower()


def test_saglikli_takimda_kural_tetiklenmez(session):
    from sqlalchemy import select

    from app.models import PullRequest, Recommendation
    from app.rules.engine import run_rules

    team, repo, devs, _ = make_team(session)
    session.add(PullRequest(
        repo_id=repo.id, external_id="ok1", author_id=devs[0].id,
        opened_at=days_ago(5), first_review_at=days_ago(4.9), merged_at=days_ago(4),
    ))
    session.commit()
    run_rules(session, _cfg())
    recs = session.scalars(select(Recommendation)).all()
    assert recs == []


def test_trello_takiminda_estimate_onerisi_uretilmez(session):
    """İŞ-07: Trello'da estimate ALANI YOKTUR. Metrik motoru bunu zaten
    dışlıyordu (SOURCES_WITHOUT_ESTIMATE) ama kural dışlamıyordu; sonuç,
    takımın hiçbir zaman kapatamayacağı kalıcı bir öneriydi."""
    from app.models import Task
    from app.rules.engine import rule_low_process_hygiene

    team, repo, devs, _ = make_team(session)
    for i in range(5):
        session.add(Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                         status="DEVELOPMENT", estimate_hours=None))
    session.commit()
    assert rule_low_process_hygiene(_data(session, team), _cfg()) is None


def test_estimate_destekleyen_kaynakta_oneri_hala_uretilir(session):
    """Jira'da alan VAR — doldurulmaması gerçek bir görünürlük kaybıdır;
    düzeltme bu sinyali susturmamalı."""
    from app.models import Task
    from app.rules.engine import rule_low_process_hygiene

    team, repo, devs, _ = make_team(session)
    for i in range(5):
        session.add(Task(source="jira", external_id=f"J-{i}", team_id=team.id,
                         status="To Do", estimate_hours=None))
    session.commit()
    finding = rule_low_process_hygiene(_data(session, team), _cfg())
    assert finding is not None
    assert "estimate" in finding.message.lower()


def test_karisik_kaynakta_payda_yalniz_estimate_destekleyenler(session):
    """Trello kartları paydayı şişirip oranı yapay yükseltmemeli."""
    from app.models import Task
    from app.rules.engine import rule_low_process_hygiene

    team, repo, devs, _ = make_team(session)
    # 8 Trello (alan yok) + 4 Jira'nın 3'ünde estimate dolu → estimable %25 eksik
    for i in range(8):
        session.add(Task(source="trello", external_id=f"T-{i}", team_id=team.id,
                         status="DEVELOPMENT", estimate_hours=None))
    for i in range(4):
        session.add(Task(source="jira", external_id=f"J-{i}", team_id=team.id,
                         status="To Do", estimate_hours=None if i == 0 else 5.0))
    session.commit()
    # %25 < %70 eşiği → öneri yok. Trello'lar paydaya girseydi %75 çıkıp tetiklerdi.
    assert rule_low_process_hygiene(_data(session, team), _cfg()) is None
