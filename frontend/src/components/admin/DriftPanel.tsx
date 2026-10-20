import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { Badge, Button, Card, LoadingSpinner } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { DriftMatrixChart } from './DriftMatrixChart';
import { DistributionOverlay } from './DistributionOverlay';
import { RetrainingStepper, type RunPhase } from './RetrainingStepper';
import { DemandShockSimulator } from './DemandShockSimulator';
import { useDriftStatus, DRIFT_POLL_INTERVAL_MS } from '@/api/endpoints/drift';
import { useModelRegistry } from '@/api/endpoints/registry';
import { useRetrainMutation } from '@/api/endpoints/retrain';
import { describeApiError } from '@/api/axios';
import {
  PSI_BAND_DESCRIPTION,
  PSI_BAND_LABEL,
  featureLabel,
  inferRunOutcome,
  type RunOutcome,
} from '@/lib/drift';
import type { DriftStatusResponse } from '@/types/drift';
import type { RetrainResponse } from '@/types/registry';
import './DriftPanel.css';

const STATUS_TONE: Record<DriftStatusResponse['overall_status'], BadgeTone> = {
  OK: 'success',
  WARNING: 'warning',
  DRIFT_DETECTED: 'danger',
};

/**
 * How long to keep watching a dispatched run before calling it quiet.
 *
 * The API gives an `estimated_duration_seconds`; this is the same figure plus
 * grace, because the estimate is explicitly "rough wall-clock cost" and the run
 * legitimately over-runs it on a cold container.
 */
const OUTCOME_GRACE_MS = 90_000;

/** The flow's own default estimate, used until a response supplies its own. */
const DEFAULT_ESTIMATE_SECONDS = 180;

/** Snapshot of everything a run's outcome is compared against. */
interface RunBaseline {
  drift: DriftStatusResponse | null;
  versionCount: number;
  productionVersion: string | null;
  at: number;
}

/**
 * Data quality & drift.
 *
 * The admin console's analytical tab: the live PSI scorecard, the distribution
 * inspector beside it, and the retraining controls. Every technical term on this
 * screen — PSI, quantile, LightGBM — is deliberate and correct here; the rule is
 * containment, not omission, and nothing on this screen appears on `/`,
 * `/inventory`, `/orders` or `/approvals`.
 */
