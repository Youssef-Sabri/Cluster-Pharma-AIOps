# ClusterOps — B2B Pharmaceutical SaaS Product Frontend

> **Target**: A polished, commercial-grade B2B SaaS platform for Egyptian pharmacy chain operations — inventory planning, AI-powered order processing, and supplier procurement — built with React 18, Vite 5, TypeScript, Recharts, and Vanilla CSS Design Tokens.
> **Identity**: Clean medical-grade white surfaces (`#ffffff`), soft slate canvas (`#f6f9fc`), and electric-blue (`#0f6eff`) UI matching Cluster's commercial brand (`clusterapp.net`). Strictly light theme, no dark mode.
> **UX Philosophy**: The user is a pharmacy operations manager, not an ML engineer. AI predictions, model versions, drift scores, and infrastructure details are **invisible** — the user sees business outcomes: stock levels, orders, approvals, and procurement totals in EGP. All technical telemetry lives behind a discrete "Admin & System" settings page.

---

## 1. Technology Stack

| Concern | Technology | Rationale |
|---|---|---|
| **Framework** | **React 18 + Vite 5** | Concurrent rendering, sub-second HMR. |
| **Language** | **Strict TypeScript (5.5+)** | Zero `any`, full backend contract parity. |
| **Routing** | **React Router v6** | SPA client-side routing with persistent shell. |
| **Server State** | **TanStack React Query v5** | Declarative caching, background re-validation. |
| **Charts** | **Recharts (2.12+)** | Composable SVG visualizations for demand trends and stock gauges. |
| **Design Tokens** | **Pure Vanilla CSS Custom Properties** | No Tailwind. Full control over the Cluster brand system. |
| **Icons & Typography** | **Lucide React + Poppins** | Clean iconography and Google Fonts Poppins. |
| **Production** | **Docker + Nginx Alpine** | Multi-stage container, reverse proxy, SPA fallback. |

---

## 2. Design System (from `clusterapp.net`)

```css
:root {
  /* === BRAND PALETTE === */
  --color-primary:        #0f6eff;   /* Electric blue — buttons, active states, links */
  --color-primary-dark:   #0E4DA4;   /* Deep brand blue — logo, accents */
  --color-primary-hover:  #2095f3;   /* Hover state */
  --color-primary-tint:   #edf4ff;   /* Soft fill for active nav items and selected cards */

  /* === SURFACES === */
  --color-bg-base:        #f6f9fc;   /* Page background */
  --color-bg-surface:     #ffffff;   /* Cards, sidebar, header */
  --color-bg-elevated:    #f8fafc;   /* Table rows, inputs */
  --color-bg-border:      #eaedf3;   /* Borders and dividers */

  /* === TYPOGRAPHY === */
  --color-text-primary:   #1c1b2e;   /* Headings and key values */
  --color-text-secondary: #6d859e;   /* Body text and labels */
  --color-text-tertiary:  #94a3b8;   /* Captions and timestamps */

  /* === STATUS COLORS (business meaning, not technical) === */
  --color-success:        #10b981;   /* In Stock, Confirmed, Approved */
  --color-warning:        #f59e0b;   /* Low Stock, Needs Attention, Please Verify */
  --color-danger:         #ef4444;   /* Critical Stockout, Rejected, Urgent */
  --color-info:           #06b6d4;   /* Informational highlights */

  /* === CHART COLORS === */
  --color-chart-forecast: #0f6eff;   /* Expected demand line */
  --color-chart-range:    rgba(15, 110, 255, 0.12); /* Demand range shading */
  --color-chart-grid:     #eaedf3;   /* Gridlines */

  /* === ELEVATION === */
  --shadow-card:          0 4px 20px rgba(97, 105, 140, 0.07);
  --shadow-hover:         0 8px 30px rgba(97, 105, 140, 0.12);
  --radius-md:            10px;
  --radius-lg:            14px;
  --radius-pill:          9999px;
}
```

