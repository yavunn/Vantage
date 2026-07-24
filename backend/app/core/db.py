"""SQLAlchemy engine/session yönetimi.

PostgreSQL birincil hedeftir; tip seçimleri (DateTime(timezone=True), JSON)
SQLite ile de uyumludur ki testler sunucusuz koşabilsin.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_config


class Base(DeclarativeBase):
    pass


# Migration'sız ortamlarda (portable pg / sqlite demo) mevcut tablolara sonradan
# eklenen kolonları güvenle ekler. create_all yalnız EKSİK TABLOYU yaratır;
# var olan tabloya kolon EKLEMEZ. Bu yüzden bu idempotent yama gerekir.
_COLUMN_PATCHES: dict[str, dict[str, str]] = {
    "users": {
        "title": "VARCHAR(120)",
        "phone": "VARCHAR(40)",
        "timezone": "VARCHAR(60)",
        "bio": "TEXT",
        "last_login_at": "TIMESTAMP WITH TIME ZONE",
        # Baş yönetici (owner): en üst yetki, kimse silemez/rütbe düşüremez.
        "is_owner": "BOOLEAN DEFAULT FALSE",
        # İK alanları: işe giriş + yıllık izin hakkı.
        "hire_date": "DATE",
        "annual_allowance": "INTEGER DEFAULT 14",
        # Login brute-force koruması.
        "failed_login_count": "INTEGER DEFAULT 0",
        "locked_until": "TIMESTAMP WITH TIME ZONE",
    },
    "leaves": {
        # Yönetici karar notu (red gerekçesi). Migration'sız ortamda da eklenir.
        "decision_note": "TEXT",
    },
    "survey_cycles": {
        # Döngü açılışında dondurulan soru snapshot'ı (JSON metni).
        "questions_json": "TEXT",
    },
}


def ensure_schema_patches() -> None:
    engine = get_engine()
    insp = inspect(engine)
    sqlite = engine.url.get_backend_name() == "sqlite"
    with engine.begin() as conn:
        for table, cols in _COLUMN_PATCHES.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name in existing:
                    continue
                col_type = "TEXT" if sqlite and "TIMESTAMP" in ddl else ddl
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {col_type}'))


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_config().database_url
        # SQLite'ta çoklu-thread erişimi (uvicorn) için gerekli
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Testlerde farklı DB'ye bağlanmak için."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
