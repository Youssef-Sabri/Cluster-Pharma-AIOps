"""Schemas for ``GET /api/v1/model-registry`` and ``POST /api/v1/retrain``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class ModelMetadataItem(ApiModel):
    """One registered model version and the metrics that justify its stage."""

    name: str = Field(description="MLflow registered model name.")
    version: str = Field(description="Model version within the registered model.")
    stage: str = Field(description="`Production`, `Archived` or `None`.")
    run_id: str | None = Field(default=None, description="MLflow run the artifacts came from.")
    status: str = Field(description="`Production` when this version serves traffic, else `candidate`.")
    registered_at: datetime | None = Field(default=None, description="Creation time of the version.")
    last_updated_at: datetime | None = Field(default=None, description="Last stage transition or tag change.")
    promotion_reason: str | None = Field(
        default=None, description="Why the promotion gate accepted or rejected this version."
    )
    test_mae: float | None = Field(default=None, description="Holdout MAE — the number the 3% gate compares.")
    metrics: dict[str, Any] = Field(
        default_factory=dict, description="Logged run metrics, when the tracking server could be read."
    )

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "name": "lgbm-demand-forecast",
                    "version": "1",
                    "stage": "Production",
                    "run_id": "0f1e2d3c4b5a",
                    "status": "Production",
                    "registered_at": "2026-10-17T16:05:00Z",
                    "last_updated_at": "2026-10-17T16:05:03Z",
                    "promotion_reason": "No active Production model found — promoted as the first production model.",
                    "test_mae": 2.3151,
                    "metrics": {"mae": 2.3151, "rmse": 6.2047, "mape": 0.2711},
                }
            ]
        },
    }


class ModelRegistryResponse(ApiModel):
    """200 response for ``GET /api/v1/model-registry``."""

    models: list[ModelMetadataItem] = Field(description="Every registered version, newest first.")
    production_version: str | None = Field(
        default=None, description="Version currently serving traffic, if any."
    )
    model_name: str = Field(description="The registered model these versions belong to.")
    tracking_uri: str | None = Field(default=None, description="Tracking backend the data came from.")
    reachable: bool = Field(
        description="False when MLflow could not be reached; `models` is then empty rather than stale."
    )

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "models": [],
                    "production_version": None,
                    "model_name": "lgbm-demand-forecast",
                    "tracking_uri": "http://mlflow:5000",
                    "reachable": True,
                }
            ]
        },
    }


class RetrainRequest(ApiModel):
    """Ask the nightly flow to run now."""

    force: bool = Field(
        default=False,
        description="Retrain even when no feature reached DRIFT_DETECTED. The drift check still runs and is logged.",
    )
    notify_on_completion: bool = Field(
        default=False, description="Reserved for webhook notification once the flow finishes."
    )
    window_days: int | None = Field(
        default=None,
        ge=7,
        le=365,
        description="Override the training window; defaults to the flow's 90 days.",
    )

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {"examples": [{"force": True, "notify_on_completion": True}]},
    }


class RetrainResponse(ApiModel):
    """202 response for ``POST /api/v1/retrain``."""

    flow_run_id: str = Field(description="Identifier for the submitted run; poll the registry for the outcome.")
    status: Literal["SUBMITTED", "SKIPPED"] = Field(
        description="`SUBMITTED` when the flow was dispatched in the background."
    )
    message: str = Field(description="What happened, in one sentence.")
    estimated_duration_seconds: int = Field(
        description="Rough wall-clock cost: drift check is seconds, training is minutes."
    )
    force: bool = Field(description="Whether the operator forced the run past the drift gate.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "flow_run_id": "b2c3d4e5-6f70-4812-9abc-def012345678",
                    "status": "SUBMITTED",
                    "message": "Retraining flow submitted. Check /api/v1/model-registry for results.",
                    "estimated_duration_seconds": 180,
                    "force": True,
                }
            ]
        },
    }


__all__ = [
    "ModelMetadataItem",
    "ModelRegistryResponse",
    "RetrainRequest",
    "RetrainResponse",
]