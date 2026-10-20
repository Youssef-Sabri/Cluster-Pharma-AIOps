/**
 * Model registry and governance API.
 *
 * Two consumers with different needs:
 *
 * - `useModelRegistry` — the raw `/api/v1/model-registry` response. Enough for
 *   lineage, stage and the retraining observer.
 * - `useModelGovernance` — the same response **plus** the champion run's error
 *   metrics from MLflow, because the registry returns `metrics: {}`.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '../axios';
import type {
  BaselineMetrics,
  ModelGovernance,
  ModelMetadataItem,
  ModelRegistryResponse,
} from '@/types/registry';

export const MODEL_REGISTRY_KEY = ['model-registry'] as const;

/** Registry changes only on promotion, so this is slow on purpose. */
export const REGISTRY_POLL_INTERVAL_MS = 60_000;

async function fetchModelRegistry(): Promise<ModelRegistryResponse> {
  const response = await apiClient.get<ModelRegistryResponse>('/api/v1/model-registry');
  return response.data;
}

/**
 * Registered model versions.
 *
 * When MLflow is unreachable the backend reports `reachable: false` with an
 * empty list rather than a stale one, so a caller can tell "no models" from
 * "cannot see the registry".
 */
export function useModelRegistry(): UseQueryResult<ModelRegistryResponse, Error> {
  return useQuery<ModelRegistryResponse, Error>({
    queryKey: MODEL_REGISTRY_KEY,
    queryFn: fetchModelRegistry,
    refetchInterval: REGISTRY_POLL_INTERVAL_MS,
    staleTime: 10_000,
    retry: 1,
  });
}

/* -------------------------------------------------------------------------- */
/* Governance                                                                  */
/* -------------------------------------------------------------------------- */

/** MLflow run payload. */
interface MlflowRunResponse {
  run?: {
    info?: { run_id?: string };
    data?: {
      metrics?: { key: string; value: string }[];
      params?: { key: string; value: string }[];
    };
  };
}

/**
 * MLflow REST base, routed through the dev/nginx proxy.
 *
 * The `/mlflow` prefix is stripped upstream, so this resolves to
 * `/api/2.0/mlflow/...`. It must **not** be written as a bare `/api/2.0/mlflow` —
 * that collides with the backend's own `/api` namespace and silently 404s.
 */
const MLFLOW_TRACKING_URI = '/mlflow/api/2.0/mlflow';

/** Training parameters worth putting in front of an administrator. */
const NOTABLE_PARAMS = ['n_estimators', 'learning_rate', 'num_leaves', 'objective', 'days', 'rows'];

function readNumber(
  metrics: { key: string; value: string }[],
  key: string,
): number | null {
  const found = metrics.find((metric) => metric.key === key);
  if (!found) return null;
  const parsed = Number(found.value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Champion and challenger with metrics resolved from every available source.
 *
 * ## Why this merges three endpoints
 *
 * The registry is authoritative for **lineage** — which versions exist, their
 * stages, why one was promoted — and it does return `test_mae`. It does not
 * return RMSE, MAPE or the baseline comparison; those are logged on the training
 * run and live in MLflow. `p95_latency_ms` is not a model metric at all and is
 * supplied by the serving telemetry.
 *
 * If MLflow cannot be reached the result is still returned, with
 * `metricsResolved: false` and the metric fields left null — the panel then
 * shows em dashes rather than zeros or invented numbers.
 */
export function useModelGovernance(): UseQueryResult<ModelGovernance, Error> {
  return useQuery<ModelGovernance, Error>({
    queryKey: [...MODEL_REGISTRY_KEY, 'governance'],
    queryFn: async () => {
      const registry = await fetchModelRegistry();

      const champion =
        registry.models.find((model) => model.status === 'Production') ??
        registry.models[0] ??
        null;

      // Anything registered but not serving is a candidate for promotion.
      const challenger =
        registry.models.find(
          (model) => model.status !== 'Production' && model.version !== champion?.version,
        ) ?? null;

      const championMetrics: ModelGovernance['championMetrics'] = {
        mae: champion?.test_mae ?? null,
        rmse: null,
        mape: null,
        vs_naive_baseline_improvement_pct: null,
        p95_latency_ms: null,
      };

      const baselineMetrics: BaselineMetrics = { mae: null, rmse: null, mape: null };
      let trainingParams: Record<string, string> = {};
      let metricsResolved = false;

      if (champion?.run_id) {
        try {
          const run = await apiClient
            .get<MlflowRunResponse>(`${MLFLOW_TRACKING_URI}/runs/get`, {
              params: { run_id: champion.run_id },
            })
            .then((response) => response.data);

          const logged = run.run?.data?.metrics ?? [];
          if (logged.length > 0) {
            metricsResolved = true;
            championMetrics.rmse = readNumber(logged, 'rmse');
            championMetrics.mape = readNumber(logged, 'mape');
            championMetrics.vs_naive_baseline_improvement_pct = readNumber(
              logged,
              'vs_baseline_improvement_pct',
            );
            championMetrics.mae = champion.test_mae ?? readNumber(logged, 'mae');

            baselineMetrics.mae = readNumber(logged, 'baseline_mae');
            baselineMetrics.rmse = readNumber(logged, 'baseline_rmse');
            baselineMetrics.mape = readNumber(logged, 'baseline_mape');
          }

          const params = run.run?.data?.params ?? [];
          trainingParams = Object.fromEntries(
            params.filter((param) => NOTABLE_PARAMS.includes(param.key)).map((param) => [param.key, param.value]),
          );
        } catch {
          // MLflow unreachable. The registry half of the answer is still valid,
          // so this degrades rather than fails the whole panel.
          metricsResolved = false;
        }
      }

      return { champion, challenger, championMetrics, baselineMetrics, trainingParams, metricsResolved };
    },
    refetchInterval: REGISTRY_POLL_INTERVAL_MS,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Narrow helper for consumers that already hold a version list. */
export function findChampion(models: ModelMetadataItem[]): ModelMetadataItem | null {
  return models.find((model) => model.status === 'Production') ?? models[0] ?? null;
}

export { describeApiError } from '../axios';
