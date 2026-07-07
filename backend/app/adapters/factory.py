"""Config'ten sağlayıcı örnekleri kurar.

Yeni bir kaynak eklemek = yeni adaptör sınıfı + buraya bir satır.
Çekirdek (ingest, metrik, kural) hiç değişmez.
"""
from __future__ import annotations

from pathlib import Path

from app.adapters.base import GitProvider, QualityProvider, TaskProvider
from app.adapters.fixture import (
    FixtureGitProvider,
    FixtureQualityProvider,
    FixtureTaskProvider,
)
from app.adapters.git_log import GitLogProvider
from app.adapters.gitlab import GitLabProvider
from app.adapters.jira import JiraProvider
from app.adapters.linter import LinterProvider
from app.adapters.sonarqube import SonarQubeProvider
from app.adapters.trello import TrelloProvider
from app.core.config import PROJECT_ROOT, Config

FIXTURE_DIR = PROJECT_ROOT / "backend" / "fixtures"


def build_git_provider(cfg: Config, fixture_dir: Path = FIXTURE_DIR) -> GitProvider | None:
    src = cfg.sources.git
    if src.provider == "git_log":
        return GitLogProvider(src.repos)
    if src.provider == "gitlab":
        gl = src.gitlab
        return GitLabProvider(gl.base_url, gl.token_env, gl.projects)
    if src.provider == "fixture":
        return FixtureGitProvider(fixture_dir)
    return None


def build_task_provider(cfg: Config, fixture_dir: Path = FIXTURE_DIR) -> TaskProvider | None:
    src = cfg.sources.tasks
    if src.provider == "jira":
        j = src.jira
        return JiraProvider(j.base_url, j.token_env, j.projects)
    if src.provider == "trello":
        t = src.trello
        return TrelloProvider(t.key_env, t.token_env, t.boards)
    if src.provider == "fixture":
        return FixtureTaskProvider(fixture_dir)
    return None  # task kaynağı yok → task metrikleri "veri yetersiz"


def build_quality_provider(cfg: Config, fixture_dir: Path = FIXTURE_DIR) -> QualityProvider | None:
    src = cfg.sources.quality
    if src.provider == "sonarqube":
        s = src.sonarqube
        return SonarQubeProvider(s.base_url, s.token_env, s.project_keys)
    if src.provider == "linter":
        return LinterProvider(src.linter.command, cfg.sources.git.repos)
    if src.provider == "fixture":
        return FixtureQualityProvider(fixture_dir)
    return None
