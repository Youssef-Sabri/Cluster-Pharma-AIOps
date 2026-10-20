"""Shared feature engineering — the single source of truth for train *and* serve.

Rule: *No Training-Serving Skew*.  Every transformation applied during offline
model training is applied identically during online inference because **both
paths call :func:`build_features`**.  Nothing in this module may be duplicated
inside the training script or the API inference router.

Feature set
-----------
===================== =====================================================
``lag_1``             units sold yesterday
``lag_7``             units sold on the same day last week
``lag_14``            units sold two weeks ago
``rolling_mean_7d``   mean of the previous 7 days (excludes today)
``rolling_std_7d``    standard deviation of the previous 7 days
``day_of_week``       0 (Monday) .. 6 (Sunday)
``is_egypt_weekend``  1 on Friday/Saturday — the Egyptian weekend
``month``             calendar month (seasonal pressure)
``week_of_year``      ISO week number
``is_ramadan``        1 inside the Hijri month of Ramadan
``product_category``  OTC / PRESCRIPTION / COSMETIC (categorical)
``pharmacy_tier``     SMALL / MEDIUM / LARGE (categorical)
===================== =====================================================

Leakage safety
--------------
For a row dated ``t`` every feature is computed from ``units_sold`` strictly
**before** ``t``: lags use ``shift(k)`` and the rolling statistics use
``shift(1).rolling(...)``.  Training additionally drops the warm-up rows whose
lags do not exist yet; inference keeps them so the most recent state is always
preserved.

Synthetic data only — this module operates on generated data.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Final

import numpy as np
import pandas as pd
from pandas.api.types import CategoricalDtype

from app.pipelines.data_generator import is_ramadan

# --- Schema ----------------------------------------------------------------

#: Key columns every input frame must provide.
REQUIRED_INPUT_COLUMNS: Final[tuple[str, ...]] = ("pharmacy_id", "product_id", "date", "units_sold")

#: Columns identifying a single pharmacy/product time series.  A ``list`` (not a
#: tuple) because pandas 2.x reads a tuple as one composite key name.
SERIES_KEY: Final[list[str]] = ["pharmacy_id", "product_id"]

#: Sorting order that guarantees lags line up with consecutive calendar days.
SORT_KEYS: Final[list[str]] = ["pharmacy_id", "product_id", "date"]

#: Lags (in days) fed to the model.
LAG_DAYS: Final[tuple[int, ...]] = (1, 7, 14)

#: Rolling window length in days (excludes the current day).
ROLLING_WINDOW_DAYS: Final[int] = 7

#: Minimum history a series needs before every lag is defined.
MAX_LOOKBACK_DAYS: Final[int] = max(LAG_DAYS)

#: The target column the model learns.
TARGET_COLUMN: Final[str] = "units_sold"

#: Fraction of the timeline reserved for evaluation (the plan mandates 20%).
DEFAULT_TEST_FRACTION: Final[float] = 0.20

#: Guard rail so a pathological split never yields a tiny training set.
MIN_TRAIN_DAYS: Final[int] = 10

#: Calendar features derived from ``date``.
CALENDAR_FEATURES: Final[tuple[str, ...]] = (
    "day_of_week",
    "is_egypt_weekend",
    "month",
    "week_of_year",
    "is_ramadan",
)

#: Categorical features with a fixed vocabulary.  Pinning the vocabulary (rather
#: than letting pandas infer it per frame) is what stops a rare category seen
#: only in training from silently re-ordering the encodings at inference time.
PRODUCT_CATEGORY_VALUES: Final[tuple[str, ...]] = ("OTC", "PRESCRIPTION", "COSMETIC")
PHARMACY_TIER_VALUES: Final[tuple[str, ...]] = ("SMALL", "MEDIUM", "LARGE")
UNKNOWN_CATEGORY: Final[str] = "__UNKNOWN__"

PRODUCT_CATEGORY_DTYPE: Final[CategoricalDtype] = CategoricalDtype(
    categories=[*PRODUCT_CATEGORY_VALUES, UNKNOWN_CATEGORY]
)
PHARMACY_TIER_DTYPE: Final[CategoricalDtype] = CategoricalDtype(
    categories=[*PHARMACY_TIER_VALUES, UNKNOWN_CATEGORY]
)

CATEGORICAL_FEATURES: Final[tuple[str, ...]] = ("product_category", "pharmacy_tier")

#: Deterministic column order handed to LightGBM — identical at train and serve.
FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    "lag_1",
    "lag_7",
    "lag_14",
    "rolling_mean_7d",
    "rolling_std_7d",
    "day_of_week",
    "is_egypt_weekend",
    "month",
    "week_of_year",
    "is_ramadan",
    "product_category",
    "pharmacy_tier",
)

#: Column order of the engineered frame: keys, target, context, features.
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "pharmacy_id",
    "product_id",
    "date",
    TARGET_COLUMN,
    "product_category",
    "pharmacy_tier",
    "day_of_week",
    "is_egypt_weekend",
    "month",
    "week_of_year",
    "is_ramadan",
    "lag_1",
    "lag_7",
    "lag_14",
    "rolling_mean_7d",
    "rolling_std_7d",
)

#: Integer columns stored as small ints to keep the LightGBM matrix compact.
_INT8_COLUMNS: Final[tuple[str, ...]] = ("day_of_week", "is_egypt_weekend", "month", "is_ramadan")


class FeatureSchemaError(ValueError):
    """Raised when an input frame does not satisfy the feature contract."""


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------


def add_calendar_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the Egyptian calendar signals to ``frame`` (mutates in place).

    Exposed separately because the inference path also needs calendar features
    for future dates, where no ``units_sold`` history exists.
    """
    calendar = pd.to_datetime(frame["date"])
    frame["day_of_week"] = calendar.dt.dayofweek.astype("int8")
    # Friday (4) and Saturday (5) are the Egyptian weekend: wholesale
    # distribution and pharmacy restocking largely stop.
    frame["is_egypt_weekend"] = frame["day_of_week"].isin([4, 5]).astype("int8")
    frame["month"] = calendar.dt.month.astype("int8")
    frame["week_of_year"] = calendar.dt.isocalendar().week.astype("int16")
    frame["is_ramadan"] = np.fromiter(
        (int(is_ramadan(day.date()) if hasattr(day, "date") else is_ramadan(day)) for day in calendar),
        dtype=np.int8,
        count=len(frame),
    )
    return frame


