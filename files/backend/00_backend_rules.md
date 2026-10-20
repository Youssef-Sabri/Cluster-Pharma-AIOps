# ClusterOps — Backend Architecture Rules & Engineering Guidelines

> **Target**: Production-grade AIOps platform built with FastAPI, PostgreSQL, LightGBM, rapidfuzz, Gemini API, MLflow, Prefect, and Prometheus.
> **Scope**: Backend service only.

---

## 1. Absolute Cardinal Rules

1. **Synthetic Data Boundaries**:
   - Every single data point, pharmacy name, order, and catalogue entry **must be synthetic**.
   - Under no circumstances should real private data, real pharmacy names, or proprietary Cluster metrics be hardcoded, generated, or claimed.
   - All references in docstrings and READMEs must state: *"Synthetic data generated for demonstration purposes"*.

2. **No Training-Serving Skew**:
   - Feature engineering logic **must live in a single shared module**: `backend/app/ml/features.py`.
   - Never write feature extraction code inside the training script that is duplicated or modified inside the API inference router.
   - Any feature transformation applied during offline model training must be applied identically during online inference.

3. **Time-Series Integrity**:
   - Never use random train/test splits for forecasting datasets.
   - Splits must be strictly chronological (e.g., train on first 80% of days, evaluate on final 20%).
   - Future values must never leak into lag features or rolling aggregations.

4. **Strict Promotion Gate (3% Rule)**:
   - A newly trained challenger model can **only** replace the production model in MLflow if its test Mean Absolute Error (MAE) is at least **3% lower** than the current production model (`challenger.mae < production.mae * 0.97`).
   - If this condition is not met, the challenger is marked `Archived` and the reason logged.

5. **Human-in-the-Loop Pharma Safety**:
   - Any order matching item with a confidence score below `0.50` must be flagged with `needs_review = True` and routed to the `order_items` review table.
   - In pharma tech, incorrect automated fulfillment carries clinical risk; automated certainty is prioritized over forced matching.

---

## 2. Code Quality & Technical Standards

### Python & Environment
- **Python Version**: 3.11+.
- **Typing**: Strict type annotations on all function signatures, arguments, and return values (`typing` / `types`).
- **Async Execution**:
  - FastAPI endpoints must be `async def`.
  - Database access must use asynchronous sessions via `SQLAlchemy 2` and `asyncpg`.
  - Non-async CPU-heavy operations (e.g., LightGBM batch prediction or heavy fuzzy matching) must run via `asyncio.to_thread` or background workers to prevent blocking the event loop.

### API & Validation
- **Pydantic v2**:
  - Every API endpoint must have dedicated Pydantic `BaseModel` schemas for both request bodies and responses (`backend/app/schemas/`).
  - No raw dictionary manipulation in endpoint handlers.
  - Auto-generated Swagger documentation at `/docs` must display accurate schemas, response examples, and status codes (200, 202, 400, 404, 422, 500).

### Error Handling & Logging
- Use structured JSON logging (`structlog` or standard library formatted).
- Never catch generic `Exception` silently. Always log stack traces at `ERROR` level and return standard RFC 7807 problem details or clean Pydantic error responses.
- API endpoints must not expose internal database errors or unhandled tracebacks to clients.

### Database Conventions
- Primary keys must use `UUID` (`gen_random_uuid()`).
- All timestamps must be timezone-aware (`TIMESTAMPTZ`, default `NOW()`).
- Schema migrations must be managed exclusively with **Alembic**. No ad-hoc `Base.metadata.create_all()` in production code.

---

## 3. Directory Layout Standards

```
backend/
├── Dockerfile
├── requirements.txt
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── main.py                  # FastAPI initialization, CORS, router inclusion
│   ├── config.py                # Settings loaded via pydantic-settings
│   ├── database.py              # Async engine, sessionmaker, get_db dependency
│   ├── api/                     # Route definitions
│   │   ├── __init__.py
│   │   ├── health.py            # /health, /metrics
│   │   ├── forecast.py          # /api/v1/forecast
│   │   ├── match_order.py       # /api/v1/match-order
│   │   ├── drift.py             # /api/v1/drift-status
│   │   ├── retrain.py           # /api/v1/retrain
│   │   ├── registry.py          # /api/v1/model-registry
│   │   ├── review_queue.py      # /api/v1/orders/review-queue
│   │   └── state.py             # In-memory live serving state & catalogue cache
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── order.py
│   │   ├── prediction.py
│   │   ├── drift_log.py
│   │   └── drug_catalogue.py
│   ├── schemas/                 # Pydantic v2 schemas
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── forecast.py
│   │   ├── match_order.py
│   │   ├── drift.py
│   │   ├── registry.py
│   │   └── review_queue.py
│   ├── ml/                      # Machine learning core
│   │   ├── __init__.py
│   │   ├── features.py          # SINGLE SOURCE OF TRUTH for feature engineering
│   │   ├── dataset.py           # Time-series chronologically split datasets
│   │   ├── forecast_model.py    # LightGBM training, evaluation, quantile intervals
│   │   ├── text_processing.py   # Arabic/English token normalization
│   │   ├── order_matcher.py     # rapidfuzz + Gemini API re-ranker
│   │   ├── drift_detector.py    # PSI calculation & evaluation logic
│   │   ├── serving.py           # In-memory fast inference loader
│   │   └── mlflow_utils.py      # MLflow tracking, registry, 3% promotion gate
│   ├── pipelines/               # Orchestration & data pipelines
│   │   ├── __init__.py
│   │   ├── data_generator.py    # Synthetic Egyptian pharma dataset generator
│   │   └── retrain_flow.py      # Prefect retraining flow
│   └── monitoring/
│       ├── __init__.py
│       └── metrics.py           # Prometheus custom metrics & instrumentations
├── Dockerfile                   # Python 3.11-slim production container
├── requirements.txt             # Pinned production dependencies
└── alembic.ini                  # Alembic migration configuration
```

---

## 4. Operational Health & Verification
- The backend is packaged into a production Docker image (`clusterops/backend:1.0.0`) orchestrated by `docker-compose.yml`.
- Health and runtime integrity are continuously validated via:
  - `GET /health`: Asserts database connectivity and in-memory LightGBM model readiness.
  - `GET /metrics`: Custom Prometheus metrics exposition scraped every 15s.
  - Route contract validation using strict Pydantic v2 schemas across all inference and governance endpoints.
