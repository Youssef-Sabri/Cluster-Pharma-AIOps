/**
 * Shared API types mirroring `backend/app/schemas/common.py`.
 *
 * Rule: strict schema parity, never `any`. Optional fields are modelled as
 * `| null` because the backend emits JSON `null` rather than omitting keys.
 */

export interface ApiErrorDetail {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string | null;
}

export interface ApiErrorEnvelope {
  error: ApiErrorDetail;
}

/** `GET /health` — `backend/app/schemas/common.py::HealthResponse`. */
export interface HealthResponse {
  status: string;
  version: string;
  models_loaded: boolean;
  db_connected: boolean;
  timestamp: string;
}

/**
 * Confidence bands enforced across the whole UI.
 *
 * These mirror `app.config`: below `review` a match is never auto-fulfilled and
 * is rendered with a NEEDS REVIEW chip; below `accept` it was not auto-matched.
 */
export const CONFIDENCE_THRESHOLDS = {
  review: 0.5,
  accept: 0.7,
} as const;

export type ConfidenceBand = 'high' | 'moderate' | 'low';

/** Map a confidence score onto its safety band. */
export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence >= CONFIDENCE_THRESHOLDS.accept) return 'high';
  if (confidence >= CONFIDENCE_THRESHOLDS.review) return 'moderate';
  return 'low';
}

/** External tooling the dashboard links out to (compose service map). */
export const BACKEND_TOOLS = {
  swagger: 'http://localhost:8000/docs',
  mlflow: 'http://localhost:5000',
  grafana: 'http://localhost:3001',
  prometheus: 'http://localhost:9090',
} as const;

/** Attribution required by the synthetic-data rule on headers and footers. */
export const SYNTHETIC_NOTICE =
  'ClusterOps Demo — Synthetic Egyptian Pharmaceutical Data';