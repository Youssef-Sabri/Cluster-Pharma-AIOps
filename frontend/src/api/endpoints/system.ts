/**
 * Backend runtime state.
 *
 * Complements `useHealth`: `/health` answers "is this process serving?", while
 * `/api/v1/system/state` answers "what did it actually manage to load?" — the
 * distinction matters, because a process can be serving perfectly well while
 * its catalogue failed to load, in which case matching returns 503.
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../axios';
import type { SystemStateResponse } from '@/types/system';

async function fetchSystemState(): Promise<SystemStateResponse> {
  const response = await apiClient.get<SystemStateResponse>('/api/v1/system/state');
  return response.data;
}

export function useSystemState() {
  return useQuery<SystemStateResponse>({
    queryKey: ['system-state'],
    queryFn: fetchSystemState,
    refetchInterval: 30_000,
    staleTime: 10_000,
    retry: 1,
  });
}
