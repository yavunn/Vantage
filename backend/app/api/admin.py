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


class CodeAnalysisUpdate(BaseModel):
    enabled: bool | None = None
    llm_enabled: bool | None = None
    llm_provider: str | None = None          # none | local | claude
    weights: dict[str, float] | None = None
    exclude_globs: list[str] | None = None
    max_files_per_run: int | None = None
    max_diff_lines: int | None = None


@router.get("/code-analysis")
def get_code_analysis(_: User = Depends(require_admin)):
    """AI kod analizi ayarları (rubrik ağırlıkları, hariç klasörler, sıklık).
    API anahtarı config'e yazılmaz; yalnızca env durumu gösterilir."""
    cfg = get_config()
    ca = cfg.code_analysis
    return {
        "enabled": ca.enabled,
        "llm_enabled": cfg.llm.enabled,
        "llm_provider": cfg.llm.provider,
        "model": cfg.llm.claude.model,
        "api_key": _env_status(cfg.llm.claude.api_key_env),
        "weights": ca.weights,
        "exclude_globs": ca.exclude_globs,
        "max_files_per_run": ca.max_files_per_run,
        "max_diff_lines": ca.max_diff_lines,
    }


@router.put("/code-analysis")
def update_code_analysis(body: CodeAnalysisUpdate, _: User = Depends(require_admin)):
    raw = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw.setdefault("code_analysis", {})
    raw.setdefault("llm", {})

    if body.enabled is not None:
        raw["code_analysis"]["enabled"] = body.enabled
    if body.llm_enabled is not None:
        raw["llm"]["enabled"] = body.llm_enabled
    if body.llm_provider is not None:
        raw["llm"]["provider"] = body.llm_provider
    if body.weights is not None:
        # yalnızca bilinen boyutları kabul et, negatifleri kırp
        from app.services.code_analysis import DIMENSIONS
        raw["code_analysis"]["weights"] = {
            d: max(0.0, float(body.weights.get(d, 1.0))) for d in DIMENSIONS
        }
    if body.exclude_globs is not None:
        raw["code_analysis"]["exclude_globs"] = [g for g in body.exclude_globs if g.strip()]
    if body.max_files_per_run is not None:
        raw["code_analysis"]["max_files_per_run"] = max(1, body.max_files_per_run)
    if body.max_diff_lines is not None:
        raw["code_analysis"]["max_diff_lines"] = max(20, body.max_diff_lines)

    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    reset_config_cache()
    return {"ok": True}


@router.post("/code-analysis/run")
def run_code_analysis_now(_: User = Depends(require_admin)):
    """Elle AI kod analizi çalıştır (git_log repoları, tüm yazarlar)."""
    from app.core.db import get_sessionmaker
    from app.services.code_analysis import run_code_analysis

    session = get_sessionmaker()()
    try:
        return run_code_analysis(session, get_config())
    finally:
        session.close()


@router.get("/code-analysis/overview")
def code_analysis_overview(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    """Tüm şirketin genel AI kod sağlığı (admin)."""
    from app.services.code_health import company_code_health

    return company_code_health(session, get_config())


@router.get("/code-analysis/overview/breakdown")
def code_analysis_overview_breakdown(session: Session = Depends(get_session), _: User = Depends(require_admin)):
    from app.services.code_health import company_code_health_breakdown

    return company_code_health_breakdown(session)


@router.get("/code-analysis/developers")
def code_analysis_developers(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Kişi listesi: admin herkesi tek tek analiz edip sonucunu görsün.
    git_email tanımsızsa atıf yapılamaz (analiz edilebilir=false)."""
    from app.models import CodeAnalysis, Developer
    from app.services.code_health import _latest_per_file

    out = []
    for dev in session.scalars(select(Developer)):
        git_email = (dev.external_ids or {}).get("git")
        files = _latest_per_file(list(session.scalars(
            select(CodeAnalysis).where(CodeAnalysis.developer_id == dev.id))))
        composite = round(sum(f.composite for f in files) / len(files), 1) if files else None
        out.append({
            "id": dev.id, "display_name": dev.display_name,
            "git_email": git_email, "analyzable": bool(git_email),
            "analyzed_files": len(files), "composite": composite,
        })
    out.sort(key=lambda d: d["display_name"].lower())
    return out


@router.post("/code-analysis/run-developer/{dev_id}")
def run_code_analysis_developer(dev_id: int, _: User = Depends(require_admin)):
    """Admin, tek bir kişinin kodunu (git yazarı) isteğe bağlı analiz eder."""
    from app.core.db import get_sessionmaker
    from app.services.code_analysis import run_code_analysis

    session = get_sessionmaker()()
    try:
        return run_code_analysis(session, get_config(), only_developer_id=dev_id)
    finally:
        session.close()


@router.post("/sync")
def trigger_sync(_: User = Depends(require_admin)):
    """Elle senkron: kaynaklardan çek + metrik hesapla + öneri üret."""
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    return {"ok": True, "stats": stats}