---

## 3. Information Architecture & Navigation

The sidebar is structured around **business workflows**, not backend endpoints:

```
┌─────────────────────────────────────────────────┐
│  🔵 Cluster                                      │
│     Pharmacy Operations                          │
├─────────────────────────────────────────────────┤
│  📊  Home                          /             │
│  📦  Inventory & Forecasting       /inventory    │
│  🛒  New Order                     /orders/new   │
│  📋  Order History                 /orders       │
│  ✅  Approvals                     /approvals    │
├─────────────────────────────────────────────────┤
│  ⚙️  Admin & System               /admin        │
│      (AI performance, drift,                     │
│       model registry, system health)             │
└─────────────────────────────────────────────────┘
```

### Route-to-Backend Mapping (invisible to user)

| User-Facing Route | What the User Sees | Backend API Used |
|---|---|---|
| `/` Home | Welcome, KPI cards, activity feed | `GET /health`, `GET /api/v1/drift-status`, `GET /api/v1/model-registry`, `GET /api/v1/orders/review-queue` |
| `/inventory` Inventory | Product catalog with stock status, demand charts, reorder buttons | `POST /api/v1/forecast` |
| `/orders/new` New Order | Chat-style order input, instant invoice generation | `POST /api/v1/match-order` |
| `/orders` History | Table of past orders with status badges | `GET /api/v1/orders/review-queue` |
| `/approvals` Approvals | Items flagged for pharmacist verification | `GET /api/v1/orders/review-queue`, `PATCH /api/v1/orders/review-queue/{id}` |
| `/admin` Admin & System | AI model performance, drift charts, infrastructure health, Swagger/MLflow/Grafana links | `GET /api/v1/drift-status`, `GET /api/v1/model-registry`, `POST /api/v1/retrain`, `GET /health` |

---

## 4. Page Specifications

### 4.1 Home (`/`)

A warm, at-a-glance overview — not a technical dashboard.

- **Welcome Banner**: "Good afternoon" with the current date and environment label (*ClusterOps Demo — Synthetic Data*).
- **4 Summary Cards** (large, prominent, business-language):
  1. **Today's Orders**: Count of orders processed today. Icon: 🛒. Link → `/orders`.
  2. **Low Stock Alerts**: Count of products with < 3 days of inventory. Icon: ⚠️. Link → `/inventory` (filtered to critical).
  3. **Pending Approvals**: Items requiring pharmacist verification. Icon: ✅. Link → `/approvals`.
  4. **AI Accuracy**: Expressed as a percentage (e.g., "96.5% accurate") — computed from MAE but displayed in human terms. Icon: 🎯.
- **Recent Activity Feed**: Chronological list of recent events in plain language:
  - "Order #1042 from PH-001 processed — 5 items matched"
  - "Panadol Extra restocked ✓"
  - "2 items from Order #1038 need your review"
  - "Congestal running low — reorder suggested"

---

### 4.2 Inventory & Forecasting (`/inventory`)

A product catalog with built-in demand intelligence — the AI is invisible.

- **Product Catalog Table**:
  | Column | Description |
  |---|---|
  | **Drug Name** | e.g. "Panadol Extra 500mg" |
  | **Category** | Analgesic, Antibiotic, etc. |
  | **Current Stock** | Units on hand (synthetic) |
  | **7-Day Forecast** | "Expected demand: ~120 units" (plain language, no "q50") |
  | **Stock Status** | 🟢 Adequate (> 7 days) / 🟡 Low (3–7 days) / 🔴 Critical (< 3 days) |
  | **Action** | "View Details" or "Reorder" button |