export function DriftPanel() {
  const [shockId, setShockId] = useState<string>('none');
  const [phase, setPhase] = useState<RunPhase>('idle');
  const [response, setResponse] = useState<RetrainResponse | null>(null);
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const baselineRef = useRef<RunBaseline | null>(null);

  const drift = useDriftStatus();
  const registry = useModelRegistry();
  const retrain = useRetrainMutation();

  const features = drift.data?.features ?? [];
  const threshold = drift.data?.psi_threshold;
  const status = drift.data?.overall_status ?? null;
  const driftDetected = status === 'DRIFT_DETECTED';

  /** Counts of each band, for the banner. */
  const counts = useMemo(() => {
    const tally: Record<string, number> = { OK: 0, WARNING: 0, DRIFT_DETECTED: 0 };
    for (const feature of features) tally[feature.status] = (tally[feature.status] ?? 0) + 1;
    return tally;
  }, [features]);

  const handleTrigger = useCallback(() => {
    setRunError(null);
    setOutcome(null);
    setPhase('submitting');

    // Captured *before* dispatch, so the observer can tell what this run changed.
    baselineRef.current = {
      drift: drift.data ?? null,
      versionCount: registry.data?.models.length ?? 0,
      productionVersion: registry.data?.production_version ?? null,
      at: Date.now(),
    };

    retrain.mutate(
      { force: false, notify_on_completion: false },
      {
        onSuccess: (data) => {
          setResponse(data);
          setPhase('in-flight');
        },
        onError: (cause) => {
          setPhase('idle');
          setRunError(describeApiError(cause));
        },
      },
    );
  }, [drift.data, registry.data, retrain]);

  const handleClear = useCallback(() => {
    setPhase('idle');
    setResponse(null);
    setOutcome(null);
    setRunError(null);
    baselineRef.current = null;
  }, []);

  /**
   * Watch a dispatched run for its only observable effects.
   *
   * Two signals exist, per the endpoint's own description: a new version in the
   * registry, and `retraining_triggered` flipping in the drift scorecard. When
   * either appears the run is reported as finished. When neither has after the
   * estimated window plus grace, it is reported as quiet — which is the truthful
   * outcome of a night where drift was not detected and nothing trained.
   */
  useEffect(() => {
    if (phase !== 'in-flight') return;
    const baseline = baselineRef.current;
    if (!baseline) return;

    const versionChanged =
      (registry.data?.models.length ?? 0) > baseline.versionCount ||
      (registry.data?.production_version ?? null) !== baseline.productionVersion;

    const current = inferRunOutcome(baseline.drift, drift.data ?? null, versionChanged);

    if (current !== 'in-flight') {
      setOutcome(current);
      setPhase('observed');
      return;
    }

    // Only the retrain endpoint is allowed to change phase; the deadline just
    // turns an indefinitely "in-flight" run into an honest "no change seen".
    //
    // The deadline is **absolute**, measured from submission, because this effect
    // re-runs on every drift (30 s) and registry (15 s) poll and a relative timer
    // would be reset by each of those and never fire.
    //
    // The timer therefore re-arms itself against the absolute deadline, and each
    // firing re-checks it rather than assuming it has been reached. Capping the
    // interval only bounds how long the check can be late — capping it without
    // re-checking would end the run on the first tick instead of the deadline.
    const estimateSeconds = response?.estimated_duration_seconds ?? DEFAULT_ESTIMATE_SECONDS;
    const deadline = baseline.at + estimateSeconds * 1000 + OUTCOME_GRACE_MS;

    let timer = 0;
    const arm = (): void => {
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        setOutcome('quiet');
        setPhase('observed');
        return;
      }
      timer = window.setTimeout(arm, Math.min(remaining, DRIFT_POLL_INTERVAL_MS));
    };
    arm();

    return () => window.clearTimeout(timer);
  }, [drift.data, phase, registry.data, response]);

  return (
    <div className="driftpanel">
      {/* -------------------------------------------------------------- */}
      {/* Health banner                                                    */}
      {/* -------------------------------------------------------------- */}
      {drift.isPending ? (
        <Card>
          <LoadingSpinner label="Loading drift scorecard" />
        </Card>
      ) : drift.isError ? (
        <Card tone="danger">
          <p className="driftpanel__error">{describeApiError(drift.error)}</p>
          <div className="driftpanel__error-actions">
            <Button variant="secondary" onClick={() => void drift.refetch()}>
              Try again
            </Button>
          </div>
        </Card>
      ) : (
        <div className={`driftpanel__banner driftpanel__banner--${(status ?? 'OK').toLowerCase()}`}>
          <div className="driftpanel__banner-main">
            <div className="driftpanel__banner-head">
              <Activity size={18} aria-hidden="true" />
              <h3 className="driftpanel__banner-title">
                {status ? PSI_BAND_LABEL[status] : 'Not evaluated'}
              </h3>
              {status ? (
                <Badge tone={STATUS_TONE[status]} size="sm">
                  {status}
                </Badge>
              ) : null}
            </div>

            <p className="driftpanel__banner-text">
              {!drift.data?.evaluated
                ? 'No drift evaluation has run yet, so feature health is unknown. This is not a report of healthy data.'
                : `${features.length} monitored ${features.length === 1 ? 'feature' : 'features'}: ${counts.OK} healthy, ${counts.WARNING} with a moderate shift, ${counts.DRIFT_DETECTED} needing action.`}
            </p>

            {status ? (
              <p className="driftpanel__banner-note">{PSI_BAND_DESCRIPTION[status]}</p>
            ) : null}
          </div>

          <dl className="driftpanel__banner-facts">
            <div>
              <dt>Highest score</dt>
              <dd className="numeric">{drift.data?.evaluated ? drift.data.max_psi.toFixed(4) : '—'}</dd>
            </div>
            <div>
              <dt>Last evaluated</dt>
              <dd>
                {drift.data?.checked_at
                  ? new Date(drift.data.checked_at).toLocaleString()
                  : 'Never'}
              </dd>
            </div>
            <div>
              <dt>Retraining</dt>
              <dd>{drift.data?.retraining_triggered ? 'Triggered by last check' : 'Not triggered'}</dd>
            </div>
          </dl>
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Scorecard + distribution inspector                              */}
      {/* -------------------------------------------------------------- */}
      <div className="driftpanel__grid">
        <Card
          title="Feature stability matrix"
          action={
            drift.isFetching && !drift.isPending ? (
              <span className="driftpanel__updating">
                <RefreshCw size={12} aria-hidden="true" /> updating
              </span>
            ) : undefined
          }
        >
          <DriftMatrixChart
            features={features}
            {...(threshold !== undefined ? { threshold } : {})}
          />
        </Card>

        <Card>
          <DistributionOverlay features={features} />
        </Card>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Retraining + simulator                                          */}
      {/* -------------------------------------------------------------- */}
      <div className="driftpanel__grid driftpanel__grid--lower">
        <Card title="Retraining controls">
          <RetrainingStepper
            phase={phase}
            response={response}
            outcome={outcome}
            driftDetected={driftDetected}
            onTrigger={handleTrigger}
            onClear={handleClear}
          />

          {outcome ? (
            <p className="driftpanel__outcome">
              <strong>Run outcome:</strong> {outcome === 'promoted' ? 'a new model version is registered.' : outcome === 'retraining' ? 'drift re-detected; retraining is proceeding.' : outcome === 'quiet' ? 'no observable change within the estimated window.' : 'still running.'}
            </p>
          ) : null}

          {runError ? <p className="driftpanel__error">{runError}</p> : null}
        </Card>

        <Card>
          <DemandShockSimulator
            features={features}
            selectedShockId={shockId}
            onSelect={setShockId}
            {...(threshold !== undefined ? { threshold } : {})}
          />
        </Card>
      </div>

      {features.length > 0 ? (
        <p className="driftpanel__footnote">
          Monitored features: {features.map((feature) => featureLabel(feature.feature_name)).join(', ')}.
          Boundaries are the backend&rsquo;s own <code>drift_psi_warning</code> (0.10) and{' '}
          <code>drift_psi_alert</code> (0.20); this console reads the active threshold from the
          response rather than assuming it.
        </p>
      ) : null}
    </div>
  );
}

export default DriftPanel;
