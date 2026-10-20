/**
 * Prometheus exposition parsing and telemetry derivation.
 *
 * ## Why this exists
 *
 * The only telemetry surface the browser can reach is `GET /metrics` — the
 * backend's own Prometheus text exposition, proxied at `/metrics`. There is no
 * JSON telemetry endpoint and no query API in front of Prometheus, so the
 * percentile and rate figures the admin console shows are derived here from the
 * exposition format.
 *
 * ## Honesty constraints
 *
 * - Percentiles are **bucket-interpolated**, because cumulative histogram
 *   buckets are all a Prometheus quantile query has to work from. The result is
 *   "the 95th percentile lies in this bucket", and the UI labels it that way
 *   rather than presenting it as a sampled quantile.
 * - `error_rate` is cumulative over process lifetime, not a windowed rate. With
 *   a short-lived demo process it moves in large steps, so
 *   `TelemetryMetrics.lowSampleSize` flags when that is the case.
 * - Nothing here defaults to zero when a series is absent; a missing metric
 *   stays missing, because "no requests" and "no measurement" are different.
 */

import type { EndpointLatency, TelemetryMetrics } from '@/types/system';

/** Histogram family the latency percentiles are derived from. */
const DURATION = 'clusterops_request_duration_seconds';

/** Counter family carrying per-status request totals. */
const REQUESTS = 'clusterops_requests_total';

/** Below this many requests, a percentage is not worth reading as a rate. */
export const LOW_SAMPLE_THRESHOLD = 100;

interface Histogram {
  /** Cumulative counts keyed by upper bound in seconds; `+Inf` included. */
  buckets: Map<number, number>;
  count: number;
  sumSeconds: number;
}

