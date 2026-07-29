"""Alembic ortamı — DB URL'i uygulama config'inden (YAML/env) okur."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — tablolar metadata'ya kaydolsun
from app.core.config import get_config
from app.core.db import Base
from app.core.secrets import load_secrets

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL'i sır olarak tutuluyor olabilir (DATABASE_URL). Config okunmadan ÖNCE
# yükle; yoksa `alembic upgrade head` config'teki geliştirme varsayılanına
# (sqlite) düşer ve migration'ları YANLIŞ veritabanına uygular.
load_secrets()
config.set_main_option("sqlalchemy.url", get_config().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
