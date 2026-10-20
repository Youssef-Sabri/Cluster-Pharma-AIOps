# Phase 5: REST API Endpoints & Observability

> **Objective**: Implement all FastAPI REST endpoints with strict Pydantic v2 schemas, wire up asynchronous database interactions, instrument custom Prometheus metrics, configure Prometheus scraping, and create pre-provisioned Grafana dashboards.

---

## 1. Deliverables Checklist

- [x] `backend/app/main.py`:
  - Lifespan handler pre-loading the active LightGBM model and in-memory drug catalogue cache at startup.
  - CORS middleware allowing frontend communication (`localhost:3000`).
  - Request logging and Prometheus latency timing middleware.
  - Auto-generated Swagger documentation at `/docs` with detailed endpoint metadata.
- [x] Pydantic v2 Schemas (`backend/app/schemas/`):
  - `forecast.py`: `ForecastRequest`, `ForecastResponse`, `ForecastItem`.
  - `match_order.py`: `MatchOrderRequest`, `MatchOrderResponse`, `MatchedItem`.
  - `drift.py`: `DriftStatusResponse`, `DriftFeatureItem`.
  - `registry.py`: `ModelRegistryResponse`, `ModelMetadataItem`.
  - `review_queue.py`: `ReviewQueueItemResponse`, `ReviewActionRequest`.
- [x] API Routers (`backend/app/api/`):
  - `health.py`: `GET /health` and `GET /metrics`.
  - `forecast.py`: `POST /api/v1/forecast`.
  - `match_order.py`: `POST /api/v1/match-order` (writes to `orders` and `order_items`).
  - `drift.py`: `GET /api/v1/drift-status`.
  - `retrain.py`: `POST /api/v1/retrain` (triggers Prefect flow, returns 202 Accepted).
  - `registry.py`: `GET /api/v1/model-registry` (retrieves active and candidate models from MLflow).
  - `review_queue.py`: `GET /api/v1/orders/review-queue` and `PATCH /api/v1/orders/review-queue/{item_id}`.
- [x] `backend/app/monitoring/metrics.py`:
  - `clusterops_requests_total` (counter, labels: endpoint, method, status).
  - `clusterops_request_duration_seconds` (histogram, p50, p95, p99).
  - `clusterops_forecast_mae` (gauge per product).
  - `clusterops_match_confidence_bucket` (histogram).
  - `clusterops_low_confidence_total` (counter).
  - `clusterops_drift_psi_score` (gauge per feature).
- [x] Observability Configuration:
  - `prometheus/prometheus.yml` configured to scrape `backend:8000/metrics` every 15s.
  - `grafana/dashboards/clusterops.json` pre-provisioned dashboard displaying KPI panels.
- [x] Comprehensive async API tests in `backend/tests/test_api.py`.

---

## 2. Technical Specifications

### 2.1 Prometheus Metrics Registry
```python
from prometheus_client import Counter, Histogram, Gauge

REQUEST_COUNT = Counter(
    "clusterops_requests_total",
    "Total HTTP requests handled by ClusterOps API",
    ["endpoint", "method", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "clusterops_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

DRIFT_PSI_GAUGE = Gauge(
    "clusterops_drift_psi_score",
    "Current Population Stability Index score per feature",
    ["feature_name"],
)

LOW_CONFIDENCE_COUNTER = Counter(
    "clusterops_low_confidence_total",
    "Count of order match tokens requiring human review (< 0.50)",
)
```

### 2.2 API Route Matrix
| Endpoint | Method | Status | Auth | Purpose |
|---|---|---|---|---|
| `/health` | `GET` | 200 | Public | Liveness & model readiness check |
| `/metrics` | `GET` | 200 | Internal | Prometheus metrics scrape |
| `/api/v1/forecast` | `POST` | 200 | None | Generate multi-horizon demand forecasts |
| `/api/v1/match-order` | `POST` | 200 | None | Parse raw unstructured text into catalogue items |
| `/api/v1/drift-status` | `GET` | 200 | None | Query latest statistical drift metrics |
| `/api/v1/retrain` | `POST` | 202 | None | Trigger asynchronous Prefect retraining flow |
| `/api/v1/model-registry` | `GET` | 200 | None | Retrieve active model versions and metrics |
| `/api/v1/orders/review-queue` | `GET` | 200 | None | Fetch orders flagged for human review |
| `/api/v1/orders/review-queue/{item_id}`| `PATCH` | 200 | None | Accept, correct, or dismiss a review item |

---

## 3. Step-by-Step Implementation Instructions

1. **Metrics & Middleware Setup**:
   Build `backend/app/monitoring/metrics.py`. In `backend/app/main.py`, install middleware to measure request duration and increment counters for all calls.

2. **Implement Schemas**:
   Create all Pydantic v2 schemas under `backend/app/schemas/` with strict type validation, field descriptions, and realistic JSON examples.

3. **Implement API Routers**:
   Implement routers under `backend/app/api/` connecting to the database through `get_db` async dependency and calling the ML modules (`DemandForecaster`, `CatalogueMatcher`, `DriftDetector`).

4. **Configure Prometheus & Grafana**:
   Create `prometheus/prometheus.yml` pointing to `backend:8000`. Create `grafana/dashboards/clusterops.json` visualizing:
   - Request throughput & error rate.
   - p95 latency line chart with a 500ms red SLA line.
   - Latest PSI drift scores per feature with a 0.20 red alert threshold.
   - Match confidence distribution histogram.

5. **Write Async Test Suite**:
   In `backend/tests/test_api.py`, test every route using `httpx.AsyncClient` verifying status codes, schema validation errors on bad input (422), and business logic execution.

---

## 4. Verification & Acceptance Criteria

```bash
# Start backend service
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Execute full API test suite
pytest tests/test_api.py -v

# Verify Swagger docs
curl http://localhost:8000/docs
```

**Success criteria**:
- All 8 routes return valid responses conforming to Pydantic schemas.
- `/health` responds with `"status": "ok"` and `"models_loaded": true`.
- `/metrics` exposes valid Prometheus exposition format with custom `clusterops_*` series.
- p95 latency across all mock endpoints remains $< 500\text{ ms}$.
- `POST /api/v1/retrain` returns 202 Accepted with a valid tracking ID.
