# Phase 4: Admin Console — Data Quality, Statistical Drift & Retraining Ops

> **Objective**: Build the Data Quality & Retraining tab inside the Admin page (`/admin`) — providing ML engineers and system administrators with real-time Population Stability Index (PSI) tracking, baseline vs. inference distribution shifts, and automated retraining pipeline controls. Normal pharmacy operators never see this tab; all technical complexity is safely encapsulated in the Admin console.

---

## 1. Deliverables

- [x] **TypeScript Contracts** (`src/types/drift.ts`):
  - `DriftStatus` enum: `'OK'` | `'WARNING'` | `'DRIFT_DETECTED'`.
  - `DriftFeatureItem`: `{ feature_name: string; psi_score: number; status: string; baseline_mean: number; current_mean: number }`.
  - `DriftStatusResponse`: `{ checked_at: string; overall_status: DriftStatus; max_psi: number; psi_threshold: number; features: DriftFeatureItem[]; retraining_triggered: boolean; evaluated: boolean }`.
  - `RetrainResponse`: `{ flow_run_id: string; status: string; message: string; estimated_duration_seconds: number }`.
- [x] **Data Quality Tab Component** (`src/components/admin/DriftPanel.tsx`):
  - Embeds inside `AdminPage.tsx` under the **"Data Quality & Drift"** tab.
  - Status banner summarizing overall feature health and last evaluation timestamp.
  - Grid layout housing the PSI Drift Matrix, Distribution Shift Inspector, and Retraining Pipeline controls.
- [x] **Feature PSI Matrix Chart** (`src/components/admin/DriftMatrixChart.tsx`):
  - Horizontal Recharts `<BarChart>` displaying PSI per feature.
  - Styled for Cluster Light Theme (clean white cards, `#eaedf3` gridlines, `#1c1b2e` text).
  - Amber reference line at $\text{PSI} = 0.10$ (Early Warning).
  - Red dashed reference line at $\text{PSI} = 0.20$ (Critical Drift Alert Threshold).
  - Dynamic bar coloring:
    - 🟢 Green (`--color-success`): $\text{PSI} < 0.10$ (Healthy)
    - 🟡 Amber (`--color-warning`): $0.10 \le \text{PSI} < 0.20$ (Moderate Shift)
    - 🔴 Red (`--color-danger`): $\text{PSI} \ge 0.20$ (Action Required)
- [x] **Distribution Shift Inspector** (`src/components/admin/DistributionOverlay.tsx`):
  - Interactive binned frequency histogram comparing **Baseline Training Distribution** (blue) vs. **Current 30-Day Inference Window** (amber/purple).
  - Feature selector dropdown to isolate shifts in order volume, lead times, or seasonal demand spikes.
- [x] **Autonomous Retraining Pipeline Stepper** (`src/components/admin/RetrainingStepper.tsx`):
  - Visual DAG pipeline execution stepper tracking the 5 phases of the Prefect workflow:
    $$\text{Data Ingestion} \longrightarrow \text{Feature Pipeline} \longrightarrow \text{LightGBM Fit} \longrightarrow \text{3\% Gate Evaluation} \longrightarrow \text{MLflow Promotion}$$
  - Real-time status indicators (Pending, Running, Succeeded, Failed).
  - Prominent **"Trigger Retraining Flow"** button calling `POST /api/v1/retrain`.
- [x] **Synthetic Demand Shock Simulator** (`src/components/admin/DemandShockSimulator.tsx`):
  - Admin testing tool allowing operators to simulate synthetic demand shifts (+35% flu surge, +50% holiday rush) to demonstrate drift threshold alerts.

---

## 2. Key UX Decisions

### Where this lives:
- **Exclusively inside `/admin`** under the "Data Quality & Drift" tab.
- Accessible only via the Admin link in the sidebar or direct URL `/admin`.

### What normal users see elsewhere:
- On **Home (`/`)**: A calm "AI Accuracy: 96.5%" metric. No PSI scores, no drift alarms.
- On **Inventory (`/inventory`)**: Accurate demand forecasts.
- Normal users are never exposed to statistical jargon (PSI, distributions, LightGBM, Prefect DAGs).

---

## 3. Technical Specifications

