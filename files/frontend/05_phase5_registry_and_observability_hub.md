# Phase 5: Admin Console — Model Governance, Telemetry & Developer Tools

> **Objective**: Build the Model Governance and System Telemetry panels inside the Admin page (`/admin`) — providing ML engineers and operations administrators with model lineage, Champion vs. Challenger benchmarking with mathematical 3% promotion gate proof, system SLA metrics, and direct launch links to backend developer tools (Swagger, MLflow, Prometheus, Grafana). All infrastructure endpoints and raw model metrics are safely isolated inside the Admin console.

---

## 1. Deliverables

- [x] **TypeScript Contracts** (`src/types/registry.ts` & `src/types/system.ts`):
  - `ModelMetrics`: `{ mae: number; rmse: number; mape: number; vs_naive_baseline_improvement_pct: number; p95_latency_ms: number }`.
  - `ModelMetadataItem`: `{ version: string; name: string; stage: string; registered_at: string; run_id: string; metrics: ModelMetrics; promotion_reason?: string }`.
  - `ModelRegistryResponse`: `{ models: ModelMetadataItem[]; production_version: string; model_name: string; reachable: boolean }`.
  - `TelemetryMetrics`: `{ p50_latency_ms: number; p95_latency_ms: number; p99_latency_ms: number; request_rate: number; error_rate: number }`.
- [x] **AI Performance & Governance Panel** (`src/components/admin/AiPerformancePanel.tsx`):
  - **Active Champion Overview**: Current production model version, registration date, out-of-sample MAE, and baseline gain percentage.
  - **Champion vs. Challenger Arena** (`src/components/admin/ModelComparisonTable.tsx`): Side-by-side metric comparison table showing MAE, RMSE, and P95 latency deltas.
  - **Mathematical 3% Promotion Gate Proof** (`src/components/admin/PromotionGateProof.tsx`): Clear visual formula display demonstrating compliance with the 3% promotion rule:
    $$\text{Improvement} = \frac{\text{MAE}_{\text{prod}} - \text{MAE}_{\text{chal}}}{\text{MAE}_{\text{prod}}} \ge 3.0\%$$
    Displays green "Promotion Approved" or red "Gate Rejected" based on real calculations.
- [x] **Infrastructure & System Health Panel** (`src/components/admin/InfrastructurePanel.tsx`):
  - Live service status cards for the 5 core stack components:
    1. **FastAPI Gateway** (Port 8000) — Uptime, latency, health endpoint status.
    2. **PostgreSQL Database** (Port 5432) — Connection pool and table health.
    3. **MLflow Tracking Server** (Port 5000) — Artifact store and active experiment status.
    4. **Prometheus Telemetry** (Port 9090) — Metrics ingestion rate.
    5. **Grafana Dashboards** (Port 3001) — Operational visualization service status.
  - Latency percentiles visualization (P50 / P95 / P99) with a 500ms red SLA ceiling reference line.
- [x] **Developer Tools Launchpad** (`src/components/admin/DeveloperLinks.tsx`):
  - Quick-launch cards with outbound links to external developer tools (opening in separate tabs):
    - 📘 **Swagger REST API Docs** (`http://localhost:8000/docs`)
    - 🧪 **MLflow Tracking & Registry UI** (`http://localhost:5000`)
    - 📊 **Grafana Executive Dashboards** (`http://localhost:3001`)
    - 📈 **Prometheus Telemetry Explorer** (`http://localhost:9090`)
  - Explicit developer notice explaining these are infrastructure tools for backend engineers.

---

## 2. Key UX Decisions

### Complete Separation of Concerns:
- **No developer links in the main sidebar**: Normal users only see Home, Inventory, New Order, Order History, Approvals, and Admin.
- **Admin-only visibility**: Champion/Challenger comparisons, MAE numbers, mathematical gate proofs, and port numbers are only visible when an operator explicitly opens `/admin`.
- **Pure Cluster light theme**: All panels and charts use `#ffffff` cards with subtle `#61698c12` elevation, electric blue `#0f6eff` highlights, and `#eaedf3` borders. No dark mode.

---

## 3. Technical Specifications

### 3.1 Mathematical Promotion Gate Proof Component (`src/components/admin/PromotionGateProof.tsx`)

