/**
 * Drift status API.
 *
 * The scorecard the admin console leads with: the latest PSI per monitored
 * feature, the band each one sits in, and whether the last evaluation caused a
 * retraining run.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '../axios';
import type { DriftStatusResponse } from '@/types/drift';

/** Shared query key, also invalidated after a retraining submission. */
export const DRIFT_STATUS_KEY = ['drift-status'] as const;

/**
 * How often the drift scorecard refreshes.
 *
 * A drift evaluation is a nightly job, so this is slow on purpose — 30 s is
 * frequent enough that a threshold breach appears promptly and rare enough not to
 * hammer an endpoint that reads a table which changes about once a day.
 */
export const DRIFT_POLL_INTERVAL_MS = 30_000;

async function fetchDriftStatus(): Promise<DriftStatusResponse> {
  const response = await apiClient.get<DriftStatusResponse>('/api/v1/drift-status');
  return response.data;
}

/**
 * Latest Population Stability Index per monitored feature.
 *
 * An empty `drift_logs` table is a legitimate response — `evaluated: false` —
 * and is surfaced as such rather than being smoothed into "healthy".
 */
export function useDriftStatus(): UseQueryResult<DriftStatusResponse, Error> {
  return useQuery<DriftStatusResponse, Error>({
    queryKey: DRIFT_STATUS_KEY,
    queryFn: fetchDriftStatus,
    refetchInterval: DRIFT_POLL_INTERVAL_MS,
    staleTime: 10_000,
    retry: 1,
  });
}

export { describeApiError } from '../axios';