### 3.1 Feature Drift Bar Chart (`src/components/admin/DriftMatrixChart.tsx`)

```tsx
import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell
} from 'recharts';
import { DriftFeatureItem } from '../../types/drift';

interface DriftMatrixProps {
  features: DriftFeatureItem[];
  threshold?: number;
}

export const DriftMatrixChart: React.FC<DriftMatrixProps> = ({ features, threshold = 0.20 }) => {
  const getBarColor = (psi: number) => {
    if (psi >= threshold) return 'var(--color-danger)';
    if (psi >= 0.10) return 'var(--color-warning)';
    return 'var(--color-success)';
  };

  return (
    <div style={{ width: '100%', height: 320 }}>
      <ResponsiveContainer>
        <BarChart
          layout="vertical"
          data={features}
          margin={{ top: 12, right: 32, left: 120, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-bg-border)" horizontal={false} />
          <XAxis type="number" domain={[0, 0.4]} stroke="var(--color-text-secondary)" tickLine={false} />
          <YAxis dataKey="feature_name" type="category" stroke="var(--color-text-primary)" tickLine={false} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-bg-surface)',
              borderColor: 'var(--color-bg-border)',
              borderRadius: '8px',
              color: 'var(--color-text-primary)',
              boxShadow: 'var(--shadow-card)'
            }}
            formatter={(val: number) => [`${val.toFixed(4)} PSI`, 'Stability Index']}
          />
          <ReferenceLine
            x={0.10}
            stroke="#f59e0b"
            strokeDasharray="3 3"
            label={{ value: 'Warning (0.10)', fill: '#f59e0b', position: 'top', fontSize: 11 }}
          />
          <ReferenceLine
            x={threshold}
            stroke="#ef4444"
            strokeDasharray="4 4"
            label={{ value: `Alert Threshold (${threshold})`, fill: '#ef4444', position: 'top', fontSize: 11 }}
          />
          <Bar dataKey="psi_score" radius={[0, 6, 6, 0]}>
            {features.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={getBarColor(entry.psi_score)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};
```

### 3.2 Retraining Pipeline Stepper (`src/components/admin/RetrainingStepper.tsx`)

The retraining tracker provides visual status feedback for each stage of the Prefect flow:
1. **Data Ingestion**: Reading latest 180-day order panel from PostgreSQL.
2. **Feature Engineering**: Computing lags (`lag_1`, `lag_7`, `lag_14`) and rolling aggregations.
3. **Model Training**: Fitting 3 LightGBM quantile boosters (`q10`, `q50`, `q90`).
4. **Promotion Gate**: Evaluating if $\text{MAE}_{\text{challenger}} < 0.97 \times \text{MAE}_{\text{production}}$.
5. **MLflow Registry**: Transitioning model stage to `Production` or `Archived`.

---

## 4. Step-by-Step Implementation Instructions

1. **Implement API Endpoints**:
   - `src/api/endpoints/drift.ts`: Query `useDriftStatus` with 30s auto-refresh against `GET /api/v1/drift-status`.
   - `src/api/endpoints/retrain.ts`: Mutation `useRetrainMutation` calling `POST /api/v1/retrain`.
2. **Build Data Quality Components**:
   - `DriftMatrixChart.tsx` with light-theme Recharts styling.
   - `DistributionOverlay.tsx` displaying baseline vs. inference histograms.
   - `RetrainingStepper.tsx` with 5 pipeline stage chips and live status badges.
   - `DemandShockSimulator.tsx` for synthetic drift demonstration.
3. **Assemble DriftPanel in Admin**:
   - Mount `DriftPanel.tsx` inside `AdminPage.tsx` under the Data Quality tab.
   - Verify seamless tab switching between AI Performance, Data Quality, and System Health.

---

## 5. Verification & Acceptance Criteria

- `GET /api/v1/drift-status` response populates the PSI matrix with feature scores.
- Reference lines at $0.10$ and $0.20$ render cleanly in light mode with no contrast issues.
- Clicking "Trigger Retraining Flow" sends `POST /api/v1/retrain`, returns HTTP 202 Accepted with a flow run tracking ID, and animates the stepper.
- Entire view is contained within `/admin` and completely hidden from the main operational workflow.
