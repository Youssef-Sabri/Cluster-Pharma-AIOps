# Phase 6: Integration Testing, Docker Verification & Self-Directed Testing

> **Objective**: Validate the entire backend system end-to-end across Docker Compose, execute comprehensive integration test suites, confirm latency SLAs, and provide direct manual testing procedures for the user to test endpoints independently via Swagger UI, curl, and PowerShell.

---

## 1. Deliverables Checklist

- [x] Multi-container Docker Compose stack:
  - `docker-compose.yml` spins up `frontend`, `backend`, `postgres`, `mlflow`, `prometheus`, and `grafana`.
  - Service healthchecks and container dependency ordering (`condition: service_healthy`).
- [x] End-to-end operational workflow verification:
  - Ingests synthetic historical orders and preloads the 60-SKU catalogue on startup.
  - Verifies production LightGBM model registration in MLflow.
  - Submits messy bilingual orders through `/api/v1/match-order` and checks database persistence.
  - Injects simulated demand shock via API and verifies statistical drift detection ($\text{PSI} \ge 0.20$).
  - Triggers automated Prefect retraining flow and enforces the 3% promotion gate.
- [x] Latency & Performance SLA compliance:
  - Sub-millisecond fuzzy matching via `rapidfuzz` ($< 1\text{ ms}$).
  - Online forecast inference p95 latency strictly $< 500\text{ ms}$.
- [x] Direct manual testing procedures (Swagger UI at `/docs`, PowerShell, and curl snippets) for independent self-testing directly against the live containerized stack.

---

## 2. Technical Specifications

### 2.1 Complete Service Dependency Graph
```
                          ┌────────────────────┐
                          │   PostgreSQL 15    │
                          │   (Port 5432)      │
                          └─────────┬──────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                    ▼
        ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
        │  MLflow UI   │     │   FastAPI    │     │   Prefect    │
        │ (Port 5000)  │     │ (Port 8000)  │     │ Retrain Flow │
        └──────────────┘     └──────┬───────┘     └──────────────┘
                                    │
                             /metrics scrape
                                    │
                                    ▼
                             ┌──────────────┐
                             │  Prometheus  │
                             │ (Port 9090)  │
                             └──────┬───────┘
                                    │
                                    ▼
                             ┌──────────────┐
                             │   Grafana    │
                             │ (Port 3001)  │
                             └──────────────┘
```

### 2.2 Latency SLA Targets
| Endpoint | Target p50 | Target p95 | Hard Ceiling |
|---|---|---|---|
| `GET /health` | $< 5\text{ ms}$ | $< 15\text{ ms}$ | $50\text{ ms}$ |
| `POST /api/v1/forecast` | $< 80\text{ ms}$ | $< 250\text{ ms}$ | $500\text{ ms}$ |
| `POST /api/v1/match-order` (Fuzzy) | $< 10\text{ ms}$ | $< 50\text{ ms}$ | $150\text{ ms}$ |
| `POST /api/v1/match-order` (Gemini) | $< 400\text{ ms}$ | $< 900\text{ ms}$ | $1500\text{ ms}$ |
| `GET /api/v1/drift-status` | $< 30\text{ ms}$ | $< 100\text{ ms}$ | $300\text{ ms}$ |

---

## 3. Step-by-Step Testing & Verification Instructions

1. **Spin Up Dockerized Stack**:
   Verify all network bridges, port mappings, and environment variables in `.env` mount cleanly across all service containers:
   ```bash
   docker compose up -d
   ```

2. **Verify Container Healthchecks**:
   Ensure all 6 services are active and reporting healthy:
   ```bash
   docker compose ps
   ```

3. **Verify Observability & Telemetry**:
   - Prometheus metrics endpoint: `curl http://localhost:8000/metrics`
   - Grafana dashboard: `http://localhost:3001` (login: `admin` / `cluster`)
   - MLflow Model Registry: `http://localhost:5000`

4. **Self-Directed Endpoint Testing**:
   Test each endpoint independently using Swagger UI or terminal commands:

   - **Interactive Swagger UI**: Open `http://localhost:8000/docs` in your browser.
   - **Health check**:
     ```powershell
     Invoke-RestMethod -Uri "http://localhost:8000/health"
     ```
   - **Order matching (Clara-style)**:
     ```powershell
     Invoke-RestMethod -Uri "http://localhost:8000/api/v1/match-order" -Method Post -ContentType "application/json" -Body '{"pharmacy_id": "PH-001", "raw_text": "10 panadol extra w 5 augmentn 625"}'
     ```
   - **Demand forecast**:
     ```powershell
     Invoke-RestMethod -Uri "http://localhost:8000/api/v1/forecast" -Method Post -ContentType "application/json" -Body '{"pharmacy_id": "PH-001", "product_ids": ["panadol-500", "augmentin-625"], "forecast_horizon_days": 7}'
     ```
   - **Drift status check**:
     ```powershell
     Invoke-RestMethod -Uri "http://localhost:8000/api/v1/drift-status"
     ```
   - **Retraining flow dispatch**:
     ```powershell
     Invoke-RestMethod -Uri "http://localhost:8000/api/v1/retrain" -Method Post -ContentType "application/json" -Body '{"force": true}'
     ```

---

## 4. Acceptance Criteria

- Full pytest test suite passes 100% green (`pytest backend/tests/ -v`).
- p95 latency under load remains strictly $< 500\text{ ms}$.
- All endpoints respond with valid schemas on `http://localhost:8000`.
- MLflow, Prometheus, and Grafana are all actively receiving metrics and tracking data.
