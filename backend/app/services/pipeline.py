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
        # Takımsız repo = commitleri hiçbir takım metriğine girmez (metrik motoru
        # commitleri takımın repolarından çeker). Sessiz kalırsa pano boş görünür
        # ve sebebi anlaşılmaz — senkron bunu açıkça söyler.
        stats["warnings"] = [
            *stats.get("warnings", []),
            *(
                f"Repo '{r['name']}' hiçbir takıma bağlı değil — commitleri hiçbir takım "
                "metriğine girmez. Entegrasyon → Repo'lar bölümünden takım seçin."
                for r in cfg.sources.git.repos
                if isinstance(r, dict) and r.get("name") and not r.get("team")
            ),
        ]
        # RAG indeksi ingest'ten SONRA, metrikten ÖNCE tazelenir: indeks kaynağı
        # normalize şemadır, metrik hesabı değil. Kapalıysa hiç çalışmaz.
        from app.services.rag.embedding import build_embedding_provider
        from app.services.rag.indexer import reindex

        rag_stats = reindex(session, cfg, build_embedding_provider(cfg))
        stats["rag_chunks"] = rag_stats.get("embedded", 0)
        stats["warnings"] = [*stats.get("warnings", []), *rag_stats.get("warnings", [])]

        # Task↔commit önerilerini tazele. İnsan kararlarına DOKUNMAZ — onaylanmış
        # ya da reddedilmiş bağlar olduğu gibi kalır (bkz. task_link.refresh_suggestions).
        # Embedding ucu erişilemezse senkron çökmez, uyarıyla devam eder.
        if cfg.rag.enabled:
            from app.services.task_link import refresh_suggestions
            try:
                link_stats = refresh_suggestions(session, cfg)
                stats["task_links_suggested"] = link_stats["suggested"]
            except Exception as e:  # noqa: BLE001 — öneri üretimi senkronu düşürmesin
                stats["warnings"].append(
                    f"Task↔commit önerileri üretilemedi ({type(e).__name__}) — "
                    "embedding sağlayıcısı erişilebilir mi?"
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
