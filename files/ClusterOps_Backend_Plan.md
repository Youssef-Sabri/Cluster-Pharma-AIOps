# ClusterOps — Backend Technical Plan

> **Portfolio project** demonstrating AIOps engineering skills aligned to Cluster's public roadmap.
> All data is **synthetic only**. No real Cluster data, systems, or internal architecture is used or claimed.

---

## 1. Stack at a Glance

| Layer | Technology | Why |
|---|---|---|
| API Framework | **FastAPI** (Python 3.11) | Async, Pydantic-native, auto-generates Swagger UI at `/docs` |
| ML — Forecasting | **LightGBM** | Fast gradient boosting, handles time-series features well |
| ML — Order Matching (pass 1) | **rapidfuzz** | Token-set ratio fuzzy matching, < 1 ms per query |
| ML — Order Matching (pass 2) | **Gemini API** (free tier, `gemini-2.0-flash`) | LLM re-ranker only for low-confidence matches (< 0.70 score) |
| Experiment Tracking | **MLflow** | Model registry, metric logging, version promotion gate |
| Drift Detection | **scipy / PSI** | Population Stability Index, fires alarm when PSI > 0.20 |
| Retraining Scheduler | **Prefect** | Python-native flows, runs locally, built-in UI on port 4200 |
| Database | **PostgreSQL 15** | Stores synthetic orders, predictions, drift logs, review queue |
| ORM | **SQLAlchemy 2 + Alembic** | Async ORM, Alembic for migrations |
| Monitoring | **Prometheus + Grafana** | Metrics scraping and alerting dashboards |
| Containerisation | **Docker + Docker Compose** | All services in one docker-compose.yml at the repo root |
| Validation / Docs | **Pydantic v2 + Swagger UI** | Auto-generated OpenAPI docs at `/docs` |
| Testing | **pytest + httpx** | Unit + integration tests for all endpoints and pipelines |

---

## 2. Repository Layout

```
clusterops/                          <- repo root
├── docker-compose.yml               <- spins up ALL services
├── .env.example
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                  <- FastAPI app entry point (lifespan, CORS, middleware)
│   │   ├── config.py                <- settings via pydantic-settings (.env)
│   │   ├── database.py              <- async SQLAlchemy engine + sessionmaker
│   │   ├── logging_config.py        <- structured JSON logging
│   │   │
│   │   ├── api/
│   │   │   ├── forecast.py          <- POST /api/v1/forecast
│   │   │   ├── match_order.py       <- POST /api/v1/match-order
│   │   │   ├── drift.py             <- GET /api/v1/drift-status
│   │   │   ├── retrain.py           <- POST /api/v1/retrain
│   │   │   ├── registry.py          <- GET /api/v1/model-registry
│   │   │   ├── review_queue.py      <- GET/PATCH /api/v1/orders/review-queue
│   │   │   ├── health.py            <- GET /health, GET /metrics
│   │   │   └── state.py             <- in-memory live serving state & catalogue cache
│   │   │
│   │   ├── models/                  <- SQLAlchemy ORM models
│   │   │   ├── base.py
│   │   │   ├── order.py             <- orders & order_items tables
│   │   │   ├── prediction.py        <- predictions table
│   │   │   ├── drift_log.py         <- drift_logs table
│   │   │   └── drug_catalogue.py    <- drug_catalogue table
│   │   │
│   │   ├── schemas/                 <- Pydantic v2 schemas
│   │   │   ├── common.py
│   │   │   ├── forecast.py
│   │   │   ├── match_order.py
│   │   │   ├── drift.py
│   │   │   ├── registry.py
│   │   │   └── review_queue.py
│   │   │
│   │   ├── ml/
│   │   │   ├── features.py          <- SHARED feature function (train = serve, no skew)
│   │   │   ├── dataset.py           <- time-series dataset preparation
│   │   │   ├── forecast_model.py    <- LightGBM train / predict / quantile intervals
│   │   │   ├── text_processing.py   <- Arabic/English normalization & quantity extraction
│   │   │   ├── order_matcher.py     <- rapidfuzz + Gemini 2.0 Flash re-ranker
│   │   │   ├── drift_detector.py    <- PSI computation with epsilon smoothing
│   │   │   ├── serving.py           <- high-speed in-memory inference loader
│   │   │   └── mlflow_utils.py      <- log, register, 3% promotion gate logic
│   │   │
│   │   ├── pipelines/
│   │   │   ├── retrain_flow.py      <- Prefect flow: drift -> train -> compare -> promote
│   │   │   └── data_generator.py    <- synthetic data generation + demand shock mode
│   │   │
│   │   └── monitoring/
│   │       └── metrics.py           <- Prometheus instrumentation (requests, latency, PSI)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── alembic.ini
│
├── frontend/                        <- React 18 + Vite 5 + TypeScript SPA (see Frontend Plan)
├── ops/
│   ├── postgres/init/               <- creates mlflow & test databases
│   └── mlflow/Dockerfile            <- MLflow image with pinned postgres driver
├── prometheus/
│   ├── prometheus.yml               <- scrapes backend:8000/metrics every 15s
│   └── alerts.yml                   <- Prometheus alerting rules
└── grafana/
    ├── provisioning/                <- automated datasource & dashboard provisioning
    └── dashboards/
        └── clusterops.json          <- pre-provisioned Grafana operational dashboard
```

