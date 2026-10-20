import { Check, CircleDashed, Loader2, Play, TriangleAlert } from 'lucide-react';
import { Badge, Button } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { RETRAIN_STAGES, type RunOutcome } from '@/lib/drift';
import type { RetrainResponse } from '@/types/registry';
import './RetrainingStepper.css';

/** What the console knows about a run. */
export type RunPhase = 'idle' | 'submitting' | 'in-flight' | 'observed';

export interface RetrainingStepperProps {
  phase: RunPhase;
  /** The 202 response, once received. */
  response: RetrainResponse | null;
  /** Outcome inferred from observable API changes. */
  outcome: RunOutcome | null;
  /** Whether the drift gate currently warrants a retraining run. */
  driftDetected: boolean;
  onTrigger: () => void;
  onClear: () => void;
  disabled?: boolean;
}

const PHASE_COPY: Record<RunPhase, { title: string; detail: string }> = {
  idle: {
    title: 'Idle',
    detail: 'No retraining run has been requested from this console.',
  },
  submitting: {
    title: 'Submitting',
    detail: 'Handing the flow to the background runner.',
  },
  'in-flight': {
    title: 'Running',
    detail:
      'Accepted and dispatched. The flow reports its progress to its own log, not to this API, so the console can only watch for its effects.',
  },
  observed: { title: 'Finished', detail: 'The run concluded and its effects were observed.' },
};

function PhaseBadge({ phase, outcome }: { phase: RunPhase; outcome: RunOutcome | null }): { tone: BadgeTone; label: string } {
  if (phase === 'submitting') return { tone: 'info', label: 'Submitting' };
  if (phase === 'in-flight') return { tone: 'info', label: 'Running' };
  if (phase === 'observed') {
    if (outcome === 'promoted') return { tone: 'success', label: 'Promoted' };
    if (outcome === 'retraining') return { tone: 'success', label: 'Retraining' };
    return { tone: 'neutral', label: 'No change observed' };
  }
  return { tone: 'neutral', label: 'Idle' };
}

/**
 * Retraining pipeline stepper.
 *
 * ## Why stages are not individually animated
 *
 * The brief asks for per-stage Pending / Running / Succeeded / Failed
 * indicators. `POST /api/v1/retrain` returns `202` with a tracking id and nothing
 * further, and no endpoint reports per-stage progress — the endpoint description
 * names exactly two observables: a new version appearing in the model registry,
 * and `retraining_triggered` flipping in the drift scorecard.
 *
 * Walking a timer through seven stages would render "Challenger fit: succeeded"
 * and "3% gate and promotion: succeeded" for a run whose outcome this console has
 * observed nothing about. That is a fabricated measurement on the one screen
 * where an operator would trust it, so it is not done.
 *
 * Instead the stage list is the real flow, drawn from `retrain_flow.py`, and each
 * stage carries the status that is actually true:
 *
 * - **Dispatched** — the flow accepted the run and would be executing now.
 * - **Awaiting observation** — no telemetry exists for this stage.
 * - **Observed** — set on every stage only once the registry or the drift
 *   scorecard actually reports the consequence.
 */
export function RetrainingStepper({
  phase,
  response,
  outcome,
  driftDetected,
  onTrigger,
  onClear,
  disabled = false,
}: RetrainingStepperProps) {
  const badge = PhaseBadge({ phase, outcome });
  const copy = PHASE_COPY[phase];

  const dispatched = phase === 'in-flight' || phase === 'observed';
  const observed = phase === 'observed';

  return (
    <div className="rstep">
      <div className="rstep__head">
        <div>
          <h3 className="rstep__title">Retraining pipeline</h3>
          <p className="rstep__subtitle">{copy.detail}</p>
        </div>
        <Badge tone={badge.tone} size="sm">
          {badge.label}
        </Badge>
      </div>

      <ol className="rstep__stages">
        {RETRAIN_STAGES.map((stage, index) => {
          const state = observed ? 'observed' : dispatched ? 'dispatched' : 'idle';
          return (
            <li key={stage.task} className={`rstep__stage rstep__stage--${state}`}>
              <span className="rstep__marker" aria-hidden="true">
                {state === 'observed' ? (
                  <Check size={13} />
                ) : state === 'dispatched' ? (
                  <Loader2 size={13} className="rstep__spin" />
                ) : (
                  <CircleDashed size={13} />
                )}
              </span>

              <span className="rstep__body">
                <span className="rstep__label">
                  <span className="rstep__index">{index + 1}</span>
                  {stage.label}
                </span>
                <code className="rstep__task">{stage.task}</code>
              </span>

              <span className="rstep__state">
                {state === 'observed'
                  ? 'Observed'
                  : state === 'dispatched'
                    ? 'Awaiting observation'
                    : 'Not started'}
              </span>
            </li>
          );
        })}
      </ol>

      {response ? (
        <dl className="rstep__facts">
          <div className="rstep__fact">
            <dt>Flow run</dt>
            <dd className="mono">{response.flow_run_id}</dd>
          </div>
          <div className="rstep__fact">
            <dt>Status</dt>
            <dd>{response.status}</dd>
          </div>
          <div className="rstep__fact">
            <dt>Estimated window</dt>
            <dd>~{Math.round(response.estimated_duration_seconds / 60)} min</dd>
          </div>
          <div className="rstep__fact">
            <dt>Forced past gate</dt>
            <dd>{response.force ? 'Yes' : 'No'}</dd>
          </div>
        </dl>
      ) : null}

      {response?.message ? <p className="rstep__message">{response.message}</p> : null}

      {/*
        A run that ends with nothing observable is the case an operator is most
        likely to misread as "still training". In this deployment it has a known
        cause: the Prefect SDK is installed but no orchestration server is, so
        the flow is accepted and then cannot execute. The 202 confirms the
        request was queued, not that anything ran — which is the distinction the
        rest of this component exists to preserve.
      */}
      {phase === 'observed' && outcome === 'quiet' ? (
        <p className="rstep__caveat">
          <TriangleAlert size={14} aria-hidden="true" />
          <span>
            Nothing changed. This demo environment runs without a Prefect orchestration server, so
            a triggered flow is accepted and then cannot execute — the <code>202</code> confirms the
            request was queued, not that training ran.
          </span>
        </p>
      ) : null}

      <div className="rstep__actions">
        <Button
          variant="primary"
          onClick={onTrigger}
          loading={phase === 'submitting'}
          disabled={disabled}
          icon={<Play size={15} />}
        >
          {phase === 'submitting' ? 'Submitting' : 'Trigger retraining flow'}
        </Button>

        {phase !== 'idle' ? (
          <Button variant="ghost" onClick={onClear} disabled={phase === 'submitting'}>
            Clear
          </Button>
        ) : null}
      </div>

      {!driftDetected && phase === 'idle' ? (
        <p className="rstep__hint">
          <TriangleAlert size={14} aria-hidden="true" />
          No feature is currently at the critical threshold, so a plain run is expected to stop at
          the gate and train nothing. Trigger it anyway to re-evaluate drift on demand.
        </p>
      ) : null}
    </div>
  );
}

export default RetrainingStepper;
