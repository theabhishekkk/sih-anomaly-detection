from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.storage import metadata
from backend.settings import normalize_database_url

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

configured_database_url = (
    context.config.attributes.get("database_url")
    or os.getenv("DATABASE_URL", "").strip()
)
if not configured_database_url:
    raise RuntimeError("DATABASE_URL must be configured to run database migrations.")
database_url = normalize_database_url(configured_database_url)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        pool_pre_ping=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
