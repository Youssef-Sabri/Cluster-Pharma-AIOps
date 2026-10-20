# Phase 1: Environment Setup, Database Schema & Synthetic Data Generator

> **Objective**: Establish the core repository structure, configure PostgreSQL and MLflow via Docker Compose, set up Alembic migrations with the complete database schema, and implement a realistic Egyptian pharmaceutical synthetic data generator with a demand-shock toggle.

---

## 1. Deliverables Checklist

- [x] Root `docker-compose.yml` spinning up PostgreSQL 15 and MLflow.
- [x] Backend structure with `requirements.txt` containing pinned dependencies (FastAPI, SQLAlchemy 2, asyncpg, Alembic, LightGBM, rapidfuzz, google-genai / google-generativeai, mlflow, prefect, prometheus-client, pytest, httpx).
- [x] `backend/app/config.py` utilizing `pydantic-settings` to load `.env`.
- [x] `backend/app/database.py` with async SQLAlchemy engine and session dependency.
- [x] Alembic setup with an initial migration creating all 5 tables:
  - `drug_catalogue`
  - `orders`
  - `order_items`
  - `predictions`
  - `drift_logs`
- [x] `backend/app/pipelines/data_generator.py`:
  - Curated catalogue of 50+ Egyptian drugs (Panadol, Augmentin, Brufen, Congestal, Antinal, Cataflam, etc.) with brand, generic, Arabic, Franco-Arabic names, strengths, forms, and EGP prices.
  - 50 synthetic pharmacies across Egyptian governorates (Cairo, Giza, Alexandria, Gharbia, etc.).
  - 180 days of order history with Egyptian seasonality (Friday/Saturday weekend drop, winter flu spikes, Ramadan pattern).
  - Configurable `simulate_demand_shock` flag (multiplies antibiotic & antipyretic demand by 3x-4x for drift simulation).
  - Calculation and logging of the naive baseline (same day last week).
- [x] CLI command to seed the database: `python -m app.pipelines.data_generator --seed`.
- [x] Unit tests in `backend/tests/test_data_generator.py` verifying data realism and database persistence.

---

## 2. Technical Specifications

### 2.1 Pinned Dependencies (`backend/requirements.txt`)
```text
fastapi==0.115.0
uvicorn[standard]==0.31.0
pydantic==2.9.2
pydantic-settings==2.5.2
sqlalchemy==2.0.35
asyncpg==0.29.0
alembic==1.13.3
psycopg2-binary==2.9.9
lightgbm==4.5.0
scikit-learn==1.5.2
numpy==1.26.4
pandas==2.2.3
scipy==1.14.1
rapidfuzz==3.10.0
google-genai==0.1.1
mlflow==2.16.2
prefect==3.0.4
prometheus-client==0.21.0
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
python-dotenv==1.0.1
```

### 2.2 Database Table Schemas
Ensure tables match the technical plan specification with proper indexes:
- `drug_catalogue`: Primary key `catalogue_id` (varchar), indexed on `brand_name` and `franco_arabic`.
- `orders`: Primary key `id` (UUID), `pharmacy_id`, `raw_text`, `created_at` (indexed).
- `order_items`: Primary key `id` (UUID), foreign key `order_id` (cascade delete), `raw_token`, `catalogue_id`, `quantity`, `confidence`, `match_method`, `needs_review` (indexed boolean).
- `predictions`: Primary key `id` (UUID), indexed on `(pharmacy_id, product_id, forecast_date)`.
- `drift_logs`: Primary key `id` (UUID), `checked_at` (indexed), `feature_name`, `psi_score`, `status`, `retraining_triggered`.

---

## 3. Step-by-Step Implementation Instructions

1. **Docker Compose Setup**:
   Create `docker-compose.yml` at the repository root defining `postgres` (with healthcheck) and `mlflow` (using postgres as backend store).

2. **Configuration & Database Engine**:
   Implement `backend/app/config.py` and `backend/app/database.py`. Ensure async connection strings format:
   `postgresql+asyncpg://cluster:cluster@localhost:5432/clusterops`.

3. **SQLAlchemy Models & Alembic Migration**:
   Define declarative models under `backend/app/models/`. Run `alembic init -t async alembic`, configure `target_metadata = Base.metadata`, and generate the migration script.

4. **Synthetic Data Engine**:
   In `backend/app/pipelines/data_generator.py`:
   - Define Egyptian drug items with authentic dosages (e.g., `Panadol Extra 500mg`, `Augmentin 1g`, `Cataflam 50mg`, `Antinal 200mg`).
   - Implement volume generation using Poisson/Negative Binomial distributions combined with day-of-week multipliers:
     - Friday multiplier: `0.45` (Egyptian weekend slowdown).
     - Saturday multiplier: `0.70`.
     - Midweek multiplier: `1.15`.
   - Implement the `demand_shock` mode generating high-magnitude distribution shift.

5. **Seed Execution**:
   Verify database population by running the seed script and confirming row counts via an async test.

---

## 4. Verification & Acceptance Criteria

```bash
# 1. Start database and MLflow services
docker compose up -d postgres mlflow

# 2. Run database migrations
cd backend && alembic upgrade head

# 3. Seed synthetic database
python -m app.pipelines.data_generator --seed --days 180

# 4. Execute unit tests
pytest tests/test_data_generator.py -v
```

**Success criteria**:
- PostgreSQL starts healthy and responds on port 5432.
- MLflow UI is reachable at `http://localhost:5000`.
- All tables created via Alembic migrations.
- `drug_catalogue` has $\ge 50$ distinct pharmaceutical products.
- `orders` has at least 5,000 synthetic historical orders.
- Naive baseline error benchmark is computed and printed to console.