```tsx
import React from 'react';
import { CheckCircle2, ShieldAlert } from 'lucide-react';

interface GateProofProps {
  prodMae: number;
  challengerMae: number;
}

export const PromotionGateProof: React.FC<GateProofProps> = ({ prodMae, challengerMae }) => {
  const delta = prodMae - challengerMae;
  const improvementPct = (delta / prodMae) * 100;
  const qualifies = improvementPct >= 3.0;

  return (
    <div className="card" style={{ padding: 'var(--space-4)', border: '1px solid var(--color-bg-border)' }}>
      <div className="row-between" style={{ marginBottom: 'var(--space-3)' }}>
        <span className="text-sm font-semibold" style={{ textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-text-secondary)' }}>
          Strict Promotion Gate (3% Rule)
        </span>
        {qualifies ? (
          <span className="badge badge--success text-xs">
            <CheckCircle2 size={12} style={{ marginRight: 4 }} /> PROMOTION APPROVED (+{improvementPct.toFixed(1)}%)
          </span>
        ) : (
          <span className="badge badge--danger text-xs">
            <ShieldAlert size={12} style={{ marginRight: 4 }} /> GATE REJECTED ({improvementPct.toFixed(1)}% &lt; 3.0%)
          </span>
        )}
      </div>

      <div style={{ backgroundColor: 'var(--color-bg-elevated)', padding: 'var(--space-3)', borderRadius: 'var(--radius-sm)', fontFamily: 'monospace', fontSize: '0.85rem' }}>
        Improvement = (MAE_prod - MAE_chal) / MAE_prod = ({prodMae.toFixed(2)} - {challengerMae.toFixed(2)}) / {prodMae.toFixed(2)} = <strong>{improvementPct.toFixed(2)}%</strong>
      </div>
      <p className="text-xs" style={{ marginTop: 'var(--space-2)', color: 'var(--color-text-secondary)' }}>
        Under ClusterOps automated safety rules, a challenger model cannot replace production unless out-of-sample error is strictly reduced by at least 3.0%.
      </p>
    </div>
  );
};
```

### 3.2 Developer Tools Launchpad (`src/components/admin/DeveloperLinks.tsx`)

```tsx
import React from 'react';
import { ExternalLink, Database, Activity, FileCode, Layers } from 'lucide-react';

export const DeveloperLinks: React.FC = () => {
  const tools = [
    { name: 'FastAPI Interactive Docs', desc: 'Swagger UI for exploring and testing API endpoints', port: '8000', url: 'http://localhost:8000/docs', icon: FileCode },
    { name: 'MLflow Tracking Server', desc: 'Experiment runs, parameters, metrics and model registry', port: '5000', url: 'http://localhost:5000', icon: Layers },
    { name: 'Grafana Dashboards', desc: 'Real-time operational metrics and system telemetry', port: '3001', url: 'http://localhost:3001', icon: Activity },
    { name: 'Prometheus Server', desc: 'Raw time-series metrics queries and target health', port: '9090', url: 'http://localhost:9090', icon: Database },
  ];

  return (
    <div className="card" style={{ padding: 'var(--space-4)' }}>
      <h3 className="text-md font-semibold" style={{ marginBottom: 'var(--space-3)' }}>
        Developer & Infrastructure Tools
      </h3>
      <p className="text-sm" style={{ color: 'var(--color-text-secondary)', marginBottom: 'var(--space-4)' }}>
        These links open external infrastructure monitoring and debugging dashboards in a new tab. Intended for developers and system operators.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--space-3)' }}>
        {tools.map((tool) => {
          const Icon = tool.icon;
          return (
            <a
              key={tool.name}
              href={tool.url}
              target="_blank"
              rel="noopener noreferrer"
              className="card card--hover"
              style={{
                padding: 'var(--space-3)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--space-3)',
                textDecoration: 'none',
                color: 'inherit',
                border: '1px solid var(--color-bg-border)'
              }}
            >
              <div style={{ padding: '8px', borderRadius: '8px', backgroundColor: 'var(--color-primary-tint)', color: 'var(--color-primary)' }}>
                <Icon size={20} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span className="font-semibold text-sm">{tool.name}</span>
                  <ExternalLink size={14} style={{ color: 'var(--color-text-secondary)' }} />
                </div>
                <div className="text-xs" style={{ color: 'var(--color-text-secondary)', marginTop: '2px' }}>
                  {tool.desc}
                </div>
                <span className="badge text-xs" style={{ marginTop: '6px', display: 'inline-block' }}>
                  Port :{tool.port}
                </span>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
};
```

---

## 4. Step-by-Step Implementation Instructions

1. **Implement API Hooks**:
   - `src/api/endpoints/registry.ts`: Query `useModelRegistry` fetching versions from `/api/v1/model-registry`.
   - `src/api/endpoints/health.ts`: Fetch live health and system latency metrics.
2. **Build Admin Panels**:
   - Create `AiPerformancePanel.tsx` with champion card, model comparison table, and mathematical promotion proof.
   - Create `InfrastructurePanel.tsx` with service cards and latency percentile charts.
   - Create `DeveloperLinks.tsx` with external tool cards.
3. **Integrate into Admin Page (`AdminPage.tsx`)**:
   - Tab 1: **AI Performance & Governance** (`AiPerformancePanel`)
   - Tab 2: **Data Quality & Drift** (`DriftPanel` from Phase 4)
   - Tab 3: **Infrastructure & System Health** (`InfrastructurePanel` + `DeveloperLinks`)

---

## 5. Verification & Acceptance Criteria

- Navigating to `/admin` defaults cleanly to the AI Performance tab.
- Active production version 1 renders with MAE `2.2758 units` and registration metadata.
- Promotion gate calculation dynamically computes the MAE reduction percentage and shows correct approval/rejection badge.
- Infrastructure panel displays live connection status for backend and database.
- Developer links cleanly open Swagger UI (`:8000/docs`), MLflow (`:5000`), Grafana (`:3001`), and Prometheus (`:9090`) in separate browser tabs.