---

## 3. API Endpoints

All routes versioned under `/api/v1/`. Swagger UI at `http://localhost:8000/docs`.

### 3.1 `/health` — GET
```json
{
  "status": "ok",
  "version": "1.0.0",
  "models_loaded": true,
  "db_connected": true,
  "timestamp": "2026-10-17T18:00:00Z"
}
```

### 3.2 `/metrics` — GET
Prometheus text format scraped every 15 s. Key metrics:
- `clusterops_requests_total{endpoint, method, status}`
- `clusterops_request_duration_seconds{endpoint}` — histogram (p50/p95/p99)
- `clusterops_forecast_mae{product_id}`
- `clusterops_match_confidence_bucket` — histogram of confidence scores
- `clusterops_low_confidence_total` — orders below 0.70 threshold
- `clusterops_drift_psi_score{feature}`

### 3.3 `/api/v1/forecast` — POST

**Request:**
```json
{
  "pharmacy_id": "PH-001",
  "product_ids": ["panadol-500", "augmentin-625"],
  "forecast_horizon_days": 7
}
```

**Response 200:**
```json
{
  "pharmacy_id": "PH-001",
  "generated_at": "2026-10-17T18:00:00Z",
  "model_version": "lgbm-v3",
  "forecasts": [
    {
      "product_id": "panadol-500",
      "product_name": "Panadol 500mg",
      "dates": ["2026-10-18", "2026-10-19"],
      "predicted_units": [42, 38],
      "lower_bound": [35, 30],
      "upper_bound": [49, 46],
      "mae_last_7d": 4.2
    }
  ]
}
```

### 3.4 `/api/v1/match-order` — POST

**Request:**
```json
{
  "raw_text": "10 panadol and 5 augmentn 625, 2 boxes brufen 400",
  "pharmacy_id": "PH-001"
}
```

**Response 200:**
```json
{
  "order_id": "ord-abc123",
  "items": [
    {
      "raw_token": "10 panadol",
      "catalogue_id": "panadol-500",
      "catalogue_name": "Panadol 500mg",
      "quantity": 10,
      "confidence": 0.95,
      "match_method": "fuzzy",
      "needs_review": false
    },
    {
      "raw_token": "5 augmentn 625",
      "catalogue_id": "augmentin-625",
      "catalogue_name": "Augmentin 625mg",
      "quantity": 5,
      "confidence": 0.63,
      "match_method": "llm",
      "needs_review": true
    }
  ],
  "overall_confidence": 0.79
}
```

**Two-Stage Matching Logic:**
1. **Stage 1 — rapidfuzz** `token_set_ratio` vs catalogue. Score ≥ 0.70 → accept.
2. **Stage 2 — Gemini API** (`gemini-2.0-flash`) — called only when rapidfuzz < 0.70.
3. Final confidence < 0.50 → item added to **human review queue**.

**Gemini re-ranker prompt:**
```
You are a pharmaceutical order matcher for the Egyptian market.
Raw token: "{token}"
Top 5 rapidfuzz candidates: {candidates}
Return JSON: {"catalogue_id": "...", "confidence": 0.0}
```

### 3.5 `/api/v1/drift-status` — GET

```json
{
  "checked_at": "2026-10-17T17:45:00Z",
  "overall_status": "DRIFT_DETECTED",
  "psi_threshold": 0.20,
  "features": [
    {
      "feature_name": "daily_units_sold",
      "psi_score": 0.32,
      "status": "DRIFT_DETECTED"
    },
    {
      "feature_name": "order_frequency",
      "psi_score": 0.08,
      "status": "OK"
    }
  ],
  "retraining_triggered": true
}
```

**PSI Thresholds:**
| PSI | Status |
|---|---|
| < 0.10 | `OK` |
| 0.10 – 0.20 | `WARNING` |
| ≥ 0.20 | `DRIFT_DETECTED` → triggers retraining |

