"""FastAPI uygulaması.

- /api/*  : REST uçları
- /       : frontend build çıktısı (frontend/dist) — tek process, on-prem
- APScheduler: config'teki aralıkla periyodik senkron + hesap (0 = kapalı)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.leave import router as leave_router
from app.api.routes import router
from app.api.user_projects import router as user_projects_router
from app.core.config import PROJECT_ROOT, get_config
from app.core.db import Base, get_engine
from app.services.pipeline import run_pipeline

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    Base.metadata.create_all(get_engine())  # şema garanti (alembic da mevcut)
    scheduler = None
    if cfg.sync.interval_minutes > 0:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            run_pipeline, "interval", minutes=cfg.sync.interval_minutes,
            id="sync", coalesce=True, max_instances=1,
        )
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Engineering Health Dashboard",
    description="On-prem mühendislik sağlığı panosu — takım/süreç odaklı, "
                "bireysel gözetim aracı DEĞİLDİR.",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(user_projects_router)
app.include_router(leave_router)
app.include_router(router)

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
