"""Structured JSON logging configuration.

Rules mandate structured logs with stack traces at ERROR level and forbid
swallowing exceptions.  ``structlog`` is deliberately *not* a dependency of the
pinned requirement set, so this module configures the standard library
``logging`` package with a JSON formatter that is RFC-8259 compliant and works
identically on Python 3.11+.

Usage::

    from app.logging_config import configure_logging
    configure_logging()
    logger.info("seeded", extra={"pharmacies": 50, "orders": 7243})
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import logging.config
import sys
from typing import Any, Final

from app.config import Settings, settings

# Attributes present on every ``LogRecord``; anything else was injected via
# ``extra=`` and belongs in the structured payload.
_RESERVED_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as a single JSON object."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Readable console formatter used when ``LOG_JSON=false``."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)-8s %(name)s :: %(message)s", datefmt="%H:%M:%S")


def configure_logging(db_settings: Settings | None = None) -> None:
    """Install the root log handler.  Idempotent — safe to call from app + CLI."""
    db_settings = db_settings or settings
    handler = logging.StreamHandler(stream=sys.stdout)
    if db_settings.log_json:
        handler.setFormatter(
            JsonFormatter(service=db_settings.app_name, environment=db_settings.environment)
        )
    else:
        handler.setFormatter(HumanFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(db_settings.log_level)

    # Third-party loggers are noisy at DEBUG; keep them at WARNING.
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "asyncio", "httpx", "mlflow", "prefect"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (all app loggers use the ``clusterops.`` prefix)."""
    return logging.getLogger(name if name.startswith("clusterops") else f"clusterops.{name}")


__all__ = ["HumanFormatter", "JsonFormatter", "configure_logging", "get_logger"]