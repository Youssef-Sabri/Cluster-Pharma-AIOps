import type { ReactNode } from 'react';
import { TrendingDown, TrendingUp, Minus } from 'lucide-react';
import './MetricCard.css';

export type MetricTone = 'primary' | 'success' | 'warning' | 'danger' | 'info';
export type MetricTrend = 'up' | 'down' | 'flat';

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  /** Optional secondary line, e.g. "vs naive baseline". */
  hint?: string;
  tone?: MetricTone;
  /** Direction only — the meaning (good/bad) depends on the metric. */
  trend?: MetricTrend;
  /** Percentage shown beside the trend arrow; sign is pre-formatted by the caller. */
  trendValue?: string;
  /** Inverts trend colouring, for metrics where down is good (e.g. MAE, latency). */
  trendIsImprovement?: boolean;
  icon?: ReactNode;
  /**
   * Steps the value down one size. Use it for words rather than numbers
   * ("No data") — a 30px display face sized for digits will overflow or wrap
   * unpredictably on a long label.
   */
  valueSize?: 'lg' | 'md';
  /**
   * Slot below the trend/hint row, for a status chip or a deep link into the
   * screen where the number can be acted on.
   */
  children?: ReactNode;
}

/** KPI tile: one number, its label, and optionally how to act on it. */
export function MetricCard({
  label,
  value,
  hint,
  tone = 'primary',
  trend,
  trendValue,
  trendIsImprovement = true,
  icon,
  valueSize = 'lg',
  children,
}: MetricCardProps) {
  const trendTone =
    trend === undefined || trend === 'flat'
      ? 'flat'
      : (trend === 'up') === trendIsImprovement
        ? 'good'
        : 'bad';

  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus;

  return (
    <article className={`metric metric--${tone}`}>
      <div className="metric__head">
        <span className="metric__label">{label}</span>
        {icon ? <span className="metric__icon">{icon}</span> : null}
      </div>

      <div className={`metric__value metric__value--${valueSize} numeric`}>{value}</div>

      <div className="metric__foot">
        {trend !== undefined ? (
          <span className={`metric__trend metric__trend--${trendTone}`}>
            <TrendIcon size={14} aria-hidden="true" />
            {trendValue ?? ''}
          </span>
        ) : null}
        {hint ? <span className="metric__hint">{hint}</span> : null}
      </div>

      {children ? <div className="metric__extra">{children}</div> : null}
    </article>
  );
}

export default MetricCard;
