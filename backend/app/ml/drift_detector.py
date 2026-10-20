"""Statistical drift detection with the Population Stability Index.

The nightly AIOps job compares the **current** inference window against a
**reference** baseline and reports how far each monitored distribution has moved:

.. math::

    \\mathrm{PSI} = \\sum_{k=1}^{B} (P_k - Q_k) \\cdot \\ln\\!\\left(\\frac{P_k}{Q_k}\\right)

where :math:`Q_k` is the proportion of the *reference* sample in bin ``k``,
:math:`P_k` the proportion of the *current* sample, and :math:`B` the number of
bins (:math:`B = 10`).

Status bands follow the phase specification:

===========  ===================
PSI          Status
===========  ===================
``< 0.10``   ``OK``
``< 0.20``   ``WARNING``
``>= 0.20``  ``DRIFT_DETECTED``
===========  ===================

Why the implementation looks the way it does
--------------------------------------------
Three properties of the real data drive the design, and each one is a bug that
a naive implementation would ship:

1. **The panel is ~79 % zeros.**  Decile quantiles of a zero-inflated
   distribution repeat the same edge many times, so the raw 11 quantiles
   collapse to far fewer distinct edges.  The bins are built with
   :func:`numpy.unique`, and a reference that is *constant* degrades to a
   two-bin comparison rather than raising.
2. **Drift is usually a shift *upwards*.**  ``numpy.histogram`` silently discards
   values above the last edge, so a window whose values all exceed the
   reference maximum would report almost no drift.  The outer edges are
   therefore extended to ±∞, which keeps the decile interior intact while
   catching every out-of-range value in the first/last bin.
3. **Empty bins are normal, not exceptional.**  A proportion of exactly zero
   would make ``ln(P_k / Q_k)`` undefined, so empty proportions are replaced by
   :data:`PSI_EPSILON` on *both* sides before the logarithm is taken.  Identical
   distributions still give exactly ``0.0``, because both sides are smoothed
   identically.

Synthetic data only — every distribution checked here comes from the generated
dataset, never from real Cluster or pharmacy data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Iterable, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging_config import get_logger
from app.models import DriftLog
from app.models.drift_log import (
    MONITORED_FEATURES,
    STATUS_DRIFT_DETECTED,
    STATUS_OK,
    STATUS_WARNING,
)

logger: Final[logging.Logger] = get_logger("ml.drift_detector")

# --- PSI configuration -------------------------------------------------------

#: Number of quantile bins (the specification mandates deciles).
DEFAULT_BINS: Final[int] = 10

#: Proportion substituted for an empty bin, per the specification.  Keeps
#: ``ln(P_k / Q_k)`` finite without materialising a fake population.
PSI_EPSILON: Final[float] = 1e-4

#: Lower bound of the ``WARNING`` band.
PSI_WARNING_THRESHOLD: Final[float] = settings.drift_psi_warning

#: Lower bound of the ``DRIFT_DETECTED`` band.
PSI_ALERT_THRESHOLD: Final[float] = settings.drift_psi_alert

#: Columns of the long-format monitored-feature frame.
FEATURE_FRAME_COLUMNS: Final[tuple[str, ...]] = (
    "feature_name",
    "value",
    "date",
    "pharmacy_id",
    "product_id",
)

#: Default current/reference window lengths, in days.
DEFAULT_CURRENT_WINDOW_DAYS: Final[int] = 14
DEFAULT_REFERENCE_WINDOW_DAYS: Final[int] = 90


class InsufficientDriftDataError(ValueError):
    """Raised when a distribution is empty and cannot be compared."""


# ---------------------------------------------------------------------------
# The PSI calculation (pure)
# ---------------------------------------------------------------------------


def _finite(values: Iterable[float]) -> np.ndarray:
    """Drop NaN/±inf and flatten to a 1-D float array."""
    array = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    array = array.ravel()
    return array[np.isfinite(array)]


def quantile_bin_edges(reference: np.ndarray, bins: int = DEFAULT_BINS) -> np.ndarray:
    """Return the bin edges for ``reference``, with the outer bins unbounded.

    The interior edges are the deciles of the *reference* sample (that is the
    definition), de-duplicated because a zero-inflated reference repeats them.
    The first and last edges become ±∞ so that values outside the reference
    range are still counted instead of being discarded by ``np.histogram``.

    Degenerate references are handled explicitly, because getting this wrong
    fails *silently*.  A reference that is 95 % zeros has deciles 0.0 … 0.9 all
    equal to zero, so ``deciles[1:-1]`` is empty and the comparison collapses to
    one unbounded bin that reports ``PSI == 0`` for *any* current sample — the
    detector would declare "no drift" on a distribution that had quadrupled.
    In that case the reference's own distinct values are used as edges, which
    restores resolution; a genuinely constant reference is split on that
    constant so "unchanged" stays distinguishable from "moved".
    """
    deciles = np.unique(np.quantile(reference, np.linspace(0.0, 1.0, bins + 1)))
    interior = deciles[1:-1] if deciles.size >= 3 else np.unique(reference)

    low, high = float(reference.min()), float(reference.max())
    interior = interior[(interior > low) & (interior < high)]
    if interior.size == 0:
        # Degenerate reference (constant, or only two distinct values).  Split
        # just above the minimum so the reference lands in the *lower* bin:
        # np.histogram treats bins as [lo, hi) except the last, so an edge at
        # exactly ``low`` would push the reference into the upper bin together
        # with every shifted value and report PSI 0.0 for any change.
        interior = np.array([np.nextafter(low, np.inf)], dtype=float)
    return np.concatenate(([-np.inf], interior, [np.inf]))


def _proportions(counts: np.ndarray, epsilon: float) -> np.ndarray:
    """Normalise counts to proportions, replacing exact zeros with ``epsilon``."""
    total = counts.sum()
    proportions = counts.astype(float) / total if total else counts.astype(float)
    return np.where(proportions > 0.0, proportions, epsilon)


def calculate_psi(
    reference: np.ndarray | Sequence[float],
    current: np.ndarray | Sequence[float],
    bins: int = DEFAULT_BINS,
    epsilon: float = PSI_EPSILON,
) -> float:
    """Population Stability Index between two samples.

    Parameters
    ----------
    reference:
        Baseline sample.  **Its** quantiles define the bins, so the reference
        must be the window the production model was trained against.
    current:
        Recent inference window, compared on the bins derived from ``reference``.
    bins:
        Target number of quantile bins (:data:`DEFAULT_BINS`).
    epsilon:
        Floor substituted for an empty bin.

    Returns
    -------
    float
        PSI, always ``>= 0``.  Zero for identical distributions; larger means
        more distribution shift.

    Raises
    ------
    InsufficientDriftDataError
        If either sample is empty after removing non-finite values.
    ValueError
        If ``bins < 2`` or ``epsilon <= 0``.

    Notes
    -----
    The result is a *distribution* comparison, not a mean comparison: two
    windows with identical averages but different spread produce a non-zero
    PSI.  This is intentional — a change in demand *shape* is drift too.
    """
    if bins < 2:
        raise ValueError(f"bins must be at least 2, got {bins}")
    if epsilon <= 0.0:
        raise ValueError(f"epsilon must be positive, got {epsilon}")

    reference_array = _finite(reference)
    current_array = _finite(current)
    if reference_array.size == 0:
        raise InsufficientDriftDataError("reference sample is empty after dropping non-finite values")
    if current_array.size == 0:
        raise InsufficientDriftDataError("current sample is empty after dropping non-finite values")

    edges = quantile_bin_edges(reference_array, bins)
    reference_counts, _ = np.histogram(reference_array, bins=edges)
    current_counts, _ = np.histogram(current_array, bins=edges)

    expected = _proportions(reference_counts, epsilon)
    actual = _proportions(current_counts, epsilon)

    # (P - Q) * ln(P / Q); every term is non-negative because ln(P/Q) shares the
    # sign of (P - Q), so the sum can never come out negative.
    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    return max(psi, 0.0)


def classify_psi(
    psi: float,
    warning: float = PSI_WARNING_THRESHOLD,
    alert: float = PSI_ALERT_THRESHOLD,
) -> str:
    """Map a PSI score onto its status band."""
    if psi >= alert:
        return STATUS_DRIFT_DETECTED
    if psi >= warning:
        return STATUS_WARNING
    return STATUS_OK


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriftResult:
    """PSI for one monitored feature."""

    feature_name: str
    psi_score: float
    status: str
    reference_size: int
    current_size: int
    note: str = ""

    @property
    def drift_detected(self) -> bool:
        """``True`` when this feature reached the ``DRIFT_DETECTED`` band."""
        return self.status == STATUS_DRIFT_DETECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "psi_score": round(self.psi_score, 6),
            "status": self.status,
            "reference_size": self.reference_size,
            "current_size": self.current_size,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Outcome of comparing a current window against a reference baseline."""

    results: tuple[DriftResult, ...]
    reference_start: date | None = None
    reference_end: date | None = None
    current_start: date | None = None
    current_end: date | None = None
    skipped_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Coerce the collections to tuples, as the annotations promise.

        A caller that passes a generator would otherwise get silently different
        answers on the second iteration: ``drift_detected`` consumes it, and the
        following ``max_psi`` / ``drifting_features`` then see nothing.
        """
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "skipped_features", tuple(self.skipped_features))

    def __iter__(self) -> Any:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    @property
    def max_psi(self) -> float:
        """Worst PSI across every evaluated feature."""
        return max((result.psi_score for result in self.results), default=0.0)

    @property
    def drift_detected(self) -> bool:
        """``True`` when any feature reached ``DRIFT_DETECTED``."""
        return any(result.drift_detected for result in self.results)

    @property
    def worst(self) -> DriftResult | None:
        """The feature with the highest PSI, or ``None`` when nothing was compared."""
        return max(self.results, key=lambda result: result.psi_score, default=None)

    @property
    def drifting_features(self) -> tuple[str, ...]:
        """Names of every feature that reached ``DRIFT_DETECTED``."""
        return tuple(result.feature_name for result in self.results if result.drift_detected)

    def get(self, feature_name: str) -> DriftResult | None:
        """Look one feature's result up by name."""
        return next((result for result in self.results if result.feature_name == feature_name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_psi": round(self.max_psi, 6),
            "drift_detected": self.drift_detected,
            "drifting_features": list(self.drifting_features),
            "reference_window": _window(self.reference_start, self.reference_end),
            "current_window": _window(self.current_start, self.current_end),
            "results": [result.to_dict() for result in self.results],
            "skipped_features": list(self.skipped_features),
        }


def _window(start: date | None, end: date | None) -> str:
    return f"{start}..{end}" if start and end else "unknown"


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------


class DriftDetector:
    """Compares a current inference window against a reference baseline.

    The detector is deliberately *pure* with respect to data sourcing: it
    consumes two already-windowed frames in the long format documented by
    :data:`FEATURE_FRAME_COLUMNS`, so the same instance serves the database
    loader, the synthetic generator and the tests without behaving differently.
    """

    __slots__ = ("bins", "epsilon", "warning_threshold", "alert_threshold", "features")

    def __init__(
        self,
        bins: int = DEFAULT_BINS,
        epsilon: float = PSI_EPSILON,
        warning: float = PSI_WARNING_THRESHOLD,
        alert: float = PSI_ALERT_THRESHOLD,
        features: Sequence[str] = MONITORED_FEATURES,
    ) -> None:
        if not 0.0 <= warning < alert:
            raise ValueError(f"require 0 <= warning ({warning}) < alert ({alert})")
        self.bins = bins
        self.epsilon = epsilon
        self.warning_threshold = warning
        self.alert_threshold = alert
        self.features: Final[tuple[str, ...]] = tuple(features)

    def classify(self, psi: float) -> str:
        """Map a PSI score onto a status band using this detector's thresholds."""
        return classify_psi(psi, self.warning_threshold, self.alert_threshold)

    def check_dataset_drift(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
        *,
        reference_window: tuple[date, date] | None = None,
        current_window: tuple[date, date] | None = None,
    ) -> DriftReport:
        """Compute PSI for every monitored feature.

        A feature absent from either frame is recorded in
        :attr:`DriftReport.skipped_features` and warned about — a missing
        ``match_confidence`` column must not silently stop the demand-drift
        alarm.  When *no* feature could be compared the call raises, because a
        green report built from nothing is worse than a failure.

        Raises
        ------
        ValueError
            If a frame is missing the long-format columns entirely, or if the
            two frames share no comparable feature.
        """
        for label, frame in (("reference", reference_df), ("current", current_df)):
            missing = [column for column in FEATURE_FRAME_COLUMNS[:2] if column not in frame.columns]
            if missing:
                raise ValueError(
                    f"{label} frame is missing required column(s) {missing}; "
                    f"expected a long-format frame with {list(FEATURE_FRAME_COLUMNS)}"
                )

        reference_values = _values_by_feature(reference_df)
        current_values = _values_by_feature(current_df)

        results: list[DriftResult] = []
        skipped: list[str] = []
        for feature in self.features:
            reference_sample = reference_values.get(feature)
            current_sample = current_values.get(feature)
            if reference_sample is None or current_sample is None:
                missing_side = "reference" if reference_sample is None else "current"
                logger.warning(
                    "Monitored feature missing from one window; skipping its PSI",
                    extra={"feature_name": feature, "missing_from": missing_side},
                )
                skipped.append(feature)
                continue

            psi = calculate_psi(reference_sample, current_sample, self.bins, self.epsilon)
            status = self.classify(psi)
            results.append(
                DriftResult(
                    feature_name=feature,
                    psi_score=psi,
                    status=status,
                    reference_size=int(reference_sample.size),
                    current_size=int(current_sample.size),
                )
            )
            logger.info(
                "Drift evaluation",
                extra={"feature_name": feature, "psi_score": round(psi, 6), "status": status},
            )

        if not results:
            raise ValueError(
                f"none of the monitored features {list(self.features)} appear in both windows; "
                "refusing to report a clean bill of health from an empty comparison"
            )

        return DriftReport(
            results=tuple(results),
            reference_start=reference_window[0] if reference_window else None,
            reference_end=reference_window[1] if reference_window else None,
            current_start=current_window[0] if current_window else None,
            current_end=current_window[1] if current_window else None,
            skipped_features=tuple(skipped),
        )


def _values_by_feature(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Group a long-format frame into ``{feature_name: finite values}``."""
    grouped: dict[str, np.ndarray] = {}
    for feature, group in frame.groupby("feature_name", sort=False):
        grouped[str(feature)] = _finite(group["value"].to_numpy(dtype=float))
    return grouped


# ---------------------------------------------------------------------------
# Building the monitored-feature frame
# ---------------------------------------------------------------------------


def _order_day(created_at: datetime) -> date:
    """Calendar day of an order timestamp.

    The generator stamps orders in UTC but buckets them by Egyptian local day,
    so the day is taken from the already-localised timestamp rather than being
    re-derived from the UTC instant — otherwise the panel and the drift frame
    would disagree about which day an order belongs to.
    """
    return created_at.date()


def monitored_features_from_records(
    orders: Sequence[Any],
    items: Sequence[Any],
    unit_prices: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build the long-format monitored-feature frame from generated records.

    This is the in-memory twin of :func:`load_monitored_features`; both produce
    the same schema so a drift check behaves identically whether it is fed from
    PostgreSQL or from the synthetic generator in a test.

    Parameters
    ----------
    orders:
        :class:`app.pipelines.data_generator.OrderRecord` instances.
    items:
        :class:`app.pipelines.data_generator.OrderItemRecord` instances.
    unit_prices:
        ``catalogue_id -> unit_price_egp``.  Without it ``avg_order_value_egp``
        is unavailable and that feature is omitted.
    """
    prices = unit_prices or {}
    rows: list[tuple[str, float, date, str, str | None]] = []

    # Index items by order so basket value can be assembled per order.
    items_by_order: dict[Any, list[Any]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)

    for order in orders:
        order_day = _order_day(order.created_at)
        order_items = items_by_order.get(order.order_id, [])

        # order_frequency: one sample per order, valued by the day it landed on.
        rows.append(("order_frequency", 1.0, order_day, order.pharmacy_id, None))

        basket = 0.0
        priced = True
        for item in order_items:
            price = prices.get(item.catalogue_id)
            if price is None:
                priced = False
                break
            basket += float(price) * float(item.quantity)
        if priced and order_items:
            rows.append(("avg_order_value_egp", basket, order_day, order.pharmacy_id, None))

        for item in order_items:
            rows.append(
                ("match_confidence", float(item.confidence), order_day, order.pharmacy_id, item.catalogue_id)
            )

    frame = pd.DataFrame(rows, columns=list(FEATURE_FRAME_COLUMNS))
    return frame


def daily_units_frame(panel: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    """Convert a daily units-sold panel into the long monitored-feature format.

    One sample per ``(pharmacy_id, product_id, day)`` cell, including the
    genuine zero-demand days — those zeros are most of the distribution and
    dropping them would hide exactly the sparsity a drift check should notice.
    """
    if date_column not in panel.columns:
        raise ValueError(f"panel is missing the {date_column!r} column")
    product_column = "product_id" if "product_id" in panel.columns else "catalogue_id"

    frame = pd.DataFrame(
        {
            "feature_name": "daily_units_sold",
            "value": panel["units_sold"].to_numpy(dtype=float),
            "date": pd.to_datetime(panel[date_column]).dt.date,
            "pharmacy_id": panel["pharmacy_id"].to_numpy(),
            "product_id": panel[product_column].to_numpy(),
        }
    )
    return frame


def concat_feature_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    """Stack several long-format feature frames into one."""
    usable = [frame for frame in frames if not frame.empty]
    if not usable:
        return pd.DataFrame(columns=list(FEATURE_FRAME_COLUMNS))
    return pd.concat(usable, ignore_index=True)


def split_windows(
    frame: pd.DataFrame,
    *,
    current_days: int = DEFAULT_CURRENT_WINDOW_DAYS,
    reference_days: int = DEFAULT_REFERENCE_WINDOW_DAYS,
    date_column: str = "date",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a long-format frame into ``(reference, current)`` calendar windows.

    The current window is the most recent ``current_days`` days; the reference
    window is the ``reference_days`` immediately preceding it.  The two windows
    never overlap, so the reference always describes the period *before* the one
    being judged.
    """
    if date_column not in frame.columns:
        raise ValueError(f"frame is missing the {date_column!r} column")
    if current_days < 1 or reference_days < 1:
        raise ValueError("current_days and reference_days must both be >= 1")

    days = pd.to_datetime(frame[date_column])
    last_day = days.max().date()
    current_start = last_day - timedelta(days=current_days - 1)
    reference_start = current_start - timedelta(days=reference_days)

    current = frame.loc[days.dt.date >= current_start]
    reference = frame.loc[(days.dt.date >= reference_start) & (days.dt.date < current_start)]
    return reference.reset_index(drop=True), current.reset_index(drop=True)


async def load_monitored_features(
    session: AsyncSession,
    *,
    start_date: date,
    end_date: date,
    include_daily_units: bool = True,
) -> pd.DataFrame:
    """Assemble the monitored-feature frame straight from PostgreSQL.

    The three order-derived features are aggregated in SQL (the ledger has
    ~76 000 items, so round-tripping every row into pandas to aggregate in
    Python would be wasteful).  ``daily_units_sold`` is *not* derived here — it
    comes from the densified demand panel via :func:`app.ml.dataset.load_demand_panel`,
    which is the only place that knows how to expand missing days.
    """
    from app.ml.dataset import DAY_EXPRESSION, _as_utc_start
    from app.models import DrugCatalogue, Order, OrderItem

    upper_bound = _as_utc_start(end_date + timedelta(days=1))
    lower_bound = _as_utc_start(start_date)

    prices = {
        row.catalogue_id: float(row.unit_price_egp)
        for row in (
            await session.execute(
                select(DrugCatalogue.catalogue_id, DrugCatalogue.unit_price_egp).where(
                    DrugCatalogue.unit_price_egp.is_not(None)
                )
            )
        ).all()
    }

    # --- order_frequency: one row per order -----------------------------
    order_rows = (
        await session.execute(
            select(
                Order.id.label("order_id"),
                Order.pharmacy_id.label("pharmacy_id"),
                DAY_EXPRESSION.label("order_date"),
            )
            .where(Order.created_at >= lower_bound, Order.created_at < upper_bound)
        )
    ).all()
    orders_frame = pd.DataFrame(order_rows, columns=["order_id", "pharmacy_id", "date"])
    orders_frame["date"] = pd.to_datetime(orders_frame["date"]).dt.date

    frames: list[pd.DataFrame] = [
        pd.DataFrame(
            {
                "feature_name": "order_frequency",
                "value": 1.0,
                "date": orders_frame["date"],
                "pharmacy_id": orders_frame["pharmacy_id"],
                "product_id": None,
            }
        )
    ]

    if not orders_frame.empty:
        # --- avg_order_value_egp and match_confidence -------------------
        item_rows = (
            await session.execute(
                select(
                    OrderItem.order_id.label("order_id"),
                    OrderItem.catalogue_id.label("product_id"),
                    OrderItem.quantity.label("quantity"),
                    OrderItem.confidence.label("confidence"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .where(
                    Order.created_at >= lower_bound,
                    Order.created_at < upper_bound,
                    OrderItem.catalogue_id.is_not(None),
                )
            )
        ).all()
        items_frame = pd.DataFrame(item_rows, columns=["order_id", "product_id", "quantity", "confidence"])
        items_frame = items_frame.merge(orders_frame, on="order_id", how="inner")

        if not items_frame.empty and prices:
            items_frame["line_value"] = items_frame["product_id"].map(prices).fillna(0.0) * items_frame[
                "quantity"
            ].astype(float)
            baskets = items_frame.groupby("order_id", sort=False)["line_value"].sum()
            priced_orders = items_frame.groupby("order_id", sort=False)["product_id"].apply(
                lambda series: series.isin(prices).all()
            )
            basket_rows = items_frame.drop_duplicates("order_id").set_index("order_id")
            frames.append(
                pd.DataFrame(
                    {
                        "feature_name": "avg_order_value_egp",
                        "value": baskets.reindex(basket_rows.index)[priced_orders].astype(float),
                        "date": basket_rows["date"],
                        "pharmacy_id": basket_rows["pharmacy_id"],
                        "product_id": None,
                    }
                )
            )

        confidence = items_frame.dropna(subset=["confidence"])
        if not confidence.empty:
            frames.append(
                pd.DataFrame(
                    {
                        "feature_name": "match_confidence",
                        "value": confidence["confidence"].astype(float),
                        "date": confidence["date"],
                        "pharmacy_id": confidence["pharmacy_id"],
                        "product_id": confidence["product_id"],
                    }
                )
            )

    frame = concat_feature_frames(*frames)
    logger.info(
        "Monitored features loaded",
        extra={
            "start_date": str(start_date),
            "end_date": str(end_date),
            "rows": len(frame),
            "features": sorted(frame["feature_name"].unique().tolist()) if not frame.empty else [],
            "include_daily_units": include_daily_units,
        },
    )
    return frame


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def log_drift_to_db(
    session: AsyncSession,
    report: DriftReport,
    *,
    retraining_triggered: bool = False,
    checked_at: datetime | None = None,
) -> list[str]:
    """Append one ``drift_logs`` row per evaluated feature.

    Parameters
    ----------
    session:
        Open async session; committed before returning.
    report:
        The evaluation to persist.
    retraining_triggered:
        Whether this evaluation caused a retraining run.  The retraining flow
        sets it afterwards through :func:`mark_retraining_triggered`.
    checked_at:
        Timestamp to record.  Defaults to now, and is returned implicitly
        through the rows so a later ``retraining_triggered`` update can find
        exactly the rows this evaluation wrote.

    Returns
    -------
    list[str]
        The ids of the inserted rows, in feature order.
    """
    timestamp = checked_at or datetime.now(tz=timezone.utc)
    rows = [
        DriftLog(
            checked_at=timestamp,
            feature_name=result.feature_name,
            psi_score=result.psi_score,
            status=result.status,
            retraining_triggered=retraining_triggered,
        )
        for result in report.results
    ]
    if not rows:
        logger.warning("Drift report contained no results; nothing logged")
        return []

    session.add_all(rows)
    await session.commit()
    logger.info(
        "Drift evaluation persisted",
        extra={
            "rows": len(rows),
            "features": [result.feature_name for result in report.results],
            "max_psi": round(report.max_psi, 6),
            "drift_detected": report.drift_detected,
        },
    )
    return [str(row.id) for row in rows]


async def mark_retraining_triggered(session: AsyncSession, log_ids: Sequence[str]) -> int:
    """Set ``retraining_triggered = True`` on the rows written by one evaluation.

    Applied after the retraining decision is known, so a drift check that
    exits cleanly stays ``False`` — the audit trail distinguishes "drift seen,
    nothing to do" from "drift seen, model retrained".
    """
    if not log_ids:
        return 0
    result = await session.execute(
        DriftLog.__table__.update()
        .where(DriftLog.id.in_(list(log_ids)))
        .values(retraining_triggered=True)
    )
    await session.commit()
    updated = int(result.rowcount or 0)
    logger.info("Drift rows flagged as retraining-triggered", extra={"rows": updated})
    return updated


__all__ = [
    "DEFAULT_BINS",
    "DEFAULT_CURRENT_WINDOW_DAYS",
    "DEFAULT_REFERENCE_WINDOW_DAYS",
    "FEATURE_FRAME_COLUMNS",
    "MONITORED_FEATURES",
    "PSI_ALERT_THRESHOLD",
    "PSI_EPSILON",
    "PSI_WARNING_THRESHOLD",
    "STATUS_DRIFT_DETECTED",
    "STATUS_OK",
    "STATUS_WARNING",
    "DriftDetector",
    "DriftReport",
    "DriftResult",
    "InsufficientDriftDataError",
    "calculate_psi",
    "classify_psi",
    "concat_feature_frames",
    "daily_units_frame",
    "load_monitored_features",
    "log_drift_to_db",
    "mark_retraining_triggered",
    "monitored_features_from_records",
    "quantile_bin_edges",
    "split_windows",
]


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    logging.basicConfig(level=logging.INFO)
    baseline = np.random.default_rng(0).poisson(3.0, size=5_000)
    print("identical:", round(calculate_psi(baseline, baseline), 8))
    print("shocked :", round(calculate_psi(baseline, baseline * 4), 6))
    print("status  :", classify_psi(calculate_psi(baseline, baseline * 4)))