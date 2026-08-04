"""Elle tetiklenen senkronun arka plan işi + durumu.

NEDEN: `POST /api/admin/sync` pipeline'ı İSTEK İÇİNDE çalıştırıyordu. Gerçek
kaynakla (GitHub'da repo başına yüzlerce istek, Trello board'ları, embedding
çağrıları) bu dakikalar sürer: kullanıcı ekranda bekler, tarayıcı/proxy zaman
aşımına düşer ve ilerleme hakkında hiçbir bilgi yoktur.

TASARIM KISITI: tek process, on-prem. Ayrı bir worker/kuyruk sistemi KURULMAZ —
zamanlayıcının kullandığı iş parçacığı modelinin aynısı kullanılır ve aynı
"aynı anda tek senkron" garantisi (APScheduler max_instances=1) burada da
korunur: elle tetikleme zamanlayıcı koşusuyla da çakışmaz.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Zamanlayıcı ve elle tetikleme AYNI kilidi kullanır: iki senkron aynı anda
# çalışırsa ikisi de aynı satırları upsert eder ve "kaynakta yok" tespiti
# yarım veriyle çalışabilir.
SYNC_LOCK = threading.Lock()


@dataclass
class SyncJob:
    id: str
    status: str = "running"          # running | done | error
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    stats: dict[str, Any] | None = None
    error: str | None = None
    triggered_by: str | None = None

    def payload(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "stats": self.stats,
            "error": self.error,
            "warnings": (self.stats or {}).get("warnings", []),
        }


_jobs: dict[str, SyncJob] = {}
_last_job_id: str | None = None
_lock = threading.Lock()


def sifirla(timeout: float = 3.0) -> None:
    """Test yalıtımı: çalışan iş bitene kadar bekler, sonra durumu temizler.

    Modül seviyesinde durum tutuluyor (tek process, on-prem tasarımı). Testler
    arasında sıfırlanmazsa bir testin senkronu diğerini 409'a düşürür — giriş
    hız sınırı sayacında da aynı gerekçeyle yapılıyor (bkz. conftest)."""
    global _last_job_id
    if SYNC_LOCK.acquire(timeout=timeout):
        SYNC_LOCK.release()
    with _lock:
        _jobs.clear()
        _last_job_id = None


def son_is() -> SyncJob | None:
    with _lock:
        return _jobs.get(_last_job_id) if _last_job_id else None


def is_getir(job_id: str) -> SyncJob | None:
    with _lock:
        return _jobs.get(job_id)


def calisiyor_mu() -> bool:
    job = son_is()
    return bool(job and job.status == "running")


def baslat(triggered_by: str | None = None, incremental: bool = True) -> tuple[SyncJob | None, str | None]:
    """Arka planda senkron başlatır.

    Döner: (iş, hata_sebebi). Zaten çalışan bir senkron varsa (None, sebep)."""
    global _last_job_id
    if calisiyor_mu():
        return None, "Zaten çalışan bir senkron var — bitmesini bekleyin."
    if not SYNC_LOCK.acquire(blocking=False):
        # Zamanlayıcı o anda senkron yapıyor.
        return None, "Zamanlanmış senkron şu anda çalışıyor — bitmesini bekleyin."

    job = SyncJob(id=uuid.uuid4().hex[:12], triggered_by=triggered_by)
    with _lock:
        _jobs[job.id] = job
        _last_job_id = job.id
        # Bellek sınırı: yalnız son 20 iş tutulur.
        for eski in list(_jobs)[:-20]:
            _jobs.pop(eski, None)

    def _calis() -> None:
        from app.services.pipeline import run_pipeline

        try:
            job.stats = run_pipeline(incremental=incremental)
            job.status = "done"
        except Exception as e:  # noqa: BLE001 — hata kullanıcıya sebebiyle dönmeli
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
        finally:
            job.finished_at = datetime.now(timezone.utc)
            SYNC_LOCK.release()

    threading.Thread(target=_calis, name=f"sync-{job.id}", daemon=True).start()
    return job, None
