# Phase 6: Production Packaging, Docker Compose Integration & End-to-End Verification

> **Objective**: Package the frontend application into a lean production Docker image with an Nginx reverse proxy, integrate the `frontend` service into the root `docker-compose.yml` on port 3000, and execute comprehensive manual and automated end-to-end verification across all 6 business product views.

---

## 1. Deliverables Checklist

- [x] **Production Docker Packaging**:
  - `frontend/Dockerfile`: Multi-stage build (`node:20-alpine` builder $\rightarrow$ `nginx:alpine` runner). Image size $< 50\text{ MB}$ (actual image: 20.6 MB).
  - `frontend/nginx.conf`: Nginx configuration supporting SPA client-side routing fallback (`try_files $uri $uri/ /index.html`) and reverse-proxying `/api/` and `/health` calls directly to `backend:8000`.
- [x] **Docker Compose Integration**:
  - Add `frontend` service to root `docker-compose.yml` exposing port `3000:3000`.
  - Service dependency on `backend` with `condition: service_healthy`.
  - Joined to the shared `clusterops` internal Docker network.
- [x] **End-to-End Verification Across All 6 Product Views**:
  - `/` Home (Welcome banner, 4 business KPI cards, activity feed, connection indicator).
  - `/inventory` Inventory & Smart Reorder (Product catalog, stock status badges, demand charts, reorder cards in EGP, scenario toggles, purchase order summary).
  - `/orders/new` New Order Processing (Chat-style order entry, bilingual presets, instant digital invoice generation).
  - `/orders` Order History (Past orders table, status filters, invoice detail view).
  - `/approvals` Pharmacist Approvals (Verification cards, keyboard shortcuts `[A]`, `[C]`, `[D]`, drug search modal, live badge decrement).
  - `/admin` Admin & System Console (AI Performance, Data Quality & Drift, Infrastructure Health, Developer Links).
- [x] **Comprehensive Self-Directed Manual Testing Guide** verifying the end-to-end journey of a pharmacy operations manager.

---

## 2. Technical Specifications

### 2.1 Multi-Stage Dockerfile (`frontend/Dockerfile`)

```dockerfile
# Stage 1: Build production assets
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Serve with lightweight Nginx
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
```

### 2.2 Nginx Configuration (`frontend/nginx.conf`)

```nginx
server {
    listen 3000;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # Static assets caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
    }

    # Proxy API calls directly to the FastAPI backend service
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Direct health proxy
    location /health {
        proxy_pass http://backend:8000/health;
    }

    # SPA Client-Side Routing Fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### 2.3 Docker Compose Service Definition (`docker-compose.yml`)

```yaml
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    image: clusterops/frontend:1.0.0
    container_name: clusterops-frontend
    restart: unless-stopped
    ports:
      - "3000:3000"
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - clusterops
```

---

## 3. Step-by-Step Implementation Instructions

1. **Verify Local Production Build**:
   Run `npm run build` inside `frontend/` and verify that the `dist/` directory is produced cleanly with zero TypeScript errors or missing assets.
2. **Configure Production Container**:
   Create `frontend/Dockerfile` and `frontend/nginx.conf`.
3. **Update Root Docker Compose**:
   Add the `frontend` service definition to `docker-compose.yml`.
4. **Deploy Full Stack**:
   Run `docker compose up -d --build frontend` and verify container health via `docker compose ps`.
5. **Execute Verification Walkthrough**:
   Navigate through all 6 business views on `http://localhost:3000` and confirm end-to-end data flow with the FastAPI backend.

---

## 4. Self-Directed Manual Testing & User Journey Verification

