"""``GET /api/v1/model-registry`` — registered model versions from MLflow.

Reads are blocking network I/O against the tracking server, so the handler pushes
them to a worker thread with ``asyncio.to_thread`` (rule: *Async Execution*).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Final

from fastapi import APIRouter

from app.config import settings
from app.ml.mlflow_utils import STAGE_PRODUCTION, build_client, is_server_reachable
from app.schemas.registry import ModelMetadataItem, ModelRegistryResponse

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.registry")

router = APIRouter(prefix="/api/v1", tags=["aiops"])


def _to_item(version: Any, tags: dict[str, str] | None) -> ModelMetadataItem:
    """Adapt an MLflow ``ModelVersion`` entity to the response schema."""
    stage = str(version.current_stage or "None")
    tag_map = tags or {}
    metrics_payload: dict[str, Any] = {}
    try:
        run = version.fetch_mlflow_model()  # type: ignore[attr-defined]
        run_metrics = getattr(getattr(run, "run", None), "data", None)
        if run_metrics is not None and getattr(run_metrics, "metrics", None):
            metrics_payload = {key: float(value) for key, value in run_metrics.metrics.items()}
    except Exception as exc:  # noqa: BLE001 - metrics are a bonus, not a contract
        logger.debug("Could not read run metrics", extra={"version": version.version, "error": str(exc)})

    return ModelMetadataItem(
        name=version.name,
        version=str(version.version),
        stage=stage,
        run_id=version.run_id,
        status="Production" if stage.lower() == STAGE_PRODUCTION.lower() else "candidate",
        registered_at=_as_datetime(version.creation_timestamp),
        last_updated_at=_as_datetime(version.last_updated_timestamp),
        promotion_reason=tag_map.get("promotion_reason"),
        test_mae=_as_float(tag_map.get("test_mae")),
        metrics=metrics_payload,
    )


def _as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)


def _fetch_versions(model_name: str, tracking_uri: str) -> list[ModelMetadataItem]:
    """Blocking MLflow read, executed off the event loop."""
    client = build_client(tracking_uri)
    versions = client.search_model_versions(
        f"name='{model_name}'",
        order_by=["attribute.last_updated_timestamp DESC"],
        max_results=100,
    )
    return [_to_item(version, dict(version.tags or {})) for version in versions]


@router.get(
    "/model-registry",
    response_model=ModelRegistryResponse,
    summary="Active champion and candidate models",
    description=(
        "Lists every registered version of the demand forecaster, newest first, with "
        "its stage, the reason the promotion gate recorded, and the logged run "
        "metrics. `production_version` names the version currently serving traffic.\n\n"
        "If the tracking server cannot be reached the response is `reachable: false` "
        "with an empty `models` list — the endpoint reports the outage instead of "
        "serving stale data as if it were current."
    ),
    responses={
        200: {"description": "Registry contents.", "model": ModelRegistryResponse},
    },
)
async def model_registry() -> ModelRegistryResponse:
    """Return the registered model versions."""
    tracking_uri = settings.mlflow_tracking_uri
    model_name = settings.mlflow_model_name

    reachable = await asyncio.to_thread(is_server_reachable, tracking_uri)
    if not reachable:
        logger.warning("MLflow is unreachable; reporting an empty registry", extra={"uri": tracking_uri})
        return ModelRegistryResponse(
            models=[],
            production_version=None,
            model_name=model_name,
            tracking_uri=tracking_uri,
            reachable=False,
        )

    models = await asyncio.to_thread(_fetch_versions, model_name, tracking_uri)
    production = next((item for item in models if item.status == "Production"), None)
    return ModelRegistryResponse(
        models=models,
        production_version=production.version if production else None,
        model_name=model_name,
        tracking_uri=tracking_uri,
        reachable=True,
    )


__all__ = ["model_registry", "router"]