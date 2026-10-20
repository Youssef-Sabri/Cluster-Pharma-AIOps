/**
 * Promotion-gate arithmetic.
 *
 * Pure, so the rule can be read and checked without rendering it. The gate the
 * backend enforces is `challenger_mae < production_mae * 0.97`
 * (`retrain_flow.py`), which is exactly "at least a 3% reduction in MAE".
 */

/** Minimum MAE reduction a challenger must show to be promotable. */
export const REQUIRED_IMPROVEMENT_PCT = 3.0;

/** Outcome of applying the gate to a pair of models. */
export type GateOutcome = 'approved' | 'rejected';

export interface GateEvaluation {
  outcome: GateOutcome;
  /** `(prodMae - challengerMae) / prodMae`, as a percentage. */
  improvementPct: number;
  /** True once the required reduction is met. */
  qualifies: boolean;
  /** How far short of the 3% threshold, in percentage points. Only when rejected. */
  shortfallPts: number;
}

/**
 * Evaluate the 3% rule.
 *
 * Returns null when there is nothing to evaluate — no production model, no
 * challenger, or a production MAE of zero. A zero production MAE would make the
 * ratio divide by zero, and inventing a result there would be worse than saying
 * the gate cannot be computed.
 */
export function evaluateGate(
  productionMae: number | null | undefined,
  challengerMae: number | null | undefined,
): GateEvaluation | null {
  if (productionMae === null || productionMae === undefined) return null;
  if (challengerMae === null || challengerMae === undefined) return null;
  if (!Number.isFinite(productionMae) || !Number.isFinite(challengerMae)) return null;
  if (productionMae <= 0) return null;

  const improvementPct = ((productionMae - challengerMae) / productionMae) * 100;
  const qualifies = improvementPct >= REQUIRED_IMPROVEMENT_PCT;

  return {
    outcome: qualifies ? 'approved' : 'rejected',
    improvementPct,
    qualifies,
    shortfallPts: qualifies ? 0 : REQUIRED_IMPROVEMENT_PCT - improvementPct,
  };
}

/** Which direction a lower-is-better metric moved between two models. */
export type DeltaDirection = 'better' | 'worse' | 'unchanged' | 'unknown';

export interface MetricDelta {
  direction: DeltaDirection;
  /** Relative change, as a percentage of the champion's value. */
  changePct: number;
}

/**
 * Compare one metric between champion and challenger.
 *
 * `lowerIsBetter` is a property of the metric, not of the numbers: MAE, RMSE and
 * latency all improve by going down, so a negative change is the good direction.
 * Without it a panel would colour a latency improvement as a regression.
 */
export function compareMetric(
  championValue: number | null | undefined,
  challengerValue: number | null | undefined,
  lowerIsBetter: boolean,
): MetricDelta {
  if (
    championValue === null ||
    championValue === undefined ||
    challengerValue === null ||
    challengerValue === undefined ||
    !Number.isFinite(championValue) ||
    !Number.isFinite(challengerValue) ||
    championValue === 0
  ) {
    return { direction: 'unknown', changePct: 0 };
  }

  const changePct = ((challengerValue - championValue) / Math.abs(championValue)) * 100;

  if (Math.abs(changePct) < 0.05) return { direction: 'unchanged', changePct: 0 };

  const wentDown = changePct < 0;
  const isImprovement = lowerIsBetter ? wentDown : !wentDown;

  return { direction: isImprovement ? 'better' : 'worse', changePct };
}

/** Format a percentage with an explicit sign, e.g. `+28.7%`. */
export function formatSignedPct(value: number, digits = 1): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

/** Format a signed change, e.g. `-3.2%`. */
export function formatChangePct(value: number, digits = 1): string {
  return formatSignedPct(-value, digits);
}