| Step | Page / Route | Manual Testing Actions & Expected Outcome |
| :--- | :--- | :--- |
| **1** | **Home (`/`)** | - Verify "Good afternoon" welcome banner with current date and demo environment badge.<br>- Verify 4 business KPI cards: Today's Orders, Low Stock Alerts, Pending Approvals, AI Accuracy (percentage format, e.g. "96.5%").<br>- Check that clicking "Low Stock Alerts" navigates to `/inventory` filtered to critical items.<br>- Check that clicking "Pending Approvals" navigates to `/approvals`.<br>- Inspect recent activity feed for plain-language operational events. |
| **2** | **Inventory & Smart Reorder (`/inventory`)** | - View product catalog table with columns: Drug Name, Category, Current Stock, 7-Day Forecast, Stock Status, Action.<br>- Confirm stock status badges: 🟢 Adequate (> 7 days), 🟡 Low (3–7 days), 🔴 Critical (< 3 days).<br>- Expand product detail panel: verify Recharts area chart showing "Expected demand" line and soft shaded "Possible range" band (no raw quantile jargon).<br>- Inspect Reorder Recommendation card: "Recommended reorder: 140 units — Est. 4,200 EGP".<br>- Test Scenario Toggles: click "Flu Season (+35%)" and "Supply Delay (+50%)" and verify instant recalculation.<br>- Click "Add to Purchase Order" and verify aggregation in the Purchase Order Summary table.<br>- Click "Export Purchase Order" and verify summary generation. |
| **3** | **New Order (`/orders/new`)** | - Verify chat-style input area with clean placeholder text.<br>- Click preset demo buttons: "Clean English", "Arabic", "Messy typing", "Mixed".<br>- Click "Process Order" (calls `POST /api/v1/match-order`).<br>- Verify digital invoice appears with columns: #, Item, Qty, Unit Price, Total, Status.<br>- High-confidence items show green ✅ "Matched". Ambiguous items show yellow 🟡 "Please verify" with a drug correction dropdown.<br>- Verify order total in EGP and click green "Confirm & Submit Order". |
| **4** | **Order History (`/orders`)** | - Inspect table of past orders: Date, Order #, Pharmacy, Items count, Total (EGP), Status.<br>- Test pharmacy and status filters.<br>- Click any order row to expand and inspect full digital invoice details. |
| **5** | **Approvals (`/approvals`)** | - Verify pending items counter (e.g., "3 items need your review") matches the sidebar notification badge.<br>- Inspect approval cards: customer raw text vs. AI drug suggestion with subtle status dot.<br>- Test actions: click ✅ "Approve", click ✏️ "Correct" to open the drug search modal, click ❌ "Reject".<br>- Test keyboard shortcuts: press `[A]` to approve, `[C]` to correct, `[D]` to reject, and `[↑]`/`[↓]` to navigate cards.<br>- Confirm verified items disappear and the pending badge counter decrements in real-time. |
| **6** | **Admin & System (`/admin`)** | - Switch between tabs: "AI Performance & Governance", "Data Quality & Drift", and "Infrastructure & Tools".<br>- Tab 1 (AI Performance): Verify active champion card, model comparison table, and mathematical 3% promotion gate proof formula.<br>- Tab 2 (Data Quality): Verify PSI feature drift matrix with 0.10 and 0.20 reference lines, distribution overlay histogram, demand shock simulator, and "Trigger Retraining Flow" button.<br>- Tab 3 (Infrastructure): Verify service health cards (FastAPI, Postgres, MLflow, Prometheus, Grafana) and click developer links to ensure external tools open in new tabs. |

---

## 5. Verification & Acceptance Criteria

```bash
# 1. Build and run the dockerized frontend container
docker compose up -d --build frontend

# 2. Check running container status
docker compose ps frontend

# 3. Test HTTP response and SPA fallback
curl -I http://localhost:3000
curl -I http://localhost:3000/inventory
curl -I http://localhost:3000/orders/new
curl -I http://localhost:3000/approvals
curl -I http://localhost:3000/admin
```

**Success Criteria**:
- Frontend builds into an optimized Docker image $< 50\text{ MB}$.
- `http://localhost:3000` loads instantly with HTTP 200.
- All direct SPA URLs (`/inventory`, `/orders/new`, `/orders`, `/approvals`, `/admin`) return HTTP 200 via Nginx `try_files` fallback.
- Reverse proxy forwards `/api/` calls seamlessly to `backend:8000` without CORS issues.
- All user journeys execute smoothly without browser console warnings or unhandled exceptions.
- The interface feels like an authentic, commercial-grade B2B SaaS product for Egyptian pharmacies.