- **Product Detail View** (expandable row or slide-out panel):
  - **Simple Demand Chart**: Clean area chart showing "Expected demand" as a blue line with a soft shaded "possible range" band. NO labels like "q10/q50/q90" — just "Expected" and "Range".
  - **Reorder Recommendation Card**:
    - "We recommend ordering **140 units** to cover the next 7 days with safety margin."
    - "Estimated cost: **4,200 EGP**"
    - Big blue **"Add to Purchase Order"** button.
  - **What-If Scenarios** (toggle buttons, not sliders):
    - "Normal demand" (default)
    - "Flu season (+35%)"
    - "Supply delay (+50% buffer)"
    Switching recalculates the recommendation instantly.

- **Purchase Order Summary** (bottom panel or separate tab):
  - Aggregated table of all items added to the purchase order: Drug, Quantity, Est. Unit Price, Est. Total (EGP).
  - **"Export Purchase Order"** button (generates downloadable summary).

---

### 4.3 New Order (`/orders/new`)

A friendly, chat-like order entry — like messaging a smart assistant.

- **Order Input Area**:
  - Large text area with placeholder: *"Type or paste a pharmacy order in Arabic or English..."*
  - Quick preset buttons for demo scenarios:
    - "Clean English order"
    - "Arabic order"
    - "Messy handwriting style"
    - "Mixed Arabic-English"
  - Blue **"Process Order"** button.

- **Order Result — Digital Invoice** (appears after processing):
  - Clean invoice-style table:
    | # | Item | Qty | Unit Price | Total | Status |
    |---|---|---|---|---|---|
    | 1 | Panadol Extra 500mg | 10 | 12.50 EGP | 125.00 EGP | ✅ Matched |
    | 2 | Augmentin 625mg | 5 | 45.00 EGP | 225.00 EGP | ✅ Matched |
    | 3 | "catflam 50" | 2 | — | — | 🟡 Please verify |
  - Items the AI wasn't confident about show a yellow "Please verify" badge with a dropdown to pick the correct drug.
  - **Order Total** at the bottom.
  - **"Confirm & Submit Order"** button (green, prominent).

- **NO visible technical details**: No "RapidFuzz vs Gemini" badges, no "confidence: 0.73", no "Stage 1 / Stage 2". The user just sees ✅ Matched or 🟡 Please verify.

---

### 4.4 Order History (`/orders`)

Simple chronological record of all processed orders.

- **Orders Table**:
  | Date | Order # | Pharmacy | Items | Total (EGP) | Status |
  |---|---|---|---|---|---|
  | Oct 18, 2026 | #1042 | PH-001 El-Ezaby | 5 items | 1,250 EGP | ✅ Completed |
  | Oct 18, 2026 | #1041 | PH-003 19011 | 3 items | 680 EGP | 🟡 1 pending review |
  | Oct 17, 2026 | #1040 | PH-012 Seif | 8 items | 2,100 EGP | ✅ Completed |

- Click any row → order detail view showing the full invoice breakdown.
- Filter by pharmacy, date range, or status.

---

### 4.5 Approvals (`/approvals`)

A focused pharmacist verification screen — fast, keyboard-friendly, zero clutter.

- **Pending Items Counter**: "3 items need your review"
- **Approval Cards** (one per item):
  - **What was ordered**: Raw text from the customer (e.g., *"catflam 50"*)
  - **AI's suggestion**: "Cataflam 50mg — Diclofenac Potassium" with a subtle confidence indicator (just a colored dot: 🟢🟡🔴, no percentage shown).
  - **3 Action Buttons**:
    - ✅ **Approve** — confirms the AI's suggestion.
    - ✏️ **Correct** — opens a search dropdown to pick the right drug.
    - ❌ **Reject** — removes the item.
  - **Keyboard Shortcuts**: `A` (Approve), `C` (Correct), `D` (Reject), `↑/↓` (Navigate).
- **Approval History** tab: Log of past decisions for audit trail.

---

### 4.6 Admin & System (`/admin`)

**This is the ONLY place where technical/ML details appear.** It is designed for power users and developers, not daily operators.

Organized as tabs or an accordion:

- **AI Performance**:
  - Forecast accuracy metrics (MAE, displayed honestly).
  - Model version and training date.
  - Champion vs. Challenger comparison table with the 3% promotion gate formula.
