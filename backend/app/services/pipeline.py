"""Uçtan uca pipeline: çek → normalize et → hesapla → öner.

Hem zamanlayıcı (APScheduler) hem CLI buradan geçer — tek gerçek akış.
"""
from __future__ import annotations

from app.adapters.factory import build_git_provider, build_task_provider
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.metrics.engine import compute_all
from app.rules.engine import run_rules
from app.services.ingest import run_ingest


def run_pipeline() -> dict:
    from app.core.secrets import load_secrets
    load_secrets()  # arayüzden girilen token'lar CLI senkronunda da geçerli olsun
    cfg = get_config()
    session = get_sessionmaker()()
    try:
        # Repo→takım eşlemesi: git_log/gitlab repos config'te 'team' taşıyabilir.
        # Commit/PR normalize kaydı takım bilgisi taşımadığından pano bu eşlemeyle dolar.
        repo_team_map: dict[str, str] = {}
        for r in cfg.sources.git.repos:
            if isinstance(r, dict) and r.get("name") and r.get("team"):
                repo_team_map[r["name"]] = r["team"]

        stats = run_ingest(
            session,
            build_git_provider(cfg),
            build_task_provider(cfg),
            repo_team_map=repo_team_map,
        )
        metrics_written = compute_all(session, cfg)
        recs_written = run_rules(session, cfg)
        # Metrik kırmızıya döndüyse ilgili yönetici/adminlere trend alarmı üret.
        from app.services.notifications import scan_and_emit_trend_alarms
        alarms = scan_and_emit_trend_alarms(session)
        return {
            **stats,
            "metric_results": metrics_written,
            "recommendations": recs_written,
            "trend_alarms": alarms,
        }
    finally:
        session.close()
