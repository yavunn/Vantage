"""Uçtan uca pipeline: çek → normalize et → hesapla → öner.

Hem zamanlayıcı (APScheduler) hem CLI buradan geçer — tek gerçek akış.
"""
from __future__ import annotations

from app.adapters.factory import (
    build_git_provider,
    build_quality_provider,
    build_task_provider,
)
from app.core.config import get_config
from app.core.db import get_sessionmaker
from app.metrics.engine import compute_all
from app.rules.engine import run_rules
from app.services.ingest import run_ingest


def run_pipeline() -> dict:
    cfg = get_config()
    session = get_sessionmaker()()
    try:
        stats = run_ingest(
            session,
            build_git_provider(cfg),
            build_task_provider(cfg),
            build_quality_provider(cfg),
        )
        metrics_written = compute_all(session, cfg)
        recs_written = run_rules(session, cfg)
        return {**stats, "metric_results": metrics_written, "recommendations": recs_written}
    finally:
        session.close()
