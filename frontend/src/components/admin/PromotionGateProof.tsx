import { useCssColor } from '@/hooks/useCssColor';
import {
  REQUIRED_IMPROVEMENT_PCT,
  evaluateGate,
  formatSignedPct,
  type GateEvaluation,
} from '@/lib/promotion';
import './PromotionGateProof.css';

const FALLBACK = {
  surface: '#ffffff',
  border: '#eaedf3',
  text: '#1c1b2e',
  muted: '#6d859e',
  success: '#10b981',
  danger: '#ef4444',
  successText: '#0b8f63',
  dangerText: '#d63c3c',
} as const;

export interface PromotionGateProofProps {
  /** MAE of the current Production champion, or null when there is none. */
  productionMae: number | null;
  /**
   * MAE of the challenger awaiting a decision, or null when nothing is pending.
   *
   * Deliberately not defaulted to the naive baseline: a baseline comparison is
   * informative, but it is not the promotion gate, and presenting one as the
   * other would assert a promotion decision that was never made.
   */
  challengerMae: number | null;
  /** Whether a challenger is registered and awaiting evaluation. */
  hasChallenger: boolean;
}

/**
 * Mathematical promotion-gate proof.
 *
 * Shows the arithmetic behind the 3% rule and whether it is currently satisfied.
 * **Admin-only** — MAE values and gate maths are exactly the detail the product
 * rules keep off the business screens.
 *
 * When nothing is awaiting a decision the component says so instead of showing a
 * formula with a missing operand.
 */
export function PromotionGateProof({
  productionMae,
  challengerMae,
  hasChallenger,
}: PromotionGateProofProps) {
  const surface = useCssColor('--color-bg-surface', FALLBACK.surface);
  const border = useCssColor('--color-bg-border', FALLBACK.border);
  const text = useCssColor('--color-text-primary', FALLBACK.text);
  const muted = useCssColor('--color-text-secondary', FALLBACK.muted);
  const success = useCssColor('--color-success', FALLBACK.success);
  const danger = useCssColor('--color-danger', FALLBACK.danger);
  const successText = useCssColor('--color-success-text', FALLBACK.successText);
  const dangerText = useCssColor('--color-danger-text', FALLBACK.dangerText);

  const evaluation: GateEvaluation | null = evaluateGate(productionMae, challengerMae);
  const prod = productionMae ?? null;

  return (
    <div className="gate">
      <div className="gate__head">
        <h3 className="gate__title">Promotion gate · 3% rule</h3>

        {!evaluation || !hasChallenger ? (
          <span className="gate__badge gate__badge--idle">No challenger awaiting evaluation</span>
        ) : evaluation.qualifies ? (
          <span className="gate__badge gate__badge--pass">
            Promotion approved ({formatSignedPct(evaluation.improvementPct)})
          </span>
        ) : (
          <span className="gate__badge gate__badge--fail">
            Gate rejected ({evaluation.improvementPct.toFixed(1)}% &lt;{' '}
            {REQUIRED_IMPROVEMENT_PCT.toFixed(1)}%)
          </span>
        )}
      </div>

      <div
        className="gate__formula"
        style={{ background: surface, borderColor: border, color: text }}
      >
        <span className="gate__expr">
          <span className="gate__op">improvement</span>
          <span className="gate__eq">=</span>
          <span className="gate__frac">
            <span className="gate__num">
              MAE<sub>prod</sub>
              <span className="gate__minus"> − </span>MAE<sub>chal</sub>
            </span>
            <span className="gate__bar" />
            <span className="gate__den">MAE<sub>prod</sub></span>
          </span>
          {prod !== null && challengerMae !== null && evaluation ? (
            <>
              <span className="gate__eq">=</span>
              <span className="gate__num">
                ({prod.toFixed(4)} − {challengerMae.toFixed(4)}) / {prod.toFixed(4)}
              </span>
              <span className="gate__eq">=</span>
              <strong
                className="gate__result"
                style={{
                  color: evaluation.qualifies ? successText : dangerText,
                  borderColor: evaluation.qualifies ? success : danger,
                  background: evaluation.qualifies
                    ? 'var(--color-success-tint)'
                    : 'var(--color-danger-tint)',
                }}
              >
                {formatSignedPct(evaluation.improvementPct, 2)}
              </strong>
            </>
          ) : (
            <span className="gate__blank" style={{ color: muted }}>
              — no challenger
            </span>
          )}
          <span className="gate__eq">≥</span>
          <span className="gate__threshold">{REQUIRED_IMPROVEMENT_PCT.toFixed(1)}%</span>
        </span>
      </div>

      {evaluation && hasChallenger ? (
        <p className="gate__note" style={{ color: muted }}>
          {evaluation.qualifies ? (
            <>
              The challenger beats the champion by {evaluation.improvementPct.toFixed(2)}% on
              out-of-sample MAE, clearing the required {REQUIRED_IMPROVEMENT_PCT.toFixed(1)}% with{' '}
              {(evaluation.improvementPct - REQUIRED_IMPROVEMENT_PCT).toFixed(2)} percentage points
              to spare. The gate would authorise promotion.
            </>
          ) : (
            <>
              The challenger falls short by {evaluation.shortfallPts.toFixed(2)} percentage points.
              A promotion would be rejected and the challenger would remain in staging.
            </>
          )}
        </p>
      ) : (
        <p className="gate__note" style={{ color: muted }}>
          Under ClusterOps safety rules a challenger cannot replace the champion unless out-of-sample
          error is reduced by at least {REQUIRED_IMPROVEMENT_PCT.toFixed(1)}%. The registry holds a
          single version, which was promoted as the first production model — there was no champion
          for a challenger to be measured against, so the gate has had nothing to rule on.
        </p>
      )}
    </div>
  );
}

export default PromotionGateProof;
