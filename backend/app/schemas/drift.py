"""Schemas for ``GET /api/v1/drift-status``.

Synthetic data only — PSI is computed over generated distributions.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.drift_log import STATUS_DRIFT_DETECTED, STATUS_OK, STATUS_WARNING
from app.schemas.common import ApiModel

DriftStatus = str
"""One of ``OK`` / ``WARNING`` / ``DRIFT_DETECTED`` — see :mod:`app.ml.drift_detector`."""


class DriftFeatureItem(ApiModel):
    """PSI for one monitored feature at the latest evaluation."""

    feature_name: str = Field(description="Monitored feature, e.g. `daily_units_sold`.")
    psi_score: float = Field(ge=0.0, description="Population Stability Index for the current window.")
    status: DriftStatus = Field(
        description=f"`{STATUS_OK}` / `{STATUS_WARNING}` / `{STATUS_DRIFT_DETECTED}`."
    )
    checked_at: datetime = Field(description="When this observation was written.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {"feature_name": "daily_units_sold", "psi_score": 0.3677, "status": STATUS_DRIFT_DETECTED,
                 "checked_at": "2026-10-17T17:45:00Z"}
            ]
        },
    }


class DriftStatusResponse(ApiModel):
    """200 response for ``GET /api/v1/drift-status``."""

    checked_at: datetime | None = Field(
        default=None, description="Newest observation across all features, or null when none exist yet."
    )
    overall_status: DriftStatus = Field(
        description="Worst status across the monitored features.",
    )
    max_psi: float = Field(ge=0.0, description="Highest PSI across the monitored features.")
    psi_threshold: float = Field(ge=0.0, description="PSI at or above which a feature counts as drift.")
    features: list[DriftFeatureItem] = Field(description="One entry per monitored feature.")
    retraining_triggered: bool = Field(
        description="Whether the latest evaluation caused the retraining flow to fire."
    )
    evaluated: bool = Field(description="False when the drift table is empty and nothing could be reported.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "checked_at": "2026-10-17T17:45:00Z",
                    "overall_status": STATUS_DRIFT_DETECTED,
                    "max_psi": 0.3677,
                    "psi_threshold": 0.2,
                    "features": [],
                    "retraining_triggered": True,
                    "evaluated": True,
                }
            ]
        },
    }


__all__ = ["DriftFeatureItem", "DriftStatus", "DriftStatusResponse"]