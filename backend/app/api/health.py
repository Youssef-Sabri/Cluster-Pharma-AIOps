"""``GET /health`` and ``GET /metrics``."""

from __future__ import annotations

import logging
from typing import Any, Final

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.state import state
from app.config import settings
from app.database import check_database
from app.schemas.common import HealthResponse

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.health")

router = APIRouter(tags=["operations"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and model-readiness probe",
    description=(
        "Reports process liveness plus whether PostgreSQL and the Production demand "
        "model are reachable. Returns 200 with `status=\"degraded\"` when the process "
        "is up but a dependency is not — a liveness probe should distinguish "
        "\"restart me\" from \"stop sending me traffic\"."
    ),
    responses={200: {"description": "Probe completed (inspect `status` for the verdict)."}},
)
async def health() -> HealthResponse:
    """Liveness probe. Never raises: a failed dependency is reported, not thrown."""
    db_connected = await check_database()
    models_loaded = state.models_loaded
    return HealthResponse(
        status="ok" if db_connected else "degraded",
        version=settings.app_version,
        models_loaded=models_loaded,
        db_connected=db_connected,
    )


@router.get(
    "/metrics",
    summary="Prometheus metrics scrape",
    description=(
        "Exposes the custom `clusterops_*` series (request throughput and latency, "
        "forecast MAE, match confidence, low-confidence counter, drift PSI) in the "
        "standard Prometheus text exposition format."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Metrics in text exposition format.",
            "content": {"text/plain": {"example": "# HELP clusterops_requests_total ..."}},
        }
    },
    include_in_schema=True,
)
async def metrics() -> Response:
    """Render the default Prometheus registry.

    ``/metrics`` is served by the same middleware-free path as every other
    endpoint, so it is itself counted; scraping every 15 s would otherwise skew
    the throughput numbers it reports.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get(
    "/api/v1/system/state",
    summary="Detail about pre-loaded resources",
    description=(
        "Debugging aid: which singleton resources the lifespan loaded, and any "
        "errors it recorded. Safe to expose in a demo; would be admin-only in production."
    ),
    responses={200: {"description": "Current application state."}},
)
async def system_state() -> dict[str, Any]:
    """Return the pre-loaded singletons and any startup errors."""
    return state.describe()


__all__ = ["health", "metrics", "router", "system_state"]