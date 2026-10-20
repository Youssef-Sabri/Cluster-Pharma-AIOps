# ClusterOps Frontend — Pharmacy Operations & AIOps Dashboard

React 18 + Vite 5 + TypeScript application serving as the B2B pharmacy operations interface and AIOps management dashboard for ClusterOps.

> ⚠️ **Synthetic Data Only**: All pharmaceutical data, pharmacy names, and orders are synthetic for demonstration purposes.

---

## 1. Quickstart

```bash
# 1. Install dependencies
npm install

# 2. Run local development server (with HMR on port 3000)
npm run dev

# 3. Typecheck codebase (strict tsconfig + node configs)
npm run typecheck

# 4. Build production bundle into dist/
npm run build
```

| Script | Command | Purpose |
|---|---|---|
| `npm run dev` | `vite` | Starts dev server on `http://localhost:3000` with API proxying. |
| `npm run typecheck` | `tsc --noEmit` | Strict typecheck across `src/` and `vite.config.ts`. |
| `npm run build` | `typecheck && vite build` | Generates optimized production assets in `dist/`. |
| `npm run preview` | `vite preview` | Serves the local production build on `http://localhost:3000`. |

---

## 2. Architecture & Application Views

The user persona is a **pharmacy operations manager**. All technical ML complexity (PSI scores, MAE, MLflow, Docker ports) is safely isolated within the **Admin** console (`/admin`), while user-facing screens speak pure business language:

| Route | Page | Purpose & Core Capabilities |
|---|---|---|
| `/` | **Home** | Welcome banner, today's order count, stock alert counts, and business accuracy KPIs. |
| `/inventory` | **Inventory & Forecasting** | Real-time catalogue stock tracking, 7-day quantile demand charts, automated reorder cards, and scenario toggles (Normal / Flu Surge / Delay). |
| `/orders/new` | **New Order Entry** | Bilingual chat-style order entry (English, Arabic, Franco-Arabic presets) with instant digital invoice generation. |
| `/orders` | **Order History** | Auditable table of past orders with invoice drilldown and status filtering. |
| `/approvals` | **Pharmacist Approvals** | Human-in-the-loop review workbench for low-confidence matches (< 0.50) with keyboard shortcuts (`[A]`, `[C]`, `[D]`) and typeahead catalogue search. |
| `/admin` | **Admin & Observability** | ML governance, Champion vs. Challenger benchmarking, mathematical 3% promotion gate proof, PSI drift matrix, and developer tool launchpad. |

---

## 3. Design System — Cluster Light Theme

Based on the brand identity of `clusterapp.net` (pure light mode, zero Tailwind CSS):

```css
:root {
  --color-bg-base:        #f6f9fc;   /* Soft slate-white canvas */
  --color-bg-surface:     #ffffff;   /* Pure white card surface */
  --color-bg-border:      #eaedf3;   /* Hairline borders */
  --color-primary:        #0f6eff;   /* Electric blue brand action */
  --color-primary-dark:   #0E4DA4;   /* Deep brand navy */
  --color-primary-hover:  #2095f3;   /* Hover blue */
  --color-primary-tint:   #edf4ff;   /* Active tint */
  --color-text-primary:   #1c1b2e;   /* Charcoal headings */
  --shadow-card:          0 5px 50px rgba(97, 105, 140, 0.07);
  --shadow-glow:          0 6px 20px rgba(15, 110, 255, 0.28);
  --radius-lg:            14px;
  --radius-pill:          9999px;
}
```

- **Typography**: Poppins (weights 300 to 800) with clean system font fallbacks.
- **Charts**: Recharts SVG visualizers utilizing the `useCssColor` hook to resolve CSS custom properties directly into SVG presentation attributes.

---

## 4. API Proxy & Backend Integration

Both Vite (`vite.config.ts`) in development and Nginx (`nginx.conf`) in production reverse-proxy backend traffic through the same origin:

| Prefix | Forward Target | Purpose |
|---|---|---|
| `/api` | `http://backend:8000` | REST API routes (`/api/v1/...`). |
| `/health` | `http://backend:8000` | TopBar live connectivity dot. |
| `/metrics` | `http://backend:8000` | Prometheus exposition scraped by admin telemetry. |
| `/docs` | `http://backend:8000` | Swagger interactive API documentation. |
| `/openapi.json` | `http://backend:8000` | OpenAPI schema contract. |
| `/mlflow` | `http://mlflow:5000` | Infrastructure health probe. |
| `/grafana` | `http://grafana:3000` | Infrastructure health probe. |

---

## 5. Production Docker Packaging

```dockerfile
# Multi-stage Docker build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine-slim
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

- **Image Size**: **20.6 MB** (well under the 50 MB target).
- **SPA Fallback**: Configured with `try_files $uri $uri/ /index.html` to support client-side routing on direct navigation or page refresh.
