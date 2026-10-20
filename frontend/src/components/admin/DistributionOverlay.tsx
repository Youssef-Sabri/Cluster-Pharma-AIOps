import { useMemo, useState } from 'react';
import { Info, LineChart as LineChartIcon } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useCssColor } from '@/hooks/useCssColor';
import type { DistributionComparison, DriftFeatureItem } from '@/types/drift';
import { featureLabel } from '@/lib/drift';
import './DistributionOverlay.css';

const FALLBACK = {
  grid: '#eaedf3',
  axis: '#6d859e',
  text: '#1c1b2e',
  surface: '#ffffff',
  border: '#eaedf3',
  primary: '#0f6eff',
  warning: '#f59e0b',
  muted: '#9aa9bd',
} as const;

export interface DistributionOverlayProps {
  /** Features currently listed by the drift scorecard, for the selector. */
  features: DriftFeatureItem[];
  /**
   * Distribution comparisons to plot.
   *
   * Empty today — see the note on `DistributionComparison`. The component is
   * complete and renders the moment this becomes non-empty; until then it shows
   * an explanation instead of an invented histogram.
   */
  comparisons?: DistributionComparison[];
}

/**
 * Baseline vs. inference distribution inspector.
 *
 * ## Why this is empty
 *
 * The brief specified `DriftFeatureItem` as carrying `baseline_mean` and
 * `current_mean`, from which an overlay would be drawn. The real schema has
 * neither field, and nothing else exposes distributions either:
 *
 * - `drift_logs` holds `checked_at`, `feature_name`, `psi_score`, `status`,
 *   `retraining_triggered`, `id` — a scalar per feature, no samples. Verified
 *   against `information_schema`.
 * - No endpoint returns the training window or the inference window as rows.
 * - The drift detector computes its bins internally from quantile edges and
 *   discards them; only the resulting PSI is persisted.
 *
 * A histogram drawn from PSI alone would not be a distribution — it would be a
 * chart of the same number the bar chart beside it already shows, dressed up to
 * look like evidence. So this renders the gap plainly and says what would fix it.
 */
export function DistributionOverlay({ features, comparisons = [] }: DistributionOverlayProps) {
  const grid = useCssColor('--color-bg-border', FALLBACK.grid);
  const axis = useCssColor('--color-text-secondary', FALLBACK.axis);
  const text = useCssColor('--color-text-primary', FALLBACK.text);
  const surface = useCssColor('--color-bg-surface', FALLBACK.surface);
  const border = useCssColor('--color-bg-border', FALLBACK.border);
  const primary = useCssColor('--color-primary', FALLBACK.primary);
  const warning = useCssColor('--color-warning', FALLBACK.warning);

  const featureNames = useMemo(() => features.map((feature) => feature.feature_name), [features]);
  const [selected, setSelected] = useState<string>('');

  // Fall back to the first feature once the list arrives or the choice goes away.
  const activeFeature = selected && featureNames.includes(selected) ? selected : (featureNames[0] ?? '');

  const active = comparisons.find((comparison) => comparison.featureName === activeFeature);

  const rows = useMemo(
    () =>
      (active?.bins ?? []).map((bin) => ({
        range: `${bin.from.toFixed(1)}–${bin.to.toFixed(1)}`,
        Baseline: bin.baselineShare,
        Current: bin.currentShare,
      })),
    [active],
  );

  const options = features.map((feature) => ({
    value: feature.feature_name,
    label: featureLabel(feature.feature_name),
  }));

  return (
    <div className="dov">
      <div className="dov__head">
        <div>
          <h3 className="dov__title">Distribution shift inspector</h3>
          <p className="dov__subtitle">
            Training baseline against the last 30 days of live traffic.
          </p>
        </div>

        <label className="dov__picker">
          <span className="visually-hidden">Feature to inspect</span>
          <select
            className="dov__select"
            value={activeFeature}
            onChange={(event) => setSelected(event.target.value)}
            disabled={options.length === 0}
          >
            {options.length === 0 ? (
              <option value="">No features evaluated</option>
            ) : (
              options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </select>
        </label>
      </div>

      {rows.length > 0 ? (
        <div className="dov__chart" role="img" aria-label="Baseline against current distribution">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ top: 8, right: 12, left: -12, bottom: 4 }}>
              <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="range" stroke={axis} tickLine={false} fontSize={10} interval={0} />
              <YAxis
                stroke={axis}
                tickLine={false}
                axisLine={false}
                fontSize={10}
                tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: surface,
                  border: `1px solid ${border}`,
                  borderRadius: '10px',
                  color: text,
                  fontSize: '12px',
                }}
                formatter={(value: number | string) => `${(Number(value) * 100).toFixed(1)}%`}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: axis }} />
              <Bar dataKey="Baseline" fill={primary} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="Current" fill={warning} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="dov__empty">
          <LineChartIcon size={22} aria-hidden="true" className="dov__empty-icon" />
          <p className="dov__empty-title">Distribution samples are not exposed yet</p>
          <p className="dov__empty-text">
            The drift endpoint returns one stability score per feature, and the drift table stores
            only that score — not the underlying observations. Without both windows there is nothing
            to overlay, and drawing a histogram from a single score would misrepresent a number as
            evidence.
          </p>
          <p className="dov__empty-note">
            <Info size={13} aria-hidden="true" />
            Fix: persist the detector&rsquo;s bin counts per window alongside <code>psi_score</code>.
          </p>
        </div>
      )}
    </div>
  );
}

export default DistributionOverlay;
