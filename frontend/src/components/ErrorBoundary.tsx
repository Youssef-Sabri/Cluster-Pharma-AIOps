/**
 * Global error boundary.
 *
 * Required by the frontend rules: a render failure in one route must degrade to
 * a visible message rather than blanking the whole console. It is a class
 * component because React exposes no hook equivalent.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('ClusterOps render error', error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="layout">
        <div className="layout__main">
          <main className="layout__content">
            <div
              role="alert"
              style={{
                background: 'var(--color-bg-surface)',
                border: '1px solid var(--color-danger-border)',
                borderRadius: 'var(--radius-lg)',
                boxShadow: 'var(--shadow-card)',
                padding: 'var(--space-8)',
              }}
            >
              <div className="row" style={{ color: 'var(--color-danger)', marginBottom: 'var(--space-3)' }}>
                <AlertTriangle size={20} />
                <strong>The dashboard hit an unexpected error</strong>
              </div>
              <p className="muted" style={{ marginBottom: 'var(--space-4)' }}>
                The view could not be rendered. The details below are safe to share — they come
                from the browser console, not from the backend.
              </p>
              <pre className="mono text-xs" style={{ whiteSpace: 'pre-wrap', color: 'var(--color-text-primary)' }}>
                {error.message}
              </pre>
              <button
                type="button"
                className="btn btn--primary btn--md"
                style={{ marginTop: 'var(--space-5)' }}
                onClick={() => this.setState({ error: null })}
              >
                <span className="btn__label">Try again</span>
              </button>
            </div>
          </main>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;