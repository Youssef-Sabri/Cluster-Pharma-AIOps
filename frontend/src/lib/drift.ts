/**
 * Drift and retraining vocabulary — pure, no React.
 *
 * Two things live here that the components would otherwise each re-derive:
 * the band a PSI score falls into, and the real shape of the retraining flow.
 */

import type { DriftStatus, DriftStatusResponse } from '@/types/drift';

/* -------------------------------------------------------------------------- */
/* Bands                                                                      */
/* -------------------------------------------------------------------------- */

/** Early-warning boundary. `settings.drift_psi_warning`. */
export const PSI_WARNING_THRESHOLD = 0.1;

/**
 * Critical boundary. `settings.drift_psi_alert`, and echoed per-response as
 * `psi_threshold` — which is preferred over this constant wherever the API has
 * spoken, so a retuned backend needs no frontend change.
 */
export const PSI_ALERT_THRESHOLD = 0.2;

/** Which band a PSI score sits in, given the two boundaries. */
export function psiBand(psi: number, warning = PSI_WARNING_THRESHOLD, alert = PSI_ALERT_THRESHOLD): DriftStatus {
  if (psi >= alert) return 'DRIFT_DETECTED';
  if (psi >= warning) return 'WARNING';
  return 'OK';
}

/** Business-facing description of a band, for tooltips and the banner. */
export const PSI_BAND_LABEL: Record<DriftStatus, string> = {
  OK: 'Healthy',
  WARNING: 'Moderate shift',
  DRIFT_DETECTED: 'Action required',
};

export const PSI_BAND_DESCRIPTION: Record<DriftStatus, string> = {
  OK: 'Distribution is close to the training baseline. No action needed.',
  WARNING: 'Distribution has moved away from the training baseline. Worth watching.',
  DRIFT_DETECTED: 'Distribution has moved far enough to act on. Retraining is warranted.',
};

/**
 * Turns a `feature_name` into something an administrator can read.
 *
 * The backend monitors `daily_units_sold`, `order_frequency`,
 * `avg_order_value_egp` and `match_confidence`. This is `/admin`, so the raw
 * names are acceptable — but underscores read like a column reference, and the
 * console is a place where that costs a moment.
 *
 * Labels are kept short: the chart's y-axis wraps long ones across two lines,
 * and the line break swallows the separating space, turning
 * "Order-match confidence" into "Order-matchconfidence" in the SVG.
 */
export function featureLabel(name: string): string {
  const known: Record<string, string> = {
    daily_units_sold: 'Daily units sold',
    order_frequency: 'Order frequency',
    avg_order_value_egp: 'Average order value',
    match_confidence: 'Match confidence',
  };
  return known[name] ?? name.replace(/_/g, ' ');
}

/* -------------------------------------------------------------------------- */
/* Demand shock simulator                                                     */
/* -------------------------------------------------------------------------- */

/**
 * A demand shock an operator can preview.
 *
 * `factor` is a demand multiplier. It is **not** a PSI value and is never
 * rendered as one — see `projectedPsi` in the simulator for how it is used.
 */
export interface DemandShock {
  id: string;
  label: string;
  /** Multiplier applied to observed demand. */
  factor: number;
  blurb: string;
}

/**
 * The no-shock scenario.
 *
 * Named rather than indexed out of `DEMAND_SHOCKS`, so the fallback the UI falls
 * back to is visible in the type and not an unchecked `[0]`.
 */
export const DEFAULT_SHOCK: DemandShock = {
  id: 'none',
  label: 'No shock',
  factor: 1,
  blurb: 'The measured scores, untouched.',
};

/** The three scenarios the brief asks for, plus the do-nothing baseline. */
export const DEMAND_SHOCKS: readonly DemandShock[] = [
  DEFAULT_SHOCK,
  {
    id: 'flu',
    label: 'Flu surge +35%',
    factor: 1.35,
    blurb: 'A seasonal spike in orders and units.',
  },
  {
    id: 'holiday',
    label: 'Holiday rush +50%',
    factor: 1.5,
    blurb: 'A larger, sustained demand jump.',
  },
];

/* -------------------------------------------------------------------------- */
/* Retraining flow                                                            */
/* -------------------------------------------------------------------------- */

/**
 * How a stage's displayed status is known.
 *
 * `observed` is backed by evidence the API actually reported. `awaiting` is the
 * honest answer for every stage once a run has been dispatched: the backend
 * exposes no per-stage telemetry, so the console cannot claim to know which one
 * is executing. See `RetrainingStepper`.
 */
export type StageEvidence = 'observed' | 'awaiting';

/**
 * The stages of `clusterops-nightly-retrain`, in execution order.
 *
 * Taken from the flow body in `backend/app/pipelines/retrain_flow.py`. The Phase
 * 4 brief lists five stages; the implemented flow has seven, because the drift
 * evaluation and its gate decision are their own tasks, and scoring the
 * challenger is separate from the gate that authorises the registry transition.
 * All seven are named as the code names them rather than collapsed into the
 * brief's five.
 */
export interface RetrainStage {
  /** Task name in `retrain_flow.py`, so the label can be traced back. */
  task: string;
  /** What the stage does. */
  label: string;
}

export const RETRAIN_STAGES: readonly RetrainStage[] = [
  { task: 'check_drift_task', label: 'Drift evaluation' },
  { task: 'decision_task', label: 'Retrain gate' },
  { task: 'extract_data_task', label: 'Data ingestion' },
  { task: 'feature_pipeline_task', label: 'Feature pipeline' },
  { task: 'train_challenger_task', label: 'Challenger fit' },
  { task: 'evaluate_challenger_task', label: 'Challenger scoring' },
  { task: 'promotion_gate_task', label: '3% gate and promotion' },
];

/**
 * How a dispatched run turned out, inferred only from what the API reports.
 *
 * The retrain endpoint returns a tracking id and nothing else; the only two
 * observable consequences of a run are a new version appearing in the registry
 * or `retraining_triggered` flipping in the drift status.
 */
export type RunOutcome =
  /** A run has been dispatched and nothing observable has changed yet. */
  | 'in-flight'
  /** Drift was re-detected inside the flow and retraining proceeded. */
  | 'retraining'
  /** A new model version appeared in the registry. */
  | 'promoted'
  /** The window elapsed with no observable change. */
  | 'quiet';

/**
 * Compares the drift status captured before a run with the one after.
 *
 * `before` may be null when no evaluation existed at submission time, in which
 * case a newly non-null `retraining_triggered` still counts as movement.
 */
export function inferRunOutcome(
  before: DriftStatusResponse | null,
  after: DriftStatusResponse | null,
  versionChanged: boolean,
): RunOutcome {
  if (versionChanged) return 'promoted';
  if (after?.retraining_triggered && !before?.retraining_triggered) return 'retraining';
  return 'in-flight';
}

/** Plain-language summary of a run outcome. */
export const RUN_OUTCOME_TEXT: Record<RunOutcome, string> = {
  'in-flight': 'Submitted. No change observed yet — the registry and drift scorecard are the only things this console can see.',
  retraining: 'Drift was re-detected inside the flow, so a retraining run is proceeding.',
  promoted: 'A new model version appeared in the registry.',
  quiet: 'Submitted. The estimated window elapsed with no observable change.',
};
