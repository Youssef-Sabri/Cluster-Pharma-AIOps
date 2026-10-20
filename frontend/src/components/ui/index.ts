/**
 * Barrel for the UI primitives.
 *
 * Components import from `@/components/ui` rather than reaching into
 * individual files, so a primitive can be split or renamed without touching
 * every call site.
 */

export { Card, default as CardDefault } from './Card';
export type { CardProps, CardTone } from './Card';

export { Badge } from './Badge';
export type { BadgeProps, BadgeTone } from './Badge';

export { Button } from './Button';
export type { ButtonProps, ButtonVariant, ButtonSize } from './Button';

export { MetricCard } from './MetricCard';
export type { MetricCardProps, MetricTone, MetricTrend } from './MetricCard';

export { LoadingSpinner } from './LoadingSpinner';
export type { LoadingSpinnerProps } from './LoadingSpinner';

export { Modal } from './Modal';
export type { ModalProps } from './Modal';

export { Toast } from './Toast';
export type { ToastProps, ToastTone } from './Toast';

export { StatusDot } from './StatusDot';
export type { StatusDotProps, StatusDotTone } from './StatusDot';
