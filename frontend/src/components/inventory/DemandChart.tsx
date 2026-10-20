import { useId, useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ForecastItem } from '@/types/forecast';
import { useCssColor } from '@/hooks/useCssColor';
import { round1 } from '@/lib/procurement';
import './DemandChart.css';

/** One plotted day. The API's parallel arrays are zipped into objects once. */
interface ChartDatum {
  /** Short date for the axis, e.g. "20 Oct". */
  date: string;
  /** Full date for the tooltip. */
  fullDate: string;
  /** Expected demand. */
  expected: number;
  /** Low end of the possible range. */
  low: number;
  /** High end of the possible range. */
  high: number;
  /** `[low, high]`, which Recharts renders as a filled range. */
  band: [number, number];
}

interface TooltipEntry {
  dataKey?: string | number;
  value?: number | string | [number, number];
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string;
}

/** `2026-10-20` -> `20 Oct`. Falls back to the raw string if not ISO. */
function shortDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  const [, , month, day] = match;
  const monthName = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ][Number(month) - 1] ?? month;
  return `${Number(day)} ${monthName}`;
}

/** `2026-10-20` -> `20 Oct 2026`. */
function longDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return isoDate;
  return `${shortDate(isoDate)} ${match[1]}`;
}

/**
 * Tooltip body.
 *
 * Reads as a sentence — "Expected 18 units (could be 14–22)" — because that is
 * how the information would be spoken to a pharmacist. The underlying numbers
 * are percentiles of a predictive distribution; the user neither needs nor
 * should be shown that.
 */
function DemandTooltip({ active, payload, label }: ChartTooltipProps) {
  const rangeEntry = payload?.[0]?.value;
  if (!active || !Array.isArray(rangeEntry)) return null;

  const expectedEntry = payload?.find((entry) => entry.dataKey === 'expected');
  const expected = typeof expectedEntry?.value === 'number' ? expectedEntry.value : null;
  const [low, high] = rangeEntry;

  if (typeof low !== 'number' || typeof high !== 'number') return null;

  return (
    <div className="dchart-tooltip">
      <p className="dchart-tooltip__date mono">{label}</p>
      <p className="dchart-tooltip__line">
        Expected{' '}
        <strong>{expected === null ? '—' : `${round1(expected)} units`}
        </strong>
      </p>
      <p className="dchart-tooltip__line muted">
        Possible range {round1(low)}–{round1(high)} units
      </p>
    </div>
  );
}

export interface DemandChartProps {
  item: ForecastItem;
  /** Scenario multiplier applied to every series. */
  multiplier?: number;
  height?: number;
}

/**
 * Expected demand over its possible range.
 *
 * Applies the scenario at render time rather than mutating the forecast, so
 * switching back to Normal is instant and the cached API payload is untouched.
 */
export function DemandChart({ item, multiplier = 1, height = 220 }: DemandChartProps) {
  /*
   * Unique gradient id per instance.
   *
   * A shared id would make every chart on the page resolve the first matching
   * element, so opening a second product would repaint the first.
   */
  const gradientId = `${useId()}-range`;

  // Resolved from :root so the palette keeps one source of truth while reaching
  // Recharts in the literal form SVG presentation attributes require.
  const primary = useCssColor('--color-primary', '#0f6eff');
  const primaryHover = useCssColor('--color-primary-hover', '#2095f3');
  const gridColor = useCssColor('--color-chart-grid', '#eaedf3');
  const surfaceColor = useCssColor('--color-bg-surface', '#ffffff');
  const axisText = useCssColor('--color-chart-axis', '#6d859e');

  const chartData = useMemo<ChartDatum[]>(() => {
    const points: ChartDatum[] = [];

    // These arrays are documented as parallel. Guarding each lookup means a short
    // array yields a short chart instead of `undefined` reaching Recharts and
    // rendering a NaN tick.
    item.dates.forEach((isoDate, index) => {
      const expected = item.predicted_units[index];
      const low = item.lower_bound[index];
      const high = item.upper_bound[index];
      if (typeof expected !== 'number' || typeof low !== 'number' || typeof high !== 'number') {
        return;
      }

      const scaledExpected = round1(expected * multiplier);
      const scaledLow = round1(low * multiplier);
      const scaledHigh = round1(high * multiplier);

      points.push({
        date: shortDate(isoDate),
        fullDate: longDate(isoDate),
        expected: scaledExpected,
        low: scaledLow,
        high: scaledHigh,
        band: [scaledLow, scaledHigh],
      });
    });

    return points;
  }, [item, multiplier]);

  if (chartData.length === 0) {
    return (
      <div className="dchart-empty" style={{ height }}>
        No demand history to chart for this product yet.
      </div>
    );
  }

  return (
    <div className="dchart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {/*
          `ComposedChart`, not `AreaChart`.

          `AreaChart` only understands `Area` children and silently discards a
          `Line`, which would drop the expected-demand line entirely while the
          shaded range still drew — the most confusing possible failure.
        */}
        <ComposedChart data={chartData} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={primary} stopOpacity={0.12} />
              <stop offset="100%" stopColor={primary} stopOpacity={0.03} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />

          <XAxis
            dataKey="date"
            stroke={axisText}
            tick={{ fontSize: 11, fill: axisText }}
            tickLine={false}
            axisLine={{ stroke: gridColor }}
            minTickGap={4}
          />
          <YAxis
            stroke={axisText}
            tick={{ fontSize: 11, fill: axisText }}
            tickLine={false}
            axisLine={false}
            width={42}
            // Demand cannot be negative, so pin the floor at zero rather than
            // letting Recharts fit an axis that starts above the data.
            domain={[0, 'auto']}
            allowDecimals={false}
          />

          <Tooltip
            content={<DemandTooltip />}
            cursor={{ stroke: primary, strokeOpacity: 0.3 }}
            // Recharts labels tooltips from the datum; the ISO date reads better
            // in the tooltip than the abbreviated axis label.
            labelFormatter={(_label, payload) => payload?.[0]?.payload?.fullDate ?? ''}
          />

          <Area
            type="monotone"
            dataKey="band"
            name="Possible range"
            stroke="none"
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
            activeDot={false}
          />
          <Line
            type="monotone"
            dataKey="expected"
            name="Expected demand"
            stroke={primary}
            strokeWidth={3}
            dot={{
              r: chartData.length <= 8 ? 4 : 2,
              fill: primary,
              stroke: surfaceColor,
              strokeWidth: 2,
            }}
            activeDot={{ r: 6, fill: primaryHover }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default DemandChart;
