"""Training-data assembly for the demand forecaster.

Kept separate from :mod:`app.ml.features` on purpose: ``features.py`` must stay
a pure, dependency-light transformation so that the API inference path can reuse
it unchanged (no train/serve skew).  This module owns everything to the *left*
of that transformation — SQL, panel densification and pharmacy segmentation.

The panel is the daily units-sold cube ``(pharmacy_id, product_id, date)``
derived from the synthetic ``orders`` / ``order_items`` ledger.

Synthetic data only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

import pandas as pd
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ml.features import PHARMACY_TIER_VALUES, SERIES_KEY, UNKNOWN_CATEGORY
from app.models import DrugCatalogue, Order, OrderItem
from app.pipelines.data_generator import MIN_ACTIVE_SERIES_UNITS, PHARMACY_COUNT, build_pharmacies

#: Timestamps are stored in UTC; order days are bucketed in Egyptian local time
#: so a panel row matches the calendar day the generator actually simulated.
DAY_EXPRESSION: Final[Any] = func.date(literal_column("orders.created_at AT TIME ZONE 'EET'"))

#: Columns the model consumes.
PANEL_COLUMNS: Final[tuple[str, ...]] = (
    "pharmacy_id",
    "product_id",
    "date",
    "units_sold",
    "product_category",
    "pharmacy_tier",
    "therapeutic_class",
)

#: Threshold separating "active" series (with history worth forecasting) from
#: one-off SKUs.  Matches the Phase 1 naive-baseline population so the model
#: and the benchmark are always measured on exactly the same series.
DEFAULT_MIN_SERIES_UNITS: Final[int] = MIN_ACTIVE_SERIES_UNITS


class EmptyPanelError(RuntimeError):
    """Raised when the queried window yields no usable series."""


def pharmacy_tier_map(random_seed: int | None = None) -> dict[str, str]:
    """Return ``{pharmacy_id: tier}`` for the synthetic pharmacy registry.

    The pharmacy registry is generated deterministically from a seed (Phase 1
    deliberately stores no ``pharmacies`` table), so the tier of an order's
    pharmacy is recovered by rebuilding the registry with the same seed.

    .. warning::
       If the database was seeded with a different ``--random-seed`` than
       ``settings.data_random_seed``, tiers cannot be recovered and every
       pharmacy falls back to ``MEDIUM``.  Introducing a ``pharmacies`` table
       is the proper fix and is tracked for a later phase.
    """
    seed = settings.data_random_seed if random_seed is None else random_seed
    return {pharmacy.pharmacy_id: pharmacy.tier for pharmacy in build_pharmacies(PHARMACY_COUNT, seed)}


async def load_catalogue(session: AsyncSession) -> pd.DataFrame:
    """Return ``product_id -> (category, therapeutic_class)`` as a frame."""
    rows = (
        await session.execute(select(DrugCatalogue.catalogue_id, DrugCatalogue.category, DrugCatalogue.therapeutic_class))
    ).all()
    return pd.DataFrame(rows, columns=["product_id", "product_category", "therapeutic_class"])


async def load_demand_panel(
    session: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    min_series_units: int = DEFAULT_MIN_SERIES_UNITS,
    pharmacy_ids: tuple[str, ...] | None = None,
    product_ids: tuple[str, ...] | None = None,
    densify: bool = True,
) -> pd.DataFrame:
    """Build the daily units-sold panel from the order ledger.

    Parameters
    ----------
    start_date / end_date:
        Inclusive calendar window.  Defaults to "everything in the database".
    min_series_units:
        A ``(pharmacy_id, product_id)`` series is kept only when its total units
        over the window reach this threshold, which removes one-off noise from
        training while still leaving the honest zero-demand days in place.
    densify:
        Emit one row per series per calendar day, filling days without sales
        with ``0``.  Required for correct lag/rolling features; without it a
        missing day would silently shift every lag.
    """
    catalogue = await load_catalogue(session)

    statement = (
        select(
            Order.pharmacy_id.label("pharmacy_id"),
            OrderItem.catalogue_id.label("product_id"),
            DAY_EXPRESSION.label("date"),
            func.sum(OrderItem.quantity).label("units_sold"),
        )
        .select_from(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.catalogue_id.is_not(None), OrderItem.quantity > 0)
        .group_by(Order.pharmacy_id, OrderItem.catalogue_id, DAY_EXPRESSION)
    )
    if start_date is not None:
        statement = statement.where(Order.created_at >= _as_utc_start(start_date))
    if end_date is not None:
        statement = statement.where(Order.created_at < _as_utc_start(end_date + timedelta(days=1)))
    if pharmacy_ids:
        statement = statement.where(Order.pharmacy_id.in_(pharmacy_ids))
    if product_ids:
        statement = statement.where(OrderItem.catalogue_id.in_(product_ids))

    rows = (await session.execute(statement)).all()
    if not rows:
        raise EmptyPanelError(
            "no orders matched the requested window — run "
            "`python -m app.pipelines.data_generator --seed --days 180` first"
        )

    aggregated = pd.DataFrame(rows, columns=["pharmacy_id", "product_id", "date", "units_sold"])
    aggregated["date"] = pd.to_datetime(aggregated["date"])
    aggregated["units_sold"] = aggregated["units_sold"].astype("int64")

    panel = aggregated.merge(catalogue, on="product_id", how="left")
    panel["product_category"] = panel["product_category"].fillna(UNKNOWN_CATEGORY)
    panel["therapeutic_class"] = panel["therapeutic_class"].fillna(UNKNOWN_CATEGORY)

    if min_series_units > 0:
        totals = aggregated.groupby(list(SERIES_KEY), sort=False)["units_sold"].sum()
        keep = totals[totals >= min_series_units].index
        panel = panel.loc[
            panel.set_index(list(SERIES_KEY)).index.isin(keep)
        ].reset_index(drop=True)

    if densify:
        panel = _densify(panel, calendar_start=start_date, calendar_end=end_date)

    tiers = pharmacy_tier_map()
    panel["pharmacy_tier"] = panel["pharmacy_id"].map(tiers).fillna("MEDIUM")
    unknown_tiers = set(panel["pharmacy_tier"].unique()) - set(PHARMACY_TIER_VALUES)
    if unknown_tiers:
        raise ValueError(f"unexpected pharmacy tiers {sorted(unknown_tiers)}")

    return (
        panel.sort_values(list(SERIES_KEY) + ["date"], kind="stable")
        .reset_index(drop=True)
        .loc[:, list(PANEL_COLUMNS)]
    )


def _densify(
    panel: pd.DataFrame,
    *,
    calendar_start: date | None = None,
    calendar_end: date | None = None,
) -> pd.DataFrame:
    """Expand the panel to one row per series per calendar day.

    Without this, a pharmacy that ordered a product twice in a month would have
    gaps in its timeline and every positional lag would silently reference the
    wrong calendar day.

    The calendar spans the **requested** window when the caller supplied one,
    otherwise the observed span.  Anchoring on the observed span is wrong once
    any filter narrows the result: densifying a single product whose last order
    was three days ago would silently drop the trailing zero-demand days the
    caller asked for, and every downstream forecast would be anchored on a stale
    date instead of the true end of the window.  Callers that pass no window
    (training, the retraining flow) keep the observed-span behaviour.

    The grid is built with a **cross join over the unique series pairs** (not
    ``MultiIndex.from_product`` on the two key columns, which would cross the
    3,000 pharmacy ids with the 3,000 product ids and allocate billions of
    rows).
    """
    start = pd.Timestamp(calendar_start) if calendar_start is not None else panel["date"].min()
    end = pd.Timestamp(calendar_end) if calendar_end is not None else panel["date"].max()
    # The calendar must match the panel's `date` dtype or the cross join refuses
    # to merge.  The two can disagree in *both* directions: the panel's column is
    # timezone-naive (the SQL `date()` returns plain dates), while a bound taken
    # from `max(created_at)` on a TIMESTAMPTZ arrives timezone-aware.  Coercing
    # the bounds to the panel is what keeps every caller working regardless of
    # which kind of bound it passes.
    tz = getattr(panel["date"].dt, "tz", None)
    if tz is None:
        start = start.tz_localize(None) if start.tzinfo is not None else start
        end = end.tz_localize(None) if end.tzinfo is not None else end
    else:
        start = start.tz_localize(tz) if start.tzinfo is None else start.tz_convert(tz)
        end = end.tz_localize(tz) if end.tzinfo is None else end.tz_convert(tz)
    calendar = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    series = panel[list(SERIES_KEY)].drop_duplicates()
    grid = series.merge(calendar, how="cross")

    context_columns = [
        column for column in ("product_category", "therapeutic_class") if column in panel.columns
    ]
    filled = grid.merge(panel, on=list(SERIES_KEY) + ["date"], how="left")
    filled["units_sold"] = filled["units_sold"].fillna(0).astype("int64")
    for column in context_columns:
        lookup = panel[["product_id", column]].drop_duplicates(subset=["product_id"])
        filled[column] = filled["product_id"].map(dict(zip(lookup["product_id"], lookup[column])))
    return filled


def _as_utc_start(day: date) -> datetime:
    """Midnight UTC on ``day`` (safe upper/lower bound for TIMESTAMPTZ filters)."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def panel_summary(panel: pd.DataFrame) -> dict[str, Any]:
    """Small statistics dictionary, logged with every training run."""
    series = panel.groupby(list(SERIES_KEY), sort=False)["units_sold"].sum()
    return {
        "rows": int(len(panel)),
        "series": int(len(series)),
        "pharmacies": int(panel["pharmacy_id"].nunique()),
        "products": int(panel["product_id"].nunique()),
        "days": int(panel["date"].nunique()),
        "start_date": panel["date"].min().date().isoformat(),
        "end_date": panel["date"].max().date().isoformat(),
        "total_units": int(panel["units_sold"].sum()),
        "mean_units_per_day": float(panel["units_sold"].mean()),
        "zero_share": float((panel["units_sold"] == 0).mean()),
    }


__all__ = [
    "DEFAULT_MIN_SERIES_UNITS",
    "PANEL_COLUMNS",
    "EmptyPanelError",
    "load_catalogue",
    "load_demand_panel",
    "panel_summary",
    "pharmacy_tier_map",
]