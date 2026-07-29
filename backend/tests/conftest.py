"""Test altyapısı.

Testler sunucusuz koşsun diye SQLite kullanılır (şema/tipler Postgres ile
ortak). Her test taze DB + taze config alır.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_CONFIG = """
app:
  individual_view_enabled: true
  anonymize_individuals: false
  window_days: 30
  bucket_days: 7
database:
  url: "sqlite:///{db_path}"
sync:
  interval_minutes: 0
sources:
  git: {{ provider: fixture }}
  tasks: {{ provider: fixture }}
metrics:
  cycle_time: {{ enabled: true, source: jira_status, fallback: pr_merge }}
  pr_review_time: {{ enabled: true }}
  review_latency: {{ enabled: true }}
  deployment_frequency: {{ enabled: true, deploy_signal: merge }}
  change_failure_rate: {{ enabled: true, hotfix_window_days: 3 }}
  wip: {{ enabled: true }}
  rework: {{ enabled: true, window_days: 21 }}
  estimate_accuracy: {{ enabled: false }}
  process_hygiene: {{ enabled: true }}
rules:
  review_bottleneck: {{ enabled: true, avg_review_wait_days: 4 }}
  hotspot_files: {{ enabled: true, min_fix_touches: 3, window_days: 30 }}
  wip_overload: {{ enabled: true, wip_per_dev: 5 }}
  low_process_hygiene: {{ enabled: true, missing_estimate_pct: 70 }}
  risky_deploy_window: {{ enabled: true }}
llm:
  enabled: false
"""

NOW = datetime.now(timezone.utc)


def days_ago(d: float) -> datetime:
    return NOW - timedelta(days=d)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Taze config + taze DB. Import'lardan ÖNCE env kurulmalı."""
    db_path = (tmp_path / "test.db").as_posix()
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(TEST_CONFIG.format(db_path=db_path), encoding="utf-8")
    monkeypatch.setenv("EHD_CONFIG", str(cfg_file))
    # Silmek yeterli DEĞİL: .secrets.env'de bir DATABASE_URL varsa load_secrets()
    # onu setdefault ile geri getirir ve testler gerçek veritabanına yazar.
    # Gerçek ortam değişkeni sırları ezdiği için test DB'sini açıkça sabitliyoruz.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.models  # noqa: F401 — tablolar metadata'ya kaydolsun
    from app.core.config import reset_config_cache
    from app.core.db import Base, get_engine, reset_engine

    reset_config_cache()
    reset_engine()
    Base.metadata.create_all(get_engine())
    yield cfg_file
    reset_engine()
    reset_config_cache()


@pytest.fixture()
def session(app_env):
    from app.core.db import get_sessionmaker

    s = get_sessionmaker()()
    yield s
    s.close()


def make_team(session, name="Takım A", devs=("dev1", "dev2"), manager="mgr"):
    from app.models import Developer, Repo, Team, TeamMembership

    team = Team(name=name)
    session.add(team)
    session.flush()
    repo = Repo(name=f"{name}-repo", team_id=team.id)
    session.add(repo)
    out_devs = []
    for key in devs:
        dev = Developer(external_ids={"git": key, "fixture": key}, display_name=key)
        session.add(dev)
        session.flush()
        session.add(TeamMembership(team_id=team.id, developer_id=dev.id, role="member"))
        out_devs.append(dev)
    mgr = Developer(external_ids={"git": manager}, display_name=manager)
    session.add(mgr)
    session.flush()
    session.add(TeamMembership(team_id=team.id, developer_id=mgr.id, role="manager"))
    session.commit()
    return team, repo, out_devs, mgr
