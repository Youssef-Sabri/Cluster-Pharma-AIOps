import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, AlertTriangle } from 'lucide-react';
import { Badge, Card } from '@/components/ui';
import { InfraHealth } from './InfraHealth';
import { useTelemetry } from '@/api/endpoints/telemetry';
import { describeApiError } from '@/api/axios';
import { SLA_BUDGET_MS } from '@/api/endpoints/infrastructure';
import { useCssColor } from '@/hooks/useCssColor';
import type { TelemetryMetrics } from '@/types/system';
import './InfrastructurePanel.css';

const FALLBACK = {
  grid: '#eaedf3',
  axis: '#6d859e',
  text: '#1c1b2e',
  surface: '#ffffff',
  border: '#eaedf3',
  primary: '#0f6eff',
  danger: '#ef4444',
  warning: '#f59e0b',
  muted: '#9aa9bd',
} as const;

/** The three percentiles plotted, with the value the SLA applies to. */
function percentileRows(metrics: TelemetryMetrics): { label: string; ms: number }[] {
  return [
    { label: 'P50', ms: metrics.p50_latency_ms },
    { label: 'P95', ms: metrics.p95_latency_ms },
    { label: 'P99', ms: metrics.p99_latency_ms },
  ];
}

function formatMs(value: number): string {
  return value >= 100 ? `${Math.round(value)} ms` : `${value.toFixed(1)} ms`;
}

/**
 * Infrastructure and system health.
 *
 * Composes the measured five-service matrix from `InfraHealth` with a latency
 * percentile view derived from the Prometheus request-duration histogram.
 * **Admin-only** — service names, ports and latency budgets are infrastructure
 * detail the product rules keep off every business screen.
 *
 * Percentiles are bucket-interpolated from cumulative histogram counts, which is
 * what a Prometheus quantile query has to work from; the caption says so rather
 * than implying a sampled distribution.
 */
