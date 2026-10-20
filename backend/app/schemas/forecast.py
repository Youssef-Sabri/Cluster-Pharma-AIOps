"""Request/response schemas for ``POST /api/v1/forecast``.

Synthetic data only — the payloads describe forecasts over generated demand.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field, field_validator

from app.ml.features import MAX_LOOKBACK_DAYS
from app.schemas.common import ApiModel, utc_now

#: Guard rails on the requested horizon.  The upper bound keeps one request from
#: pinning the event loop for a large batch of LightGBM predictions.
MIN_HORIZON_DAYS: int = 1
MAX_HORIZON_DAYS: int = 30

#: How much history is read per series before forecasting.  Must cover
#: ``lag_14``; the extra days absorb calendar gaps in sparse panels.
HISTORY_DAYS: int = MAX_LOOKBACK_DAYS + 14


class ForecastRequest(ApiModel):
    """Ask for a demand forecast for one pharmacy across several products."""

    pharmacy_id: str = Field(
        min_length=1,
        max_length=50,
        description="Pharmacy identifier, e.g. `PH-001`.",
        examples=["PH-001"],
    )
    product_ids: list[str] = Field(
        min_length=1,
        max_length=50,
        description="Catalogue ids to forecast. An unknown id is reported as a 404 detail, not silently skipped.",
        examples=[["panadol-extra-500", "augmentin-625"]],
    )
    forecast_horizon_days: int = Field(
        default=7,
        ge=MIN_HORIZON_DAYS,
        le=MAX_HORIZON_DAYS,
        description="Number of consecutive future days to score, starting the day after the last observation.",
    )

    @field_validator("product_ids")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        """Drop blank ids and preserve order while removing duplicates."""
        seen: list[str] = []
        for product_id in value:
            cleaned = product_id.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        if not seen:
            raise ValueError("product_ids must contain at least one non-empty id")
        return seen

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "pharmacy_id": "PH-001",
                    "product_ids": ["panadol-extra-500", "augmentin-625"],
                    "forecast_horizon_days": 7,
                }
            ]
        },
    }


class ForecastItem(ApiModel):
    """One product's forecast over the requested horizon."""

    product_id: str = Field(description="Catalogue id that was forecast.")
    product_name: str | None = Field(
        default=None, description="Display name from the catalogue, when known."
    )
    dates: list[date] = Field(description="Calendar days scored, in ascending order.")
    predicted_units: list[float] = Field(description="Median forecast per day.")
    lower_bound: list[float] = Field(description="10th percentile of the predictive interval per day.")
    upper_bound: list[float] = Field(description="90th percentile of the predictive interval per day.")
    mae_last_7d: float | None = Field(
        default=None,
        ge=0.0,
        description="In-sample MAE over the 7 observed days before the horizon; null when history is short.",
    )

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "product_id": "panadol-extra-500",
                    "product_name": "Panadol Extra 500mg",
                    "dates": ["2026-10-18", "2026-10-19"],
                    "predicted_units": [42.0, 38.0],
                    "lower_bound": [35.0, 30.0],
                    "upper_bound": [49.0, 46.0],
                    "mae_last_7d": 4.2,
                }
            ]
        },
    }


class ForecastResponse(ApiModel):
    """200 response for ``POST /api/v1/forecast``."""

    pharmacy_id: str = Field(description="Pharmacy the forecast belongs to.")
    generated_at: datetime = Field(default_factory=utc_now, description="Timezone-aware UTC generation time.")
    model_version: str = Field(description="Registry version that produced the numbers.")
    model_name: str = Field(description="MLflow registered model name.")
    forecast_horizon_days: int = Field(description="Days scored per product.")
    forecasts: list[ForecastItem] = Field(description="One entry per product with enough history to forecast.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "pharmacy_id": "PH-001",
                    "generated_at": "2026-10-17T18:00:00Z",
                    "model_version": "1",
                    "model_name": "lgbm-demand-forecast",
                    "forecast_horizon_days": 2,
                    "forecasts": [],
                }
            ]
        },
    }


class ForecastUnavailableResponse(ApiModel):
    """503 body returned when no Production model is resident in memory."""

    detail: str = Field(description="Why the forecast could not be produced.")
    hint: str = Field(
        default="Run `python -m app.ml.forecast_model --train --register` and restart the API.",
        description="Actionable next step for the operator.",
    )


__all__ = [
    "HISTORY_DAYS",
    "MAX_HORIZON_DAYS",
    "MIN_HORIZON_DAYS",
    "ForecastItem",
    "ForecastRequest",
    "ForecastResponse",
    "ForecastUnavailableResponse",
]