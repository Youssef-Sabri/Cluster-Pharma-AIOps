/**
 * Live request telemetry.
 *
 * Reads the backend's Prometheus exposition at `GET /metrics` — the only
 * telemetry surface the browser can reach — and derives percentiles and traffic
 * rates from it. The parsing lives in `lib/telemetry.ts` so it can be reasoned
 * about without a browser.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiClient } from '../axios';
import { parseTelemetry, type ParsedTelemetry } from '@/lib/telemetry';

export const TELEMETRY_KEY = ['telemetry'] as const;

/**
 * How often telemetry refreshes.
 *
 * A minute, matching the Prometheus scrape interval. Faster than that would
 * read the same cumulative counters more often and imply a resolution the
 * underlying data does not have.
 */
export const TELEMETRY_POLL_INTERVAL_MS = 60_000;

/**
 * The exposition is `text/plain`, not JSON.
 *
 * `responseType: 'text'` matters: Axios would otherwise try to parse it as JSON
 * and hand the component a parse error instead of the metrics body.
 */
async function fetchTelemetry(): Promise<ParsedTelemetry> {
  const response = await apiClient.get<string>('/metrics', { responseType: 'text' });
  return parseTelemetry(response.data);
}

export function useTelemetry(): UseQueryResult<ParsedTelemetry, Error> {
  return useQuery<ParsedTelemetry, Error>({
    queryKey: TELEMETRY_KEY,
    queryFn: fetchTelemetry,
    refetchInterval: TELEMETRY_POLL_INTERVAL_MS,
    staleTime: 15_000,
    retry: 1,
  });
}

export { describeApiError } from '../axios';
export type { ParsedTelemetry } from '@/lib/telemetry';
