/**
 * Configured Axios instance for the ClusterOps backend.
 *
 * Requests go to same-origin relative paths by default so the Vite dev proxy (and
 * the nginx config in production) forwards them to the FastAPI service. Set
 * `VITE_API_BASE_URL` to point at an absolute origin instead — the backend's
 * CORS policy allows `http://localhost:3000`, so either mode works in dev.
 */

import axios, { AxiosError } from 'axios';
import type { ApiErrorEnvelope } from '@/types/common';

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

/**
 * Normalise the backend's RFC 7807 envelope into a single readable sentence so
 * components never have to dig through `error.error.detail`.
 */
export function describeApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorEnvelope>;
    if (!axiosError.response) {
      return axiosError.code === 'ECONNABORTED'
        ? 'The backend did not respond in time.'
        : 'Cannot reach the ClusterOps backend — it may be restarting.';
    }
    const envelope = axiosError.response.data?.error;
    if (envelope?.detail) return envelope.detail;
    return `Backend returned ${String(axiosError.response.status)}.`;
  }
  if (error instanceof Error) return error.message;
  return 'Unexpected error.';
}

/** HTTP status carried by an API failure, or null for transport errors. */
export function apiErrorStatus(error: unknown): number | null {
  if (axios.isAxiosError(error)) {
    return error.response?.status ?? null;
  }
  return null;
}

export default apiClient;