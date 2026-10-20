import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useCssColor } from '@/hooks/useCssColor';
import {
  PSI_ALERT_THRESHOLD,
  PSI_BAND_LABEL,
  PSI_WARNING_THRESHOLD,
  featureLabel,
  psiBand,
} from '@/lib/drift';
import type { DriftFeatureItem } from '@/types/drift';
import './DriftMatrixChart.css';

/** Light-theme fallbacks, used before `:root` is parsed. */
const FALLBACK = {
  grid: '#eaedf3',
  axis: '#6d859e',
  text: '#1c1b2e',
  surface: '#ffffff',
  border: '#eaedf3',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  primary: '#0f6eff',
} as const;

export interface DriftMatrixChartProps {
  features: DriftFeatureItem[];
  /** Critical boundary. Defaults to the backend's own `psi_threshold`. */
  threshold?: number;
  /** Early-warning boundary. */
  warning?: number;
}

/** Upper bound of the x-axis: comfortably past the critical line. */
const AXIS_MAX = 0.3;

/**
 * Feature PSI matrix.
 *
 * A horizontal bar chart of Population Stability Index per monitored feature,
 * with the two decision boundaries drawn across it. `/admin` only — PSI is
 * statistical vocabulary that the pharmacy-facing pages must never show.
 *
 * Colours are resolved from `:root` through `useCssColor` because Recharts
 * writes them into SVG presentation attributes, where `var(--token)` is not
 * substituted and would leave the attribute unresolved.
 */
export function DriftMatrixChart({
  features,
  threshold = PSI_ALERT_THRESHOLD,
  warning = PSI_WARNING_THRESHOLD,
}: DriftMatrixChartProps) {
  const grid = useCssColor('--color-bg-border', FALLBACK.grid);
  const axis = useCssColor('--color-text-secondary', FALLBACK.axis);
  const text = useCssColor('--color-text-primary', FALLBACK.text);
  const surface = useCssColor('--color-bg-surface', FALLBACK.surface);
  const border = useCssColor('--color-bg-border', FALLBACK.border);
  const success = useCssColor('--color-success', FALLBACK.success);
  const warningColor = useCssColor('--color-warning', FALLBACK.warning);
  const danger = useCssColor('--color-danger', FALLBACK.danger);
  const primary = useCssColor('--color-primary', FALLBACK.primary);

  const rows = useMemo(
    () =>
      features
        .map((feature) => ({
          feature_name: feature.feature_name,
          label: featureLabel(feature.feature_name),
          psi_score: feature.psi_score,
          status: feature.status,
          band: psiBand(feature.psi_score, warning, threshold),
        }))
        // Worst first, so the feature that needs attention is the first thing
        // read rather than the last.
        .sort((a, b) => b.psi_score - a.psi_score),
    [features, threshold, warning],
  );

  const barColor = (band: DriftFeatureItem['status']): string => {
    if (band === 'DRIFT_DETECTED') return danger;
    if (band === 'WARNING') return warningColor;
    return success;
  };

  if (rows.length === 0) {
    return (
      <div className="dmx__empty">
        <p className="dmx__empty-title">No features evaluated yet</p>
        <p className="dmx__empty-text">
          The drift table is empty, so there is nothing to plot. This is not the same as every
          feature being healthy — it means no evaluation has run.
        </p>
      </div>
    );
  }

  return (
    <div className="dmx">
      <div className="dmx__chart" role="img" aria-label="Population stability index by monitored feature">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={rows}
            margin={{ top: 24, right: 56, left: 8, bottom: 8 }}
          >
            <CartesianGrid stroke={grid} strokeDasharray="3 3" horizontal={false} />
            <XAxis
              type="number"
              domain={[0, AXIS_MAX]}
              tickFormatter={(value: number) => value.toFixed(2)}
              stroke={axis}
              tickLine={false}
              axisLine={{ stroke: grid }}
              fontSize={11}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={168}
              stroke={text}
              tickLine={false}
              axisLine={false}
              fontSize={11}
            />
            <Tooltip
              cursor={{ fill: 'rgba(15, 110, 255, 0.05)' }}
              contentStyle={{
                backgroundColor: surface,
                border: `1px solid ${border}`,
                borderRadius: '10px',
                boxShadow: '0 8px 28px rgba(97, 105, 140, 0.12)',
                color: text,
                fontSize: '12px',
              }}
              labelStyle={{ color: text, fontWeight: 600, marginBottom: 4 }}
              formatter={(value: number | string, _name: string, item) => {
                const row = item?.payload as { band: DriftFeatureItem['status'] } | undefined;
                return [
                  `${Number(value).toFixed(4)} — ${row ? PSI_BAND_LABEL[row.band] : ''}`,
                  'Stability index',
                ];
              }}
            />

            <ReferenceLine
              x={warning}
              stroke={warningColor}
              strokeDasharray="3 3"
              strokeWidth={1.5}
              label={{
                value: `Early warning ${warning.toFixed(2)}`,
                fill: warningColor,
                position: 'top',
                fontSize: 10,
              }}
            />
            <ReferenceLine
              x={threshold}
              stroke={danger}
              strokeDasharray="4 4"
              strokeWidth={1.5}
              label={{
                value: `Critical ${threshold.toFixed(2)}`,
                fill: danger,
                position: 'top',
                fontSize: 10,
              }}
            />

            <Bar dataKey="psi_score" radius={[0, 6, 6, 0]} maxBarSize={22} isAnimationActive={false}>
              {rows.map((row) => (
                <Cell key={row.feature_name} fill={barColor(row.band)} />
              ))}
              {/*
                Every feature carries its value as a label.

                A feature that scored exactly 0 gets a bar of zero width, so
                Recharts emits no rectangle for it and the row looks empty — the
                operator cannot tell "measured zero" from "missing". The label is
                what makes the zero visible.
              */}
              <LabelList
                dataKey="psi_score"
                position="right"
                offset={8}
                formatter={(value: number | string) => Number(value).toFixed(4)}
                fill={text}
                fontSize={11}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <ul className="dmx__legend">
        <li className="dmx__legend-item">
          <span className="dmx__swatch" style={{ background: success }} aria-hidden="true" />
          &lt; {warning.toFixed(2)} · Healthy
        </li>
        <li className="dmx__legend-item">
          <span className="dmx__swatch" style={{ background: warningColor }} aria-hidden="true" />
          {warning.toFixed(2)}–{threshold.toFixed(2)} · Moderate shift
        </li>
        <li className="dmx__legend-item">
          <span className="dmx__swatch" style={{ background: danger }} aria-hidden="true" />
          ≥ {threshold.toFixed(2)} · Action required
        </li>
        <li className="dmx__legend-item dmx__legend-item--muted">
          <span
            className="dmx__swatch dmx__swatch--line"
            style={{ borderColor: primary, background: 'transparent' }}
            aria-hidden="true"
          />
          {rows.length} of {rows.length} features plotted
        </li>
      </ul>
    </div>
  );
}

export default DriftMatrixChart;