def _apply_categorical_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    """Cast the categorical columns to their pinned vocabularies."""
    for column, allowed in (
        ("product_category", PRODUCT_CATEGORY_VALUES),
        ("pharmacy_tier", PHARMACY_TIER_VALUES),
    ):
        if column not in frame.columns:
            frame[column] = UNKNOWN_CATEGORY
        values = frame[column].fillna(UNKNOWN_CATEGORY).astype(str)
        # Values outside the pinned vocabulary collapse to __UNKNOWN__ instead
        # of raising, so a brand-new category can never break online inference.
        frame[column] = values.where(values.isin(allowed), UNKNOWN_CATEGORY)

    frame["product_category"] = frame["product_category"].astype(PRODUCT_CATEGORY_DTYPE)
    frame["pharmacy_tier"] = frame["pharmacy_tier"].astype(PHARMACY_TIER_DTYPE)
    return frame


# ---------------------------------------------------------------------------
# The shared transformation
# ---------------------------------------------------------------------------


def validate_input_frame(frame: pd.DataFrame) -> None:
    """Fail loudly when the feature contract is violated."""
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise FeatureSchemaError(
            f"input frame is missing required column(s) {missing}; "
            f"expected at least {list(REQUIRED_INPUT_COLUMNS)}"
        )
    if frame.empty:
        raise FeatureSchemaError("input frame is empty")