- **Data Quality & Drift**:
  - PSI feature drift matrix with reference lines at 0.10 and 0.20.
  - Distribution overlay (baseline vs. current).
  - "Trigger Retraining" button.
- **Infrastructure Health**:
  - Service status grid: FastAPI, PostgreSQL, MLflow, Prometheus, Grafana — with ports, uptime, and latency.
- **Developer Tools**:
  - Links to Swagger UI, MLflow UI, Grafana dashboards, Prometheus console.
  - These links are **only here**, never in the main navigation.

---

## 5. Frontend Engineering Rules

1. **Product-First UX**: The user is a pharmacy manager, not an engineer. Never show raw model metrics, PSI scores, confidence decimals, or infrastructure ports in user-facing screens. Translate everything into business language.
2. **Cluster Brand Fidelity**: Strictly follow `clusterapp.net` light theme. No dark mode.
3. **Vanilla CSS Design Tokens Only**: Zero Tailwind. All styling through `src/index.css` custom properties.
4. **Strict TypeScript**: No `any`. All API responses typed in `src/types/`.
5. **Business-Language Status Colors**:
   - 🟢 Green: In Stock, Confirmed, Approved.
   - 🟡 Amber: Low Stock, Please Verify, Needs Attention.
   - 🔴 Red: Critical Stockout, Rejected, Urgent.
6. **Graceful Degradation**: If backend is down, show friendly messages ("We're having trouble connecting — please try again in a moment"), never raw error codes.
7. **Synthetic Data Notice**: Small footer badge on every page: *"ClusterOps Demo — Synthetic Egyptian Pharmaceutical Data"*.

---

## 6. Component Architecture

