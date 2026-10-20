import type { ReactNode } from 'react';
import './Card.css';

export type CardTone = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

export interface CardProps {
  children: ReactNode;
  /** Small caption above the content. */
  title?: string;
  /** Right-aligned slot in the header row. */
  action?: ReactNode;
  /** Border/accent tint used by drift and status panels. */
  tone?: CardTone;
  /** Adds the blue halo; reserved for the currently active model. */
  glow?: boolean;
  /** Removes the body padding for flush media such as charts. */
  flush?: boolean;
  className?: string;
}

/**
 * The project's only container primitive: a glassmorphic surface on the deep
 * navy base. Every variant is expressed through design tokens so the shell
 * stays a single coherent surface rather than a mix of boxes.
 */
export function Card({
  children,
  title,
  action,
  tone = 'default',
  glow = false,
  flush = false,
  className,
}: CardProps) {
  const classes = [
    'card',
    `card--${tone}`,
    glow ? 'card--glow' : '',
    flush ? 'card--flush' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <section className={classes}>
      {(title || action) && (
        <header className="card__header">
          {title ? <h2 className="card__title">{title}</h2> : <span />}
          {action ? <div className="card__action">{action}</div> : null}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}

export default Card;