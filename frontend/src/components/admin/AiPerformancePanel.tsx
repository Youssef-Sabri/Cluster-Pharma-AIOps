import { Award, Calendar, FlaskConical, TrendingDown, TrendingUp } from 'lucide-react';
import { Badge, Button, Card, LoadingSpinner } from '@/components/ui';
import { ModelComparisonTable } from './ModelComparisonTable';
import { PromotionGateProof } from './PromotionGateProof';
import { useModelGovernance } from '@/api/endpoints/registry';
import { useTelemetry } from '@/api/endpoints/telemetry';
import { describeApiError } from '@/api/axios';
import { formatSignedPct } from '@/lib/promotion';
import type { ModelMetadataItem, ModelMetrics } from '@/types/registry';
import './AiPerformancePanel.css';

/** A metric that may be absent. */
type Maybe = number | null | undefined;

/** Render a metric, or an em dash when the source never supplied it. */
function metric(value: Maybe, digits = 4): { text: string; missing: boolean } {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return { text: '—', missing: true };
  }
  return { text: value.toFixed(digits), missing: false };
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** Metrics overlaid onto a registry item for the comparison table. */
function withMetrics(model: ModelMetadataItem, metrics: ModelMetrics): ModelMetadataItem {
  return {
    ...model,
    metrics: {
      mae: metrics.mae,
      rmse: metrics.rmse,
      mape: metrics.mape,
      vs_naive_baseline_improvement_pct: metrics.vs_naive_baseline_improvement_pct,
      p95_latency_ms: metrics.p95_latency_ms,
    },
  };
}

/**
 * Model governance.
 *
 * Champion overview, champion-versus-challenger benchmarking, and the promotion
 * gate proof. **Admin-only** — out-of-sample error figures and gate arithmetic
 * never appear on a business screen.
 */
export function AiPerformancePanel() {
  const { data, isPending, isError, error, refetch } = useModelGovernance();
  const { data: telemetry } = useTelemetry();

  if (isPending) {
    return (
      <Card>
        <LoadingSpinner label="Loading model registry" />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card tone="danger">
        <p className="aip__error">{describeApiError(error)}</p>
        <div className="aip__error-actions">
          <Button variant="secondary" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      </Card>
    );
  }

  if (!data?.champion) {
    return (
      <Card tone="warning" title="No model is registered">
        <p className="aip__empty">
          The tracking server has no registered version, so there is no champion to report on. Train a
          model to populate this console.
        </p>
      </Card>
    );
  }

  const { champion, challenger, championMetrics, baselineMetrics, trainingParams, metricsResolved } = data;

  /**
   * Serving latency is not a property of a model version.
   *
   * The registry has no per-version latency, so the honest figure is the
   * service-wide p95 from the request histogram. It is labelled as such in the
   * comparison table rather than presented as a champion-specific measurement.
   */
  const serviceP95 = telemetry?.metrics.p95_latency_ms ?? null;

  const championView = withMetrics(champion, {
    ...championMetrics,
    p95_latency_ms: serviceP95,
  });
  const challengerView = challenger
    ? withMetrics(challenger, {
        mae: challenger.metrics?.mae ?? null,
        rmse: challenger.metrics?.rmse ?? null,
        mape: challenger.metrics?.mape ?? null,
        vs_naive_baseline_improvement_pct:
          challenger.metrics?.vs_naive_baseline_improvement_pct ?? null,
        p95_latency_ms: challenger.metrics?.p95_latency_ms ?? null,
      })
    : null;

  const mae = metric(championMetrics.mae);
  const improvement = championMetrics.vs_naive_baseline_improvement_pct;
  const baselineMae = metric(baselineMetrics.mae);

  return (
    <div className="aip">
      {/* -------------------------------------------------------------- */}
      {/* Champion overview                                             */}
      {/* -------------------------------------------------------------- */}
      <div className="aip__grid">
        <Card title="Active champion" className="aip__champion">
          <div className="aip__champion-head">
            <span className="aip__champion-icon" aria-hidden="true">
              <Award size={18} />
            </span>
            <div>
              <p className="aip__champion-name">{champion.name}</p>
              <p className="aip__champion-version">
                Version {champion.version}
                <Badge tone="success" size="sm">
                  {champion.stage === 'Production' ? 'Production' : champion.stage}
                </Badge>
              </p>
            </div>
          </div>

          <dl className="aip__facts">
            <div>
              <dt>
                <TrendingDown size={11} aria-hidden="true" /> Out-of-sample MAE
              </dt>
              <dd className={mae.missing ? 'aip__missing' : ''}>
                {mae.text}
                {!mae.missing ? <span className="aip__unit"> units</span> : null}
              </dd>
            </div>
            <div>
              <dt>
                <TrendingUp size={11} aria-hidden="true" /> vs naive baseline
              </dt>
              <dd className={improvement === null ? 'aip__missing' : 'aip__good'}>
                {improvement === null ? '—' : formatSignedPct(improvement)}
              </dd>
            </div>
            <div>
              <dt>Naive baseline MAE</dt>
              <dd className={baselineMae.missing ? 'aip__missing' : ''}>{baselineMae.text}</dd>
            </div>
            <div>
              <dt>
                <Calendar size={11} aria-hidden="true" /> Registered
              </dt>
              <dd>{formatDate(champion.registered_at)}</dd>
            </div>
          </dl>

          {champion.promotion_reason ? (
            <p className="aip__reason">
              <FlaskConical size={13} aria-hidden="true" />
              {champion.promotion_reason}
            </p>
          ) : null}

          {Object.keys(trainingParams).length > 0 ? (
            <ul className="aip__params">
              {Object.entries(trainingParams).map(([key, value]) => (
                <li key={key}>
                  <span>{key}</span>
                  <code>{value}</code>
                </li>
              ))}
            </ul>
          ) : null}

          {!metricsResolved ? (
            <p className="aip__caveat">
              Only the registry answered; the tracking server did not, so RMSE, MAPE and the
              baseline comparison are unavailable. Nothing is estimated in their place.
            </p>
          ) : null}
        </Card>

        <Card title="Promotion gate">
          <PromotionGateProof
            productionMae={championMetrics.mae}
            challengerMae={challengerView?.metrics?.mae ?? null}
            hasChallenger={challengerView !== null}
          />
        </Card>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Champion vs challenger                                        */}
      {/* -------------------------------------------------------------- */}
      <Card title="Champion vs challenger">
        <ModelComparisonTable champion={championView} challenger={challengerView} />
      </Card>
    </div>
  );
}

export default AiPerformancePanel;
