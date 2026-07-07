"""Komut satırı girişleri.

  python -m app.cli init-db   # şemayı oluştur
  python -m app.cli sync      # çek + hesapla + öner (tek seferlik)
  python -m app.cli serve     # API + dashboard sun
"""
from __future__ import annotations

import sys

from app.core.db import Base, get_engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())
    print("Şema oluşturuldu.")


def sync() -> None:
    from app.services.pipeline import run_pipeline

    stats = run_pipeline()
    print("Senkron tamam:", stats)


def serve() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


COMMANDS = {"init-db": init_db, "sync": sync, "serve": serve}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[cmd]()
