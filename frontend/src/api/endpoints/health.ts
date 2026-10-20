/**
 * Liveness and latency of the ClusterOps backend.
 *
 * Polled through React Query rather than a hand-rolled `setInterval`: the query
 * cache owns the refresh, deduplicates overlapping mounts and pauses polling
 * when the tab is backgrounded (rule: zero untracked polling).
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../axios';
import type { HealthResponse } from '@/types/common';

/** Match the Prometheus scrape interval so the badge cannot claim more liveness than the metrics do. */
export const HEALTH_POLL_INTERVAL_MS = 15_000;

/**
 * The SLA probe's own cost.
 *
 * Measured client-side around the `/health` call, so the dashboard reports the
 * round trip an operator actually experiences from this browser rather than a
 * server-side self-report. `duration` is unavailable because the backend does
 * not echo its own processing time.
 */
export interface HealthProbe {
  health: HealthResponse;
  latencyMs: number;
}

async function fetchHealth(): Promise<HealthProbe> {
  const startedAt = performance.now();
  const response = await apiClient.get<HealthResponse>('/health');
  const latencyMs = performance.now() - startedAt;

  return { health: response.data, latencyMs: Math.round(latencyMs * 10) / 10 };
}

export function useHealth() {
  return useQuery<HealthProbe>({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
    // A liveness probe is cheap and the value must be fresh to be meaningful,
    // so it is never served stale from the cache.
    staleTime: 0,
    retry: 1,
  });
}
