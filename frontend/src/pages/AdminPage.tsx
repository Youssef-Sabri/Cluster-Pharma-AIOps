import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card } from '@/components/ui';
import { DriftPanel } from '@/components/admin/DriftPanel';
import { AiPerformancePanel } from '@/components/admin/AiPerformancePanel';
import { InfrastructurePanel } from '@/components/admin/InfrastructurePanel';
import { DeveloperLinks } from '@/components/admin/DeveloperLinks';
import './AdminPage.css';

/** The three tabs inside `/admin`. */
type AdminTab = 'drift' | 'models' | 'health';

interface TabDefinition {
  id: AdminTab;
  label: string;
  blurb: string;
}

const DRIFT_TAB: TabDefinition = {
  id: 'drift',
  label: 'Data Quality & Drift',
  blurb: 'Feature stability scores, distribution inspection, and the retraining pipeline controls.',
};

const MODELS_TAB: TabDefinition = {
  id: 'models',
  label: 'AI Performance & Models',
  blurb: 'Champion lineage, benchmark comparison against a candidate, and the promotion gate.',
};

const HEALTH_TAB: TabDefinition = {
  id: 'health',
  label: 'System Health & Tools',
  blurb: 'Live service reachability, request latency, and the developer tooling links.',
};

const TABS: readonly TabDefinition[] = [DRIFT_TAB, MODELS_TAB, HEALTH_TAB];

function isAdminTab(value: string | null): value is AdminTab {
  return value === 'drift' || value === 'models' || value === 'health';
}

/**
 * Admin console.
 *
 * The single home for technical telemetry. Per the product rules none of this —
 * service ports, model lineage, MAE figures, PSI scores, retraining controls —
 * appears on Home, Inventory, Orders or Approvals.
 *
 * Reachable only from the bottom of the sidebar; deliberately not in the primary
 * business navigation.
 *
 * The active tab lives in the URL (`?tab=models`) rather than in component state,
 * so a tab can be linked to and survives a reload. An unrecognised value falls
 * back to the models tab.
 *
 * ## Why models is the default although it is the second tab
 *
 * Both phase specifications state that `/admin` should open on the AI
 * performance tab — Phase 5 §5 ("defaults cleanly to the AI Performance tab") and
 * Phase 6 §4 step 6 — while the tab order is set by the product brief. Landing
 * on the governance view while presenting the tabs in brief order satisfies
 * both; the drift tab is one click away and fully linkable.
 */
export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = searchParams.get('tab');
  const active: AdminTab = isAdminTab(raw) ? raw : 'models';

  const selectTab = useCallback(
    (tab: AdminTab) => {
      const next = new URLSearchParams(searchParams);
      next.set('tab', tab);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const current = TABS.find((tab) => tab.id === active) ?? MODELS_TAB;

  return (
    <div className="admin">
      <Card tone="accent" title="Admin console">
        <p className="text-sm muted" style={{ maxWidth: '72ch' }}>
          This console collects the technical telemetry for the ClusterOps demo — model quality,
          data drift, retraining and infrastructure. It is kept separate from the business screens so
          day-to-day pharmacy work never mixes with statistical or infrastructure detail.
        </p>
      </Card>

      <div className="admin__tabs" role="tablist" aria-label="Admin console sections">
        {TABS.map((tab) => {
          const selected = tab.id === active;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`admin-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`admin-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              className={`admin__tab${selected ? ' admin__tab--active' : ''}`}
              onClick={() => selectTab(tab.id)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <p className="admin__tab-blurb">{current.blurb}</p>

      <div
        role="tabpanel"
        id={`admin-panel-${active}`}
        aria-labelledby={`admin-tab-${active}`}
        className="admin__panel"
      >
        {active === 'drift' ? (
          <DriftPanel />
        ) : active === 'models' ? (
          <AiPerformancePanel />
        ) : (
          <>
            <InfrastructurePanel />

            <Card title="Developer tooling">
              <DeveloperLinks />
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

export default AdminPage;
