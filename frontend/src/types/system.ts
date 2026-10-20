/**
 * Runtime startup state mirroring `backend/app/api/system.py`.
 *
 * Note: the backend returns this as a bare dict rather than a Pydantic model, so
 * these fields are hand-maintained. Anything not listed here that appears in a
 * response is simply ignored at the type level — React Query does not strip it —
 * but nothing may read a field that is not declared here.
 */

/** The Production demand model actually resident in the process. */
export interface RuntimeModelInfo {
  model_name: string;
  model_version: string;
  run_id: string;
  /** ISO timestamp of when the model was loaded into memory. */
  loaded_at: string;
  models_loaded: boolean;
}

/** `GET /api/v1/system/state`. */
export interface SystemStateResponse {
  /** False while the Production model is still loading — forecast returns 503. */
  models_loaded: boolean;
  /** False while the product catalogue is still loading — matching returns 503. */
  catalogue_loaded: boolean;
  catalogue_entries: number;
  /**
   * Startup failures (e.g. MLflow unreachable). Empty on a healthy boot; this
   * is the honest signal that the process came up degraded.
   */
  startup_errors: string[];
  runtime: RuntimeModelInfo;
}

/* -------------------------------------------------------------------------- */
/* Telemetry                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Latency percentiles and traffic rates across the whole service.
 *
 * ## Where these numbers come from
 *
 * The backend exposes a Prometheus text exposition at `GET /metrics`, proxied at
 * `/metrics` by both the Vite dev server and the production nginx. There is no
 * JSON telemetry endpoint, so `api/endpoints/telemetry.ts` parses the exposition
 * format and derives these values from it.
 *
 * Percentiles come from the histogram's **cumulative bucket counts** —
 * `clusterops_request_duration_seconds_bucket{le=...}` — which is how Prometheus
 * answers a quantile query. They are bucket-interpolated, so a reported p95 is
 * "inside the bucket containing the 95th percentile", not a raw sample quantile.
 */
export interface TelemetryMetrics {
  /** 50th percentile of request duration, milliseconds. */
  p50_latency_ms: number;
  /** 95th percentile, milliseconds. The figure the 500 ms SLA is held to. */
  p95_latency_ms: number;
  /** 99th percentile, milliseconds. */
  p99_latency_ms: number;
  /** Mean request duration, milliseconds. Exact: `_sum / _count`. */
  mean_latency_ms: number;
  /** Total requests observed since process start. */
  request_count: number;
  /** Requests whose status code was 4xx or 5xx, since process start. */
  error_count: number;
  /** `error_count / request_count`, as a fraction 0–1. */
  error_rate: number;
  /**
   * True when the observed window is short enough that `error_rate` is
   * dominated by a handful of requests and should not be read as a trend.
   */
  lowSampleSize: boolean;
}

/** Per-route latency, so the panel can show *which* endpoint is slow. */
export interface EndpointLatency {
  /** The `endpoint` label, e.g. `/api/v1/forecast`. */
  endpoint: string;
  /** Requests observed for this route. */
  count: number;
  /** Exact mean for this route, `_sum / _count`. */
  meanLatencyMs: number;
  /** Bucket-interpolated p95 for this route. */
  p95LatencyMs: number;
}
