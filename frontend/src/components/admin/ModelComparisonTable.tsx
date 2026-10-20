import { Badge } from '@/components/ui';
import type { BadgeTone } from '@/components/ui';
import { compareMetric, formatChangePct } from '@/lib/promotion';
import type { ModelMetrics, ModelMetadataItem } from '@/types/registry';
import './ModelComparisonTable.css';

/** Stage name to badge tone. */
const STAGE_TONE: Record<string, BadgeTone> = {
  Production: 'success',
  Staging: 'info',
  Archived: 'neutral',
  candidate: 'info',
};

/** Display name for the registry's stage values, which are mixed-case. */
function stageLabel(stage: string): string {
  const known: Record<string, string> = {
    Production: 'Production',
    Staging: 'Staging',
    Archived: 'Archived',
    candidate: 'Candidate',
  };
  return known[stage] ?? stage;
}

/** One comparable metric and how it is read. */
interface MetricSpec {
  key: keyof ModelMetrics;
  label: string;
  /** MAE, RMSE and latency all improve by decreasing. */
  lowerIsBetter: boolean;
  digits: number;
}

const METRICS: readonly MetricSpec[] = [
  { key: 'mae', label: 'MAE', lowerIsBetter: true, digits: 4 },
  { key: 'rmse', label: 'RMSE', lowerIsBetter: true, digits: 4 },
  { key: 'mape', label: 'MAPE', lowerIsBetter: true, digits: 4 },
  { key: 'p95_latency_ms', label: 'P95 latency (service-wide)', lowerIsBetter: true, digits: 1 },
];

export interface ModelComparisonTableProps {
  /** The model currently serving traffic. */
  champion: ModelMetadataItem;
  /** The challenger awaiting a decision, if one exists. */
  challenger: ModelMetadataItem | null;
}

/**
 * Champion vs challenger, side by side.
 *
 * **Admin-only.** Out-of-sample error figures belong to the admin console.
 *
 * A metric absent from the payload renders as an em dash rather than a zero.
 * `metrics` arrives empty from the registry today, and a table that printed
 * `0.0000` for an unmeasured metric would be the single most misleading thing on
 * the page.
 */
export function ModelComparisonTable({ champion, challenger }: ModelComparisonTableProps) {
  const championMetrics = champion.metrics ?? {};

  return (
    <div className="mct">
      <div className="mct__heads">
        <div className="mct__metric-head">Metric</div>
        <div className="mct__model-head">
          <span className="mct__role">Production champion</span>
          <span className="mct__name">{champion.name}</span>
          <span className="mct__version">
            v{champion.version}
            <Badge tone={STAGE_TONE[champion.stage] ?? 'neutral'} size="sm">
              {stageLabel(champion.stage)}
            </Badge>
          </span>
        </div>
        {challenger ? (
          <div className="mct__model-head">
            <span className="mct__role">Challenger</span>
            <span className="mct__name">{challenger.name}</span>
            <span className="mct__version">
              v{challenger.version}
              <Badge tone={STAGE_TONE[challenger.stage] ?? 'info'} size="sm">
                {stageLabel(challenger.stage)}
              </Badge>
            </span>
          </div>
        ) : (
          <div className="mct__model-head mct__model-head--empty">
            <span className="mct__role">Challenger</span>
            <span className="mct__none">None registered</span>
          </div>
        )}
      </div>

      {METRICS.map((spec) => {
        const championValue = championMetrics[spec.key];
        const challengerValue = challenger?.metrics?.[spec.key];
        const delta = compareMetric(championValue, challengerValue, spec.lowerIsBetter);

        return (
          <div key={spec.key} className="mct__row">
            <div className="mct__metric">{spec.label}</div>

            <div className="mct__value">
              {championValue === undefined || championValue === null ? (
                <span className="mct__dash">—</span>
              ) : (
                <span className="numeric">{championValue.toFixed(spec.digits)}</span>
              )}
            </div>

            {challenger ? (
              <>
                <div className="mct__value">
                  {/* Hoisted so the null check narrows the render below. */}
                  {challengerValue === undefined || challengerValue === null ? (
                    <span className="mct__dash">—</span>
                  ) : (
                    <span className="numeric">{challengerValue.toFixed(spec.digits)}</span>
                  )}
                </div>
                <div className={`mct__delta mct__delta--${delta.direction}`}>
                  {delta.direction === 'unknown' ? (
                    '—'
                  ) : (
                    <>
                      {formatChangePct(delta.changePct)}
                      <span className="mct__delta-word">
                        {delta.direction === 'better' ? 'better' : 'worse'}
                      </span>
                    </>
                  )}
                </div>
              </>
            ) : (
              <div className="mct__value mct__value--empty">
                <span className="mct__dash">—</span>
              </div>
            )}
          </div>
        );
      })}

      {!challenger ? (
        <p className="mct__note">
          A challenger appears here once a retraining run registers a candidate version. The
          registry currently holds one version, which was promoted as the first production model.
        </p>
      ) : null}
    </div>
  );
}

export default ModelComparisonTable;
