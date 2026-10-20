/**
 * Registry + retraining types mirroring `backend/app/schemas/registry.py`.
 *
 * ## Two corrections to the Phase 5 spec
 *
 * **1. `metrics` arrives empty.** The spec types `ModelMetadataItem.metrics` as
 * `ModelMetrics` with five required numbers. The real service returns
 * `metrics: {}` — the registry accessor does not surface the run's logged
 * metrics. Every field here is therefore nullable, and the admin console renders
 * an em dash for a missing metric rather than a zero.
 *
 * `useModelGovernance` in `api/endpoints/registry.ts` fills the gap by reading
 * the champion run's metrics from MLflow, which is where they genuinely live.
 *
 * **2. `p95_latency_ms` is not a model metric.** It belongs to no training run;
 * it is a serving-time measurement, and `lib/telemetry.ts` derives it from the
 * Prometheus request-duration histogram. It is carried here because the
 * comparison table wants it, and it is labelled as a serving metric wherever it
 * appears.
 */

/** Out-of-sample metrics for one model version. */
export interface ModelMetrics {
  /** Mean absolute error, units. Lower is better. */
  mae: number | null;
  /** Root mean squared error, units. Lower is better. */
  rmse: number | null;
  /** Mean absolute percentage error, as a fraction (0.648 = 64.8%). Lower is better. */
  mape: number | null;
  /** Improvement over the naive seasonal baseline, as a percentage. */
  vs_naive_baseline_improvement_pct: number | null;
  /** P95 serving latency, milliseconds. A serving metric, not a training one. */
  p95_latency_ms: number | null;
}

/** Baseline metrics for the naive comparator, from the same training run. */
export interface BaselineMetrics {
  mae: number | null;
  rmse: number | null;
  mape: number | null;
}

/** One registered model version. */
export interface ModelMetadataItem {
  name: string;
  version: string;
  /** `Production`, `Staging` or `Archived` in practice. */
  stage: string;
  run_id: string | null;
  status: 'Production' | 'candidate';
  registered_at: string | null;
  last_updated_at: string | null;
  promotion_reason: string | null;
  /** Out-of-sample MAE. Populated by the registry even though `metrics` is not. */
  test_mae: number | null;
  /** Empty in practice — see the note at the top of this file. */
  metrics: Partial<ModelMetrics>;
}

/** `GET /api/v1/model-registry`. */
export interface ModelRegistryResponse {
  models: ModelMetadataItem[];
  production_version: string | null;
  model_name: string;
  tracking_uri: string | null;
  /** False when MLflow is unreachable — the list is then empty, never stale. */
  reachable: boolean;
}

/* -------------------------------------------------------------------------- */
/* Governance view model                                                       */
/* -------------------------------------------------------------------------- */

/**
 * The champion and any challenger, with metrics resolved.
 *
 * Produced by `useModelGovernance`, which merges three sources: the registry
 * (versions and lineage), the champion run in MLflow (error metrics, because
 * the registry returns none) and Prometheus (serving latency).
 */
export interface ModelGovernance {
  /** The version currently serving traffic, or null when there is none. */
  champion: ModelMetadataItem | null;
  /** A registered version not currently serving, or null. */
  challenger: ModelMetadataItem | null;
  /** Champion metrics, resolved where a source supplied them. */
  championMetrics: ModelMetrics;
  /** Naive-baseline metrics from the same run, for the champion's gain. */
  baselineMetrics: BaselineMetrics;
  /** Training parameters worth showing an administrator. */
  trainingParams: Record<string, string>;
  /** True when MLflow answered and its metrics were merged in. */
  metricsResolved: boolean;
}

/* -------------------------------------------------------------------------- */
/* Retraining                                                                 */
/* -------------------------------------------------------------------------- */

/** `POST /api/v1/retrain` request body. The endpoint requires a body; `{}` is valid. */
export interface RetrainRequest {
  force?: boolean;
  notify_on_completion?: boolean;
  window_days?: number;
}

/** `POST /api/v1/retrain` — 202 Accepted. */
export interface RetrainResponse {
  flow_run_id: string;
  status: 'SUBMITTED' | 'SKIPPED';
  message: string;
  estimated_duration_seconds: number;
  force: boolean;
}
