/**
 * Drift types mirroring `backend/app/schemas/drift.py` and the retrain endpoint.
 *
 * ## Field names differ from the phase document
 *
 * The Phase 4 brief specified `DriftFeatureItem` with `baseline_mean` and
 * `current_mean`. The real schema has neither — a feature observation is
 * `{ feature_name, psi_score, status, checked_at }` and nothing more. That is why
 * the distribution overlay cannot be populated from the API; see
 * `DistributionOverlay`.
 *
 * The brief also typed `RetrainResponse.status` as `string`. It is a two-value
 * enum, `SUBMITTED | SKIPPED` — declared in `types/registry.ts`.
 */

/** Band a PSI score falls into. Matches the backend's own strings. */
export type DriftStatus = 'OK' | 'WARNING' | 'DRIFT_DETECTED';

/** PSI for one monitored feature at the latest evaluation. */
export interface DriftFeatureItem {
  feature_name: string;
  psi_score: number;
  status: DriftStatus;
  checked_at: string;
}

/** `GET /api/v1/drift-status`. */
export interface DriftStatusResponse {
  /** Newest observation across all features, or null when none exist yet. */
  checked_at: string | null;
  /** Worst status across the monitored features. */
  overall_status: DriftStatus;
  max_psi: number;
  /** PSI at or above which a feature counts as drift. */
  psi_threshold: number;
  features: DriftFeatureItem[];
  retraining_triggered: boolean;
  /** False when the drift table is empty — not the same as "healthy". */
  evaluated: boolean;
}

/* -------------------------------------------------------------------------- */
/* Retraining                                                                 */
/* -------------------------------------------------------------------------- */

/*
 * `RetrainRequest`, `RetrainResponse` and `RetrainStatus` are **not** declared
 * here. They already live in `types/registry.ts`, next to `ModelRegistryResponse`
 * — which is also where the run outcome has to be compared against — and a second
 * copy would be free to drift from the first. Import them from
 * `@/types/registry`.
 */

/* -------------------------------------------------------------------------- */
/* Distribution overlay                                                        */
/* -------------------------------------------------------------------------- */

/**
 * One bin of a distribution overlay.
 *
 * ## Nothing currently produces these
 *
 * The drift endpoint returns one scalar PSI per feature. `drift_logs` has no
 * distribution columns (`checked_at`, `feature_name`, `psi_score`, `status`,
 * `retraining_triggered`, `id` — verified against `information_schema`), and no
 * endpoint returns either the training window or the inference window as samples.
 *
 * The type is kept because it is the shape the component needs, and because it
 * documents exactly what a backend change would have to provide. Until then the
 * component renders an empty state rather than a fabricated histogram.
 */
export interface DistributionBin {
  /** Left edge of the bin, inclusive. */
  from: number;
  /** Right edge of the bin, exclusive, except for the final bin. */
  to: number;
  /** Share of the baseline (training) window falling in this bin, 0–1. */
  baselineShare: number;
  /** Share of the current (inference) window falling in this bin, 0–1. */
  currentShare: number;
}

/** A feature's distribution comparison, as the overlay consumes it. */
export interface DistributionComparison {
  featureName: string;
  bins: DistributionBin[];
}