export function InfrastructurePanel() {
  const { data, isPending, isError, error } = useTelemetry();

  const grid = useCssColor('--color-bg-border', FALLBACK.grid);
  const axis = useCssColor('--color-text-secondary', FALLBACK.axis);
  const text = useCssColor('--color-text-primary', FALLBACK.text);
  const surface = useCssColor('--color-bg-surface', FALLBACK.surface);
  const border = useCssColor('--color-bg-border', FALLBACK.border);
  const primary = useCssColor('--color-primary', FALLBACK.primary);
  const danger = useCssColor('--color-danger', FALLBACK.danger);
  const muted = useCssColor('--color-text-muted', FALLBACK.muted);

  const metrics = data?.metrics ?? null;
  const rows = metrics ? percentileRows(metrics) : [];

  const aggregateOverSla = metrics !== null && metrics.p95_latency_ms > SLA_BUDGET_MS;

  /**
   * Routes whose own p95 breaches the budget.
   *
   * The headline verdict has to account for these. Judging the SLA on the
   * aggregate alone puts "Within SLA" directly above a table showing a 912 ms
   * route against a 500 ms ceiling, which reads as a contradiction — and a
   * service whose p99 breaches is over budget even when its overall p95 is not.
   */
  const routesOverSla = (data?.endpoints ?? []).filter(
    (endpoint) => endpoint.p95LatencyMs > SLA_BUDGET_MS,
  ).length;

  const slaBadge = !metrics
    ? undefined
    : aggregateOverSla || routesOverSla > 0
      ? {
          tone: 'danger' as const,
          label: routesOverSla > 0 ? `${routesOverSla} route${routesOverSla === 1 ? '' : 's'} over SLA` : 'Over SLA',
        }
      : { tone: 'success' as const, label: 'Within SLA' };

  return (
    <div className="infra">
      <InfraHealth />

      <div className="infra__grid">
        <Card
          title="Request latency"
          action={
            slaBadge ? <Badge tone={slaBadge.tone} size="sm">{slaBadge.label}</Badge> : undefined
          }
        >
          {isPending ? (
            <p className="infra__pending">Reading the metrics endpoint…</p>
          ) : isError ? (
            <p className="infra__error">{describeApiError(error)}</p>
          ) : metrics ? (
            <>
              <div
                className="infra__chart"
                role="img"
                aria-label={`Request latency percentiles. P50 ${formatMs(
                  metrics.p50_latency_ms,
                )}, P95 ${formatMs(metrics.p95_latency_ms)}, P99 ${formatMs(metrics.p99_latency_ms)}`}
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={rows} margin={{ top: 16, right: 16, left: -18, bottom: 4 }}>
                    <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" stroke={axis} tickLine={false} fontSize={11} />
                    <YAxis
                      stroke={axis}
                      tickLine={false}
                      axisLine={false}
                      fontSize={11}
                      tickFormatter={(value: number) => `${value}`}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(15, 110, 255, 0.05)' }}
                      contentStyle={{
                        backgroundColor: surface,
                        border: `1px solid ${border}`,
                        borderRadius: '10px',
                        color: text,
                        fontSize: '12px',
                      }}
                      formatter={(value: number | string) => [formatMs(Number(value)), 'Latency']}
                    />
                    <ReferenceLine
                      y={SLA_BUDGET_MS}
                      stroke={danger}
                      strokeDasharray="4 4"
                      strokeWidth={1.5}
                      label={{
                        value: `SLA ${SLA_BUDGET_MS} ms`,
                        fill: danger,
                        position: 'right',
                        fontSize: 10,
                      }}
                    />
                    <Bar
                      dataKey="ms"
                      fill={aggregateOverSla ? danger : primary}
                      radius={[6, 6, 0, 0]}
                      maxBarSize={64}
                      isAnimationActive={false}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <dl className="infra__stats">
                <div>
                  <dt>Mean</dt>
                  <dd className="numeric">{formatMs(metrics.mean_latency_ms)}</dd>
                </div>
                <div>
                  <dt>Requests</dt>
                  <dd className="numeric">{metrics.request_count.toLocaleString('en-EG')}</dd>
                </div>
                <div>
                  <dt>Errors</dt>
                  <dd className="numeric">
                    {metrics.error_count.toLocaleString('en-EG')}
                    <span className="infra__rate">
                      {' '}
                      ({(metrics.error_rate * 100).toFixed(1)}%)
                    </span>
                  </dd>
                </div>
              </dl>

              {metrics.lowSampleSize ? (
                <p className="infra__warn">
                  <AlertTriangle size={13} aria-hidden="true" />
                  Counters are cumulative since process start and the process is young, so the error
                  rate moves in large steps. Treat it as a signal, not a trend.
                </p>
              ) : null}

              <p className="infra__caption" style={{ color: muted }}>
                Percentiles are interpolated from Prometheus histogram buckets, so each figure is
                the bucket containing that percentile rather than a sampled value.
              </p>
            </>
          ) : null}
        </Card>

        <Card title="Slowest routes">
          {isPending ? (
            <p className="infra__pending">Reading the metrics endpoint…</p>
          ) : isError ? (
            <p className="infra__error">{describeApiError(error)}</p>
          ) : data && data.endpoints.length > 0 ? (
            <div className="infra__wrap">
              <table className="infra__table">
                <caption className="visually-hidden">Per-route request latency</caption>
                <thead>
                  <tr>
                    <th scope="col">Endpoint</th>
                    <th scope="col" className="infra__num">
                      Requests
                    </th>
                    <th scope="col" className="infra__num">
                      Mean
                    </th>
                    <th scope="col" className="infra__num">
                      P95
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.endpoints.slice(0, 8).map((endpoint) => (
                    <tr key={endpoint.endpoint}>
                      <th scope="row" className="infra__route">
                        {endpoint.endpoint}
                      </th>
                      <td className="infra__num numeric">{endpoint.count.toLocaleString('en-EG')}</td>
                      <td className="infra__num numeric">{formatMs(endpoint.meanLatencyMs)}</td>
                      <td
                        className={`infra__num numeric${
                          endpoint.p95LatencyMs > SLA_BUDGET_MS ? ' infra__over' : ''
                        }`}
                      >
                        {formatMs(endpoint.p95LatencyMs)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="infra__pending">
              <Activity size={14} aria-hidden="true" /> No request metrics have been recorded yet.
            </p>
          )}
        </Card>
      </div>

      {/* The SLA budget is echoed here so the ceiling is defined once and shown
          wherever it applies. */}
      <p className="infra__footnote">
        Latency budget is {SLA_BUDGET_MS} ms at p95, matching the{' '}
        <code>clusterops_request_duration_seconds</code> histogram the backend exports.
      </p>
    </div>
  );
}

export default InfrastructurePanel;
