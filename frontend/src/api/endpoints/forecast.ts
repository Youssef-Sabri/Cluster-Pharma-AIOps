/**
 * Demand forecasting API hooks.
 *
 * `POST /api/v1/forecast` is a read expressed as a POST: the body carries the
 * pharmacy, the product set and the horizon, so the request is far too large to
 * be a query string. That makes an unusual situation inevitable — the *same*
 * logical read is reachable by both a mutation (fire-and-observe) and a query
 * (cacheable, keyable). Both are exposed deliberately:
 *
 * - `useForecastQuery` is what the studio renders from. Keying on the request
 *   parameters means revisiting a pharmacy/horizon already seen is instant and
 *   free, and it keeps the previous chart on screen while a new horizon loads.
 * - `useForecastMutation` is for imperative one-shot calls, and its
 *   `onSuccess` writes into the query cache so a mutate-then-read flow does not
 *   refetch what it just received.
 *
 * They share `fetchForecast`, so both go through identical typing and identical
 * error normalisation.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { apiClient, describeApiError } from '../axios';
import type { ForecastRequest, ForecastResponse } from '@/types/forecast';

/** How long a successful forecast stays fresh before a refetch is allowed. */
export const FORECAST_STALE_TIME_MS = 5 * 60 * 1000;

/**
 * Stable cache key for a forecast request.
 *
 * `product_ids` is sorted before joining: the forecast is order-insensitive, so
 * two selections that differ only in click order must share one cache entry
 * rather than each triggering their own network request.
 */
export function forecastKey(params: ForecastRequest): readonly unknown[] {
  return [
    'forecast',
    params.pharmacy_id,
    params.forecast_horizon_days ?? null,
    [...params.product_ids].sort().join(','),
  ];
}

async function fetchForecast(params: ForecastRequest): Promise<ForecastResponse> {
  const response = await apiClient.post<ForecastResponse>('/api/v1/forecast', params);
  return response.data;
}

/** Narrow a `ForecastRequest` down to the fields the backend actually requires. */
function toPayload(params: ForecastRequest): ForecastRequest {
  return {
    pharmacy_id: params.pharmacy_id,
    product_ids: params.product_ids,
    ...(params.forecast_horizon_days === undefined
      ? {}
      : { forecast_horizon_days: params.forecast_horizon_days }),
  };
}

/**
 * Cacheable forecast read.
 *
 * Pass `undefined` for `params` to keep the query dormant — the studio does
 * this until at least one product is selected, because the API rejects an empty
 * `product_ids` with a 422.
 */
export function useForecastQuery(
  params: ForecastRequest | undefined,
  options?: { enabled?: boolean },
): UseQueryResult<ForecastResponse, Error> {
  return useQuery<ForecastResponse, Error>({
    queryKey: params ? forecastKey(params) : ['forecast', 'inactive'],
    queryFn: () => {
      // Guarded rather than asserted: the query stays dormant until `params` is
      // supplied, so this branch is unreachable, but a `!` would be a lie that
      // a future caller could walk into.
      if (!params) {
        return Promise.reject(new Error('useForecastQuery called without a request payload'));
      }
      return fetchForecast(toPayload(params));
    },
    enabled: Boolean(params) && (options?.enabled ?? true),
    staleTime: FORECAST_STALE_TIME_MS,
    retry: 1,
    // Keep the previous pharmacy/horizon on screen while the next one loads.
    // Without it the grid collapses to skeletons on every slider tick, which
    // reads as "the forecast is unavailable" rather than "it is refreshing".
    placeholderData: keepPreviousData,
  });
}

/**
 * Imperative forecast request.
 *
 * Successful responses are seeded into the query cache under the same key the
 * read hook uses, so a mutation followed by a read is served locally.
 */
export function useForecastMutation(): UseMutationResult<ForecastResponse, Error, ForecastRequest> {
  const queryClient = useQueryClient();

  return useMutation<ForecastResponse, Error, ForecastRequest>({
    mutationFn: (variables) => fetchForecast(toPayload(variables)),
    onSuccess: (data, variables) => {
      queryClient.setQueryData(forecastKey(toPayload(variables)), data);
    },
  });
}

/**
 * Human-readable form of a forecast failure.
 *
 * Re-exported from this module so consumers import one thing: `useForecastQuery`
 * surfaces `Error`, and the only sensible thing to render is
 * `describeApiError(error)` — which unwraps the backend's RFC 7807 envelope.
 */
export { describeApiError };
