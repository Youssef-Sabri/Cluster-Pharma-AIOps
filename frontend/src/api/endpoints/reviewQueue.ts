/**
 * Pharmacist review queue API.
 *
 * Every decision invalidates the queue and the pending count, so the sidebar
 * badge, the top bar and the workbench can never disagree about how many items
 * are outstanding.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { apiClient } from '../axios';
import type {
  ReviewActionRequest,
  ReviewActionResponse,
  ReviewQueueResponse,
} from '@/types/reviewQueue';

/** Shared query key for the pending count, used by the sidebar and the top bar. */
export const PENDING_COUNT_KEY = ['pending-review-count'] as const;

/** Shared query key for the queue itself. */
export const REVIEW_QUEUE_KEY = ['review-queue'] as const;

/** How often the queue refreshes. */
export const REVIEW_POLL_INTERVAL_MS = 30_000;

/** Rows fetched per page of the workbench. */
export const REVIEW_PAGE_SIZE = 50;

export interface ReviewQueueFilters {
  /** Restrict to one pharmacy. */
  pharmacyId?: string;
  limit?: number;
  offset?: number;
}

async function fetchReviewQueue(filters: ReviewQueueFilters): Promise<ReviewQueueResponse> {
  const response = await apiClient.get<ReviewQueueResponse>('/api/v1/orders/review-queue', {
    params: {
      ...(filters.pharmacyId ? { pharmacy_id: filters.pharmacyId } : {}),
      limit: filters.limit ?? REVIEW_PAGE_SIZE,
      offset: filters.offset ?? 0,
    },
  });
  return response.data;
}

/**
 * The list of order lines waiting for a pharmacist's decision.
 *
 * The count comes from the same response, so the badge and the list are always
 * from the same snapshot.
 */
export function useReviewQueue(
  filters: ReviewQueueFilters = {},
): UseQueryResult<ReviewQueueResponse, Error> {
  return useQuery<ReviewQueueResponse, Error>({
    queryKey: [...REVIEW_QUEUE_KEY, filters.pharmacyId ?? 'all', filters.offset ?? 0],
    queryFn: () => fetchReviewQueue(filters),
    refetchInterval: REVIEW_POLL_INTERVAL_MS,
    staleTime: 10_000,
    retry: 1,
  });
}

/**
 * Apply a pharmacist's decision to one flagged line.
 *
 * On success both the queue and the pending count are invalidated, so the
 * sidebar badge drops the moment a decision lands.
 */
export function useResolveReview(): UseMutationResult<
  ReviewActionResponse,
  Error,
  { itemId: string; payload: ReviewActionRequest }
> {
  const queryClient = useQueryClient();

  return useMutation<ReviewActionResponse, Error, { itemId: string; payload: ReviewActionRequest }>({
    mutationFn: async ({ itemId, payload }) => {
      const response = await apiClient.patch<ReviewActionResponse>(
        `/api/v1/orders/review-queue/${itemId}`,
        payload,
      );
      return response.data;
    },

    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REVIEW_QUEUE_KEY });
      void queryClient.invalidateQueries({ queryKey: PENDING_COUNT_KEY });
    },
  });
}

/**
 * Number of items still waiting for a pharmacist.
 *
 * Returns 0 when the count is unavailable. A failing request must never take
 * the shell down — the badge simply disappears, which is the honest rendering of
 * "we do not know" rather than a claim that nothing is pending.
 */
export function usePendingReviewCount(): number {
  const { data } = useQuery<ReviewQueueResponse>({
    queryKey: PENDING_COUNT_KEY,
    queryFn: () => fetchReviewQueue({ limit: 1 }),
    refetchInterval: REVIEW_POLL_INTERVAL_MS,
    staleTime: 15_000,
    retry: 1,
  });

  return data?.pending_total ?? 0;
}
