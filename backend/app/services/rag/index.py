"""Benzerlik araması.

TASARIM NOTU — neden pgvector uygulaması YOK:

Spec iki uygulama istiyordu (pgvector + bellek). Kurulumdaki PostgreSQL 17.5'te
`vector` eklentisi mevcut değil (`pg_available_extensions` boş döndü), yani
pgvector yolu bugün ÇALIŞTIRILAMAZ. Çalıştırılamayan bir kod yolu yazmak, test
edilemeyen ve ilk kullanıldığında kırılacak bir yalan üretir. Üstelik pgvector'ün
şemaya `vector` kolonu eklemesi gerekir; bunu koşullu migration'la yapmak
migration/model şema karşılaştırma testini bozardı.

Bunun yerine:
- `VectorIndex` protokolü duruyor → pgvector sonradan tek dosyada eklenir.
- `pgvector_available()` gerçekten kontrol eder ve `build_index` bunu RAPORLAR;
  `index: pgvector` denmişse eklenti yokken SESSİZCE düşmez, net hata verir.
- Veri hacmi birkaç yüz chunk. Kaba kuvvet kosinüs milisaniyeler sürer; ANN
  indeksi bu ölçekte çözdüğünden fazla sorun yaratır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Config
from app.models import DocChunk
from app.services.rag.embedding import cosine


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    content: str
    source_kind: str
    source_id: int
    score: float


class IndexUnavailable(RuntimeError):
    """İstenen indeks uygulaması bu kurulumda kullanılamaz."""


@runtime_checkable
class VectorIndex(Protocol):
    # team_id ZORUNLU parametre: takım sızıntısını tip düzeyinde engeller.
    # Varsayılan verilseydi, unutulduğunda tüm takımların kayıtları dönerdi.
    def search(self, query_vec: list[float], k: int, team_id: int | None) -> list[Hit]: ...


class InMemoryIndex:
    """Vektörleri DB'den okuyup kosinüsü Python'da hesaplar.

    Takım filtresi SQL'de uygulanır — önce filtrele, sonra skorla: başka takımın
    vektörü hiç belleğe alınmaz."""

    def __init__(self, session: Session, model: str | None = None):
        self.session = session
        self.model = model

    def search(self, query_vec: list[float], k: int, team_id: int | None) -> list[Hit]:
        stmt = select(DocChunk).where(DocChunk.embedding.is_not(None))
        if team_id is not None:
            stmt = stmt.where(DocChunk.team_id == team_id)
        if self.model is not None:
            # Farklı modelle gömülmüş chunk aynı uzayda değildir — kıyaslanmaz.
            stmt = stmt.where(DocChunk.model == self.model)
        scored = [
            Hit(
                chunk_id=row.id,
                content=row.content,
                source_kind=row.source_kind,
                source_id=row.source_id,
                score=cosine(query_vec, list(row.embedding or [])),
            )
            for row in self.session.scalars(stmt)
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


def pgvector_available(session: Session) -> bool:
    """Eklenti bu sunucuda kurulabilir durumda mı? (SQLite'ta her zaman False.)"""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return False
    try:
        row = session.execute(
            text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).first()
    except Exception:  # noqa: BLE001 — tespit başarısızsa indeks yine çalışsın
        return False
    return row is not None


def build_index(session: Session, cfg: Config, model: str | None = None) -> tuple[VectorIndex, str]:
    """(indeks, seçilen_uygulama_adı) döner. Seçim çağıran tarafından LOG'lanır."""
    choice = cfg.rag.index
    if choice == "pgvector":
        raise IndexUnavailable(
            "index: pgvector istendi ama pgvector uygulaması bu kurulumda yok "
            f"(sunucuda eklenti {'mevcut' if pgvector_available(session) else 'YOK'}). "
            "index: auto ya da memory kullanın."
        )
    return InMemoryIndex(session, model), "memory"
