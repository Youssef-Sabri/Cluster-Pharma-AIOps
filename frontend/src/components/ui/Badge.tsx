import type { ReactNode } from 'react';
import './Badge.css';

export type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'neutral';

export interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  /** Adds a pulsing dot — used for live/DRIFT_DETECTED states. */
  pulse?: boolean;
  size?: 'sm' | 'md';
  /** Native tooltip, used to explain what a terse chip's number means. */
  title?: string;
  className?: string;
}

/** Status chip. Tones are semantic, never decorative. */
export function Badge({
  children,
  tone = 'neutral',
  pulse = false,
  size = 'md',
  title,
  className,
}: BadgeProps) {
  const classes = [
    'badge',
    `badge--${tone}`,
    `badge--${size}`,
    pulse ? 'badge--pulse' : '',
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes} title={title}>
      {pulse ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}



export default Badge;