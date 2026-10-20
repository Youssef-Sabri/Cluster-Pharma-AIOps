"""LightGBM demand forecaster with quantile prediction intervals.

Design decisions, all traceable to the phase specification:

* **Chronological split only.**  The panel is cut on the calendar at 80 %;
  a random split would leak the future through lag features.
* **L1 objective** (``regression_l1``) for the point forecast — robust against
  the demand spikes injected by the shock scenario.
* **Two quantile regressors** (alpha 0.10 / 0.90) give the prediction interval;
  bounds are ordered and non-negative by construction.
* **Naive benchmark.**  ``y_{t-7}`` (same day last week) is scored on exactly
  the same rows so the comparison is apples-to-apples, and a challenger must
  beat it by at least 15 % to be considered deployable.

Features come exclusively from :func:`app.ml.features.build_features` — the
training path here and the serving path in the API call the same function, so
there is no train/serve skew.

Synthetic data only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from app.config import settings
from app.database import async_session_factory
from app.logging_config import configure_logging, get_logger
from app.ml.dataset import EmptyPanelError, load_demand_panel, panel_summary
from app.ml.features import (
    DEFAULT_TEST_FRACTION,
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    FeatureSchemaError,
    build_features,
    feature_matrix,
    split_chronologically,
)
from app.ml.mlflow_utils import MODEL_NAME, MlflowUnavailableError, TrainingArtifacts, evaluate_and_register

logger: Final[logging.Logger] = get_logger("ml.forecast_model")

#: Quantile levels for the prediction interval (10th and 90th percentile).
LOWER_ALPHA: Final[float] = 0.10
UPPER_ALPHA: Final[float] = 0.90

#: A deployable model must beat the naive baseline by at least this fraction.
REQUIRED_IMPROVEMENT_OVER_BASELINE: Final[float] = 0.15

#: MAPE is undefined for zero demand; such rows are excluded from the average.
MAPE_EPSILON: Final[float] = 1e-8

#: Fraction of the training window held out for early stopping.
VALIDATION_FRACTION: Final[float] = 0.15

#: Default LightGBM hyperparameters (logged to MLflow on every run).
DEFAULT_PARAMS: Final[dict[str, Any]] = {
    "objective": "regression_l1",
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 20,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "reg_alpha": 0.1,
    "reg_lambda": 0.5,
    "random_state": 42,
    "n_jobs": -1,
    # Reproducible training, independent of the thread count.
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
}


class ModelNotTrainedError(RuntimeError):
    """Raised when :meth:`DemandForecaster.predict` is called before training."""


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def mean_absolute_percentage_error(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = MAPE_EPSILON) -> float:
    """MAPE over rows with non-zero demand.

    Percentage error is unbounded when actual demand is zero, so those rows are
    excluded (the naive baseline is compared on identical rows regardless).
    """
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    mask = np.abs(actual) > epsilon
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])))


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Return MAE, RMSE and MAPE for one set of predictions."""
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "mape": mean_absolute_percentage_error(actual, predicted),
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Metrics for one chronological holdout, model vs. naive baseline."""

    mae: float
    rmse: float
    mape: float
    naive_mae: float
    naive_rmse: float
    naive_mape: float
    vs_baseline_improvement_pct: float
    observations: int
    coverage_80pct: float
    interval_valid_share: float
    test_start: str
    test_end: str
    train_rows: int
    test_rows: int
    per_product_mae: dict[str, float] = field(default_factory=dict)

    def as_metrics(self) -> dict[str, float]:
        """Flat, scalar metric dictionary for MLflow."""
        return {
            "mae": self.mae,
            "rmse": self.rmse,
            "mape": self.mape,
            "baseline_mae": self.naive_mae,
            "baseline_rmse": self.naive_rmse,
            "baseline_mape": self.naive_mape,
            "vs_baseline_improvement_pct": self.vs_baseline_improvement_pct,
            "observations": float(self.observations),
            "interval_coverage_80pct": self.coverage_80pct,
            "interval_valid_share": self.interval_valid_share,
            "per_product_mae_count": float(len(self.per_product_mae)),
        }


# ---------------------------------------------------------------------------
# Forecaster
# ---------------------------------------------------------------------------


class DemandForecaster:
    """LightGBM demand forecaster: median point forecast + 10/90 % interval.

    Typical use::

        forecaster = DemandForecaster()
        report = forecaster.train(panel)
        predictions = forecaster.predict(panel)

    ``train`` accepts the *raw* daily panel; feature engineering, the
    chronological split and the naive benchmark all happen inside, so no caller
    can accidentally feed the model a leaky frame.
    """

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        *,
        test_fraction: float = DEFAULT_TEST_FRACTION,
        early_stopping_rounds: int = 50,
    ) -> None:
        self.params: dict[str, Any] = {**DEFAULT_PARAMS, **(params or {})}
        self.test_fraction = test_fraction
        self.early_stopping_rounds = early_stopping_rounds

        self.point_model: lgb.LGBMRegressor | None = None
        self.lower_model: lgb.LGBMRegressor | None = None
        self.upper_model: lgb.LGBMRegressor | None = None
        self.feature_names: tuple[str, ...] = FEATURE_COLUMNS
        self.report: EvaluationReport | None = None
        self._categorical_dtypes: dict[str, Any] = {}

    # -- feature plumbing --------------------------------------------------
    def _prepare(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Run the shared feature pipeline, remembering the categorical dtypes."""
        featured = build_features(panel, is_inference=False)
        self._categorical_dtypes = {
            column: featured[column].dtype
            for column in ("product_category", "pharmacy_tier")
            if column in featured.columns
        }
        return featured

    def _align_categoricals(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Re-apply the *training* category vocabularies to a serving frame.

        Pandas encodes categoricals by category order, so a frame carrying a
        different category set would silently scramble the encoding.  Reusing
        the dtypes captured during training is what makes online inference
        numerically identical to the offline pipeline.
        """
        aligned = frame.copy()
        for column, dtype in self._categorical_dtypes.items():
            if column in aligned.columns:
                aligned[column] = aligned[column].astype(dtype)
        return aligned

    # -- training ----------------------------------------------------------
    def train(self, panel: pd.DataFrame) -> EvaluationReport:
        """Fit the point and quantile models and score them on the holdout.

        Parameters
        ----------
        panel:
            Raw daily panel (``pharmacy_id, product_id, date, units_sold`` plus
            the optional context columns).

        Returns
        -------
        EvaluationReport
            Model metrics *and* the naive-baseline metrics on identical rows.
        """
        featured = self._prepare(panel)
        train_frame, test_frame = split_chronologically(featured, test_fraction=self.test_fraction)

        # Carve a validation slice off the end of the training window for early
        # stopping.  Still strictly chronological — nothing is shuffled.
        validation_rows = max(1, int(len(train_frame) * VALIDATION_FRACTION))
        if len(train_frame) > validation_rows:
            fit_frame = train_frame.iloc[:-validation_rows]
            validation_frame = train_frame.iloc[-validation_rows:]
        else:
            fit_frame = validation_frame = train_frame

        x_fit = feature_matrix(fit_frame)
        y_fit = fit_frame[TARGET_COLUMN].to_numpy(dtype=float)
        x_valid = feature_matrix(validation_frame)
        y_valid = validation_frame[TARGET_COLUMN].to_numpy(dtype=float)
        categorical = list(self._categorical_dtypes)

        self.point_model = self._fit_booster(
            {**self.params, "objective": "regression_l1"},
            x_fit, y_fit, x_valid, y_valid,
            eval_metric="l1", categorical=categorical,
        )
        self.lower_model = self._fit_booster(
            {**self.params, "objective": "quantile", "alpha": LOWER_ALPHA},
            x_fit, y_fit, x_valid, y_valid,
            eval_metric="quantile", categorical=categorical,
        )
        self.upper_model = self._fit_booster(
            {**self.params, "objective": "quantile", "alpha": UPPER_ALPHA},
            x_fit, y_fit, x_valid, y_valid,
            eval_metric="quantile", categorical=categorical,
        )

        self.report = self.evaluate(test_frame, train_rows=len(fit_frame) + len(validation_frame))
        logger.info(
            "Forecaster trained",
            extra={
                "mae": round(self.report.mae, 4),
                "baseline_mae": round(self.report.naive_mae, 4),
                "improvement_pct": round(self.report.vs_baseline_improvement_pct, 2),
                "train_rows": self.report.train_rows,
                "test_rows": self.report.test_rows,
            },
        )
        return self.report

    def _fit_booster(
        self,
        params: dict[str, Any],
        x_fit: pd.DataFrame,
        y_fit: np.ndarray,
        x_valid: pd.DataFrame,
        y_valid: np.ndarray,
        *,
        eval_metric: str,
        categorical: Sequence[str],
    ) -> lgb.LGBMRegressor:
        """Fit one booster with early stopping on the chronological holdout slice."""
        model = lgb.LGBMRegressor(**params)
        model.fit(
            x_fit,
            y_fit,
            eval_set=[(x_valid, y_valid)],
            eval_metric=eval_metric,
            categorical_feature=list(categorical) if categorical else "auto",
            callbacks=[lgb.early_stopping(self.early_stopping_rounds, verbose=False), lgb.log_evaluation(0)],
        )
        return model

    # -- serving -----------------------------------------------------------
    def attach_boosters(
        self, point: Any, lower: Any, upper: Any, *, categorical_dtypes: dict[str, Any] | None = None
    ) -> None:
        """Adopt already-fitted boosters for prediction.

        The serving counterpart of :meth:`train`.  A model restored from MLflow
        arrives as three :class:`lightgbm.Booster` objects, and rather than
        reimplementing :meth:`predict` in the API layer this attaches them so the
        online path uses the *same* code — clipping, interval ordering and the
        canonical feature matrix — as the offline evaluation.  That is what keeps
        train/serve skew at zero on the prediction side too.

        Parameters
        ----------
        point, lower, upper:
            Fitted boosters for the median forecast and the 10 % / 90 % quantiles.
        categorical_dtypes:
            Category vocabularies captured at training time.  ``build_features``
            already pins them, so passing ``None`` is correct and only makes the
            alignment a no-op.
        """
        self.point_model = point
        self.lower_model = lower
        self.upper_model = upper
        self._categorical_dtypes = dict(categorical_dtypes or {})

    def is_loaded(self) -> bool:
        """``True`` when all three boosters are present and predictions can run."""
        return self.point_model is not None and self.lower_model is not None and self.upper_model is not None

    # -- inference ---------------------------------------------------------
    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Predict demand with an 80 % interval.

        Parameters
        ----------
        frame:
            Either a raw panel or an already-engineered feature frame.  Raw
            frames go through the shared pipeline; engineered frames are used
            as-is (after categorical alignment) so the serving path can never
            rebuild features differently.

        Returns
        -------
        pandas.DataFrame
            ``pharmacy_id, product_id, date, predicted_units, lower_bound,
            upper_bound`` with ``0 <= lower_bound <= predicted_units <= upper_bound``.
        """
        if self.point_model is None or self.lower_model is None or self.upper_model is None:
            raise ModelNotTrainedError("call train() before predict()")

        engineered = self._ensure_engineered(frame)
        matrix = feature_matrix(self._align_categoricals(engineered))

        point = np.clip(self.point_model.predict(matrix), 0.0, None)
        lower = np.clip(self.lower_model.predict(matrix), 0.0, None)
        upper = np.clip(self.upper_model.predict(matrix), 0.0, None)

        # Enforce interval ordering without distorting the point forecast.
        lower = np.minimum(lower, point)
        upper = np.maximum(upper, point)

        return pd.DataFrame(
            {
                "pharmacy_id": engineered["pharmacy_id"].to_numpy(),
                "product_id": engineered["product_id"].to_numpy(),
                "date": pd.to_datetime(engineered["date"]).to_numpy(),
                "predicted_units": point,
                "lower_bound": lower,
                "upper_bound": upper,
            }
        )

    def _ensure_engineered(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Accept raw panels and engineered frames interchangeably."""
        if all(column in frame.columns for column in FEATURE_COLUMNS):
            return frame
        try:
            return build_features(frame, is_inference=True)
        except FeatureSchemaError as exc:
            raise FeatureSchemaError(
                f"frame is neither an engineered feature frame (missing "
                f"{[c for c in FEATURE_COLUMNS if c not in frame.columns]}) nor a raw panel "
                f"(needs pharmacy_id, product_id, date, units_sold)"
            ) from exc

    def forecast_horizon(
        self, history: pd.DataFrame, forecast_dates: Sequence[date | pd.Timestamp]
    ) -> pd.DataFrame:
        """Forecast future days from observed history (the online serving path).

        Delegates feature creation to :func:`app.ml.features.build_inference_frame`,
        which reuses :func:`build_features` — the exact function used in training.
        """
        from app.ml.features import build_inference_frame

        return self.predict(build_inference_frame(history, forecast_dates))

    # -- evaluation --------------------------------------------------------
    def evaluate(self, test_frame: pd.DataFrame, *, train_rows: int = 0) -> EvaluationReport:
        """Score the fitted models against the naive baseline on ``test_frame``.

        ``test_frame`` must be the *engineered* holdout; the naive prediction is
        read straight from its own ``lag_7`` column, which guarantees both
        predictors are measured on exactly the same rows.
        """
        if self.point_model is None:
            raise ModelNotTrainedError("call train() before evaluate()")

        predictions = self.predict(test_frame)
        actual = test_frame[TARGET_COLUMN].to_numpy(dtype=float)
        naive = test_frame["lag_7"].to_numpy(dtype=float)

        model_metrics = regression_metrics(actual, predictions["predicted_units"].to_numpy())
        naive_metrics = regression_metrics(actual, naive)
        improvement = (
            (naive_metrics["mae"] - model_metrics["mae"]) / naive_metrics["mae"] * 100.0
            if naive_metrics["mae"] > 0
            else float("nan")
        )

        lower = predictions["lower_bound"].to_numpy()
        point = predictions["predicted_units"].to_numpy()
        upper = predictions["upper_bound"].to_numpy()
        scored = predictions.assign(actual=actual)

        per_product = {
            str(product_id): float(mean_absolute_error(group["actual"], group["predicted_units"]))
            for product_id, group in scored.groupby("product_id", sort=False)
        }

        return EvaluationReport(
            mae=model_metrics["mae"],
            rmse=model_metrics["rmse"],
            mape=model_metrics["mape"],
            naive_mae=naive_metrics["mae"],
            naive_rmse=naive_metrics["rmse"],
            naive_mape=naive_metrics["mape"],
            vs_baseline_improvement_pct=improvement,
            observations=int(len(actual)),
            coverage_80pct=float(((actual >= lower) & (actual <= upper)).mean()),
            interval_valid_share=float(((lower <= point) & (point <= upper)).mean()),
            test_start=str(pd.to_datetime(test_frame["date"]).min().date()),
            test_end=str(pd.to_datetime(test_frame["date"]).max().date()),
            train_rows=int(train_rows),
            test_rows=int(len(actual)),
            per_product_mae=dict(sorted(per_product.items(), key=lambda item: item[1], reverse=True)[:25]),
        )

    # -- reporting ---------------------------------------------------------
    def artifacts(self) -> TrainingArtifacts:
        """Package the three boosters for MLflow logging."""
        if self.point_model is None or self.lower_model is None or self.upper_model is None:
            raise ModelNotTrainedError("call train() before artifacts()")
        return TrainingArtifacts(
            point_model=self.point_model,
            lower_model=self.lower_model,
            upper_model=self.upper_model,
            feature_names=list(self.feature_names),
            best_iterations={
                "point": int(getattr(self.point_model, "best_iteration_", 0) or 0),
                "lower": int(getattr(self.lower_model, "best_iteration_", 0) or 0),
                "upper": int(getattr(self.upper_model, "best_iteration_", 0) or 0),
            },
            model_params={key: value for key, value in self.params.items() if key != "verbose"},
        )


def requires_deployment(
    report: EvaluationReport, required_improvement: float = REQUIRED_IMPROVEMENT_OVER_BASELINE
) -> bool:
    """``True`` when the model beats the naive baseline by the required margin."""
    return report.vs_baseline_improvement_pct >= required_improvement * 100.0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def persist_forecast(session: Any, predictions: pd.DataFrame, *, model_version: str) -> int:
    """Write forecasts into the ``predictions`` table (chunked batch insert)."""
    from sqlalchemy import insert

    from app.models import Prediction

    rows = [
        {
            "pharmacy_id": str(row.pharmacy_id),
            "product_id": str(row.product_id),
            "forecast_date": pd.Timestamp(row.date).date(),
            "predicted_units": float(row.predicted_units),
            "lower_bound": float(row.lower_bound),
            "upper_bound": float(row.upper_bound),
            "model_version": model_version,
        }
        for row in predictions.itertuples(index=False)
    ]
    if not rows:
        return 0

    chunk_size = 2_000
    for start in range(0, len(rows), chunk_size):
        await session.execute(insert(Prediction), rows[start : start + chunk_size])
    await session.commit()
    logger.info("Forecast persisted", extra={"rows": len(rows), "model_version": model_version})
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _load_panel(days: int | None, min_series_units: int | None) -> pd.DataFrame:
    """Load the training panel from PostgreSQL (async DB access)."""
    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1) if days else None
    async with async_session_factory() as session:
        return await load_demand_panel(
            session,
            start_date=start_date,
            end_date=end_date + timedelta(days=1) if days else None,
            min_series_units=min_series_units if min_series_units is not None else 0,
        )


def report_horizon_start(report: EvaluationReport) -> date:
    """First day of the forecast horizon (the day after the holdout ends)."""
    return date.fromisoformat(report.test_end) + timedelta(days=1)


async def _train_async(forecaster: DemandForecaster, panel: pd.DataFrame) -> EvaluationReport:
    """Run the CPU-heavy fit off the event loop (async execution rule)."""
    return await asyncio.to_thread(forecaster.train, panel)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m app.ml.forecast_model`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.ml.forecast_model",
        description="Train the ClusterOps demand forecaster and (optionally) register it in MLflow. "
        "Synthetic data only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--train", action="store_true", help="Train and log the run to MLflow.")
    parser.add_argument("--register", action="store_true", help="Register the model and apply the promotion gate.")
    parser.add_argument("--days", type=int, default=None, help="Restrict training to the last N days of history.")
    parser.add_argument("--min-series-units", type=int, default=None, help="Activity threshold per series.")
    parser.add_argument("--experiment", default=None, help="MLflow experiment name.")
    parser.add_argument("--run-name", default=None, help="MLflow run name (default: timestamped).")
    parser.add_argument("--n-estimators", type=int, default=None, help="Override LightGBM n_estimators.")
    parser.add_argument("--num-leaves", type=int, default=None, help="Override LightGBM num_leaves.")
    parser.add_argument("--learning-rate", type=float, default=None, help="Override LightGBM learning_rate.")
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=None,
        help="LightGBM thread count (-1 = all cores). Pin to 1 on CPU-quota-limited or "
        "heavily loaded hosts, where OpenMP spin-waiting can dominate runtime.",
    )
    parser.add_argument(
        "--min-improvement",
        type=float,
        default=REQUIRED_IMPROVEMENT_OVER_BASELINE,
        help="Required improvement over the naive baseline, as a fraction.",
    )
    parser.add_argument("--persist", action="store_true", help="Write the next-day forecast into `predictions`.")
    parser.add_argument("--forecast-horizon", type=int, default=7, help="Horizon persisted with --persist.")
    parser.add_argument("--json-summary", type=Path, default=None, help="Write the run summary to this JSON file.")
    parser.add_argument("--quiet", action="store_true", help="Only log warnings and errors.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging()
    logger.setLevel(logging.WARNING if args.quiet else logging.INFO)

    try:
        # A single event loop owns every database interaction: the pooled engine
        # binds to the loop that first used it, so opening one loop per step
        # would fail with "got Future attached to a different loop".
        return asyncio.run(_run_pipeline(args))
    except EmptyPanelError as exc:
        logger.error("No training data available", exc_info=True, extra={"error": str(exc)})
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FeatureSchemaError, MlflowUnavailableError) as exc:
        logger.error("Training failed", exc_info=True, extra={"error": str(exc)})
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _param_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """LightGBM overrides requested on the command line."""
    overrides: dict[str, Any] = {}
    if args.n_estimators is not None:
        overrides["n_estimators"] = args.n_estimators
    if args.num_leaves is not None:
        overrides["num_leaves"] = args.num_leaves
    if args.learning_rate is not None:
        overrides["learning_rate"] = args.learning_rate
    if args.n_jobs is not None:
        overrides["n_jobs"] = args.n_jobs
    return overrides


async def _run_pipeline(args: argparse.Namespace) -> int:
    """Train, log, register and (optionally) persist a forecast."""
    try:
        run_name = args.run_name or f"forecast-{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        experiment = args.experiment or settings.mlflow_experiment_name

        # 1. Panel assembly is I/O bound (asyncpg).
        panel = await _load_panel(args.days, args.min_series_units)
        summary = panel_summary(panel)
        # 2. Training is CPU heavy -> keep it off the event loop.
        forecaster = DemandForecaster(_param_overrides(args))
        report = await _train_async(forecaster, panel)

        payload: dict[str, Any] = {
            "panel": summary,
            "metrics": report.as_metrics(),
            "required_improvement_pct": args.min_improvement * 100.0,
            "deployable": requires_deployment(report, args.min_improvement),
            "split": {"test_start": report.test_start, "test_end": report.test_end, "strategy": "chronological_80_20"},
            "params": {**forecaster.params, "test_fraction": forecaster.test_fraction},
            "model_name": MODEL_NAME,
            "run_name": run_name,
        }

        if not args.quiet:
            print(format_report(report, summary))

        if args.train or args.register:
            try:
                # MLflow calls are blocking I/O: kept off the loop like the training.
                run_result = await asyncio.to_thread(
                    evaluate_and_register,
                    experiment_name=experiment,
                    run_name=run_name,
                    metrics=report.as_metrics(),
                    params={**forecaster.params, **summary},
                    artifacts=forecaster.artifacts(),
                    tags={"feature_module": "app.ml.features.build_features", "split": "chronological_80_20"},
                    register=args.register,
                    model_name=MODEL_NAME,
                )
                payload["mlflow"] = {
                    "run_id": run_result.run_id,
                    "model_version": run_result.model_version,
                    "action": run_result.decision.action,
                    "reason": run_result.decision.reason,
                }
                if not args.quiet:
                    print(f" MLflow run   : {run_result.run_id}")
                    print(f" Registry    : {MODEL_NAME} version {run_result.model_version}")
                    print(f" Gate        : {run_result.decision.action} — {run_result.decision.reason}\n")
            except Exception as exc:  # noqa: BLE001 - CLI boundary: report, never traceback to the user
                logger.error("MLflow logging failed", exc_info=True, extra={"error": str(exc)})
                print(f"error: MLflow logging failed: {exc}", file=sys.stderr)
                return 3

        if args.persist:
            horizon = [report_horizon_start(report) + timedelta(days=offset) for offset in range(args.forecast_horizon)]
            history = panel.loc[pd.to_datetime(panel["date"]) <= pd.Timestamp(report.test_end)]
            forecast = await asyncio.to_thread(forecaster.forecast_horizon, history, horizon)
            model_version = str(payload.get("mlflow", {}).get("model_version") or "local")
            async with async_session_factory() as session:
                rows = await persist_forecast(session, forecast, model_version=model_version)
            payload["persisted_rows"] = rows
            if not args.quiet:
                print(f" Persisted {rows:,} forecast rows into `predictions`.\n")

        if args.json_summary:
            args.json_summary.parent.mkdir(parents=True, exist_ok=True)
            args.json_summary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        if not requires_deployment(report, args.min_improvement):
            logger.warning(
                "Model does not meet the deployment threshold",
                extra={
                    "improvement_pct": report.vs_baseline_improvement_pct,
                    "required_pct": args.min_improvement * 100.0,
                },
            )
            return 1
        return 0
    finally:
        from app.database import dispose_engine

        await dispose_engine()


def format_report(report: EvaluationReport, panel_stats: dict[str, Any]) -> str:
    """Render the training summary printed to the console."""
    worst = list(report.per_product_mae.items())[:5]
    return "\n".join(
        [
            "",
            "=" * 78,
            " ClusterOps — demand forecaster (synthetic data, demonstration purposes)",
            "=" * 78,
            f" Panel                  : {panel_stats['series']:,} series | {panel_stats['rows']:,} rows | "
            f"{panel_stats['start_date']} .. {panel_stats['end_date']}",
            f" Split (chronological) : train {report.train_rows:,} rows | test {report.test_start} .. "
            f"{report.test_end} ({report.test_rows:,} rows)",
            "-" * 78,
            f" Model MAE              : {report.mae:.4f}",
            f" Model RMSE             : {report.rmse:.4f}",
            f" Model MAPE             : {report.mape:.4%}",
            f" Naive MAE (t-7)        : {report.naive_mae:.4f}",
            f" Naive RMSE (t-7)       : {report.naive_rmse:.4f}",
            f" Improvement vs naive   : {report.vs_baseline_improvement_pct:.2f}%",
            f" 80% interval coverage  : {report.coverage_80pct:.2%} (nominal 80%)",
            f" Interval ordering ok   : {report.interval_valid_share:.2%}",
            "-" * 78,
            " Worst products by MAE  : " + ", ".join(f"{name}={value:.2f}" for name, value in worst),
            "=" * 78,
            "",
        ]
    )


__all__ = [
    "DEFAULT_PARAMS",
    "LOWER_ALPHA",
    "REQUIRED_IMPROVEMENT_OVER_BASELINE",
    "UPPER_ALPHA",
    "VALIDATION_FRACTION",
    "DemandForecaster",
    "EvaluationReport",
    "ModelNotTrainedError",
    "build_parser",
    "format_report",
    "main",
    "mean_absolute_percentage_error",
    "persist_forecast",
    "regression_metrics",
    "requires_deployment",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())