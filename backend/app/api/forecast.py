"""``POST /api/v1/forecast`` — demand forecasts from the resident Production model.

The serving path is deliberately thin: history comes from PostgreSQL, features are
built by :func:`app.ml.features.build_inference_frame` (the *same* function the
Phase 2 trainer calls), and prediction runs on the pre-loaded boosters through
:meth:`DemandForecaster.forecast_horizon`.  Nothing about the feature contract is
restated here, which is what makes train/serve skew structurally impossible
rather than a review item.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import date, timedelta
from typing import Any, Final

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.state import state
from app.database import get_db
from app.ml.dataset import EmptyPanelError, load_demand_panel
from app.ml.features import MAX_LOOKBACK_DAYS
from app.ml.serving import forecast_frame
from app.models import DrugCatalogue, Order
from app.monitoring import metrics
from app.schemas.forecast import HISTORY_DAYS, ForecastItem, ForecastRequest, ForecastResponse

#: How long a cached history stays fresh, and how many pharmacies are kept.
#: Five minutes is short enough that a fresh day of orders appears quickly and
#: long enough that a burst of requests collapses onto one aggregation.
DEFAULT_TTL_SECONDS: Final[float] = 300.0
DEFAULT_MAX_ENTRIES: Final[int] = 256

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.forecast")

router = APIRouter(prefix="/api/v1", tags=["forecasting"])


class PanelCache:
    """Bounded, time-to-live cache of per-pharmacy demand history.

    Without it every forecast request re-aggregated the entire order ledger
    (``orders`` x ``order_items``, tens of thousands of rows) before the model
    could run.  That is fine for one request and hopeless for fifty: the Phase 6
    load benchmark measured a forecast p50 of 6.2 s at 50-way concurrency, purely
    queueing behind repeated identical aggregation.

    Keyed by ``(pharmacy_id, product_ids, last_day)`` and expiring after
    :data:`DEFAULT_TTL_SECONDS`, so a new day of orders invalidates naturally.
    Entries are held in an ``OrderedDict`` and evicted least-recently-used once
    :data:`DEFAULT_MAX_ENTRIES` is reached, which keeps the memory bounded on a
    long-lived process serving many pharmacies.

    The cached frame is never handed to a caller directly — every consumer in
    this module copies before use — so a cached entry cannot be mutated by a
    request.
    """

    __slots__ = ("_entries", "_ttl", "_max_entries", "hits", "misses")

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._entries: "OrderedDict[tuple[Any, ...], tuple[float, pd.DataFrame]]" = OrderedDict()
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[Any, ...]) -> pd.DataFrame | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        stored_at, frame = entry
        if time.monotonic() - stored_at > self._ttl:
            self._entries.pop(key, None)
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return frame

    def put(self, key: tuple[Any, ...], frame: pd.DataFrame) -> None:
        self._entries[key] = (time.monotonic(), frame)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses}


#: Process-wide panel cache.  A forecast for the same pharmacy repeats within a
#: burst of traffic, so even a short TTL removes almost all repeated aggregation.
panel_cache: Final[PanelCache] = PanelCache()

#: Display-name lookups are stable for the life of a catalogue; caching them
#: removes a query per request without any staleness risk worth measuring.
NAME_CACHE: Final[dict[tuple[str, ...], dict[str, str]]] = {}

#: In-sample MAE per ``(pharmacy, product, last_day)``.  Computing it means
#: scoring the whole observed history through LightGBM, which is the other
#: expensive per-request step; it only changes when the history changes.
MAE_CACHE: Final[PanelCache] = PanelCache(max_entries=1024)

#: Finished forecasts, keyed by the request shape and the anchor day.  Even with
#: the history cached, one request still runs three LightGBM boosters for the
#: horizon plus pandas work to build the inference frame — tens of milliseconds
#: each, which is what saturated the loop under concurrency.  Two pharmacies
#: asking the same question minutes apart must not each pay that, so the result
#: is cached alongside the inputs it derives from.
RESPONSE_CACHE: Final[PanelCache] = PanelCache(max_entries=512)

#: Newest order day, used to anchor every forecast.  It only moves once new
#: orders land, so it is cached briefly to keep one query per request off the
#: hot path.
LAST_DAY_CACHE: Final[dict[str, Any]] = {"value": None, "at": 0.0}
LAST_DAY_TTL_SECONDS: Final[float] = 30.0


async def _catalogue_names(session: AsyncSession, product_ids: list[str]) -> dict[str, str]:
    """Look up display names for the requested products, skipping unknown ids."""
    key = tuple(product_ids)
    cached = NAME_CACHE.get(key)
    if cached is not None:
        return cached
    rows = (
        await session.execute(
            select(DrugCatalogue.catalogue_id, DrugCatalogue.brand_name, DrugCatalogue.strength).where(
                DrugCatalogue.catalogue_id.in_(product_ids)
            )
        )
    ).all()
    names = {
        catalogue_id: " ".join(part for part in (brand, strength) if part)
        for catalogue_id, brand, strength in rows
    }
    NAME_CACHE[key] = names
    return names


def _in_sample_mae(
    runtime: Any, series: pd.DataFrame
) -> tuple[float | None, pd.DataFrame]:
    """Score the observed history and return the last-7-days MAE.

    This is the *model's* error over the most recent week, not a naive
    ``y_{t-7}`` baseline — it answers "how well is this series being predicted
    right now".  ``None`` when the series is too short to score.
    """
    if series.empty:
        return None, series
    predictions = runtime.forecaster.predict(series)
    actual = series.sort_values("date")["units_sold"].to_numpy(dtype=float)
    predicted = predictions.sort_values("date")["predicted_units"].to_numpy(dtype=float)
    window = min(len(actual), len(predicted), 7)
    if window == 0:
        return None, predictions
    mae = float(pd.Series(actual[-window:] - predicted[-window:]).abs().mean())
    return mae, predictions


@router.post(
    "/forecast",
    response_model=ForecastResponse,
    summary="Generate a multi-horizon demand forecast",
    description=(
        "Scores `forecast_horizon_days` consecutive future days for each requested "
        "product of one pharmacy, using the Production model resident in memory.\n\n"
        "Products with too little history to form `lag_14` are omitted from `forecasts` "
        "rather than scored with fabricated values. Returns **503** when no Production "
        "model is loaded and **404** when the pharmacy has no order history."
    ),
    responses={
        200: {"description": "Forecast produced.", "model": ForecastResponse},
        404: {"description": "Unknown pharmacy or product id."},
        422: {"description": "Request body failed validation."},
        503: {"description": "No Production model is loaded."},
    },
)
async def create_forecast(
    request: ForecastRequest,
    db: AsyncSession = Depends(get_db),
) -> ForecastResponse:
    """Forecast demand for one pharmacy's products."""
    runtime = state.require_runtime()
    last_day = await _latest_order_day(db)

    # A cached forecast is returned only after the anchor day is confirmed fresh,
    # so new orders invalidate it rather than being served stale.
    response_key = (
        request.pharmacy_id,
        tuple(request.product_ids),
        request.forecast_horizon_days,
        last_day.isoformat(),
    )
    cached_items = RESPONSE_CACHE.get(response_key)
    if cached_items is not None:
        logger.debug("Forecast cache hit", extra=RESPONSE_CACHE.stats())
        return ForecastResponse(
            pharmacy_id=request.pharmacy_id,
            model_version=runtime.model_version,
            model_name=runtime.model_name,
            forecast_horizon_days=request.forecast_horizon_days,
            forecasts=list(cached_items),
        )

    # One pharmacy, a bounded window: the read is small enough to stay inside the
    # 500 ms p95 budget while still covering lag_14 plus sparse-series gaps.
    cache_key = (request.pharmacy_id, tuple(request.product_ids), last_day.isoformat())
    history = panel_cache.get(cache_key)
    if history is None:
        try:
            history = await load_demand_panel(
                db,
                start_date=last_day - timedelta(days=HISTORY_DAYS - 1),
                end_date=last_day,
                pharmacy_ids=(request.pharmacy_id,),
                product_ids=tuple(request.product_ids),
                min_series_units=0,
            )
        except EmptyPanelError as exc:
            # An unknown pharmacy or a product the pharmacy never orders is a
            # client error, not a server fault; the dataset layer signals "no
            # rows" by raising, so translate it here rather than leaking a 500.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no order history for pharmacy {request.pharmacy_id!r} on "
                    f"{', '.join(request.product_ids)}; nothing to forecast"
                ),
            ) from exc
        panel_cache.put(cache_key, history)
        logger.info("Panel cache miss; aggregated order ledger", extra=panel_cache.stats())

    if history.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no order history for pharmacy {request.pharmacy_id!r} on "
                f"{', '.join(request.product_ids)}; nothing to forecast"
            ),
        )

    names = await _catalogue_names(db, request.product_ids)
    forecast_dates = [last_day + timedelta(days=offset) for offset in range(1, request.forecast_horizon_days + 1)]

    forecasts: list[ForecastItem] = []
    per_product_error: dict[str, float] = {}
    for product_id in request.product_ids:
        series = history.loc[history["product_id"] == product_id]
        if series.empty:
            continue
        # `build_inference_frame` needs the calendar to be contiguous; densify
        # guarantees one row per series per day before lags are formed.
        item = await _forecast_one(
            runtime,
            series,
            forecast_dates,
            product_id,
            names.get(product_id),
            per_product_error,
            mae_key=(request.pharmacy_id, product_id, last_day.isoformat()),
        )
        if item is not None:
            forecasts.append(item)

    metrics.set_forecast_mae(per_product_error)
    RESPONSE_CACHE.put(response_key, tuple(forecasts))
    return ForecastResponse(
        pharmacy_id=request.pharmacy_id,
        model_version=runtime.model_version,
        model_name=runtime.model_name,
        forecast_horizon_days=request.forecast_horizon_days,
        forecasts=forecasts,
    )


