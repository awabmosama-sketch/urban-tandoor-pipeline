"""
Alembic environment for Urban Tandoor.

Migrations run against the DIRECT Neon host (non-pooler); the app runs against
the pooled host. PgBouncer transaction pooling rejects the prepared statements
Alembic uses, so we strip "-pooler" here only.

Uses async_engine_from_config + NullPool per the official Alembic async template.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import pgvector.sqlalchemy  # noqa: F401  (registers Vector type for autogenerate)
import app.models  # noqa: F401  (populates SQLModel.metadata before autogenerate)
from app.config import get_settings
from sqlmodel import SQLModel

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- URL: strip "-pooler" so we hit the direct Neon host ---
_raw = get_settings().database_url
_migration_url = _raw.replace("-pooler", "")
config.set_main_option("sqlalchemy.url", _migration_url)

# --- Autogenerate target ---
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Offline mode: emit SQL without a DBAPI."""
    context.configure(
        url=_migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
