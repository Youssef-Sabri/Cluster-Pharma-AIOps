"""Shared schema building blocks for the ClusterOps API.

Keeping these in one module means every endpoint renders the same shape for
errors and health, so a client only has to learn one envelope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Timezone-aware current time, used as a response default."""
    return datetime.now(tz=timezone.utc)


class ApiModel(BaseModel):
    """Base for every request/response schema.

    ``extra="forbid"`` turns a misspelled field into a 422 instead of silently
    dropping it — on a write endpoint a typo in ``pharmacy_id`` that is quietly
    ignored is worse than a rejected request.

    ``protected_namespaces=()`` is set because several response schemas
    legitimately carry ``model_name`` / ``model_version``, which pydantic
    otherwise reserves for its own namespace.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        protected_namespaces=(),
    )


class ErrorDetail(ApiModel):
    """RFC 7807 problem detail."""

    type: str = Field(default="about:blank", description="URI identifying the problem type.")
    title: str = Field(description="Short, human-readable summary of the problem.")
    status: int = Field(description="HTTP status code, repeated in the body for clients that log bodies only.")
    detail: str = Field(description="Explanation specific to this occurrence of the problem.")
    instance: str | None = Field(default=None, description="Path of the request that produced the problem.")


class ErrorResponse(ApiModel):
    """Envelope returned for every 4xx/5xx response."""

    error: ErrorDetail


class HealthResponse(ApiModel):
    """``GET /health`` payload."""

    status: str = Field(description="'ok' when the process is serving; 'degraded' when a dependency is down.")
    version: str = Field(description="Application version.")
    models_loaded: bool = Field(description="Whether a Production demand model is resident in memory.")
    db_connected: bool = Field(description="Whether PostgreSQL answered the health probe.")
    timestamp: datetime = Field(default_factory=utc_now, description="Timezone-aware UTC time of the probe.")

    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
                    "version": "1.0.0",
                    "models_loaded": True,
                    "db_connected": True,
                    "timestamp": "2026-10-17T18:00:00Z",
                }
            ]
        },
    )


class MessageResponse(ApiModel):
    """Simple acknowledgement body."""

    message: str = Field(description="Human-readable confirmation.")
    detail: dict[str, Any] = Field(default_factory=dict, description="Structured payload for the client.")


__all__ = [
    "ApiModel",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "MessageResponse",
    "utc_now",
]