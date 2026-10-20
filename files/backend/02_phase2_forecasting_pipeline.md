# Phase 2: Forecasting Pipeline & MLflow Tracking

> **Objective**: Implement the unified feature engineering module, build the LightGBM demand forecasting model with uncertainty intervals, enforce chronological evaluation against a naive baseline, and integrate MLflow for experiment tracking and model registration.

---

## 1. Deliverables Checklist

- [x] `backend/app/ml/features.py`:
  - Shared feature transformation function used for both training and online inference (`build_features(df, is_inference=False)`).
  - Lag features: `lag_1`, `lag_7`, `lag_14`.
  - Rolling window features: 7-day rolling mean and standard deviation.
  - Calendar signals: `day_of_week`, `is_egypt_weekend` (Friday/Saturday flag), `month`, `is_ramadan`.
  - Category encodings: `drug_category`, `pharmacy_tier`.
- [x] `backend/app/ml/forecast_model.py`:
  - Time-series split (strictly chronological: train on initial 80%, test on final 20%).
  - Core LightGBM Regressor (`objective='regression_l1'`) for median point prediction.
  - Two auxiliary LightGBM Quantile Regressors (`alpha=0.10` and `alpha=0.90`) for confidence bounds (lower/upper limits).
  - Evaluation metrics calculation: MAE, RMSE, MAPE.
  - Benchmark comparator evaluating model MAE against the naive baseline (same day last week).
  - Target: **$\ge 15\%$ lower MAE than the naive baseline**.
- [x] `backend/app/ml/mlflow_utils.py`:
  - Logging runs to MLflow server with parameters, metrics, and serialized model artifacts.
  - Auto-registration under model name `lgbm-demand-forecast`.
  - Promotion gate logic: compare challenger MAE vs active production model; promote to `Production` only if test MAE is at least 3% lower (`challenger_mae < production_mae * 0.97`).
- [x] Unit & integration tests in `backend/tests/test_forecast.py`.

---

## 2. Technical Specifications

### 2.1 Shared Feature Pipeline (`backend/app/ml/features.py`)
```python
def build_features(df: pd.DataFrame, is_inference: bool = False) -> pd.DataFrame:
    """
    Unified feature pipeline shared between training and inference to prevent skew.
    Computes lag features, rolling statistics, calendar indicators, and encodings.
    """
    df = df.sort_values(["pharmacy_id", "product_id", "date"]).copy()

    # Lags & Rolling
    for lag in [1, 7, 14]:
        df[f"lag_{lag}"] = df.groupby(["pharmacy_id", "product_id"])["units_sold"].shift(lag)

    df["rolling_mean_7d"] = (
        df.groupby(["pharmacy_id", "product_id"])["units_sold"]
        .transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    )
    df["rolling_std_7d"] = (
        df.groupby(["pharmacy_id", "product_id"])["units_sold"]
        .transform(lambda s: s.shift(1).rolling(7, min_periods=1).std())
        .fillna(0)
    )

    # Egyptian Calendar specifics
    df["day_of_week"] = df["date"].dt.dayofweek
    df["is_egypt_weekend"] = df["day_of_week"].isin([4, 5]).astype(int)  # Friday & Saturday
    df["month"] = df["date"].dt.month

    if not is_inference:
        # Drop rows with NaN from lag computations during training
        df = df.dropna(subset=["lag_14", "rolling_mean_7d"])

    return df
```

### 2.2 Model Training & Baseline Comparison
- **Naive Baseline**: $\hat{y}_t = y_{t-7}$ (the sales figure on the exact same day of the prior week).
- **LightGBM Objective**: L1 regression minimizes absolute error and is robust against synthetic outlier spikes.
- **Quantile Bounds**:
  - `lower_bound`: LightGBM trained with `objective='quantile'`, `alpha=0.10`.
  - `upper_bound`: LightGBM trained with `objective='quantile'`, `alpha=0.90`.

### 2.3 MLflow Registry & Promotion Rule
```python
def evaluate_and_register(challenger_metrics: dict, model_artifacts: dict) -> str:
    # 1. Log to active MLflow experiment
    # 2. Query MLflow for currently active 'Production' model version
    # 3. If no production model exists, promote challenger immediately
    # 4. If production model exists:
    #      if challenger.mae < current_prod.mae * 0.97:
    #          transition challenger to 'Production', previous to 'Archived'
    #      else:
    #          transition challenger to 'Archived'
```

---

## 3. Step-by-Step Implementation Instructions

1. **Implement Feature Pipeline**:
   Write `backend/app/ml/features.py`. Write a fast unit test verifying that applying features on a mock DataFrame creates exactly the expected columns and preserves chronological ordering.

2. **Build Training & Evaluation Logic**:
   In `backend/app/ml/forecast_model.py`, build the `DemandForecaster` class. Implement:
   - `train(train_df, val_df)`
   - `predict(inference_features_df)` returning predictions, lower bounds, and upper bounds.
   - `evaluate(test_df)` returning MAE, RMSE, MAPE, and baseline MAE.

3. **Integrate MLflow Client**:
   Implement `backend/app/ml/mlflow_utils.py` connecting to `MLFLOW_TRACKING_URI` (`http://localhost:5000`). Ensure runs log LightGBM parameters (`learning_rate`, `num_leaves`, `max_depth`), metrics, and model tags.

4. **Add Unit & Integration Tests**:
   Write `backend/tests/test_forecast.py`:
   - Verify that training on seeded synthetic data completes within seconds.
   - Assert `model_mae < naive_baseline_mae * 0.85` (confirming $\ge 15\%$ improvement).
   - Verify that predictions output positive numbers and valid confidence intervals (`lower_bound <= predicted <= upper_bound`).

---

## 4. Verification & Acceptance Criteria

```bash
# Execute training script
python -m app.ml.forecast_model --train --register

# Run test suite
pytest tests/test_forecast.py -v
```

**Success criteria**:
- Model trains successfully on 180 days of synthetic data.
- Test MAE is at least 15% lower than naive baseline error.
- Experiment appears in MLflow UI at `http://localhost:5000/#/experiments` with tags, metrics, and parameters.
- Model `lgbm-demand-forecast` appears in MLflow Model Registry with version `1` tagged as `Production`.