def _drop_calendar_gaps(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows whose date is one day after the previous row of the series.

    Lags and rolling windows are computed positionally, so a missing calendar
    day would silently turn ``lag_7`` into "7 rows ago" instead of "7 days
    ago" — a subtle source of train/serve skew on sparse panels.
    """
    previous_date = frame.groupby(SERIES_KEY, sort=False)["date"].shift(1)
    consecutive = (frame["date"] - previous_date).dt.days == 1
    return frame.loc[consecutive.fillna(False).to_numpy()].reset_index(drop=True)


def build_features(frame: pd.DataFrame, is_inference: bool = False) -> pd.DataFrame:
    """Engineer the demand-forecasting feature matrix.

    This is the **only** place features are created — the training script and
    the online inference router both call it, which is what guarantees zero
    train/serve skew.

    Parameters
    ----------
    frame:
        Columns ``pharmacy_id``, ``product_id``, ``date``, ``units_sold``
        (one row per series per day).  ``product_category`` and
        ``pharmacy_tier`` are used when present and fall back to
        ``__UNKNOWN__`` otherwise.
    is_inference:
        ``False`` (training/evaluation): rows whose ``lag_14`` or rolling mean
        is not yet available are dropped, because they cannot be scored and
        would bias the loss surface.
        ``True`` (serving): every row is preserved, so the latest state of a
        series stays available for forecasting the next day.

    Returns
    -------
    pandas.DataFrame
        Sorted by ``pharmacy_id, product_id, date`` with the columns in
        :data:`OUTPUT_COLUMNS`.
    """
    validate_input_frame(frame)

    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"])
    working = working.sort_values(SORT_KEYS, kind="stable").reset_index(drop=True)
    working = _drop_calendar_gaps(working)

    # One positional shift per series; every value therefore comes from a
    # strictly earlier calendar day.
    grouped = working.groupby(SERIES_KEY, sort=False)[TARGET_COLUMN]
    for lag in LAG_DAYS:
        working[f"lag_{lag}"] = grouped.shift(lag)

    shifted = grouped.shift(1)
    working["rolling_mean_7d"] = shifted.groupby(
        [working[column] for column in SERIES_KEY], sort=False
    ).transform(lambda series: series.rolling(ROLLING_WINDOW_DAYS, min_periods=1).mean())
    working["rolling_std_7d"] = (
        shifted.groupby([working[column] for column in SERIES_KEY], sort=False)
        .transform(lambda series: series.rolling(ROLLING_WINDOW_DAYS, min_periods=1).std())
        .fillna(0.0)
    )

    add_calendar_features(working)
    _apply_categorical_dtypes(working)

    if not is_inference:
        # Warm-up rows have no lag_14 / rolling mean yet; they are unscorable.
        working = working.dropna(subset=["lag_14", "rolling_mean_7d"]).reset_index(drop=True)

    available = [column for column in OUTPUT_COLUMNS if column in working.columns]
    return working[available]


def build_inference_frame(
    history: pd.DataFrame,
    forecast_dates: Sequence[date | pd.Timestamp],
    *,
    lookback_days: int = MAX_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Append future rows to ``history`` and engineer their features.

    The serving counterpart of training: history is extended with placeholder
    rows (``units_sold = NaN``) for each forecast date, :func:`build_features`
    runs in ``is_inference`` mode, and the rows for those dates are returned.

    Parameters
    ----------
    history:
        Observed ``(pharmacy_id, product_id, date, units_sold)`` rows.  Only
        the last ``lookback_days`` days per series are kept, which bounds the
        serving latency.
    forecast_dates:
        Calendar days to score.

    Notes
    -----
    ``lag_1`` for the first forecast day reads the last observed day and
    ``lag_7`` reads the same weekday a week back — exactly the signals the
    model saw during training.  For later days inside a multi-day horizon the
    lags have no observed value yet, so they stay ``NaN``; LightGBM's native
    missing-value handling covers that, and the model never sees a fabricated
    demand value.
    """
    validate_input_frame(history)
    if not forecast_dates:
        raise FeatureSchemaError("forecast_dates must not be empty")

    history = history.copy()
    history["date"] = pd.to_datetime(history["date"])
    # Keep ``lookback_days`` prior days *plus the anchor day itself*.  The bound
    # is inclusive on purpose: excluding the ``max - lookback_days`` row would
    # silently null out ``lag_14`` at serving time while training saw a real
    # value there — a textbook train/serve skew.
    oldest_needed = history["date"].max() - pd.Timedelta(days=lookback_days)
    history = history.loc[history["date"] >= oldest_needed]
    history = history.sort_values(SORT_KEYS, kind="stable")

    future_dates = sorted({pd.Timestamp(day).normalize() for day in forecast_dates})
    # One template row per series: its most recent observed context row.
    templates = history.groupby(SERIES_KEY, sort=False, as_index=False).tail(1)

    future_blocks: list[pd.DataFrame] = []
    for future_date in future_dates:
        block = templates.copy()
        block["date"] = future_date
        block[TARGET_COLUMN] = np.nan
        future_blocks.append(block)

    combined = pd.concat([history, *future_blocks], ignore_index=True)
    featured = build_features(combined, is_inference=True)
    return featured.loc[featured["date"].isin(future_dates)].reset_index(drop=True)


def split_chronologically(
    frame: pd.DataFrame,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    min_train_days: int = MIN_TRAIN_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split on the calendar, never randomly (rule: *Time-Series Integrity*).

    The unique sorted dates are cut at ``test_fraction``: the earliest days form
    the training set, the final days the test set.  Because every feature is
    derived from strictly past ``units_sold``, no future value can reach a
    training row through a lag or rolling window.
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be in (0, 1), got {test_fraction}")

    dates = np.sort(pd.to_datetime(frame["date"]).unique())
    if len(dates) <= min_train_days:
        raise ValueError(
            f"only {len(dates)} distinct days available; need more than {min_train_days} "
            "to split chronologically"
        )

    split_index = max(min_train_days, min(int(len(dates) * (1.0 - test_fraction)), len(dates) - 1))
    cutoff = pd.Timestamp(dates[split_index])

    train = frame.loc[pd.to_datetime(frame["date"]) < cutoff].reset_index(drop=True)
    test = frame.loc[pd.to_datetime(frame["date"]) >= cutoff].reset_index(drop=True)
    if train.empty or test.empty:
        raise ValueError("chronological split produced an empty train or test partition")
    return train, test


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Return exactly :data:`FEATURE_COLUMNS` in the canonical order."""
    missing = [column for column in FEATURE_COLUMNS if column not in frame.columns]
    if missing:
        raise FeatureSchemaError(f"engineered frame is missing feature column(s) {missing}")
    return frame.loc[:, list(FEATURE_COLUMNS)]


def describe_features() -> list[dict[str, Any]]:
    """Machine-readable feature manifest, logged alongside every MLflow run."""
    descriptions: dict[str, str] = {
        "lag_1": "Units sold 1 day before the forecast date",
        "lag_7": "Units sold on the same weekday one week before (naive baseline signal)",
        "lag_14": "Units sold on the same weekday two weeks before",
        "rolling_mean_7d": f"Mean units sold over the previous {ROLLING_WINDOW_DAYS} days (excludes today)",
        "rolling_std_7d": f"Std-dev of units sold over the previous {ROLLING_WINDOW_DAYS} days (excludes today)",
        "day_of_week": "0 = Monday .. 6 = Sunday",
        "is_egypt_weekend": "1 on Friday and Saturday (Egyptian weekend slowdown)",
        "month": "Calendar month 1-12",
        "week_of_year": "ISO week number",
        "is_ramadan": "1 inside the Hijri month of Ramadan",
        "product_category": f"Retail segment {list(PRODUCT_CATEGORY_VALUES)}",
        "pharmacy_tier": f"Synthetic pharmacy size tier {list(PHARMACY_TIER_VALUES)}",
    }
    dtypes = dict.fromkeys(CATEGORICAL_FEATURES, "category")
    return [
        {"name": column, "dtype": dtypes.get(column, "float64"), "description": descriptions[column]}
        for column in FEATURE_COLUMNS
    ]


__all__ = [
    "CALENDAR_FEATURES",
    "CATEGORICAL_FEATURES",
    "DEFAULT_TEST_FRACTION",
    "FEATURE_COLUMNS",
    "LAG_DAYS",
    "MAX_LOOKBACK_DAYS",
    "MIN_TRAIN_DAYS",
    "OUTPUT_COLUMNS",
    "PHARMACY_TIER_DTYPE",
    "PHARMACY_TIER_VALUES",
    "PRODUCT_CATEGORY_DTYPE",
    "PRODUCT_CATEGORY_VALUES",
    "REQUIRED_INPUT_COLUMNS",
    "ROLLING_WINDOW_DAYS",
    "SERIES_KEY",
    "TARGET_COLUMN",
    "FeatureSchemaError",
    "add_calendar_features",
    "build_features",
    "build_inference_frame",
    "describe_features",
    "feature_matrix",
    "split_chronologically",
    "validate_input_frame",
]