"""Async database engine, session factory and FastAPI session dependency.

The whole application talks to PostgreSQL through SQLAlchemy 2's asyncio layer
driven by ``asyncpg`` (rules: *Database access must use asynchronous sessions*).
Nothing in this module performs I/O at import time, so importing it is always
cheap and never blocks the event loop.

Synthetic data only — demonstration purposes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Final

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import Settings, settings

logger: Final[logging.Logger] = logging.getLogger("clusterops.database")

# Statement timeout applied to every pooled connection (milliseconds).
STATEMENT_TIMEOUT_MS: Final[int] = 15_000


def _engine_options(db_settings: Settings, *, url: str | None = None) -> dict[str, object]:
    """Build the keyword arguments shared by every engine created here."""
    return {
        "echo": db_settings.db_echo,
        "pool_size": db_settings.db_pool_size,
        "max_overflow": db_settings.db_max_overflow,
        "pool_pre_ping": True,
        "connect_args": {
            "server_settings": {"application_name": "clusterops", "statement_timeout": str(STATEMENT_TIMEOUT_MS)},
            "timeout": 10,
        },
    }


def build_async_engine(db_settings: Settings | None = None, *, url: str | None = None) -> AsyncEngine:
    """Create a pooled async engine for ``url`` (defaults to ``settings.database_url``).

    Exposed as a factory so tests can point an isolated engine at the disposable
    ``clusterops_test`` database without mutating global state.
    """
    db_settings = db_settings or settings
    target_url = url or db_settings.database_url
    return create_async_engine(target_url, **_engine_options(db_settings, url=target_url))  # type: ignore[arg-type]


def build_sync_engine(db_settings: Settings | None = None, *, url: str | None = None) -> Engine:
    """Create a sync (psycopg2) engine.

    Used by Alembic ``env.py`` and by the test bootstrap; the application
    runtime never uses it.  Uses ``NullPool`` so short-lived helper connections
    are never held open.
    """
    db_settings = db_settings or settings
    target_url = url or db_settings.sync_database_url
    return create_engine(  # type: ignore[call-overload]
        target_url,
        echo=db_settings.db_echo,
        poolclass=NullPool,
        connect_args={"options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}", "connect_timeout": 10},
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an ``async_sessionmaker`` bound to ``engine``."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


# Process-wide engine / session factory used by the API and the pipelines.
engine: Final[AsyncEngine] = build_async_engine()
async_session_factory: Final[async_sessionmaker[AsyncSession]] = build_session_factory(engine)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped :class:`AsyncSession`.

    Rolls back on failure and always closes the session.  Usage::

        @router.get("/things")
        async def list_things(db: AsyncSession = Depends(get_db)) -> list[Thing]: ...
    """
    session: AsyncSession = async_session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def build_probe_engine(db_settings: Settings | None = None) -> AsyncEngine:
    """Create a throwaway ``NullPool`` engine for the liveness probe.

    The probe deliberately does **not** use the shared serving pool.  A pooled
    connection is bound to the event loop that first checked it out, so reusing
    one from a different loop fails even though PostgreSQL is perfectly healthy
    — a false "database is down" from a liveness endpoint is worse than no probe
    at all.  A throwaway ``NullPool`` engine always opens a fresh connection in
    whichever loop is asking, and is disposed immediately afterwards.
    """
    target = (db_settings or settings).database_url
    return create_async_engine(
        target,
        poolclass=NullPool,
        future=True,
        connect_args={"timeout": 5},
    )


async def check_database() -> bool:
    """Return ``True`` when a trivial round-trip to PostgreSQL succeeds.

    Used by ``GET /health``; failures are logged and reported, never raised.
    """
    engine = build_probe_engine()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - health probes must never raise
        logger.warning("Database health check failed", extra={"error": str(exc)})
        return False
    finally:
        await engine.dispose()


async def dispose_engine() -> None:
    """Dispose the pooled engine (application shutdown hook)."""
    await engine.dispose()


def sync_url_to_async(sync_url: str) -> str:
    """Convert a psycopg2 URL to its asyncpg equivalent.

    Alembic and the test bootstrap work with sync URLs; the ORM layer needs the
    async driver.  Keeping the conversion in one place avoids ad-hoc string
    surgery at call sites.
    """
    url = make_url(sync_url)
    if url.drivername.startswith("postgresql+asyncpg"):
        return sync_url
    return str(url.set(drivername="postgresql+asyncpg"))


def create_sync_session(engine: Engine) -> Session:
    """Return a sync session for Alembic env / CLI tooling."""
    return Session(engine, expire_on_commit=False)


__all__ = [
    "STATEMENT_TIMEOUT_MS",
    "async_session_factory",
    "build_async_engine",
    "build_probe_engine",
    "build_session_factory",
    "build_sync_engine",
    "check_database",
    "create_sync_session",
    "dispose_engine",
    "engine",
    "get_db",
    "sync_url_to_async",
]