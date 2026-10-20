# Phase 1: App Shell, Home Page & Navigation

> **Objective**: Build the application shell with business-workflow navigation, the Home page with welcome banner and KPI summary cards, and the connection to the live backend — all in Cluster light theme.

---

## 1. Deliverables

- [x] Vite 5 + React 18 + TypeScript project scaffold with dependencies.
- [x] `src/index.css` with Cluster light theme design tokens (from `clusterapp.net`).
- [x] **Sidebar Navigation** (`src/components/layout/Sidebar.tsx`):
  - Cluster brand mark at top.
  - Business-workflow links (not backend endpoint names):
    - 📊 **Home** → `/`
    - 📦 **Inventory** → `/inventory`
    - 🛒 **New Order** → `/orders/new`
    - 📋 **Order History** → `/orders`
    - ✅ **Approvals** → `/approvals` (with live pending count badge)
  - Separator, then:
    - ⚙️ **Admin & System** → `/admin`
  - No external links (Swagger, MLflow, Grafana) in the sidebar — those live inside `/admin` only.
- [x] **TopBar** (`src/components/layout/TopBar.tsx`):
  - Current page title (e.g., "Home", "Inventory", "New Order").
  - Small connection indicator (just a colored dot: 🟢 connected / 🔴 disconnected — no "FastAPI port 8000" text).
  - Notification bell for pending approvals.
- [x] **Home Page** (`src/pages/HomePage.tsx`):
  - **Welcome Banner**: "Good afternoon" with current date. Subtle environment badge: *"Demo Environment — Synthetic Data"*.
  - **4 Summary KPI Cards** (large, clean, business-language):
    1. **Today's Orders** — count of orders processed. Links to `/orders`.
    2. **Low Stock Alerts** — count of products with critical inventory. Links to `/inventory`.
    3. **Pending Approvals** — items needing pharmacist review. Links to `/approvals`.
    4. **AI Accuracy** — displayed as a percentage ("96.5% accurate"), NOT as raw MAE. Computed from backend model metrics but translated.
  - **Recent Activity Feed** — chronological list in plain language:
    - "Order #1042 from PH-001 processed — 5 items matched"
    - "Panadol Extra stock level restored ✓"
    - "2 items from Order #1038 need your review"
    - "Congestal inventory running low — reorder suggested"
- [x] UI primitives: `Card`, `Badge`, `Button`, `MetricCard`, `LoadingSpinner`, `StatusDot`.

---

## 2. Key UX Decisions

### What IS on this page:
- Business KPIs in plain language.
- An activity feed that reads like a notification center.
- Clean, welcoming design matching `clusterapp.net`.

### What is NOT on this page:
- ❌ No "Production Champion MAE: 2.2758"
- ❌ No "PSI Drift Status: HEALTHY (0.0412)"
- ❌ No "FastAPI Gateway (port 8000) — Connected"
- ❌ No "MLflow Tracking Server" or "Prometheus Metrics"
- ❌ No infrastructure health matrix
- ❌ No model version stamps or champion/challenger badges

All of those belong exclusively on `/admin`.

---

## 3. Implementation Steps

1. Scaffold project with Vite, install dependencies.
2. Write `src/index.css` with Cluster light theme tokens.
3. Build `Sidebar.tsx` with the 5 business navigation links + admin link.
4. Build `TopBar.tsx` with page title and minimal connection dot.
5. Build `Layout.tsx` combining sidebar + topbar + outlet.
6. Build UI primitives (`Card`, `Badge`, `Button`, `MetricCard`).
7. Build `HomePage.tsx` with welcome banner, 4 KPI cards, and activity feed.
8. Wire KPI data from backend endpoints (health, review queue count, model registry for accuracy conversion).

---

## 4. Verification

```bash
npm run typecheck   # Zero errors
npm run dev         # http://localhost:3000
```

**Success criteria**:
- Home page loads with a warm welcome banner and 4 business KPI cards.
- Sidebar shows business-workflow links, NOT endpoint names.
- No technical jargon visible anywhere on screen.
- Connection dot shows green when backend is reachable.
- Pending approvals badge updates live on the sidebar.
