import './LoadingSpinner.css';

export interface LoadingSpinnerProps {
  /** Diameter in pixels. */
  size?: number;
  /** Accessible label; pass an empty string for purely decorative spinners. */
  label?: string;
}

/**
 * Brand-coloured spinner.
 *
 * Drawn as inline SVG rather than a CSS border so it inherits
 * `--color-primary` and scales cleanly at any size.
 */
export function LoadingSpinner({ size = 28, label = 'Loading' }: LoadingSpinnerProps) {
  return (
    <span className="spinner" role="status" aria-live="polite">
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.18" strokeWidth="2.5" />
        <path
          d="M21 12a9 9 0 0 0-9-9"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span className="visually-hidden">{label}</span> : null}
    </span>
  );
}

export default LoadingSpinner;