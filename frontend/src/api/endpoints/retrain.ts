/**
 * Retraining API.
 *
 * `POST /api/v1/retrain` hands the nightly Prefect flow to the background and
 * returns **202 Accepted** with a tracking id. It does **not** report progress,
 * and there is no endpoint that does — see `RetrainingStepper` for how the
 * outcome is observed instead.
 */

import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { apiClient } from '../axios';
import { DRIFT_STATUS_KEY } from './drift';
import type { RetrainRequest, RetrainResponse } from '@/types/registry';

/**
 * The endpoint declares its request body **required**.
 *
 * An empty object is valid — every field inside is optional — but omitting the
 * body entirely is a 422, so this wrapper always sends one.
 */
export function useRetrainMutation(): UseMutationResult<RetrainResponse, Error, RetrainRequest> {
  const queryClient = useQueryClient();

  return useMutation<RetrainResponse, Error, RetrainRequest>({
    mutationFn: async (request: RetrainRequest) => {
      const response = await apiClient.post<RetrainResponse>('/api/v1/retrain', request);
      return response.data;
    },
    onSuccess: () => {
      // The flow re-evaluates drift as its first act, so `retraining_triggered`
      // is the field most likely to move. Refresh it rather than wait for the
      // next poll tick.
      void queryClient.invalidateQueries({ queryKey: DRIFT_STATUS_KEY });
    },
  });
}

export { describeApiError } from '../axios';
