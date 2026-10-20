/**
 * Procurement arithmetic for the Inventory page.
 *
 * Every function is pure and takes plain numbers, so the maths can be read and
 * checked on its own — no React, no formatting decisions beyond rounding.
 * Provenance is stated next to each formula, including where it is a planning
 * convention rather than a derived result.
 *
 * The formulas themselves are never shown to the user; they exist only to power
 * the numbers the catalog and the reorder card display.
 */

import type { ForecastItem } from '@/types/forecast';
import type { Scenario } from '@/types/scenario';

/** Round to one decimal without a formatter library. */
export const round1 = (value: number): number => Math.round(value * 10) / 10;

/**
 * Safety buffer in the reorder recommendation.
 *
 * The recommendation is our high-demand estimate plus 15 %:
 *
 *     Q* = ceil(Σ upper_estimate × 1.15)
 *
 * The high end of the range is used deliberately, so this over-orders relative
 * to expected demand: running out on an essential line costs more than the 15 %
 * of shelf value it ties up. A `supply_delay` scenario widens the buffer
 * further, because a longer lead time is exactly what safety stock exists to
 * absorb.
 */
export const BASE_SAFETY_FACTOR = 1.15;

/**
 * Below this many units of high-demand across the whole window, no order is
 * recommended.
 *
 * A mostly-flat series still has a high estimate of, say, 0.03 units. Without
 * this floor `ceil(0.03 × 1.15)` yields `1`, and the catalog would suggest
 * buying a single unit of a product nobody is buying. Rounding noise is not a
 * replenishment signal.
 */
export const MIN_ORDERABLE_UNITS = 1;

export interface ProjectedDemand {
  /** Window length in days. */
  days: number;
  /** Sum of expected demand across the window, scenario-adjusted. */
  totalExpected: number;
  /** Sum of the high end of the range, scenario-adjusted. */
  totalUpper: number;
  /** Mean expected demand per day, scenario-adjusted. */
  meanPerDay: number;
  /** Scenario multiplier that produced these numbers, kept for display. */
  multiplier: number;
}

/**
 * Aggregate a forecast into planning totals under a scenario.
 *
 * The scenario is applied once, here, and every downstream figure derives from
 * the adjusted totals — so the table, the chart and the recommendation cannot
 * disagree with each other.
 */
export function projectDemand(item: ForecastItem, scenario: Scenario): ProjectedDemand {
  const factor = scenario.demandMultiplier;

  const totalExpected = item.predicted_units.reduce((sum, units) => sum + units, 0) * factor;
  const totalUpper = item.upper_bound.reduce((sum, units) => sum + units, 0) * factor;
  const days = item.dates.length;

  return {
    days,
    totalExpected,
    totalUpper,
    meanPerDay: days > 0 ? totalExpected / days : 0,
    multiplier: factor,
  };
}

export interface ReorderRecommendation {
  /** Whole units, never fractional. */
  quantity: number;
  /** quantity × catalogue unit price. */
  estimatedCostEgp: number;
  unitPriceEgp: number;
  /** Effective buffer applied. */
  safetyFactor: number;
  /** Whether there is anything worth ordering. */
  orderable: boolean;
}

/** Economic reorder recommendation for one product. */
export function recommendReorder(
  projection: ProjectedDemand,
  unitPriceEgp: number,
  scenario: Scenario,
): ReorderRecommendation {
  const safetyFactor = BASE_SAFETY_FACTOR * scenario.safetyFactor;

  if (projection.totalUpper < MIN_ORDERABLE_UNITS) {
    return { quantity: 0, estimatedCostEgp: 0, unitPriceEgp, safetyFactor, orderable: false };
  }

  const quantity = Math.ceil(projection.totalUpper * safetyFactor);
  return {
    quantity,
    estimatedCostEgp: round1(quantity * unitPriceEgp),
    unitPriceEgp,
    safetyFactor,
    orderable: true,
  };
}

/* -------------------------------------------------------------------------- */
/* Stock status                                                               */
/* -------------------------------------------------------------------------- */

export type StockBand = 'adequate' | 'low' | 'critical' | 'unknown';

/**
 * Days-of-cover thresholds, in days.
 *
 * `> 7` adequate, `3–7` low, `< 3` critical — the bands specified for this
 * phase. Exactly 3 days is *low* and exactly 7 is *low*: the thresholds are
 * inclusive at the top of the "low" band so a product sitting exactly on a
 * boundary is never over-stated as comfortable.
 */
export const STOCK_BANDS = {
  criticalBelowDays: 3,
  adequateAboveDays: 7,
} as const;

export const STOCK_BAND_LABELS: Record<StockBand, string> = {
  adequate: 'Adequate',
  low: 'Low Stock',
  critical: 'Critical',
  unknown: 'Not set',
};

export interface StockStatus {
  band: StockBand;
  /**
   * Days of cover, or null when it cannot be computed.
   *
   * Null happens when stock has not been entered or expected demand is zero.
   * Both are reported rather than coerced to a number, because "infinite cover"
   * and "we do not know" are very different claims to an operator.
   */
  daysOfCover: number | null;
  /** Whether a cover figure exists at all. */
  computable: boolean;
}

/**
 * Days of cover against expected daily demand.
 *
 * `onHandUnits` is `undefined` until the operator enters it — see
 * `hooks/useStockLevels` for why it cannot come from the backend.
 */
export function assessStockStatus(
  onHandUnits: number | undefined,
  meanPerDay: number,
): StockStatus {
  if (onHandUnits === undefined) {
    return { band: 'unknown', daysOfCover: null, computable: false };
  }

  if (meanPerDay <= 0) {
    // No expected demand means nothing will run out, but we cannot express that
    // as a day count, so it is reported as not-computable rather than "∞".
    return { band: 'adequate', daysOfCover: null, computable: false };
  }

  const daysOfCover = round1(onHandUnits / meanPerDay);

  let band: StockBand;
  if (daysOfCover < STOCK_BANDS.criticalBelowDays) {
    band = 'critical';
  } else if (daysOfCover <= STOCK_BANDS.adequateAboveDays) {
    band = 'low';
  } else {
    band = 'adequate';
  }

  return { band, daysOfCover, computable: true };
}

/**
 * Sort weight so the most urgent stock floats to the top of the catalog.
 *
 * `unknown` sits deliberately between `low` and `adequate`: a missing stock
 * figure still needs the operator to enter something, because without it there
 * is no reorder recommendation at all. `adequate` needs nothing and sinks.
 */
export const BAND_PRIORITY: Record<StockBand, number> = {
  critical: 0,
  low: 1,
  unknown: 2,
  adequate: 3,
};

/**
 * Order rows by urgency, then name.
 *
 * Lives here rather than beside the table component on purpose: a module that
 * exports both a React component and a plain function cannot use React Fast
 * Refresh — Vite invalidates the whole module on every edit instead of
 * hot-swapping it. Keeping the helper in a plain module keeps the component
 * file's refresh working.
 *
 * Typed structurally so it works for any row shape carrying a band and a label.
 */
export function sortByUrgency<T extends { band: StockBand; label: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const bandDiff = BAND_PRIORITY[a.band] - BAND_PRIORITY[b.band];
    if (bandDiff !== 0) return bandDiff;
    return a.label.localeCompare(b.label);
  });
}
/** Format a number of Egyptian Pounds for display. */
export function formatEgp(value: number): string {
  return `${value.toLocaleString('en-EG', { maximumFractionDigits: 0 })} EGP`;
}