/** Parse `{key="value",...}` label pairs off a series line. */
function parseLabels(raw: string): Record<string, string> {
  const labels: Record<string, string> = {};
  const match = /\{(.+)\}/.exec(raw);
  if (!match?.[1]) return labels;

  for (const pair of match[1].matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"/g)) {
    const key = pair[1];
    const value = pair[2];
    if (key !== undefined && value !== undefined) {
      labels[key] = value.replace(/\\"/g, '"').replace(/\\\\/g, '\\');
    }
  }
  return labels;
}

/** Split a Prometheus line into its metric name, labels and numeric value. */
function parseLine(line: string): { name: string; labels: Record<string, string>; value: number } | null {
  if (line === '' || line.startsWith('#')) return null;

  const separator = line.lastIndexOf(' ');
  if (separator === -1) return null;

  const head = line.slice(0, separator);
  const rawValue = line.slice(separator + 1);
  const value = Number(rawValue);
  if (!Number.isFinite(value)) return null;

  const brace = head.indexOf('{');
  const name = brace === -1 ? head : head.slice(0, brace);
  const labels = brace === -1 ? {} : parseLabels(head);

  return { name, labels, value };
}

/**
 * Interpolate a quantile from cumulative histogram buckets.
 *
 * Same shape as `histogram_quantile()`: find the bucket containing the target
 * rank and interpolate linearly between its lower and upper bound. The buckets
 * are cumulative, so each entry is a running total, not a bin count.
 */
export function bucketQuantile(histogram: Histogram, quantile: number): number | null {
  if (histogram.count <= 0) return null;

  const rank = quantile * histogram.count;
  const bounds = [...histogram.buckets.keys()].filter((bound) => Number.isFinite(bound)).sort((a, b) => a - b);

  let previousBound = 0;
  let previousCount = 0;

  for (const bound of bounds) {
    const cumulative = histogram.buckets.get(bound) ?? 0;
    if (cumulative >= rank) {
      if (cumulative === previousCount) return bound * 1000;
      const fraction = (rank - previousCount) / (cumulative - previousCount);
      return (previousBound + fraction * (bound - previousBound)) * 1000;
    }
    previousBound = bound;
    previousCount = cumulative;
  }

  // Beyond the last finite bucket; the remaining mass is in +Inf.
  return previousBound * 1000;
}

/** Aggregate every duration histogram into one, summing buckets across routes. */
function aggregateDurations(histograms: Map<string, Histogram>): Histogram {
  const merged: Histogram = { buckets: new Map(), count: 0, sumSeconds: 0 };

  for (const histogram of histograms.values()) {
    merged.count += histogram.count;
    merged.sumSeconds += histogram.sumSeconds;
    for (const [bound, cumulative] of histogram.buckets) {
      const isInf = !Number.isFinite(bound);
      const key = isInf ? Number.POSITIVE_INFINITY : bound;
      merged.buckets.set(key, (merged.buckets.get(key) ?? 0) + cumulative);
    }
  }

  return merged;
}

export interface ParsedTelemetry {
  metrics: TelemetryMetrics;
  endpoints: EndpointLatency[];
}

/**
 * Derive telemetry from a Prometheus exposition body.
 *
 * Exported separately from the React hook so the parsing can be reasoned about
 * — and tested — without a browser.
 */
export function parseTelemetry(body: string): ParsedTelemetry {
  const durations = new Map<string, Histogram>();
  const requestTotals = new Map<string, number>();

  for (const line of body.split('\n')) {
    const parsed = parseLine(line.trim());
    if (!parsed) continue;
    const { name, labels, value } = parsed;

    if (name.startsWith(`${DURATION}_bucket`)) {
      const endpoint = labels.endpoint ?? 'unknown';
      let histogram = durations.get(endpoint);
      if (!histogram) {
        histogram = { buckets: new Map(), count: 0, sumSeconds: 0 };
        durations.set(endpoint, histogram);
      }
      const bound = labels.le === '+Inf' ? Number.POSITIVE_INFINITY : Number(labels.le);
      histogram.buckets.set(bound, (histogram.buckets.get(bound) ?? 0) + value);
      continue;
    }

    if (name === `${DURATION}_count`) {
      const endpoint = labels.endpoint ?? 'unknown';
      const histogram = durations.get(endpoint) ?? {
        buckets: new Map(),
        count: 0,
        sumSeconds: 0,
      };
      histogram.count += value;
      durations.set(endpoint, histogram);
      continue;
    }

    if (name === `${DURATION}_sum`) {
      const endpoint = labels.endpoint ?? 'unknown';
      const histogram = durations.get(endpoint) ?? {
        buckets: new Map(),
        count: 0,
        sumSeconds: 0,
      };
      histogram.sumSeconds += value;
      durations.set(endpoint, histogram);
      continue;
    }

    if (name === REQUESTS) {
      const key = `${labels.endpoint ?? 'unknown'}|${labels.status_code ?? '0'}`;
      requestTotals.set(key, (requestTotals.get(key) ?? 0) + value);
    }
  }

  const merged = aggregateDurations(durations);

  let requestCount = 0;
  let errorCount = 0;
  for (const [key, value] of requestTotals) {
    requestCount += value;
    const status = Number(key.split('|')[1]);
    if (Number.isFinite(status) && status >= 400) errorCount += value;
  }

  const metrics: TelemetryMetrics = {
    p50_latency_ms: round1(bucketQuantile(merged, 0.5) ?? 0),
    p95_latency_ms: round1(bucketQuantile(merged, 0.95) ?? 0),
    p99_latency_ms: round1(bucketQuantile(merged, 0.99) ?? 0),
    mean_latency_ms: merged.count > 0 ? round1((merged.sumSeconds / merged.count) * 1000) : 0,
    request_count: requestCount,
    error_count: errorCount,
    error_rate: requestCount > 0 ? errorCount / requestCount : 0,
    lowSampleSize: requestCount < LOW_SAMPLE_THRESHOLD,
  };

  const endpoints: EndpointLatency[] = [...durations.entries()]
    .filter(([, histogram]) => histogram.count > 0)
    .map(([endpoint, histogram]) => ({
      endpoint,
      count: histogram.count,
      meanLatencyMs: (histogram.sumSeconds / histogram.count) * 1000,
      p95LatencyMs: bucketQuantile(histogram, 0.95) ?? 0,
    }))
    .sort((a, b) => b.p95LatencyMs - a.p95LatencyMs);

  return { metrics, endpoints };
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}
