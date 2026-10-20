import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  ClipboardCheck,
  PackageX,
  PlusCircle,
  ShoppingBag,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import { Card } from '@/components/ui';
import { KpiCard, type KpiState } from '@/components/home/KpiCard';
import { usePendingReviewCount } from '@/api/endpoints/reviewQueue';
import { useForecastAccuracy } from '@/api/endpoints/accuracy';
import { useSystemState } from '@/api/endpoints/system';
import { useHealth } from '@/api/endpoints/health';
import { SYNTHETIC_NOTICE } from '@/types/common';
import './HomePage.css';

interface FeedEntry {
  id: string;
  tone: 'neutral' | 'success' | 'warning';
  message: string;
  detail?: string;
  to?: string;
}

/** Time-of-day greeting. */
function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

const round1 = (value: number): number => Math.round(value * 10) / 10;

export function HomePage() {
  const { data: health, isError: healthFailed } = useHealth();
  const { data: system } = useSystemState();
  const pendingApprovals = usePendingReviewCount();
  const accuracy = useForecastAccuracy();

  const allHealthy = healthFailed
    ? false
    : Boolean(health?.health.db_connected && health?.health.models_loaded);

  /*
   * Two of the four commercial KPIs have no data source in the backend yet.
   *
   * - "Today's orders" needs an orders-summary endpoint. Nothing exposes an
   *   order count: `/metrics` has no order counter, and the review queue only
   *   sees flagged lines.
   * - "Low stock alerts" needs inventory data. The schema has no stock,
   *   inventory or on-hand column in any table, so there is nothing to compare
   *   against demand.
   *
   * Both render as "not available" rather than `0`. A zero would be actively
   * dangerous here: an operator seeing "0 low stock alerts" concludes the
   * shelves are fine and does not reorder.
   */
  const ordersState: KpiState = 'unavailable';
  const stockState: KpiState = 'unavailable';

  const feed = useMemo<FeedEntry[]>(() => {
    const entries: FeedEntry[] = [];

    if (pendingApprovals > 0) {
      entries.push({
        id: 'approvals',
        tone: 'warning',
        message: `${pendingApprovals.toLocaleString('en-EG')} order lines need your review`,
        detail: 'Our matching was not confident enough to confirm them automatically.',
        to: '/approvals',
      });
    } else {
      entries.push({
        id: 'approvals-clear',
        tone: 'success',
        message: 'No orders are waiting for review',
        detail: 'Every incoming order line was matched confidently.',
        to: '/approvals',
      });
    }

    if (accuracy.data) {
      entries.push({
        id: 'accuracy',
        tone: 'success',
        message: `Forecasts are ${round1(accuracy.data.improvementPct)}% more accurate than last season`,
        detail: 'Measured against a simple seasonal average.',
      });
    }

    if (system?.catalogue_loaded) {
      entries.push({
        id: 'catalogue',
        tone: 'neutral',
        message: `${system.catalogue_entries} products available to order`,
        detail: 'Your catalogue is loaded and ready for new orders.',
        to: '/inventory',
      });
    }

    entries.push({
      id: 'services',
      tone: healthFailed ? 'warning' : allHealthy ? 'success' : 'warning',
      message: allHealthy ? 'All services are operating normally' : 'Some services need attention',
      detail: healthFailed
        ? 'We are having trouble connecting. Some features may be unavailable.'
        : undefined,
      to: '/admin',
    });

    return entries;
  }, [pendingApprovals, accuracy.data, system, allHealthy, healthFailed]);

  return (
    <div className="home">
      {/* ---------------------------------------------------------------- */}
      {/* Cluster Intelligence Hub Hero Banner                            */}
      {/* ---------------------------------------------------------------- */}
      <section className="home__hero">
        <div className="home__hero-content">
          <div className="home__hero-eyebrow">
            <span className="home__hero-badge">
              <Sparkles size={12} aria-hidden="true" />
              Cluster Intelligence • {greeting()}
            </span>
            <span className="home__hero-date">
              {new Date().toLocaleDateString(undefined, {
                weekday: 'long',
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
            </span>
          </div>

          <h1 className="home__hero-title">
            Digital Pharmacy Operations & AI Demand Hub
          </h1>
          <p className="home__hero-subtitle">
            Automate pharmaceutical procurement, monitor seasonal demand forecasts, and
            resolve unmatched order lines with high-confidence AI matching.
          </p>

          <div className="home__hero-actions">
            <Link to="/orders/new" className="home__hero-btn home__hero-btn--primary">
              <PlusCircle size={15} aria-hidden="true" />
              New Order
            </Link>
            <Link to="/inventory" className="home__hero-btn home__hero-btn--secondary">
              Demand Forecasts
              <ArrowRight size={14} aria-hidden="true" />
            </Link>
            <Link to="/approvals" className="home__hero-btn home__hero-btn--secondary">
              Review Queue
              {pendingApprovals > 0 && (
                <span className="home__hero-badge-count">{pendingApprovals}</span>
              )}
            </Link>
          </div>
        </div>

        <div className="home__hero-aside" title={SYNTHETIC_NOTICE}>
          <div className="home__hero-synthetic-pill">
            <Sparkles size={12} aria-hidden="true" />
            <span>Synthetic Demonstration Mode</span>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* Commercial KPIs                                                  */}
      {/* ---------------------------------------------------------------- */}
      <section className="home__kpis">
        <KpiCard
          label="Today's Orders"
          to="/orders"
          icon={<ShoppingBag size={17} />}
          state={ordersState}
          unavailableReason="Order totals are not connected yet"
        />
        <KpiCard
          label="Low Stock Alerts"
          to="/inventory"
          icon={<PackageX size={17} />}
          state={stockState}
          unavailableReason="Stock levels are not connected yet"
        />
        <KpiCard
          label="Pending Approvals"
          to="/approvals"
          icon={<ClipboardCheck size={17} />}
          state={pendingApprovals > 0 ? 'ready' : 'ready'}
          value={pendingApprovals.toLocaleString('en-EG')}
          hint="Order lines waiting for your confirmation"
        />
        <KpiCard
          label="AI Accuracy"
          to="/admin"
          icon={<TrendingUp size={17} />}
          state={accuracy.isPending ? 'loading' : accuracy.isError ? 'unavailable' : 'ready'}
          value={
            accuracy.data ? `${round1(accuracy.data.accuracyPct)}% accurate` : undefined
          }
          hint={
            accuracy.data
              ? `${round1(accuracy.data.improvementPct)}% better than last season`
              : undefined
          }
          unavailableReason="Accuracy is unavailable right now"
        />
      </section>

      {/* ---------------------------------------------------------------- */}
      {/* Activity                                                          */}
      {/* ---------------------------------------------------------------- */}
      <Card title="Recent activity">
        {feed.length === 0 ? (
          <p className="muted text-sm">Nothing to show yet.</p>
        ) : (
          <ul className="feed">
            {feed.map((entry) => {
              const body = (
                <>
                  <span className={`feed__dot feed__dot--${entry.tone}`} aria-hidden="true" />
                  <span className="feed__body">
                    <span className="feed__message">{entry.message}</span>
                    {entry.detail ? <span className="feed__detail">{entry.detail}</span> : null}
                  </span>
                </>
              );

              return (
                <li key={entry.id} className="feed__item">
                  {entry.to ? (
                    <Link to={entry.to} className="feed__link">
                      {body}
                    </Link>
                  ) : (
                    <span className="feed__link">{body}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <p className="feed__note">
          <Activity size={13} aria-hidden="true" />
          These reflect live service state. A historical order-event log is not connected in this
          build.
        </p>
      </Card>
    </div>
  );
}

export default HomePage;
