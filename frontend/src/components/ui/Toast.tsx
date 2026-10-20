import { useEffect } from 'react';
import { CheckCircle2, AlertTriangle, X } from 'lucide-react';
import './Toast.css';

export type ToastTone = 'success' | 'error' | 'info';

export interface ToastProps {
  open: boolean;
  tone?: ToastTone;
  title: string;
  message?: string;
  onClose: () => void;
  /** Auto-dismiss delay in ms. `0` keeps it until dismissed. */
  durationMs?: number;
}

/**
 * Transient confirmation banner.
 *
 * Used instead of `window.alert` so the operator keeps their place on the page
 * and the confirmation is dismissible. Errors stay until dismissed; successes
 * fade on their own.
 */
export function Toast({
  open,
  tone = 'success',
  title,
  message,
  onClose,
  durationMs = 4200,
}: ToastProps) {
  useEffect(() => {
    if (!open || durationMs <= 0) return;
    const timer = window.setTimeout(onClose, durationMs);
    return () => window.clearTimeout(timer);
  }, [open, durationMs, onClose]);

  if (!open) return null;

  const Icon = tone === 'success' ? CheckCircle2 : AlertTriangle;

  return (
    <div className={`toast toast--${tone}`} role="status" aria-live="polite">
      <Icon size={18} className="toast__icon" aria-hidden="true" />
      <div className="toast__body">
        <p className="toast__title">{title}</p>
        {message ? <p className="toast__message">{message}</p> : null}
      </div>
      <button type="button" className="toast__close" onClick={onClose} aria-label="Dismiss">
        <X size={15} />
      </button>
    </div>
  );
}

export default Toast;
