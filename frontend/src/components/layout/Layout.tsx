import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { usePendingReviewCount } from '@/api/endpoints/reviewQueue';
import './Layout.css';

/**
 * Application shell.
 *
 * Mounted once and reused by every route, so the sidebar and top bar never
 * re-render on navigation. The pending-approval count is fetched here rather
 * than inside `Sidebar` so it is one piece of shared server state; the hook
 * swallows failures, so a broken approvals endpoint degrades to a hidden badge
 * instead of a blank page.
 */
export function Layout() {
  const pendingApprovals = usePendingReviewCount();

  return (
    <div className="layout">
      <Sidebar pendingApprovals={pendingApprovals} />
      <div className="layout__main">
        <TopBar />
        <main className="layout__content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default Layout;
