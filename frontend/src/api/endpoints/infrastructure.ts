/**
 * Live reachability of the ClusterOps infrastructure.
 *
 * Every entry is a **measured** probe, not a configured constant. The dashboard
 * shows what is actually answering right now; if a container is down the tile
 * turns red rather than continuing to assert health from stale config.
 *
 * Two of the five are reached indirectly through the backend, because the
 * browser cannot open a database socket and the FastAPI process is the only
 * component that can:
 *
 * - **PostgreSQL** — `db_connected` from the backend's own health probe, which
 *   runs a throwaway query rather than reusing the request's pooled connection.
 * - **MLflow** — `reachable` from `GET /api/v1/model-registry`, which the backend
 *   answers only after actually reaching the tracking server.
 *
 * The remaining three are probed directly from the browser through the Vite /
 * nginx proxy.
 */

import { useQuery } from '@tanstack/react-query';
import type { DriftStatusResponse } from '@/types/drift';
import type { ModelRegistryResponse } from '@/types/registry';
import type { HealthProbe } from './health';

export type ServiceStatus = 'up' | 'degraded' | 'down' | 'unknown';

export interface ServiceProbe {
  id: string;
  /** Display name, e.g. "FastAPI Gateway". */
  name: string;
  /** Compose service and published port. */
  endpoint: string;
  status: ServiceStatus;
  /** Measured round trip in milliseconds, or null when the probe failed. */
  latencyMs: number | null;
  /** One short clause explaining what was measured. */
  detail: string;
}

/** SLA the backend's own p95 budget is held to (Phase 6 benchmark). */
export const SLA_BUDGET_MS = 500;

/**
 * Probe a URL and time it.
 *
 * A plain same-origin GET, deliberately *not* `mode: 'no-cors'` — that mode
 * forces an opaque response, so neither the status code nor the body can be
 * read, and an unreachable service would be indistinguishable from a healthy
 * one. Through the proxy these endpoints are same-origin, so status is
 * observable.
 */
async function timeProbe(url: string): Promise<{ ok: boolean; latencyMs: number }> {
  const startedAt = performance.now();
  try {
    const response = await fetch(url, { method: 'GET', cache: 'no-store' });
    return { ok: response.ok, latencyMs: performance.now() - startedAt };
  } catch {
    return { ok: false, latencyMs: performance.now() - startedAt };
  }
}

const round1 = (value: number): number => Math.round(value * 10) / 10;

export function buildServiceMatrix(
  health: HealthProbe | undefined,
  healthFailed: boolean,
  drift: DriftStatusResponse | undefined,
  registry: ModelRegistryResponse | undefined,
  direct: { grafana: number | null; mlflow: number | null; prometheus: number | null },
): ServiceProbe[] {
  const probes: ServiceProbe[] = [];

  // --- FastAPI Gateway -----------------------------------------------------
  const apiLatency = health?.latencyMs ?? null;
  probes.push({
    id: 'fastapi',
    name: 'FastAPI Gateway',
    endpoint: ':8000',
    status: healthFailed ? 'down' : health ? 'up' : 'unknown',
    latencyMs: apiLatency,
    detail: healthFailed
      ? 'Health endpoint unreachable'
      : apiLatency !== null && apiLatency > SLA_BUDGET_MS
        ? `Responding in ${round1(apiLatency)} ms — over the ${SLA_BUDGET_MS} ms SLA`
        : `Round trip ${apiLatency !== null ? `${round1(apiLatency)} ms` : 'pending'}`,
  });

  // --- PostgreSQL ---------------------------------------------------------
  const dbConnected = health?.health.db_connected ?? null;
  probes.push({
    id: 'postgres',
    name: 'PostgreSQL 15',
    endpoint: ':5432',
    status: healthFailed ? 'unknown' : dbConnected === null ? 'unknown' : dbConnected ? 'up' : 'down',
    latencyMs: null,
    detail: healthFailed
      ? 'Undetermined — backend unreachable'
      : dbConnected
        ? 'Health probe query succeeded'
        : 'Health probe query failed',
  });

  // --- MLflow -------------------------------------------------------------
  // Prefer the direct browser probe; fall back to the backend's `reachable`
  // flag, which is authoritative even when the proxy is not configured.
  const mlflowReachable = registry?.reachable ?? null;
  probes.push({
    id: 'mlflow',
    name: 'MLflow Tracking',
    endpoint: ':5000',
    status:
      direct.mlflow !== null
        ? 'up'
        : mlflowReachable === null
          ? 'unknown'
          : mlflowReachable
            ? 'degraded'
            : 'down',
    latencyMs: direct.mlflow,
    detail:
      direct.mlflow !== null
        ? `Registry API ${round1(direct.mlflow)} ms`
        : mlflowReachable === null
          ? 'Not yet probed'
          : mlflowReachable
            ? 'Reachable from the backend, proxy not configured'
            : 'Backend cannot reach the tracking server',
  });

  // --- Prometheus ---------------------------------------------------------
  probes.push({
    id: 'prometheus',
    name: 'Prometheus',
    endpoint: ':9090',
    status: direct.prometheus === null ? 'unknown' : 'up',
    latencyMs: direct.prometheus,
    detail:
      direct.prometheus === null
        ? 'Metrics endpoint did not answer'
        : `Exposition ${round1(direct.prometheus)} ms`,
  });

  // --- Grafana ------------------------------------------------------------
  probes.push({
    id: 'grafana',
    name: 'Grafana',
    endpoint: ':3001',
    status: direct.grafana === null ? 'unknown' : 'up',
    latencyMs: direct.grafana,
    detail:
      direct.grafana === null
        ? 'Health endpoint did not answer'
        : `Health API ${round1(direct.grafana)} ms`,
  });

  // Drift is not a service, but a drift alarm is an operational incident and
  // belongs in the same matrix so it cannot be missed.
  if (drift) {
    probes.push({
      id: 'drift',
      name: 'Drift Monitor',
      endpoint: ':8000',
      status: drift.evaluated
        ? drift.overall_status === 'OK'
          ? 'up'
          : drift.overall_status === 'WARNING'
            ? 'degraded'
            : 'down'
        : 'unknown',
      latencyMs: null,
      detail: drift.evaluated
        ? `Max PSI ${drift.max_psi.toFixed(3)} against a ${drift.psi_threshold} alarm`
        : 'No evaluation recorded yet',
    });
  }

  return probes;
}

/** Refresh cadence for the infrastructure matrix. */
export const INFRA_POLL_INTERVAL_MS = 30_000;

/**
 * Direct probes for the services the browser can reach itself.
 *
 * Kept in its own query so a hung Prometheus cannot delay the health badge or
 * the rest of the dashboard — each probe races the others rather than blocking.
 */
export function useDirectServiceProbes() {
  return useQuery<{ grafana: number | null; mlflow: number | null; prometheus: number | null }>({
    queryKey: ['infrastructure', 'direct'],
    queryFn: async () => {
      const [grafana, mlflow, prometheus] = await Promise.all([
        timeProbe('/grafana/api/health'),
        timeProbe('/mlflow/health'),
        timeProbe('/metrics'),
      ]);

      return {
        grafana: grafana.ok ? round1(grafana.latencyMs) : null,
        mlflow: mlflow.ok ? round1(mlflow.latencyMs) : null,
        prometheus: prometheus.ok ? round1(prometheus.latencyMs) : null,
      };
    },
    refetchInterval: INFRA_POLL_INTERVAL_MS,
    staleTime: 15_000,
    // A failed probe is still data — it means "down", not "don't know" — so the
    // query resolves either way and never surfaces an error state.
    retry: 0,
  });
}
