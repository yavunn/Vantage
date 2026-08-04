"""RAG bellek indeksinin ölçek davranışını ölçer (İŞ-24).

index.py'nin tasarım notu "veri hacmi birkaç yüz chunk" varsayımını yazıyordu
ama bu HİÇ ölçülmemişti. Bu betik üç hacimde (72 / 5.000 / 20.000 chunk) arama
süresini ve bellek etkisini ölçer; MAX_MEMORY_CHUNKS sabiti bu ölçüme dayanır.

Gerçek embedding sağlayıcısı GEREKMEZ: vektörler sentetik üretilir — ölçülen
şey modelin kalitesi değil, indeksin arama maliyetidir.

Komut: .venv\\Scripts\\python scripts\\rag_scale_test.py
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BOYUT = 1024   # bge-m3 vektör boyutu
HACIMLER = (72, 5_000, 20_000)


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="vantage-rag-")) / "rag.db"
    cfg = db.parent / "config.yaml"
    cfg.write_text(
        f'database: {{url: "sqlite:///{db.as_posix()}"}}\n'
        "sync: {interval_minutes: 0}\nllm: {enabled: false}\n",
        encoding="utf-8",
    )
    os.environ["VANTAGE_CONFIG"] = str(cfg)
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"

    import app.models  # noqa: F401
    from app.core.config import reset_config_cache
    from app.core.db import Base, get_engine, get_sessionmaker, reset_engine
    from app.models import DocChunk, Team
    from app.services.rag.index import InMemoryIndex, invalidate_cache

    reset_config_cache()
    reset_engine()
    Base.metadata.create_all(get_engine())
    session = get_sessionmaker()()

    team = Team(name="T")
    session.add(team)
    session.commit()

    rnd = random.Random(7)
    sorgu = [rnd.uniform(-1, 1) for _ in range(BOYUT)]
    print(f"{'chunk':>8} {'ilk arama':>12} {'önbellekli':>12} {'tepe bellek':>12}")
    eklendi = 0
    for hedef in HACIMLER:
        toplu = []
        for i in range(eklendi, hedef):
            toplu.append(DocChunk(
                source_kind="task", source_id=i, chunk_index=0, team_id=team.id,
                content=f"kayıt {i}", content_hash=f"h{i}", model="test",
                embedding=[rnd.uniform(-1, 1) for _ in range(BOYUT)],
            ))
            if len(toplu) >= 2000:
                session.bulk_save_objects(toplu)
                session.commit()
                toplu = []
        if toplu:
            session.bulk_save_objects(toplu)
            session.commit()
        eklendi = hedef

        invalidate_cache()
        idx = InMemoryIndex(session, model="test")
        # Bellek: önbellek tüm vektörleri süreçte tutar — ölçeğin asıl maliyeti
        # süre kadar bellektir ve bu hiç ölçülmemişti.
        tracemalloc.start()
        t0 = time.perf_counter()
        idx.search(sorgu, 3, team.id)
        ilk = time.perf_counter() - t0
        _, tepe = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        t0 = time.perf_counter()
        idx.search(sorgu, 3, team.id)
        onbellekli = time.perf_counter() - t0
        print(f"{hedef:>8} {ilk:>11.3f}s {onbellekli:>11.3f}s {tepe / 1024 / 1024:>9.1f} MB"
              + ("   ← uyarı üretildi" if idx.warnings else ""))

    session.close()
    reset_engine()
    try:
        db.unlink(missing_ok=True)
        cfg.unlink(missing_ok=True)
        db.parent.rmdir()
        print(f"\nGeçici veritabanı silindi: {db}")
    except OSError as e:
        print(f"\nGeçici dosya silinemedi ({e}) — yol: {db.parent}")


if __name__ == "__main__":
    main()
