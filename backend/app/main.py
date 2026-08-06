"""FastAPI uygulaması.

- /api/*  : REST uçları
- /       : frontend build çıktısı (frontend/dist) — tek process, on-prem
- APScheduler: config'teki aralıkla periyodik senkron + hesap (0 = kapalı)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.api.admin import router as admin_router
from app.api.annotations import router as annotations_router
from app.api.auth import router as auth_router
from app.api.credentials import router as credentials_router
from app.api.documents import router as documents_router
from app.api.leaves import router as leaves_router
from app.api.projects import router as projects_router
from app.api.routes import router
from app.api.survey import router as survey_router
from app.core.config import PROJECT_ROOT, get_config
from app.core.db import Base, ensure_schema_patches, get_engine
from app.core.i18n import normalize_lang, reset_current_lang, set_current_lang, tr_error
from app.services.pipeline import run_pipeline

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


class LanguageMiddleware(BaseHTTPMiddleware):
    """İsteğin `Accept-Language` başlığını bir ContextVar'a yazar.

    NEDEN MIDDLEWARE: `HTTPException(detail=...)` çağrıları (bkz. `core.i18n.
    tr_error`) düzinelerce dosyada yüzlerce yerde geçiyor. Her birine
    `request: Request` parametresi eklemek imza kirliliği ve unutma riski
    demekti — bir endpoint eklenip lang parametresi unutulursa o uç sessizce
    hep Türkçe hata döner. ContextVar bunu tek merkezden garanti eder."""

    async def dispatch(self, request: Request, call_next):
        token = set_current_lang(normalize_lang(request.headers.get("accept-language")))
        try:
            return await call_next(request)
        finally:
            # ASGI sunucusu aynı thread'i sıradaki isteğe yeniden kullanabilir;
            # sıfırlanmazsa bu isteğin dili bir SONRAKİ isteğe sızar.
            reset_current_lang(token)


def _zamanlanmis_senkron() -> None:
    """Zamanlayıcı işi — elle tetiklenen senkronla AYNI kilidi kullanır.

    max_instances=1 yalnız zamanlayıcının kendi işlerini serileştirir; elle
    tetiklenen senkron ayrı bir iş parçacığında koştuğu için ikisi çakışabilirdi
    (aynı satırları upsert eden iki koşu + yarım veriyle 'kaynakta yok' tespiti).
    Kilit alınamıyorsa bu tur atlanır: bir sonraki aralıkta yeniden denenir."""
    from app.services.sync_job import SYNC_LOCK

    if not SYNC_LOCK.acquire(blocking=False):
        return
    try:
        run_pipeline()
    finally:
        SYNC_LOCK.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.secrets import load_secrets
    load_secrets()  # kalıcı sırları ortama yükle (config'ten önce)
    from app.core.security import ensure_jwt_secret
    ensure_jwt_secret()  # VANTAGE_SECRET yoksa güçlü üret + kalıcı yaz (tahmin edilebilir sabit yok)
    cfg = get_config()
    Base.metadata.create_all(get_engine())  # şema garanti (alembic da mevcut)
    ensure_schema_patches()  # var olan tablolara sonradan eklenen kolonlar
    scheduler = None
    if cfg.sync.interval_minutes > 0:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _zamanlanmis_senkron, "interval", minutes=cfg.sync.interval_minutes,
            id="sync", coalesce=True, max_instances=1,
        )
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Vantage",
    description="On-prem mühendislik sağlığı panosu — takım/süreç odaklı, "
                "bireysel gözetim aracı DEĞİLDİR.",
    lifespan=lifespan,
)
app.add_middleware(LanguageMiddleware)


@app.get("/api/health")
def health():
    """Kimliksiz sağlık kontrolü — izleme/otomasyon buraya bağlanır.

    Bilinçli olarak DAR: yalnız "DB'ye erişebiliyor muyum" ve "en son ne zaman
    senkron oldum". Sürüm/şema/hata detayı gibi iç bilgi sızdırmaz (bu uç
    tokensizdir). DB erişilemiyorsa 503 döner ki yük dengeleyici düğümü
    trafikten alsın."""
    from datetime import datetime, timezone

    from fastapi import HTTPException
    from sqlalchemy import func, select

    from app.core.db import get_sessionmaker
    from app.models import MetricResult

    session = get_sessionmaker()()
    try:
        son = session.scalar(select(func.max(MetricResult.computed_at)))
    except Exception as e:
        raise HTTPException(503, detail=tr_error("Veritabanına erişilemiyor")) from e
    finally:
        session.close()

    yas_dk = None
    if son is not None:
        if son.tzinfo is None:
            son = son.replace(tzinfo=timezone.utc)
        yas_dk = int((datetime.now(timezone.utc) - son).total_seconds() // 60)
    return {
        "status": "ok",
        "database": "ok",
        "last_sync_at": son.isoformat() if son else None,
        "last_sync_age_minutes": yas_dk,
    }


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(projects_router)
app.include_router(credentials_router)
app.include_router(leaves_router)
app.include_router(documents_router)
app.include_router(annotations_router)
app.include_router(survey_router)
app.include_router(router)

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