### 3.6 `/api/v1/retrain` — POST
```json
// Request
{ "force": true, "notify_on_completion": true }

// Response 202
{
  "flow_run_id": "prefect-run-xyz",
  "status": "SUBMITTED",
  "message": "Retraining flow submitted. Check /model-registry for results.",
  "estimated_duration_seconds": 120
}
```

### 3.7 `/api/v1/model-registry` — GET
```json
{
  "models": [
    {
      "version": "3",
      "name": "lgbm-demand-forecast",
      "stage": "Production",
      "registered_at": "2026-10-17T16:05:00Z",
      "metrics": {
        "mae": 3.8,
        "rmse": 5.1,
        "mape": 0.09,
        "vs_naive_baseline_improvement_pct": 18.4
      }
    }
  ]
}
```

### 3.8 `/api/v1/orders/review-queue` — GET / PATCH
- **GET**: Returns orders with confidence < 0.50 pending human review
- **PATCH**: Accepts or corrects a match, closes the human-in-the-loop loop

---

## 4. ML Architecture

### 4.1 Demand Forecasting (LightGBM)

**Features** — defined in `ml/features.py` (shared between training and serving):

| Feature | Description |
|---|---|
| `lag_1`, `lag_7`, `lag_14` | Units sold 1, 7, 14 days ago |
| `rolling_mean_7d`, `rolling_std_7d` | Rolling statistics |
| `day_of_week` | 0–6 (Friday/Saturday = weekend in Egypt) |
| `is_ramadan` | Binary flag (Egyptian Islamic calendar) |
| `month`, `week_of_year` | Seasonality signals |
| `product_category` | Drug category (OTC / prescription / cosmetics) |
| `pharmacy_tier` | Small / medium / large (synthetic segmentation) |

**Training rules:**
- Time-based split — last 20% of timeline for test, never random
- Per-product MAE, RMSE, MAPE logged to MLflow
- Naive baseline (same day last week) logged alongside every run
- Prediction intervals via LightGBM quantile regression

**Promotion Gate:**
```python
if challenger.mae < production.mae * 0.97:   # must be 3%+ better
    mlflow.transition_model_version_stage(name, version, "Production")
else:
    mlflow.transition_model_version_stage(name, version, "Archived")
    log_rejection_reason()
```

### 4.2 Drift Detection (PSI)

```python
def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    # Bucketize reference, apply same bins to current
    # PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))
    return psi_score
```

Monitored features: `daily_units_sold`, `order_frequency`, `avg_order_value_egp`, `match_confidence`.

### 4.3 Retraining Pipeline (Prefect Flow)

```
Flow: clusterops-nightly-retrain (schedule: 02:00 EET / 00:00 UTC)
  Task 1: compute_drift_scores()
  Task 2: if no PSI > 0.20 → skip (log "no drift")
  Task 3: generate_training_data(window_days=90)
  Task 4: engineer_features()               <- ml/features.py
  Task 5: train_challenger_model()
  Task 6: evaluate_challenger(vs_naive, vs_production)
  Task 7: promote_model() OR archive_challenger()
  Task 8: update_drift_log() in PostgreSQL
```

---

## 5. Database Schema

```sql
CREATE TABLE orders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pharmacy_id VARCHAR(50) NOT NULL,
    raw_text    TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE order_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      UUID REFERENCES orders(id),
    raw_token     TEXT,
    catalogue_id  VARCHAR(100),
    catalogue_name VARCHAR(200),
    quantity      INTEGER,
    confidence    FLOAT,
    match_method  VARCHAR(20),   -- fuzzy | llm
    needs_review  BOOLEAN DEFAULT FALSE,
    reviewed_at   TIMESTAMPTZ,
    reviewed_by   VARCHAR(100)
);

CREATE TABLE predictions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pharmacy_id     VARCHAR(50),
    product_id      VARCHAR(100),
    forecast_date   DATE,
    predicted_units FLOAT,
    lower_bound     FLOAT,
    upper_bound     FLOAT,
    model_version   VARCHAR(50),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE drift_logs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    checked_at            TIMESTAMPTZ DEFAULT NOW(),
    feature_name          VARCHAR(100),
    psi_score             FLOAT,
    status                VARCHAR(20),   -- OK | WARNING | DRIFT_DETECTED
    retraining_triggered  BOOLEAN DEFAULT FALSE
);

CREATE TABLE drug_catalogue (
    catalogue_id   VARCHAR(100) PRIMARY KEY,
    brand_name     VARCHAR(200) NOT NULL,
    generic_name   VARCHAR(200),
    arabic_name    VARCHAR(200),
    franco_arabic  VARCHAR(200),   -- e.g. "augmentyn", "banadol"
    form           VARCHAR(50),
    strength       VARCHAR(50),
    unit_price_egp FLOAT
);
```

