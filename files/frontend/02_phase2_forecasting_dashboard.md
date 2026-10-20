# Phase 2: Inventory & Smart Reorder

> **Objective**: Build the Inventory page (`/inventory`) — a product catalog with built-in demand forecasting, stock status indicators, automated reorder recommendations in EGP, and scenario planning. The AI is invisible; the user sees business outcomes.

---

## 1. Deliverables

- [x] **Product Catalog Table** (`src/components/inventory/ProductTable.tsx`):
  - Columns:
    | Drug Name | Category | Current Stock | 7-Day Forecast | Stock Status | Action |
    |---|---|---|---|---|---|
    | Panadol Extra 500mg | Analgesic | 85 units | ~120 units expected | 🟡 Low Stock | View / Reorder |
  - Stock Status logic (computed from forecast vs. current stock):
    - 🟢 **Adequate**: > 7 days of inventory remaining.
    - 🟡 **Low**: 3–7 days remaining.
    - 🔴 **Critical**: < 3 days remaining. Row highlighted with soft red tint.
  - Sortable by stock status (critical items float to top).
  - Filterable by category and status.

- [x] **Product Detail Panel** (expandable row or slide-out):
  - **Demand Chart** (`src/components/inventory/DemandChart.tsx`):
    - Clean Recharts area chart with:
      - Solid blue line: "Expected demand" (the q50 median, but labeled in business terms).
      - Soft blue shaded area: "Possible range" (q10–q90 interval, no quantile labels).
    - X-axis: dates. Y-axis: units. Clean gridlines, no technical annotations.
    - Hover tooltip: "Oct 20: Expected 18 units (could be 14–22)".
  - **Reorder Recommendation** (`src/components/inventory/ReorderCard.tsx`):
    - Prominent card stating:
      - "**Recommended reorder: 140 units**"
      - "Covers 7 days of expected demand with safety buffer"
      - "Estimated cost: **4,200 EGP**"
    - Big blue **"Add to Purchase Order"** button.
    - Calculation is based on: `ceil(upper_bound_total × 1.15)` — but the user never sees this formula.
  - **Scenario Toggles** (`src/components/inventory/ScenarioToggle.tsx`):
    - 3 toggle buttons (not a slider, not technical):
      - **Normal** (1.0× — default, selected)
      - **Flu Season** (+35% demand surge)
      - **Supply Delay** (+50% safety buffer)
    - Switching recalculates the demand chart and reorder recommendation instantly.

- [x] **Purchase Order Summary** (`src/components/inventory/PurchaseOrderSummary.tsx`):
  - Bottom panel or separate tab showing all items added to the current purchase order:
    | Drug | Quantity | Est. Unit Price | Est. Total (EGP) |
    |---|---|---|---|
    | Panadol Extra 500mg | 140 | 30 EGP | 4,200 EGP |
    | Augmentin 625mg | 85 | 52 EGP | 4,420 EGP |
    | **Total** | | | **8,620 EGP** |
  - **"Export Purchase Order"** button.

---

## 2. Key UX Decisions

### What the user sees:
- A product catalog that looks like a modern inventory management tool.
- "Expected demand: ~120 units" — simple, actionable.
- "Low Stock" / "Critical" badges — immediate visual priority.
- "Recommended reorder: 140 units — 4,200 EGP" — ready to act on.
- "Flu Season" toggle — intuitive, no math.

### What the user does NOT see:
- ❌ No "q10 / q50 / q90" labels anywhere.
- ❌ No "LightGBM Multi-Quantile Regression".
- ❌ No "MAE: 2.2758 units" or "Model v1 (Production)".
- ❌ No "80% predictive interval cone".
- ❌ No "EOQ = ceil(upper_bound × 1.15)" formula.
- ❌ No MLflow model stamp or lineage badge.

All of that powers the calculations silently. The user just gets the answer.

---

## 3. Backend API Mapping

| User Action | API Call | What User Sees |
|---|---|---|
| Open Inventory page | `POST /api/v1/forecast` (all products, 7-day horizon) | Product table with stock status |
| Click "View" on a drug | Same forecast data, rendered as detail chart | Demand chart + reorder card |
| Toggle "Flu Season" | Client-side: multiply forecast × 1.35 | Chart & reorder update instantly |
| Click "Add to Purchase Order" | Client-side state (local cart) | Item added to summary table |
| Click "Export Purchase Order" | Client-side PDF/table generation | Downloadable summary |

---

## 4. Implementation Steps

1. Create TypeScript types for forecast data (reuse existing `src/types/forecast.ts`).
2. Build `ProductTable.tsx` with stock status computation from forecast data.
3. Build `DemandChart.tsx` — clean Recharts area chart with business-language labels.
4. Build `ReorderCard.tsx` — prominent EGP recommendation with action button.
5. Build `ScenarioToggle.tsx` — 3-button toggle group with client-side multiplier.
6. Build `PurchaseOrderSummary.tsx` — aggregated cart with export.
7. Assemble `InventoryPage.tsx` combining all components.

---

## 5. Verification

**Success criteria**:
- `/inventory` shows a product catalog with 🟢🟡🔴 stock status for each drug.
- Clicking any drug shows a clean demand chart with "Expected" and "Range" labels (no q10/q50/q90).
- Reorder card shows a concrete number and EGP cost.
- Switching "Flu Season" recalculates the chart and recommendation in < 300ms.
- No technical ML terminology visible anywhere on this page.
