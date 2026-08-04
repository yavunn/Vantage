"""Config'ten sağlayıcı örnekleri kurar.

Yeni bir kaynak eklemek = yeni adaptör sınıfı + buraya bir satır.
Çekirdek (ingest, metrik, kural) hiç değişmez.
"""
from __future__ import annotations

from pathlib import Path

from app.adapters.base import GitProvider, TaskProvider
from app.adapters.fixture import FixtureGitProvider, FixtureTaskProvider
from app.adapters.git_log import GitLogProvider
from app.adapters.github import GitHubProvider
from app.adapters.gitlab import GitLabProvider
from app.adapters.jira import JiraProvider
from app.adapters.trello import TrelloProvider
from app.core.config import PROJECT_ROOT, Config

FIXTURE_DIR = PROJECT_ROOT / "backend" / "fixtures"


def build_git_provider(cfg: Config, fixture_dir: Path = FIXTURE_DIR) -> GitProvider | None:
    src = cfg.sources.git
    if src.provider == "git_log":
        return GitLogProvider(src.repos, src.scan_all_branches)
    if src.provider == "github":
        gh = src.github
        return GitHubProvider(src.repos, gh.token_env, gh.detail_limit, gh.max_prs)
    if src.provider == "gitlab":
        gl = src.gitlab
        # repos: github ile ORTAK liste — repo→takım eşlemesi repo adıyla yapılır,
        # hedefler ayrı bir listede yaşarsa takımsız kalırdı (bkz. gitlab.py).
        return GitLabProvider(
            gl.base_url, gl.token_env, gl.projects, src.repos,
            detail_limit=gl.detail_limit, max_notes_pages=gl.max_notes_pages,
            bot_users=gl.bot_users,
        )
    if src.provider == "fixture":
        return FixtureGitProvider(fixture_dir)
    return None


def build_task_provider(cfg: Config, fixture_dir: Path = FIXTURE_DIR) -> TaskProvider | None:
    src = cfg.sources.tasks
    if src.provider == "jira":
        j = src.jira
        return JiraProvider(
            j.base_url, j.token_env, j.projects,
            auth=j.auth, email=j.email, email_env=j.email_env,
            api_style=j.api_style, story_points_field=j.story_points_field,
        )
    if src.provider == "trello":
        t = src.trello
        return TrelloProvider(t.key_env, t.token_env, t.boards)
    if src.provider == "fixture":
        return FixtureTaskProvider(fixture_dir)
    return None  # task kaynağı yok → task metrikleri "veri yetersiz"
