"""Benzerlik araması.

ÖLÇEK: bellek içi arama ÖLÇÜLDÜ (bkz. MAX_MEMORY_CHUNKS yorumundaki tablo).
5.000 chunk'a kadar önbellekli arama saniye altında; ötesinde sistem sessizce
yavaşlamak yerine uyarı üretir. pgvector gerektiren nokta orasıdır.

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
- Veri hacmi ÖLÇÜLDÜ: 72 chunk'ta arama 0,033 sn, 5.000'de 0,64 sn (önbellekli).
  Bu ölçekte kaba kuvvet kosinüs yeterli; ANN
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


# Bellek indeksinin ÖLÇÜLMÜŞ sınırı — tahmin değil (scripts/rag_scale_test.py,
# bge-m3 boyutu 1024, bu makine):
#
#     chunk    ilk arama   önbellekli   tepe bellek
#        72       0.033s       0.009s        3,9 MB
#     5.000       2.354s       0.642s      264   MB
#    20.000       9.813s       2.531s     1.056   MB  (≈1 GB)
#
# NOT: süreler tracemalloc KAPALI koşudan, bellek AÇIK koşudandır. tracemalloc
# her ayırmayı izlediği için süreleri ~5 kat şişiriyor; ikisini aynı koşudan
# almak yanıltıcı olurdu.
#
# Maliyet doğrusal büyüyor. 5.000'de önbellekli arama hâlâ saniye altında
# (264 MB — tek process on-prem için kabul edilebilir üst sınır); 20.000'de
# her soru önbellekliyken bile 2,5 sn sürüyor ve önbellek ~1 GB tutuyor —
# kullanıcı için "bozuk" hissi veren nokta burası. Sınır bu yüzden 5.000.
#
# Dosyanın eski tasarım notu ölçeği yalnız yorumda ("veri hacmi birkaç yüz
# chunk") varsayıyordu ve aşıldığında sistem hata vermiyor, SESSİZCE
# yavaşlıyordu — kullanıcı sebebini göremiyordu.
MAX_MEMORY_CHUNKS = 5_000

# Süreç içi vektör önbelleği: aynı takım için her soruda tüm vektörleri yeniden
# okumak gereksiz. Anahtar (team_id, model); indeks tazelendiğinde (reindex)
# geçersiz kılınır — bayat vektörle cevap üretmek yanlış kaynak göstermektir.
_CACHE: dict[tuple[int | None, str | None], tuple[int, list]] = {}


def invalidate_cache() -> None:
    """Indeks değiştiğinde çağrılır (reindex sonu)."""
    _CACHE.clear()


class InMemoryIndex:
    """Vektörleri DB'den okuyup kosinüsü Python'da hesaplar.

    Takım filtresi SQL'de uygulanır — önce filtrele, sonra skorla: başka takımın
    vektörü hiç belleğe alınmaz."""

    def __init__(self, session: Session, model: str | None = None):
        self.session = session
        self.model = model
        self.warnings: list[str] = []

    def _rows(self, team_id: int | None):
        anahtar = (team_id, self.model)
        onbellek = _CACHE.get(anahtar)
        if onbellek is not None:
            return onbellek[1]
        stmt = select(DocChunk).where(DocChunk.embedding.is_not(None))
        if team_id is not None:
            stmt = stmt.where(DocChunk.team_id == team_id)
        if self.model is not None:
            # Farklı modelle gömülmüş chunk aynı uzayda değildir — kıyaslanmaz.
            stmt = stmt.where(DocChunk.model == self.model)
        satirlar = [
            (r.id, r.content, r.source_kind, r.source_id, list(r.embedding or []))
            for r in self.session.scalars(stmt)
        ]
        _CACHE[anahtar] = (len(satirlar), satirlar)
        return satirlar

    def search(self, query_vec: list[float], k: int, team_id: int | None) -> list[Hit]:
        satirlar = self._rows(team_id)
        if len(satirlar) > MAX_MEMORY_CHUNKS:
            # SESSİZ yavaşlama yerine net sınır: cevap yine üretilir ama
            # kullanıcı ölçeğin aşıldığını öğrenir (pgvector gerekir).
            self.warnings.append(
                f"Asistan indeksi {len(satirlar)} kayda ulaştı; bellek içi arama "
                f"{MAX_MEMORY_CHUNKS} kayda kadar ölçülmüştür. Cevaplar yavaşlayabilir — "
                "bu ölçekte pgvector kurulumu gerekir."
            )
        scored = [
            Hit(chunk_id=cid, content=icerik, source_kind=kind, source_id=sid,
                score=cosine(query_vec, vec))
            for cid, icerik, kind, sid, vec in satirlar
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
