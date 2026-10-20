import { useMemo } from 'react';
import { FlaskConical, RotateCcw } from 'lucide-react';
import { Badge, Button } from '@/components/ui';
import { DEMAND_SHOCKS, DEFAULT_SHOCK, PSI_ALERT_THRESHOLD, PSI_BAND_LABEL, PSI_WARNING_THRESHOLD, psiBand } from '@/lib/drift';
import type { DriftFeatureItem } from '@/types/drift';
import './DemandShockSimulator.css';

/**
 * How much a shock inflates the stability score.
 *
 * PSI is `Σ (actual% − expected%) · ln(actual% / expected%)`, so scaling the
 * observed distribution by a factor inflates it faster than linearly. The
 * exponent is a **demonstration approximation**, not a reimplementation of PSI —
 * the real computation belongs to the backend detector.
 *
 * Note what it does *not* do: with the features currently monitored (all below
 * `0.05`), neither scenario reaches the `0.10` boundary, because they are not
 * near it. That is the honest result and the note reports it as such — the
 * exponent is not tuned to force a crossing that the data does not support.
 */
const SHOCK_EXPONENT = 1.5;

/** Preview the stability score a shock would be expected to produce. */
function projectedPsi(measured: number, factor: number): number {
  if (factor <= 1) return measured;
  return measured * factor ** SHOCK_EXPONENT;
}

export interface DemandShockSimulatorProps {
  /** The real, measured feature scores. Never mutated. */
  features: DriftFeatureItem[];
  selectedShockId: string;
  onSelect: (shockId: string) => void;
  threshold?: number;
  warning?: number;
}

/**
 * Synthetic demand shock simulator.
 *
 * An admin demonstration tool: pick a scenario and see which features would cross
 * a decision boundary. The measured scores stay on screen at all times, and every
 * projected number is badged, because the whole point of this console is that
 * its numbers can be trusted — a simulator that blurs into the real scorecard
 * would spend that.
 */
export function DemandShockSimulator({
  features,
  selectedShockId,
  onSelect,
  threshold = PSI_ALERT_THRESHOLD,
  warning = PSI_WARNING_THRESHOLD,
}: DemandShockSimulatorProps) {
  const shock = DEMAND_SHOCKS.find((entry) => entry.id === selectedShockId) ?? DEFAULT_SHOCK;
  const simulating = shock.factor > 1;

  const rows = useMemo(
    () =>
      features
        .map((feature) => {
          const projected = projectedPsi(feature.psi_score, shock.factor);
          const measuredBand = psiBand(feature.psi_score, warning, threshold);
          const projectedBand = psiBand(projected, warning, threshold);
          return {
            feature,
            projected,
            measuredBand,
            projectedBand,
            escalates: simulating && measuredBand !== projectedBand,
          };
        })
        .sort((a, b) => b.projected - a.projected),
    [features, shock.factor, simulating, threshold, warning],
  );

  const escalations = rows.filter((row) => row.escalates).length;

  /** Highest score in the current view, measured or projected. */
  const highest = useMemo(
    () => rows.reduce((max, row) => Math.max(max, row.projected), 0),
    [rows],
  );

  return (
    <div className="dsim">
      <div className="dsim__head">
        <div>
          <h3 className="dsim__title">
            <FlaskConical size={15} aria-hidden="true" />
            Demand shock simulator
          </h3>
          <p className="dsim__subtitle">
            Preview how a demand surge would move the stability scores, to rehearse the alerting
            path without waiting for a real shock.
          </p>
        </div>
        {simulating ? (
          <Badge tone="warning" size="sm">
            Simulated
          </Badge>
        ) : (
          <Badge tone="neutral" size="sm">
            Measured values
          </Badge>
        )}
      </div>

      <div className="dsim__controls">
        {DEMAND_SHOCKS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`dsim__btn${entry.id === shock.id ? ' dsim__btn--on' : ''}`}
            onClick={() => onSelect(entry.id)}
            title={entry.blurb}
            aria-pressed={entry.id === shock.id}
          >
            {entry.label}
          </button>
        ))}

        {simulating ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSelect('none')}
            icon={<RotateCcw size={13} />}
          >
            Reset
          </Button>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="dsim__empty">
          No features have been evaluated, so there is nothing to project against. Run a drift
          evaluation first.
        </p>
      ) : (
        <>
          <table className="dsim__table">
            <caption className="visually-hidden">
              Measured stability scores against the selected simulated shock
            </caption>
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col" className="dsim__num">
                  Measured
                </th>
                <th scope="col" className="dsim__num">
                  Projected
                </th>
                <th scope="col">Band</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ feature, projected, measuredBand, projectedBand, escalates }) => (
                <tr key={feature.feature_name} className={escalates ? 'dsim__row--escalates' : ''}>
                  <th scope="row">{feature.feature_name}</th>
                  <td className="dsim__num numeric">{feature.psi_score.toFixed(4)}</td>
                  <td className={`dsim__num numeric${simulating ? ' dsim__projected' : ''}`}>
                    {projected.toFixed(4)}
                  </td>
                  <td>
                    <span className={`dsim__band dsim__band--${(simulating ? projectedBand : measuredBand).toLowerCase()}`}>
                      {PSI_BAND_LABEL[simulating ? projectedBand : measuredBand]}
                      {escalates ? ' ↑' : ''}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {simulating ? (
            <p className="dsim__note">
              {escalations > 0 ? (
                <>
                  <strong>{escalations}</strong> of {rows.length}{' '}
                  {escalations === 1 ? 'feature would' : 'features would'} change band under this
                  shock and become candidates for retraining.
                </>
              ) : (
                <>
                  No feature changes band. The highest projected score is{' '}
                  <strong>{highest.toFixed(4)}</strong>, still{' '}
                  {warning > 0 && highest > 0
                    ? `${Math.max(1, Math.floor(warning / highest))}× below`
                    : 'below'}{' '}
                  the {warning.toFixed(2)} early-warning boundary — these features are not close
                  enough to it for a {Math.round((shock.factor - 1) * 100)}% surge to matter.
                </>
              )}{' '}
              Projections are a demonstration heuristic, not a measurement.
            </p>
          ) : (
            <p className="dsim__note dsim__note--muted">
              Values above are the live measurements from the drift scorecard.
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default DemandShockSimulator;
