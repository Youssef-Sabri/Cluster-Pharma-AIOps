# ClusterOps — Frontend Rules & Engineering Guidelines

> **Target**: A polished B2B SaaS product for pharmacy chain operations, not a developer dashboard.
> **Scope**: Frontend web application (`frontend/`).

---

## 1. Product UX Rules (Highest Priority)

1. **Product-First Language**:
   - The user is a pharmacy operations manager. They do not know what MAE, PSI, q10/q50/q90, RapidFuzz, or LightGBM are.
   - Every label, heading, and tooltip must use **business language**: "Expected demand", "Stock status", "Please verify", "Reorder recommendation", "AI accuracy: 96.5%".
   - Never show raw model output without translating it into a business outcome.

2. **Hide All Technical Details from Normal Screens**:
   - Model versions, drift scores, PSI values, confidence decimals, infrastructure ports, Swagger links, MLflow links — **none of these appear** on Home, Inventory, Orders, or Approvals pages.
   - All technical telemetry is consolidated in the **Admin & System** page (`/admin`), accessible only from the bottom of the sidebar.

3. **Business-Language Status Colors**:
   - 🟢 **Green**: In Stock, Confirmed, Approved, Healthy.
   - 🟡 **Amber**: Low Stock, Please Verify, Needs Attention.
   - 🔴 **Red**: Critical Stockout, Rejected, Urgent, Out of Stock.
   - Use colored dots, badges, and row highlights — never raw confidence numbers in user-facing views.

4. **Synthetic Data Notice**:
   - Every page must include a small, non-intrusive footer badge: *"ClusterOps Demo — Synthetic Egyptian Pharmaceutical Data"*.
   - Under no circumstances should UI copy suggest this is real pharmacy data.

---

## 2. Cluster Brand Fidelity

5. **Cluster Light Theme (clusterapp.net)**:
   - Soft slate-white canvas (`#f6f9fc`) and pure white card surfaces (`#ffffff`).
   - Primary electric blue (`#0f6eff`), deep brand blue (`#0E4DA4`), hover blue (`#2095f3`).
   - Charcoal navy headings (`#1c1b2e`) and slate body text (`#6d859e`).
   - Poppins font family (weights 300 to 800).
   - Subtle ambient shadows (`0 4px 20px rgba(97, 105, 140, 0.07)`), crisp borders (`#eaedf3`), rounded cards (`10–14px`).
   - **Do NOT use dark mode.** The entire app is light-themed.

6. **Vanilla CSS Design Tokens Only**:
   - Zero Tailwind CSS. Every layout, card, badge, and button uses custom CSS properties defined in `src/index.css`.

---

## 3. Technical Standards

7. **Strict TypeScript**:
   - `strict: true`, no implicit `any`, strict null checks.
   - All API responses typed in `src/types/` mirroring backend Pydantic schemas.
   - Functional components with explicit props interfaces.

8. **React Query Discipline**:
   - All server state via `@tanstack/react-query` v5.
   - Never raw `setInterval` inside `useEffect` for polling.
   - Configure `staleTime`, `retry`, and polling intervals per endpoint.

9. **Graceful Degradation**:
   - If backend is unreachable: show a friendly banner ("We're having trouble connecting — please try again in a moment"), not a crash or raw error.
   - Skeleton loaders during async fetches.
   - Each panel degrades independently — one failing endpoint doesn't break the whole page.

10. **Accessibility & Performance**:
    - Interactive inputs respond in < 100ms.
    - Color contrast meets WCAG 2.1 AA.
    - All animations respect `@media (prefers-reduced-motion: reduce)`.
    - Keyboard navigation for approval workflows.

---

## 4. Directory Layout

```
frontend/src/
├── main.tsx                 # React DOM mount, QueryClientProvider, Router
├── App.tsx                  # Route definitions and layout shell
├── index.css                # Global CSS variables, resets, utilities
├── api/                     # Axios client & React Query hooks
│   ├── axios.ts
│   └── endpoints/
│       ├── forecast.ts      # Inventory demand data
│       ├── matchOrder.ts    # Order processing
│       ├── reviewQueue.ts   # Approval queue
│       ├── drift.ts         # Admin: drift status
│       ├── registry.ts      # Admin: model registry
│       └── health.ts        # System health
├── types/                   # TypeScript interfaces
├── components/
│   ├── layout/              # Sidebar, TopBar, Layout shell
│   ├── ui/                  # Card, Badge, Button, MetricCard, Modal, Spinner
│   ├── inventory/           # ProductTable, DemandChart, ReorderCard, ScenarioToggle
│   ├── orders/              # OrderInput, InvoiceTable, OrderHistory, PresetButtons
│   ├── approvals/           # ApprovalCard, DrugSearchModal, ApprovalHistory
│   └── admin/               # AiPerformance, DriftPanel, InfraHealth, DevLinks
└── pages/
    ├── HomePage.tsx
    ├── InventoryPage.tsx
    ├── NewOrderPage.tsx
    ├── OrderHistoryPage.tsx
    ├── ApprovalsPage.tsx
    ├── AdminPage.tsx
    └── NotFoundPage.tsx
```

---

## 5. Testing & Verification

- `npm run typecheck` must pass with zero errors.
- `npm run build` must compile clean production bundles.
- Docker Nginx container must serve the app on port 3000 and proxy `/api/*` to `backend:8000`.
- No technical jargon visible on any user-facing page (Home, Inventory, Orders, Approvals).
- All technical details confined to `/admin`.
