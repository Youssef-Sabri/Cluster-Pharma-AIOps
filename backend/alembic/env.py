"""Alembic environment (async template) — ClusterOps backend.

Responsibilities
----------------
* Point Alembic at the ORM metadata (:mod:`app.models`) so ``--autogenerate``
  diffs the live PostgreSQL schema against the models.
* Inject the connection URL from :mod:`app.config`, keeping ``.env`` the single
  source of truth (nothing hardcoded in ``alembic.ini``).
* Run migrations through ``async_engine_from_config`` with ``NullPool``; the
  migration itself is executed synchronously via ``connection.run_sync`` so that
  ``op.*`` operations keep working on a normal sync ``Connection``.

Tables are created exclusively through this migration chain — never through
``Base.metadata.create_all()``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models import Base

# Alembic Config object, providing access to alembic.ini values.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate target — all five tables are registered on import.
target_metadata: Base = Base.metadata


def _database_url() -> str:
    """Resolve the migration URL.

    Precedence: an explicit ``sqlalchemy.url`` (CLI ``-x``, or ``Config`` used
    by the test-suite to migrate the disposable ``clusterops_test`` database)
    > ``settings.database_url`` from ``.env``.  ``alembic.ini`` ships with an
    empty value, so production always resolves through :mod:`app.config`.
    """
    from_config = (config.get_main_option("sqlalchemy.url", None) or "").strip()
    if from_config:
        return from_config
    return settings.database_url


# `%%` escaping is required because ConfigParser treats `%` as interpolation.
config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))


def _common_kwargs() -> dict[str, Any]:
    """Autogenerate comparison options shared by online and offline runs.

    ``compare_type``/``compare_server_default`` matter here because the schema
    relies on server defaults (``gen_random_uuid()``, ``NOW()``) and on
    ``TIMESTAMPTZ`` columns, which Alembic would otherwise silently miss.
    """
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "compare_indexes": True,
        "include_schemas": False,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_common_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an already-established (sync) connection."""
    context.configure(connection=connection, **_common_kwargs())
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create the async engine and drive ``do_run_migrations`` through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def _uses_async_driver(url: str) -> bool:
    """``True`` when the URL is bound to an asyncio driver (asyncpg)."""
    return "+asyncpg" in url


def run_migrations_online() -> None:
    """Entry point for online migrations.

    The application URL is async (``postgresql+asyncpg://``, the ``-t async``
    template).  A synchronous URL is also accepted so the test-suite and
    maintenance tooling can migrate the disposable database without building a
    second configuration file.
    """
    if _uses_async_driver(_database_url()):
        asyncio.run(run_async_migrations())
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            do_run_migrations(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()