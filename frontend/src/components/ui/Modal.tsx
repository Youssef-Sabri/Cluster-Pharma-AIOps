import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import './Modal.css';

export interface ModalProps {
  open: boolean;
  title: string;
  /** Optional line under the title. */
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  /** Footer row, usually the action buttons. */
  footer?: ReactNode;
  /** Widens the dialog, for the catalogue picker. */
  wide?: boolean;
}

/**
 * Modal dialog.
 *
 * Closes on Escape and on a click on the backdrop, and moves focus into the
 * dialog when it opens so keyboard users are not left behind on the page
 * underneath. Focus is restored to the trigger on close.
 */
export function Modal({ open, title, subtitle, onClose, children, footer, wide }: ModalProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  /**
   * `onClose` is usually an inline arrow, so its identity changes on every
   * render of the parent. Holding it in a ref keeps the focus effect below
   * keyed on `open` alone — otherwise a background refetch (the review queue
   * polls every 30s) would re-run the effect and pull focus off whatever the
   * user was typing into.
   */
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="modal" role="presentation" onMouseDown={onClose}>
      <div
        className={`modal__panel${wide ? ' modal__panel--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panelRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal__head">
          <div>
            <h2 className="modal__title">{title}</h2>
            {subtitle ? <p className="modal__subtitle">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            className="modal__close"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </header>

        <div className="modal__body">{children}</div>

        {footer ? <footer className="modal__foot">{footer}</footer> : null}
      </div>
    </div>
  );
}

export default Modal;
