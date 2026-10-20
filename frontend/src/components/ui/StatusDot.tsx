import './StatusDot.css';

export type StatusDotTone = 'online' | 'offline' | 'connecting' | 'degraded';

export interface StatusDotProps {
  tone: StatusDotTone;
  /** Visible text beside the dot. Keep it a word, never a port or a log line. */
  label: string;
  /** Full explanation for assistive tech and the hover tooltip. */
  title?: string;
}

/**
 * Connection indicator.
 *
 * Deliberately a dot plus a word. The product rules forbid surfacing ports,
 * service names or database detail to a pharmacy operations manager, so there is
 * no "FastAPI :8000 · db up" text anywhere in this component.
 */
export function StatusDot({ tone, label, title }: StatusDotProps) {
  return (
    <span className={`status-dot status-dot--${tone}`} role="status" aria-live="polite" title={title}>
      <span className="status-dot__mark" aria-hidden="true" />
      <span className="status-dot__label">{label}</span>
    </span>
  );
}

export default StatusDot;