```
frontend/src/
├── api/
│   ├── axios.ts                       # Base client, error normalizer
│   └── endpoints/
│       ├── accuracy.ts                # Model accuracy queries
│       ├── drift.ts                   # Admin: drift status query
│       ├── forecast.ts                # Inventory demand queries
│       ├── health.ts                  # System health probe
│       ├── infrastructure.ts          # Probe matrix builder
│       ├── matchOrder.ts              # Order processing mutations
│       ├── registry.ts                # Admin: model registry & governance
│       ├── retrain.ts                 # Admin: autonomous retrain mutation
│       ├── reviewQueue.ts             # Approval queue queries & patches
│       └── telemetry.ts               # Prometheus request-latency metrics
├── components/
│   ├── admin/
│   │   ├── AiPerformancePanel.tsx     # Active champion card & governance
│   │   ├── DemandShockSimulator.tsx   # Synthetic demand shock demo tool
│   │   ├── DeveloperLinks.tsx         # Swagger, MLflow, Grafana, Prometheus
│   │   ├── DistributionOverlay.tsx    # Baseline vs current distribution shift
│   │   ├── DriftMatrixChart.tsx       # Recharts horizontal PSI bar chart
│   │   ├── DriftPanel.tsx             # Data quality & drift tab layout
│   │   ├── InfrastructurePanel.tsx    # Telemetry percentiles & SLA ceiling
│   │   ├── InfraHealth.tsx            # Multi-service connection matrix
│   │   ├── ModelComparisonTable.tsx   # Champion vs Challenger metrics arena
│   │   ├── PromotionGateProof.tsx     # Mathematical 3% gate rule proof
│   │   └── RetrainingStepper.tsx      # 5-stage Prefect DAG stepper
│   ├── approvals/
│   │   ├── ApprovalCard.tsx           # Single review item card with actions
│   │   ├── ApprovalHistory.tsx        # Audit log of recently reviewed lines
│   │   └── DrugSearchModal.tsx        # Auto-complete drug correction search
│   ├── home/
│   │   └── KpiCard.tsx                # Commercial KPI tile component
│   ├── inventory/
│   │   ├── DemandChart.tsx            # Recharts area chart ("Expected" + "Range")
│   │   ├── ProductTable.tsx           # Drug catalog with stock status column
│   │   ├── PurchaseOrderSummary.tsx   # Procurement table with CSV export
│   │   ├── ReorderCard.tsx            # "Order 140 units — Est. 4,200 EGP"
│   │   └── ScenarioToggle.tsx         # "Normal" / "Flu Season" / "Supply Delay"
│   ├── layout/
│   │   ├── Layout.tsx                 # Persistent shell wrapper
│   │   ├── Sidebar.tsx                # Business-workflow navigation
│   │   └── TopBar.tsx                 # Page title, status dot, notifications
│   └── ui/
│       ├── Badge.tsx                  # Status chips (Adequate, Low, Critical)
│       ├── Button.tsx                 # Primary, secondary, ghost variants
│       ├── Card.tsx                   # White elevated container
│       ├── LoadingSpinner.tsx         # Brand spinner
│       ├── MetricCard.tsx             # KPI container tile
│       ├── Modal.tsx                  # Accessible modal wrapper
│       ├── StatusDot.tsx              # Colored connection indicator dot
│       └── Toast.tsx                  # Non-blocking feedback notification
├── data/
│   └── catalogue.ts                   # Curated Egyptian pharmaceutical catalogue
├── hooks/
│   ├── useCssColor.ts                 # Resolve CSS tokens for Recharts presentation
│   ├── useDebouncedValue.ts           # Debounce fast inputs / filters
│   ├── useReviewLog.ts                # Client-persisted review decision log
│   └── useStockLevels.ts              # LocalStorage stock level persistence
├── lib/
│   ├── drift.ts                       # PSI bands, shock math, outcome inference
│   ├── money.ts                       # Currency and precision formatting (EGP)
│   ├── procurement.ts                 # Demand projection, coverage, stock status
│   ├── promotion.ts                   # 3% promotion gate evaluation arithmetic
│   └── telemetry.ts                   # Prometheus latency parsing & SLA checks
├── pages/
│   ├── AdminPage.tsx                  # Technical telemetry (3 linkable tabs)
│   ├── ApprovalsPage.tsx              # Pharmacist verification workbench
│   ├── HomePage.tsx                   # Welcome banner, 4 KPIs, activity feed
│   ├── InventoryPage.tsx              # Product catalog + smart reorder
│   ├── NewOrderPage.tsx               # Chat-style order entry & digital invoice
│   ├── NotFoundPage.tsx               # Clean 404 handler
│   └── OrderHistoryPage.tsx           # Past orders table & breakdown
└── types/
    ├── common.ts
    ├── drift.ts
    ├── forecast.ts
    ├── matchOrder.ts
    ├── registry.ts
    ├── reviewQueue.ts
    ├── scenario.ts
    └── system.ts
```

---

## 7. Implementation Roadmap

| Phase | Title | What the User Gets |
|---|---|---|
| **Phase 1** | **App Shell & Home** | Sidebar with business navigation, TopBar, Home page with welcome banner, 4 KPI cards, activity feed. |
| **Phase 2** | **Inventory & Smart Reorder** | Product catalog table, demand chart, stock status badges, reorder cards with EGP pricing, scenario toggles, purchase order export. |
| **Phase 3** | **Order Processing & Approvals** | Chat-style order entry, digital invoice generation, order history table, pharmacist approval workbench with keyboard shortcuts. |
| **Phase 4** | **Admin — Data Quality & Drift** | Feature drift matrix (PSI), distribution shift overlay, demand shock simulation, and automated retraining trigger — contained in `/admin`. |
| **Phase 5** | **Admin — Governance & Telemetry** | Model comparison table, mathematical 3% promotion gate proof, system telemetry, and developer tool deep links — contained in `/admin`. |
| **Phase 6** | **Production & E2E Verification** | Production Docker packaging, Nginx reverse proxy, Docker Compose integration, and full manual E2E user journey verification. |
