import { NavLink } from 'react-router-dom';
import {
  ClipboardCheck,
  Home,
  Package,
  Settings,
  ShoppingCart,
  History,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { SYNTHETIC_NOTICE } from '@/types/common';
import './Sidebar.css';

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  /** Rendered as a live counter on the right of the row. */
  badge?: number;
}

export interface SidebarProps {
  /** Items waiting on a pharmacist. */
  pendingApprovals?: number;
}

/**
 * Primary business navigation.
 *
 * Workflow-shaped, not infrastructure-shaped: a pharmacy operations manager
 * thinks in orders, stock and approvals. Developer tooling (Swagger, MLflow,
 * Grafana, Prometheus) is deliberately absent — per the product rules it lives
 * exclusively behind `/admin`, reachable from the bottom of this rail.
 */
export function Sidebar({ pendingApprovals = 0 }: SidebarProps) {
  const primary: NavItem[] = [
    { to: '/', label: 'Home', icon: <Home size={18} /> },
    { to: '/inventory', label: 'Inventory', icon: <Package size={18} /> },
    { to: '/orders/new', label: 'New Order', icon: <ShoppingCart size={18} /> },
    { to: '/orders', label: 'Order History', icon: <History size={18} /> },
    {
      to: '/approvals',
      label: 'Approvals',
      icon: <ClipboardCheck size={18} />,
      badge: pendingApprovals,
    },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <NavLink to="/" className="sidebar__brand-link" title="Cluster Intelligence Hub">
          <img
            src="/cluster-logo.png"
            alt="Cluster"
            className="sidebar__logo"
          />
        </NavLink>
        <span className="sidebar__brand-badge">Operations</span>
      </div>

      <nav className="sidebar__nav" aria-label="Main">
        {primary.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `sidebar__link${isActive ? ' sidebar__link--active' : ''}`}
          >
            <span className="sidebar__icon">{item.icon}</span>
            <span className="sidebar__label">{item.label}</span>
            {item.badge !== undefined && item.badge > 0 ? (
              <span
                className="sidebar__badge"
                title={`${item.badge.toLocaleString('en-EG')} order ${
                  item.badge === 1 ? 'line' : 'lines'
                } awaiting review`}
              >
                {/*
                  The exact count, not a rounded "99+".

                  This badge is the pharmacist's work-queue size, and the demo
                  backlog runs to several thousand lines. Capping it at 99 left
                  the badge reading "99+" permanently, so working through the
                  queue produced no visible progress anywhere in the shell. The
                  pill is sized for it and the numbers use tabular figures.
                */}
                {item.badge > 9999 ? '9999+' : item.badge.toLocaleString('en-EG')}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      {/* Divider, then system administration — kept visually separate so the
          business workflow above is never confused with tooling. */}
      <div className="sidebar__spacer" />

      <nav className="sidebar__nav" aria-label="System">
        <NavLink
          to="/admin"
          className={({ isActive }) => `sidebar__link sidebar__link--admin${isActive ? ' sidebar__link--active' : ''}`}
        >
          <span className="sidebar__icon">
            <Settings size={18} />
          </span>
          <span className="sidebar__label">Admin &amp; System</span>
        </NavLink>
      </nav>

      <footer className="sidebar__footer">{SYNTHETIC_NOTICE}</footer>
    </aside>
  );
}

export default Sidebar;
