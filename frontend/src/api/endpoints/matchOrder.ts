/**
 * Order matching API.
 *
 * The matching engine works invisibly: the caller submits raw order text and
 * receives priced, resolved lines. Nothing here exposes *how* the matching was
 * done — the engine's technique names stay in the response types and are never
 * rendered.
 */

import { useMutation, type UseMutationResult } from '@tanstack/react-query';
import { apiClient, describeApiError } from '../axios';
import type { MatchOrderRequest, MatchOrderResponse } from '@/types/matchOrder';

/**
 * Submit an order for matching.
 *
 * `persist: false` performs a dry run — the order is matched and priced but
 * nothing is written, which is what the invoice preview uses so an abandoned
 * order leaves no rows behind.
 */
async function submitOrder(request: MatchOrderRequest): Promise<MatchOrderResponse> {
  const response = await apiClient.post<MatchOrderResponse>('/api/v1/match-order', request);
  return response.data;
}

export function useMatchOrderMutation(): UseMutationResult<
  MatchOrderResponse,
  Error,
  MatchOrderRequest
> {
  return useMutation<MatchOrderResponse, Error, MatchOrderRequest>({
    mutationFn: submitOrder,
  });
}

export { describeApiError };
