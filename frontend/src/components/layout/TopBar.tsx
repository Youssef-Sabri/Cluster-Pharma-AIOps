import { Link, useLocation } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { useHealth } from '@/api/endpoints/health';
import { StatusDot, type StatusDotTone } from '@/components/ui/StatusDot';
import { SYNTHETIC_NOTICE } from '@/types/common';
import './TopBar.css';

const ROUTE_TITLES: Record<string, string> = {
  '/': 'Home',
  '/inventory': 'Inventory',
  '/orders/new': 'New Order',
  '/orders': 'Order History',
  '/approvals': 'Approvals',
  '/admin': 'Admin & System',
};

/**
 * Connection state.
 *
 * Four states, expressed as a dot and a single word. "Serving but with no model
 * resident" is a real state — it is what an order submitted now would be
 * rejected by — so it gets its own tone rather than being flattened into green.
 */
function resolveConnection(
  data: { health: { db_connected: boolean; models_loaded: boolean } } | undefined,
  isError: boolean,
): { tone: StatusDotTone; label: string; title: string } {
  if (isError && !data) {
    return {
      tone: 'offline',
      label: 'Disconnected',
      title: 'We cannot reach the Cluster service right now.',
    };
  }
  if (!data) {
    return { tone: 'connecting', label: 'Connecting', title: 'Connecting to the Cluster service.' };
  }

  const { db_connected: dbConnected, models_loaded: modelsLoaded } = data.health;

  if (!dbConnected) {
    return {
      tone: 'degraded',
      label: 'Limited',
      title: 'Some services are unavailable — orders may not be saved right now.',
    };
  }
  if (!modelsLoaded) {
    return {
      tone: 'degraded',
      label: 'Limited',
      title: 'Demand forecasts are unavailable until the service finishes starting up.',
    };
  }
  return { tone: 'online', label: 'Connected', title: 'All services are operating normally.' };
}

export function TopBar() {
  const location = useLocation();
  const { data, isError } = useHealth();
  const connection = resolveConnection(data, isError);
  const title = ROUTE_TITLES[location.pathname] ?? 'ClusterOps';

  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>

      <div className="topbar__actions">
        <StatusDot tone={connection.tone} label={connection.label} title={connection.title} />

        {/*
          The bell deep-links to the approvals queue rather than opening a
          dropdown: in Phase 1 the only thing it could notify about *is* the
          approval queue, so a dead button would be worse than a real link.
        */}
        <Link
          to="/approvals"
          className="topbar__bell"
          aria-label="Go to approvals"
          title="Approvals"
        >
          <Bell size={18} />
        </Link>
      </div>
    </header>
  );
}

export { SYNTHETIC_NOTICE };
export default TopBar;
