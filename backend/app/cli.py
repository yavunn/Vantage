"""Komut satırı girişleri.

  python -m app.cli init-db   # şemayı oluştur
  python -m app.cli sync      # çek + hesapla + öner (tek seferlik)
  python -m app.cli serve     # API + dashboard sun
  python -m app.cli set-password <email> <parola>  # bir hesabın parolasını ayarla
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


def analyze_code() -> None:
    """python -m app.cli analyze-code — git_log repolarındaki değişen dosyaları
    AI ile analiz eder (llm.enabled + code_analysis.enabled gerektirir)."""
    from app.core.config import get_config
    from app.core.db import get_sessionmaker
    from app.services.code_analysis import run_code_analysis

    session = get_sessionmaker()()
    try:
        print("Kod analizi:", run_code_analysis(session, get_config()))
    finally:
        session.close()


def serve() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


def set_password() -> None:
    """python -m app.cli set-password <email> <parola>"""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.core.security import hash_password
    from app.models import User

    if len(sys.argv) < 4:
        print("Kullanım: python -m app.cli set-password <email> <parola>")
        sys.exit(1)
    email, password = sys.argv[2].lower(), sys.argv[3]
    session = get_sessionmaker()()
    try:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"Hesap yok: {email}")
            sys.exit(1)
        user.password_hash = hash_password(password)
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        session.commit()
        print(f"Parola ayarlandı: {email} (role={user.role})")
    finally:
        session.close()


COMMANDS = {
    "init-db": init_db,
    "sync": sync,
    "analyze-code": analyze_code,
    "serve": serve,
    "set-password": set_password,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[cmd]()
