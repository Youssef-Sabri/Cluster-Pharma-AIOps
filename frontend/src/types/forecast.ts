/**
 * Forecast types mirroring `backend/app/schemas/forecast.py`.
 */

export interface ForecastRequest {
  pharmacy_id: string;
  product_ids: string[];
  forecast_horizon_days?: number;
}

export interface ForecastItem {
  product_id: string;
  product_name: string | null;
  /** ISO calendar dates, ascending. */
  dates: string[];
  /** q50 — the median forecast. */
  predicted_units: number[];
  /** q10 — the optimistic bound of the 80% interval. */
  lower_bound: number[];
  /** q90 — the pessimistic bound of the 80% interval. */
  upper_bound: number[];
  mae_last_7d: number | null;
}

/** `POST /api/v1/forecast`. */
export interface ForecastResponse {
  pharmacy_id: string;
  generated_at: string;
  model_version: string;
  model_name: string;
  forecast_horizon_days: number;
  forecasts: ForecastItem[];
}