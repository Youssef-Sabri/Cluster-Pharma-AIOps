import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import './KpiCard.css';

export type KpiState = 'loading' | 'ready' | 'unavailable';

interface KpiCardBase {
  label: string;
  /** Short business-language qualifier under the value. */
  hint?: string;
  /** Where the card navigates to. */
  to: string;
  icon: ReactNode;
}

/**
 * Discriminated union rather than one loose prop bag.
 *
 * The alternative — a `value?: ReactNode` alongside a separate `state` — cannot
 * stop a caller rendering a "ready" card with no value, which is precisely the
 * failure this component exists to make impossible. Here the compiler enforces
 * the invariant: `ready` requires a value, and `unavailable` must explain why.
 */
export type KpiCardProps = KpiCardBase &
  (
    | { state?: 'ready'; value: ReactNode }
    | { state: 'loading' }
    | {
        state: 'unavailable';
        /**
         * Why the number is missing, shown instead of a value.
         *
         * A missing data feed must never render as `0`. A pharmacy manager
         * reading "0 low stock alerts" would conclude inventory is healthy and
         * skip reordering — the exact failure this product must not cause.
         */
        unavailableReason: string;
      }
  );

/**
 * Commercial KPI tile.
 *
 * The whole card is one link, because the number is only useful as an entry
 * point to the screen where the operator can act on it.
 */
export function KpiCard(props: KpiCardProps) {
  const { label, hint, to, icon, state } = props;
  const unavailable = state === 'unavailable';

  return (
    <Link
      to={to}
      className={`kpi-card${unavailable ? ' kpi-card--unavailable' : ''}`}
      aria-disabled={unavailable || undefined}
    >
      <div className="kpi-card__head">
        <span className="kpi-card__label">{label}</span>
        <span className="kpi-card__icon">{icon}</span>
      </div>

      {state === 'loading' ? (
        <>
          <div className="skeleton kpi-card__skeleton" />
          <div className="skeleton kpi-card__skeleton-sm" />
        </>
      ) : unavailable ? (
        <>
          <span className="kpi-card__value kpi-card__value--unavailable">—</span>
          <span className="kpi-card__reason">{props.unavailableReason}</span>
        </>
      ) : (
        <>
          <span className="kpi-card__value numeric">{props.value}</span>
          {hint ? <span className="kpi-card__hint">{hint}</span> : null}
        </>
      )}

      <span className="kpi-card__cta">
        View details <ArrowUpRight size={13} aria-hidden="true" />
      </span>
    </Link>
  );
}

export default KpiCard;
