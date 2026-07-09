"""Yönetici operasyon uçları: kaynak/entegrasyon durumu, ayar, elle senkron.

Etik/güvenlik notu: token (sır) ASLA config'e yazılmaz; yalnızca ortam
değişkeninin adı ve "tanımlı mı" bilgisi gösterilir. Bu uçlar yönetici
yetkisi ister.
"""
from __future__ import annotations

import os

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.core.config import DEFAULT_CONFIG_PATH, get_config, reset_config_cache
from app.core.db import get_session
from app.models import MetricResult, User

router = APIRouter(prefix="/api/admin")


class SourcesUpdate(BaseModel):
    git_provider: str | None = None       # git_log | gitlab | fixture
    tasks_provider: str | None = None     # jira | trello | fixture | none
    quality_provider: str | None = None   # sonarqube | linter | fixture | none
    gitlab_base_url: str | None = None
    jira_base_url: str | None = None
    sonarqube_base_url: str | None = None
    sync_interval_minutes: int | None = None


def _env_status(var: str) -> dict:
    return {"env_var": var, "configured": bool(os.environ.get(var))}


@router.get("/sources")
def get_sources(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    cfg = get_config()
    last_sync = session.scalar(select(func.max(MetricResult.computed_at)))
    return {
        "last_sync": last_sync.isoformat() if last_sync else None,
        "sync_interval_minutes": cfg.sync.interval_minutes,
        "git": {
            "provider": cfg.sources.git.provider,
            "gitlab_base_url": cfg.sources.git.gitlab.base_url,
            "token": _env_status(cfg.sources.git.gitlab.token_env),
            "repo_count": len(cfg.sources.git.repos),
        },
        "tasks": {
            "provider": cfg.sources.tasks.provider,
            "jira_base_url": cfg.sources.tasks.jira.base_url,
            "token": _env_status(cfg.sources.tasks.jira.token_env),
        },
        "quality": {
            "provider": cfg.sources.quality.provider,
            "sonarqube_base_url": cfg.sources.quality.sonarqube.base_url,
            "token": _env_status(cfg.sources.quality.sonarqube.token_env),
        },
    }


@router.put("/sources")
def update_sources(
    body: SourcesUpdate,
    _: User = Depends(require_admin),
):
    # Mevcut config.yaml'ı ham oku, yalnızca verilen alanları güncelle, geri yaz.
    # (Yorumlar kaybolur — on-prem tek dosya, kabul edilebilir.) Sır YAZILMAZ.
    raw = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    raw.setdefault("sources", {})
    raw["sources"].setdefault("git", {}).setdefault("gitlab", {})
    raw["sources"].setdefault("tasks", {}).setdefault("jira", {})
    raw["sources"].setdefault("quality", {}).setdefault("sonarqube", {})
    raw.setdefault("sync", {})

    if body.git_provider is not None:
        raw["sources"]["git"]["provider"] = body.git_provider
    if body.tasks_provider is not None:
        raw["sources"]["tasks"]["provider"] = body.tasks_provider
    if body.quality_provider is not None:
        raw["sources"]["quality"]["provider"] = body.quality_provider
    if body.gitlab_base_url is not None:
        raw["sources"]["git"]["gitlab"]["base_url"] = body.gitlab_base_url
    if body.jira_base_url is not None:
        raw["sources"]["tasks"]["jira"]["base_url"] = body.jira_base_url
    if body.sonarqube_base_url is not None:
        raw["sources"]["quality"]["sonarqube"]["base_url"] = body.sonarqube_base_url
    if body.sync_interval_minutes is not None:
        raw["sync"]["interval_minutes"] = max(0, body.sync_interval_minutes)

    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}


@router.post("/sync")
def trigger_sync(_: User = Depends(require_admin)):
    """Elle senkron: kaynaklardan çek + metrik hesapla + öneri üret."""
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    return {"ok": True, "stats": stats}