---

## 6. Docker Compose (All Services)

```yaml
# docker-compose.yml — repo root
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, mlflow]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      VITE_API_BASE_URL: http://localhost:8000

  postgres:
    image: postgres:15
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: cluster
      POSTGRES_PASSWORD: cluster
      POSTGRES_DB: clusterops
    volumes: [postgres_data:/var/lib/postgresql/data]

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.14.0
    ports: ["5000:5000"]
    command: >
      mlflow server --host 0.0.0.0
      --backend-store-uri postgresql://cluster:cluster@postgres:5432/mlflow
    depends_on: [postgres]

  prefect:
    build: ./backend
    command: prefect server start --host 0.0.0.0
    ports: ["4200:4200"]

  prometheus:
    image: prom/prometheus:v2.52.0
    ports: ["9090:9090"]
    volumes: [./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml]

  grafana:
    image: grafana/grafana:10.4.0
    ports: ["3001:3000"]
    volumes: [./grafana/dashboards:/var/lib/grafana/dashboards]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: cluster

volumes:
  postgres_data:
```

**Service map:**
| Service | URL |
|---|---|
| FastAPI + Swagger | http://localhost:8000/docs |
| React Frontend | http://localhost:3000 |
| MLflow UI | http://localhost:5000 |
| Prefect UI | http://localhost:4200 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |

---

## 7. Prometheus Alert Rules

```yaml
# Grafana alerts
- "clusterops_drift_psi_score > 0.20"              -> "Drift detected"
- "histogram_quantile(0.95, ...) > 0.5"            -> "p95 latency > 500ms SLA"
- "rate(clusterops_low_confidence_total[5m]) > 0.3" -> "High low-confidence match rate"
```

---

## 8. Environment Variables (`.env.example`)

```bash
DATABASE_URL=postgresql+asyncpg://cluster:cluster@postgres:5432/clusterops
MLFLOW_TRACKING_URI=http://mlflow:5000
GEMINI_API_KEY=your-gemini-api-key-here
PREFECT_API_URL=http://prefect:4200/api
LOG_LEVEL=INFO
CONFIDENCE_THRESHOLD=0.70
DRIFT_PSI_WARNING=0.10
DRIFT_PSI_ALERT=0.20
PROMOTION_GATE_IMPROVEMENT=0.03
```

---

## 9. Key Engineering Decisions (Interview Talking Points)

| Decision | Rationale |
|---|---|
| **Naive baseline always logged** | Complex model that can't beat same-day-last-week isn't worth deploying |
| **Time-based split, never random** | Random splits leak the future in time-series |
| **One shared `features.py`** | Prevents training/serving skew — #1 source of production ML bugs |
| **rapidfuzz first, Gemini only on ambiguous tokens** | Controls API cost; cost-per-order is documented in README |
| **Human review queue for confidence < 0.50** | Pharma orders need a safe fallback — wrong medicine is dangerous |
| **Promotion gate (3% improvement rule)** | No worse model ever reaches production |
| **PSI for drift** | Interpretable, industry-standard, works without ground-truth labels |
| **Async FastAPI + asyncpg** | Non-blocking DB calls; supports p95 latency < 500ms target |

---

## 10. Testing Strategy

```
tests/
  test_data_generator.py -> synthetic order & catalogue generation, demand shock injection
  test_forecast.py       -> train on synthetic data, assert MAE < naive baseline
  test_match_order.py    -> golden set 100+ orders (English / Arabic / Franco-Arabic / typos)
  test_drift.py          -> inject demand shock, assert PSI > 0.20 detected
  test_retrain.py        -> full flow: drift -> retrain -> gate -> promote/reject
  test_api.py            -> httpx async client, all endpoints return correct Pydantic schemas
  test_e2e_workflow.py   -> complete end-to-end integration test across all services
  benchmark_load.py      -> concurrency & load benchmark asserting p95 latency < 500ms
```

Run: `pytest backend/tests/ -v --asyncio-mode=auto`

---

## 11. Honesty Checklist

- [ ] README: "prototype on fully synthetic data"
- [ ] Can explain MAE, RMSE, MAPE, PSI in 30 seconds each
- [ ] Gemini API cost-per-order measured and documented
- [ ] Never claim Cluster's real order volumes, prices, or internal architecture
- [ ] Closing interview discussion: *"With your real data and ERP, the first thing I'd do is calibrate the fuzzy threshold on your actual catalogue size."*
