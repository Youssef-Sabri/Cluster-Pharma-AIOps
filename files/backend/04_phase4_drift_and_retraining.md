# Phase 4: AIOps Layer — Drift Detection & Automated Retraining

> **Objective**: Build the core AIOps infrastructure: automated statistical drift detection using the Population Stability Index (PSI), automated alert logging in PostgreSQL, and an end-to-end retraining pipeline orchestrated with Prefect that respects the strict 3% promotion gate.

---

## 1. Deliverables Checklist

- [x] `backend/app/ml/drift_detector.py`:
  - Robust Population Stability Index (PSI) implementation utilizing quantile binning with zero-frequency epsilon smoothing.
  - Calculation across core distributions:
    - `daily_units_sold` (sales volume shift)
    - `order_frequency` (pharmacy activity shift)
    - `avg_order_value_egp` (price/basket size shift)
    - `match_confidence` (catalogue drift / user language shift)
  - Status evaluation:
    - $\text{PSI} < 0.10 \rightarrow \text{OK}$
    - $0.10 \le \text{PSI} < 0.20 \rightarrow \text{WARNING}$
    - $\text{PSI} \ge 0.20 \rightarrow \text{DRIFT\_DETECTED}$
  - Asynchronous persistence of drift results to the `drift_logs` database table.
- [x] `backend/app/pipelines/retrain_flow.py`:
  - Prefect flow (`clusterops-nightly-retrain`) consisting of discrete tasks:
    1. `check_drift_task`: Compute latest PSI across monitored features.
    2. `decision_task`: Branch based on drift threshold or manual override flag.
    3. `extract_data_task`: Ingest the most recent 90-day window from PostgreSQL.
    4. `feature_pipeline_task`: Execute shared `build_features()` from `features.py`.
    5. `train_challenger_task`: Train new LightGBM forecaster.
    6. `evaluate_challenger_task`: Compute test MAE against current production model.
    7. `promotion_gate_task`: Transition challenger in MLflow to `Production` if MAE is $\ge 3\%$ better; otherwise `Archived`.
    8. `audit_log_task`: Update database records.
- [x] Automated injection script to simulate an antibiotic/antipyretic demand shock and test the alarm.
- [x] Unit & pipeline tests in `backend/tests/test_drift.py` and `backend/tests/test_retrain.py`.

---

## 2. Technical Specifications

### 2.1 Population Stability Index (PSI) Formula
$$\text{PSI} = \sum_{k=1}^{B} \left( P_k - Q_k \right) \times \ln\left( \frac{P_k}{Q_k} \right)$$
Where:
- $Q_k$: Expected percentage of samples in bin $k$ (Reference baseline dataset).
- $P_k$: Actual percentage of samples in bin $k$ (Current live inference window).
- Bins ($B=10$) are calculated on the reference dataset using deciles.
- Epsilon smoothing ($\epsilon = 10^{-4}$) is applied to prevent division by zero or infinite logarithms.

### 2.2 Retraining Decision Matrix
```
                    ┌─────────────────────────┐
                    │  Compute Current PSI    │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
          Max PSI < 0.20                  Max PSI >= 0.20
          (No action / OK)             (DRIFT_DETECTED Trigger)
                 │                               │
                 ▼                               ▼
          Exit Cleanly                 Train Challenger Model
                                                 │
                                                 ▼
                                        Evaluate vs Production
                                                 │
                                 ┌───────────────┴───────────────┐
                                 ▼                               ▼
                      Challenger MAE < Prod * 0.97     Challenger MAE >= Prod * 0.97
                                 │                               │
                                 ▼                               ▼
                         PROMOTE to Production            ARCHIVE Challenger
                        (MLflow stage transition)       (Keep current production)
```

---

## 3. Step-by-Step Implementation Instructions

1. **Implement Drift Detector**:
   In `backend/app/ml/drift_detector.py`, create the `DriftDetector` class.
   - Implement `calculate_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float`.
   - Implement `check_dataset_drift(reference_df, current_df)` evaluating all target features.
   - Implement `log_drift_to_db(db_session, drift_results)`.

2. **Construct Prefect Retraining Flow**:
   In `backend/app/pipelines/retrain_flow.py`, define tasks decorated with `@task` and the main workflow with `@flow(name="clusterops-nightly-retrain")`.
   - Ensure the flow can be executed both on a schedule and triggered programmatically via a function call with an optional `force=True` parameter.

3. **Verify Demand Shock Detection**:
   In `backend/tests/test_drift.py`:
   - Generate baseline normal data.
   - Generate demand-shocked data (+300% unit surge).
   - Assert `daily_units_sold` yields $\text{PSI} \ge 0.20$ and triggers `DRIFT_DETECTED`.

4. **Verify Retraining & Promotion Logic**:
   In `backend/tests/test_retrain.py`:
   - Run the flow with a synthetic challenger that beats the baseline and assert successful promotion in MLflow.
   - Run the flow with an inferior challenger and assert rejection/archival.

---

## 4. Verification & Acceptance Criteria

```bash
# 1. Run drift detection unit tests
pytest tests/test_drift.py -v

# 2. Run retraining pipeline tests
pytest tests/test_retrain.py -v

# 3. Trigger manual flow run via CLI
python -m app.pipelines.retrain_flow --force
```

**Success criteria**:
- Clean data produces $\text{PSI} < 0.10$ with status `OK`.
- Demand shock dataset reliably triggers $\text{PSI} \ge 0.20$ with status `DRIFT_DETECTED`.
- Retraining flow executes end-to-end without unhandled exceptions.
- Promotion gate strictly rejects models failing the 3% improvement threshold.
- All drift checks and retraining decisions are persisted to the PostgreSQL `drift_logs` table.
