"""Serving runtime — the in-memory model the API answers forecasts from.

The FastAPI process holds one :class:`ForecastRuntime`, built once at startup by
:func:`load_production_runtime`.  It owns:

* the three LightGBM boosters restored from the MLflow ``Production`` version,
* the registry version string reported to clients and stamped into ``predictions``,
* the catalogue matcher, so order matching is a pure in-memory lookup.

Why the boosters are attached to a :class:`DemandForecaster` rather than wrapped
in a new predictor: the API must not reimplement prediction.  Attaching them means
online inference runs the *same* :meth:`DemandForecaster.predict` — same feature
matrix, same non-negativity clipping, same interval ordering — that offline
evaluation used, and features still come only from
:func:`app.ml.features.build_inference_frame`.  Both halves of the zero-skew rule
therefore hold by construction rather than by review.

Nothing here is imported at module import time on a request path: MLflow and
LightGBM loading happen once during the lifespan handler.

Synthetic data only — the loaded model was trained on generated data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

import pandas as pd

from app.logging_config import get_logger
from app.ml.forecast_model import DemandForecaster
from app.ml.mlflow_utils import (
    MODEL_NAME,
    MlflowUnavailableError,
    RegisteredModelVersion,
    get_production_model,
    load_booster_from_uri,
)
from app.ml.order_matcher import CatalogueMatcher, OrderMatcher, load_catalogue_from_database

logger: Final[logging.Logger] = get_logger("ml.serving")

#: Artifact paths written by :func:`app.ml.mlflow_utils.evaluate_and_register`.
POINT_ARTIFACT: Final[str] = "model"
LOWER_ARTIFACT: Final[str] = "lower_model"
UPPER_ARTIFACT: Final[str] = "upper_model"


class ModelUnavailableError(RuntimeError):
    """Raised when a forecast is requested but no model is loaded."""


@dataclass(frozen=True, slots=True)
class ForecastRuntime:
    """A loaded model plus the metadata the API reports alongside it."""

    forecaster: DemandForecaster
    model_version: str
    model_name: str
    loaded_at: datetime
    run_id: str | None = None

    @property
    def models_loaded(self) -> bool:
        """``True`` when this runtime can actually serve predictions."""
        return self.forecaster.is_loaded()

    def describe(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "run_id": self.run_id,
            "loaded_at": self.loaded_at.isoformat(),
            "models_loaded": self.models_loaded,
        }


def build_runtime(
    forecaster: DemandForecaster,
    *,
    model_version: str,
    model_name: str = MODEL_NAME,
    run_id: str | None = None,
    loaded_at: datetime | None = None,
) -> ForecastRuntime:
    """Wrap an already-fitted forecaster as a serving runtime.

    Used by the production loader and by tests, which hand over a forecaster
    trained on synthetic data rather than restoring one from MLflow.
    """
    if not forecaster.is_loaded():
        raise ModelUnavailableError("cannot build a serving runtime from an untrained forecaster")
    return ForecastRuntime(
        forecaster=forecaster,
        model_version=model_version,
        model_name=model_name,
        run_id=run_id,
        loaded_at=loaded_at or datetime.now(tz=timezone.utc),
    )


def load_runtime_from_version(
    version: RegisteredModelVersion, tracking_uri: str | None = None
) -> ForecastRuntime:
    """Restore the three boosters of one registered version into memory."""
    if not version.run_id:
        raise MlflowUnavailableError(
            f"model version {version.name} v{version.version} has no run_id; it cannot be loaded"
        )

    base = f"runs:/{version.run_id}"
    forecaster = DemandForecaster()
    for path, attach in (
        (POINT_ARTIFACT, "point_model"),
        (LOWER_ARTIFACT, "lower_model"),
        (UPPER_ARTIFACT, "upper_model"),
    ):
        booster = load_booster_from_uri(f"{base}/{path}")
        setattr(forecaster, attach, booster)

    forecaster.attach_boosters(
        forecaster.point_model, forecaster.lower_model, forecaster.upper_model
    )
    logger.info(
        "Serving model loaded",
        extra={"model": version.name, "version": version.version, "run_id": version.run_id},
    )
    return ForecastRuntime(
        forecaster=forecaster,
        model_version=str(version.version),
        model_name=version.name,
        run_id=version.run_id,
        loaded_at=datetime.now(tz=timezone.utc),
    )


def load_production_runtime(
    *, tracking_uri: str | None = None, model_name: str = MODEL_NAME
) -> ForecastRuntime | None:
    """Load the MLflow ``Production`` model, or ``None`` when there is none.

    Returning ``None`` rather than raising is deliberate: the API must still start
    (and still answer ``/health`` and ``/metrics``) on a machine where MLflow is
    unreachable or no model has been registered yet.  ``/api/v1/forecast`` then
    answers 503 with a clear message instead of the whole service refusing to boot.
    """
    try:
        production = get_production_model(model_name)
        if production is None:
            logger.warning("No Production model found in the registry", extra={"model_name": model_name})
            return None
        return load_runtime_from_version(production, tracking_uri)
    except Exception as exc:  # noqa: BLE001 - startup must survive an unavailable registry
        logger.warning("Could not load the production model", exc_info=True, extra={"error": str(exc)})
        return None


async def load_catalogue(session: Any) -> CatalogueMatcher:
    """Load and install the catalogue matcher singleton from PostgreSQL."""
    matcher = await load_catalogue_from_database(session)
    logger.info("Catalogue installed", extra={"entries": len(matcher)})
    return matcher


def build_matcher(catalogue: CatalogueMatcher, *, enable_llm: bool = True) -> OrderMatcher:
    """Construct an order matcher bound to ``catalogue``."""
    if enable_llm:
        return OrderMatcher(catalogue=catalogue)
    return OrderMatcher(catalogue=catalogue, reranker=None)


def forecast_frame(
    runtime: ForecastRuntime,
    history: pd.DataFrame,
    forecast_dates: list[Any],
) -> pd.DataFrame:
    """Run the serving forecast for one series' history.

    Delegates to :meth:`DemandForecaster.forecast_horizon`, which builds the
    inference frame with the shared :func:`app.ml.features.build_inference_frame`.
    CPU-bound, so callers run it with ``asyncio.to_thread``.
    """
    if not runtime.models_loaded:
        raise ModelUnavailableError("no production model is loaded; train and register one first")
    return runtime.forecaster.forecast_horizon(history, forecast_dates)


__all__ = [
    "LOWER_ARTIFACT",
    "POINT_ARTIFACT",
    "UPPER_ARTIFACT",
    "ForecastRuntime",
    "ModelUnavailableError",
    "build_matcher",
    "build_runtime",
    "forecast_frame",
    "load_catalogue",
    "load_production_runtime",
    "load_runtime_from_version",
]