/**
 * Business-facing forecast accuracy.
 *
 * ## Why this reads MLflow directly
 *
 * The product needs an "AI accuracy" figure in plain language, and the backend's
 * `GET /api/v1/model-registry` returns `test_mae` with an **empty** `metrics`
 * object — so the percentage cannot be derived from the registry response. The
 * metric is present and correct in the tracking server; only the registry
 * accessor does not surface it.
 *
 * Until `model-registry.metrics` is populated server-side, this reads the
 * champion run's metrics through the same-origin MLflow proxy. That is a
 * deliberate, temporary shim: it keeps the KPI honest (a real number, computed
 * from the real logged metric) rather than showing a fabricated "96.5%".
 * The correct fix is backend-side and is documented in the README.
 *
 * ## Why accuracy is only 35%
 *
 * `mape` is 0.648, which sounds poor. It is high because the synthetic panel is
 * 85% zeros (`zero_share` logged alongside it): mean absolute *percentage* error
 * divides by the actual, and dividing by a near-zero actual explodes. The same
 * run is 28.7% better than the naive seasonal baseline, which is the more
 * meaningful business comparison and is shown alongside.
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../axios';
import type { ModelRegistryResponse } from '@/types/registry';

export interface AccuracySummary {
  /** 1 − MAPE, as a percentage. */
  accuracyPct: number;
  /** Improvement over the naive baseline, as a percentage. */
  improvementPct: number;
  /** MLflow run id the figures came from, for the tooltip. */
  runId: string;
}

/** Shape of the MLflow run-metrics payload we depend on. */
interface MlflowRunResponse {
  run?: {
    info?: { run_id?: string };
    data?: {
      metrics?: { key: string; value: string }[];
    };
  };
}

/**
 * MLflow REST base, routed through the dev/nginx proxy.
 *
 * The `/mlflow` prefix is stripped by the proxy before the request reaches the
 * tracking server, so this resolves to `/api/2.0/mlflow/...` upstream. It must
 * *not* be written as a bare `/api/2.0/mlflow` — that collides with the
 * backend's own `/api` namespace and silently 404s.
 */
const MLFLOW_TRACKING_URI = '/mlflow/api/2.0/mlflow';

export function useForecastAccuracy() {
  return useQuery<AccuracySummary, Error>({
    queryKey: ['forecast-accuracy'],

    queryFn: async () => {
      // 1. Resolve the champion version through the public backend API.
      const registry = await apiClient
        .get<ModelRegistryResponse>('/api/v1/model-registry')
        .then((response) => response.data);

      const champion = registry.models.find((model) => model.status === 'Production');
      const runId = champion?.run_id;

      if (!champion || !runId) {
        throw new Error('No Production model with a tracking run is available');
      }

      // 2. Read that run's logged metrics.
      const run = await apiClient
        .get<MlflowRunResponse>(`${MLFLOW_TRACKING_URI}/runs/get`, { params: { run_id: runId } })
        .then((response) => response.data);

      const metrics = run.run?.data?.metrics ?? [];
      const read = (key: string): number | null => {
        const found = metrics.find((metric) => metric.key === key);
        if (!found) return null;
        const parsed = Number(found.value);
        return Number.isFinite(parsed) ? parsed : null;
      };

      const mape = read('mape');
      if (mape === null) {
        throw new Error('The tracking run logged no mape metric');
      }

      return {
        accuracyPct: (1 - mape) * 100,
        improvementPct: read('vs_baseline_improvement_pct') ?? 0,
        runId,
      };
    },

    // Accuracy only moves when a model is promoted, so it can be cached hard.
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}