async def _forecast_one(
    runtime: Any,
    series: pd.DataFrame,
    forecast_dates: list[date],
    product_id: str,
    product_name: str | None,
    per_product_error: dict[str, float],
    *,
    mae_key: tuple[Any, ...] | None = None,
) -> ForecastItem | None:
    """Score one product, returning ``None`` when the series is too short."""
    if len(series) < MAX_LOOKBACK_DAYS:
        logger.info(
            "Skipping product with insufficient history",
            extra={"product_id": product_id, "rows": len(series)},
        )
        return None
    try:
        # LightGBM prediction is CPU bound -> off the event loop.
        predictions = await asyncio.to_thread(forecast_frame, runtime, series, forecast_dates)
    except (ValueError, KeyError) as exc:
        # A series that cannot form its lags is a data condition, not a crash.
        logger.warning("Could not forecast product", extra={"product_id": product_id, "error": str(exc)})
        return None

    if predictions.empty:
        return None

    mae: float | None = MAE_CACHE.get(mae_key) if mae_key is not None else None
    if mae is None:
        mae, _ = await asyncio.to_thread(_in_sample_mae, runtime, series)
        if mae_key is not None and mae is not None:
            MAE_CACHE.put(mae_key, mae)
    if mae is not None:
        per_product_error[product_id] = mae

    return ForecastItem(
        product_id=product_id,
        product_name=product_name,
        dates=[pd.Timestamp(value).date() for value in predictions["date"]],
        predicted_units=[float(value) for value in predictions["predicted_units"]],
        lower_bound=[float(value) for value in predictions["lower_bound"]],
        upper_bound=[float(value) for value in predictions["upper_bound"]],
        mae_last_7d=mae,
    )


async def _latest_order_day(db: AsyncSession) -> date:
    """Newest day present in the order ledger, memoised briefly.

    Forecast dates start the day after the last observation, so every forecast is
    strictly in the future relative to the data — the same discipline the
    chronological split enforces during training.  The value only moves when new
    orders land, so it is cached for :data:`LAST_DAY_TTL_SECONDS` to keep a
    query off every request; the cache is checked before use and the TTL bounds
    how stale it can ever be.
    """
    cached = LAST_DAY_CACHE["value"]
    if cached is not None and time.monotonic() - LAST_DAY_CACHE["at"] <= LAST_DAY_TTL_SECONDS:
        return cached

    latest = (await db.execute(select(func.max(Order.created_at)))).scalar()
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="the order ledger is empty; seed the database before forecasting",
        )
    day = pd.Timestamp(latest).date()
    LAST_DAY_CACHE["value"] = day
    LAST_DAY_CACHE["at"] = time.monotonic()
    return day


__all__ = ["HISTORY_DAYS", "create_forecast", "router"]