"""Nightly retraining flow — the AIOps loop that closes on drift.

::

    check_drift_task ──▶ decision_task ──(clean)──▶ exit cleanly
          │                   │
          │                   └──(drift / force)──▶ extract_data_task
          │                                            │
          │                                            ▼
          │                                   feature_pipeline_task
          │                                            │
          │                                            ▼
          │                                   train_challenger_task
          │                                            │
          │                                            ▼
          │                                   evaluate_challenger_task
          │                                            │
          │                                            ▼
          │                                    promotion_gate_task ──▶ audit_log_task

Two engineering rules are load-bearing here and are asserted by the tests:

* **Zero train/serve skew** — :func:`feature_pipeline_task` calls the shared
  :func:`app.ml.features.build_features`, the same function the Phase 2 trainer
  and the Phase 5 inference router use.  The feature contract is never restated
  inside this module.
* **Strict 3 % promotion gate** — a challenger reaches ``Production`` only when
  ``challenger_mae < production_mae * 0.97``.  The rule itself lives in the pure
  function :func:`app.ml.mlflow_utils.evaluate_promotion`; this module only
  performs the registry side effects, so the policy has exactly one
  implementation shared with the manual training path.

Everything is ``async def``.  Prefect runs synchronous tasks in a worker thread
that still has the calling event loop attached, where :func:`asyncio.run` raises
``RuntimeError: asyncio.run() cannot be called from a running event loop``; async
tasks avoid that entirely and let the CPU-bound LightGBM fit be pushed to a
worker thread explicitly.

Synthetic data only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Sequence

import pandas as pd
from prefect import flow, get_run_logger, task
from prefect.exceptions import MissingContextError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import async_session_factory
from app.logging_config import configure_logging, get_logger
from app.ml.dataset import EmptyPanelError, load_demand_panel, panel_summary
from app.ml.drift_detector import (
    DEFAULT_CURRENT_WINDOW_DAYS,
    DEFAULT_REFERENCE_WINDOW_DAYS,
    DriftDetector,
    DriftReport,
    concat_feature_frames,
    daily_units_frame,
    load_monitored_features,
    log_drift_to_db,
    mark_retraining_triggered,
    split_windows,
)
from app.ml.features import build_features
from app.ml.forecast_model import DEFAULT_PARAMS, DemandForecaster, EvaluationReport
from app.ml.mlflow_utils import (
    MODEL_NAME,
    PromotionDecision,
    RegisteredModelVersion,
    evaluate_promotion,
    evaluate_and_register,
    get_production_model,
)
from app.models import Order

logger: Final[logging.Logger] = get_logger("pipelines.retrain_flow")

#: Training window ingested for a retraining run.
RETRAIN_WINDOW_DAYS: Final[int] = 90

#: LightGBM is pinned to one thread inside the flow.  The nightly job shares a
#: host with the API, and an unpinned OpenMP pool spins against every core while
#: the serving path is trying to answer requests; on CPU-quota-limited hosts
#: that spin-waiting is measurably slower than running sequentially.
TRAINING_N_JOBS: Final[int] = 1

#: Logged verbatim when the run exits without retraining.
NO_DRIFT_MESSAGE: Final[str] = "No drift detected; skipping retraining"

#: Message logged when a manual ``--force`` run overrides a clean drift report.
FORCED_MESSAGE: Final[str] = "Retraining forced by operator despite no drift"


def resolve_session_factory(session_factory: Any) -> async_sessionmaker[AsyncSession]:
    """Return the injected session factory, or the process-wide application one.

    Flow and task signatures declare the factory as ``Any`` defaulting to
    ``None`` rather than as ``async_sessionmaker[...]`` defaulting to the module
    singleton.  Prefect builds a pydantic model from every parameter of a
    decorated flow/task and *deep-copies* each default while doing so; a session
    factory bound to a live ``AsyncEngine`` is not deep-copyable and raises
    ``TypeError: cannot pickle 'module' object`` at import time.  Resolving the
    default here keeps the injection seam without breaking Prefect's schema
    generation.
    """
    return async_session_factory if session_factory is None else session_factory


def run_logger() -> logging.Logger:
    """Prefect's run logger inside a flow or task, the module logger outside one.

    Every task and the flow are plain ``async def`` coroutines underneath, so
    they can be awaited directly — which is how several tests exercise them in
    isolation, and how the CLI would behave if Prefect's context were absent.
    ``get_run_logger()`` raises :class:`MissingContextError` in that case, so
    this degrades to the structured module logger rather than failing.
    """
    try:
        return get_run_logger()
    except MissingContextError:
        return logger


# ---------------------------------------------------------------------------
# Task payload dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriftCheck:
    """A drift evaluation plus the ``drift_logs`` rows it wrote."""

    report: DriftReport
    log_ids: tuple[str, ...] = ()

    @property
    def drift_detected(self) -> bool:
        return self.report.drift_detected

    @property
    def max_psi(self) -> float:
        return self.report.max_psi

    def to_dict(self) -> dict[str, Any]:
        return {"report": self.report.to_dict(), "log_ids": list(self.log_ids)}


@dataclass(frozen=True, slots=True)
class RetrainDecision:
    """Whether the flow should proceed past the drift gate."""

    should_retrain: bool
    reason: str
    forced: bool
    max_psi: float
    drifting_features: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_retrain": self.should_retrain,
            "reason": self.reason,
            "forced": self.forced,
            "max_psi": round(self.max_psi, 6),
            "drifting_features": list(self.drifting_features),
        }


@dataclass(slots=True)
class TrainedChallenger:
    """A fitted forecaster plus its holdout metrics."""

    forecaster: Any
    report: EvaluationReport

    @property
    def mae(self) -> float:
        return self.report.mae

    @property
    def baseline_mae(self) -> float:
        return self.report.naive_mae

    @property
    def improvement_pct(self) -> float:
        return self.report.vs_baseline_improvement_pct


@dataclass(frozen=True, slots=True)
class ChallengerEvaluation:
    """Challenger scored against both the naive baseline and production."""

    trained: TrainedChallenger
    production: RegisteredModelVersion | None
    production_mae: float | None

    @property
    def challenger_mae(self) -> float:
        return self.trained.mae

    def predicted_decision(self, required_improvement: float) -> PromotionDecision:
        """The decision the gate *will* reach, computed without any I/O."""
        return evaluate_promotion(
            challenger_mae=self.challenger_mae,
            production_mae=self.production_mae,
            required_improvement=required_improvement,
            previous_version=self.production.version if self.production else None,
        )


@dataclass(frozen=True, slots=True)
class PromotionOutcome:
    """What the promotion gate actually did in the MLflow registry."""

    decision: PromotionDecision
    challenger_version: str | None
    run_id: str | None
    tracking_uri: str

    @property
    def promoted(self) -> bool:
        return self.decision.promoted

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.decision.action,
            "reason": self.decision.reason,
            "challenger_version": self.challenger_version,
            "run_id": self.run_id,
            "tracking_uri": self.tracking_uri,
        }


@dataclass(frozen=True, slots=True)
class RetrainOutcome:
    """Everything one flow run produced, for the CLI, logs and Phase 5 APIs."""

    ran: bool
    reason: str
    forced: bool
    max_psi: float
    drifting_features: tuple[str, ...]
    drift_log_ids: tuple[str, ...]
    audit_log_ids: tuple[str, ...] = ()
    panel: dict[str, Any] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    challenger_mae: float | None = None
    baseline_mae: float | None = None
    vs_baseline_pct: float | None = None
    production_mae: float | None = None
    production_version: str | None = None
    promotion: PromotionOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "reason": self.reason,
            "forced": self.forced,
            "max_psi": round(self.max_psi, 6),
            "drifting_features": list(self.drifting_features),
            "drift_log_ids": list(self.drift_log_ids),
            "audit_log_ids": list(self.audit_log_ids),
            "panel": self.panel,
            "features": self.features,
            "challenger_mae": self.challenger_mae,
            "baseline_mae": self.baseline_mae,
            "vs_baseline_pct": self.vs_baseline_pct,
            "production_mae": self.production_mae,
            "production_version": self.production_version,
            "promotion": self.promotion.to_dict() if self.promotion else None,
        }


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def _latest_order_day(session: AsyncSession) -> date | None:
    """Newest day present in the order ledger, or ``None`` when it is empty.

    ``max(created_at)`` on a ``TIMESTAMPTZ`` column returns a timezone-aware
    *datetime*, not a date, so it is converted explicitly.  Returning the raw
    aware value made every downstream calendar bound aware while the panel's own
    ``date`` column stays naive, which broke the panel densification.
    """
    latest = (await session.execute(select(func.max(Order.created_at)))).scalar()
    if latest is None:
        return None
    return pd.Timestamp(latest).date()


@task(name="check-drift", retries=0)
async def check_drift_task(
    reference_days: int = DEFAULT_REFERENCE_WINDOW_DAYS,
    current_days: int = DEFAULT_CURRENT_WINDOW_DAYS,
    session_factory: Any = None,
    end_date: date | None = None,
    detector: DriftDetector | None = None,
) -> DriftCheck:
    """Evaluate PSI for every monitored feature and persist the result.

    The current window is the most recent ``current_days`` days of the ledger;
    the reference is the ``reference_days`` immediately before it, so the
    baseline always describes the period *prior* to the one being judged.
    """
    run_log = run_logger()
    detector = detector or DriftDetector()
    factory = resolve_session_factory(session_factory)

    async with factory() as session:
        last_day = end_date or await _latest_order_day(session)
        if last_day is None:
            raise EmptyPanelError("the order ledger is empty — seed the database before monitoring drift")

        window_start = last_day - timedelta(days=reference_days + current_days - 1)
        frame = await load_monitored_features(session, start_date=window_start, end_date=last_day)

        # daily_units_sold needs the densified panel: the ledger has no rows for
        # zero-demand days, and those zeros are most of the distribution.
        panel = await load_demand_panel(session, start_date=window_start, end_date=last_day)
        frame = concat_feature_frames(frame, daily_units_frame(panel))

        reference, current = split_windows(
            frame, current_days=current_days, reference_days=reference_days
        )
        report = detector.check_dataset_drift(
            reference,
            current,
            reference_window=(reference["date"].min(), reference["date"].max())
            if not reference.empty
            else None,
            current_window=(current["date"].min(), current["date"].max())
            if not current.empty
            else None,
        )
        log_ids = tuple(await log_drift_to_db(session, report))

    run_log.info(
        f"Drift check: max PSI {report.max_psi:.4f} ({report.drifting_features or 'no drift'}); "
        f"logged {len(log_ids)} rows to drift_logs"
    )
    return DriftCheck(report=report, log_ids=log_ids)


@task(name="retrain-decision", retries=0)
async def decision_task(check: DriftCheck, force: bool = False) -> RetrainDecision:
    """Branch on drift or the manual override.

    ``force=True`` short-circuits the gate so an operator can retrain on demand;
    the drift evaluation still ran and is still logged, so the audit trail shows
    *why* a run happened.
    """
    run_log = run_logger()
    if check.drift_detected:
        decision = RetrainDecision(
            should_retrain=True,
            reason=(
                f"Drift detected on {', '.join(check.report.drifting_features)} "
                f"(max PSI {check.max_psi:.4f} >= {DriftDetector().alert_threshold:.2f})"
            ),
            forced=force,
            max_psi=check.max_psi,
            drifting_features=check.report.drifting_features,
        )
    elif force:
        decision = RetrainDecision(
            should_retrain=True,
            reason=f"{FORCED_MESSAGE} (max PSI {check.max_psi:.4f})",
            forced=True,
            max_psi=check.max_psi,
        )
    else:
        decision = RetrainDecision(
            should_retrain=False,
            reason=NO_DRIFT_MESSAGE,
            forced=False,
            max_psi=check.max_psi,
        )
    run_log.info(decision.reason)
    return decision


@task(name="extract-data", retries=0)
async def extract_data_task(
    days: int = RETRAIN_WINDOW_DAYS,
    session_factory: Any = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Ingest the most recent ``days`` of the demand panel."""
    run_log = run_logger()
    async with resolve_session_factory(session_factory)() as session:
        last_day = end_date or await _latest_order_day(session)
        if last_day is None:
            raise EmptyPanelError("the order ledger is empty — seed the database before retraining")
        panel = await load_demand_panel(
            session, start_date=last_day - timedelta(days=days - 1), end_date=last_day
        )
    summary = panel_summary(panel)
    run_log.info(
        f"Extracted {summary['rows']:,} rows | {summary['series']:,} series | "
        f"{summary['start_date']}..{summary['end_date']}"
    )
    return panel


@task(name="feature-pipeline", retries=0)
async def feature_pipeline_task(panel: pd.DataFrame) -> pd.DataFrame:
    """Engineer features through the shared module.

    Calls :func:`app.ml.features.build_features` — the single source of truth for
    training *and* serving.  Nothing about the feature contract is restated here;
    that is what keeps retraining free of train/serve skew.
    """
    run_log = run_logger()
    featured = await asyncio.to_thread(build_features, panel, False)
    run_log.info(f"Engineered {len(featured):,} feature rows from {len(panel):,} panel rows")
    return featured


@task(name="train-challenger", retries=0)
async def train_challenger_task(
    panel: pd.DataFrame,
    features: pd.DataFrame,
    n_jobs: int = TRAINING_N_JOBS,
    test_fraction: float | None = None,
    extra_params: dict[str, Any] | None = None,
) -> TrainedChallenger:
    """Fit the challenger LightGBM forecaster.

    Both the raw ``panel`` and the engineered ``features`` are passed.  The
    trainer deliberately fits from the **raw** panel, not from ``features``:

    ``build_features`` drops the warm-up rows whose ``lag_14`` is undefined, so
    it is *not* idempotent — feeding its own output back in discards a further
    ``MAX_LOOKBACK_DAYS`` (14) days from every series and silently shrinks the
    training window.  :meth:`DemandForecaster.train` re-derives the features from
    the raw panel exactly as the manual Phase 2 path does, so this flow trains on
    the same window as everything else.  ``features`` is carried to assert that
    the two agree rather than to shortcut the trainer.

    ``n_jobs=1`` by default: see :data:`TRAINING_N_JOBS`.

    Parameters
    ----------
    extra_params:
        LightGBM overrides layered on top of :data:`DEFAULT_PARAMS` (for example
        a smaller ``n_estimators`` for a fast verification run).  ``n_jobs`` is
        always applied last so the thread count cannot be overridden.
    """
    run_log = run_logger()
    if len(features) > len(panel):
        raise RuntimeError(
            f"engineered frame ({len(features)} rows) is larger than the panel "
            f"({len(panel)} rows); the feature contract is broken"
        )
    params: dict[str, Any] = {**DEFAULT_PARAMS, **(extra_params or {}), "n_jobs": n_jobs}
    forecaster = DemandForecaster(params, **({"test_fraction": test_fraction} if test_fraction else {}))

    # LightGBM fit is CPU bound; keep it off the event loop (async execution rule).
    report = await asyncio.to_thread(forecaster.train, panel)

    if forecaster.params.get("n_jobs") != n_jobs:  # pragma: no cover - defensive
        raise RuntimeError(f"thread count not applied: {forecaster.params.get('n_jobs')} != {n_jobs}")
    run_log.info(
        f"Challenger trained: MAE {report.mae:.4f} vs naive {report.naive_mae:.4f} "
        f"({report.vs_baseline_improvement_pct:+.2f}%) over {report.test_rows:,} holdout rows"
    )
    return TrainedChallenger(forecaster=forecaster, report=report)


@task(name="evaluate-challenger", retries=0)
async def evaluate_challenger_task(
    trained: TrainedChallenger,
    tracking_uri: str | None = None,
    registry_name: str = MODEL_NAME,
) -> ChallengerEvaluation:
    """Score the challenger against the naive baseline and the active champion.

    The naive comparison arrives free with the training report (both predictors
    are scored on identical rows); the production MAE is read from MLflow.
    """
    run_log = run_logger()
    # MLflow client calls are blocking network I/O — keep them off the loop.
    production = await asyncio.to_thread(get_production_model, registry_name)
    production_mae = production.test_mae if production else None

    run_log.info(
        f"Evaluation: challenger MAE {trained.mae:.4f} | naive {trained.baseline_mae:.4f} "
        f"({trained.improvement_pct:+.2f}%) | production "
        f"{'none' if production_mae is None else f'{production_mae:.4f} (v{production.version})'}"
    )
    return ChallengerEvaluation(
        trained=trained, production=production, production_mae=production_mae
    )


@task(name="promotion-gate", retries=0)
async def promotion_gate_task(
    evaluation: ChallengerEvaluation,
    experiment_name: str | None = None,
    tracking_uri: str | None = None,
    registry_name: str = MODEL_NAME,
    required_improvement: float | None = None,
    register_in_registry: bool = True,
    run_name: str | None = None,
    max_psi: float | None = None,
) -> PromotionOutcome:
    """Apply the 3 % rule and move the challenger in the MLflow registry.

    The gate itself is :func:`app.ml.mlflow_utils.evaluate_promotion` — the same
    pure function the Phase 2 manual path uses.  Registering the challenger and
    transitioning stages is delegated to
    :func:`app.ml.mlflow_utils.evaluate_and_register`, which re-derives the
    identical decision from the registry, so there is exactly one promotion
    policy in the codebase rather than two that can drift apart.
    """
    run_log = run_logger()
    improvement = (
        settings.promotion_gate_improvement if required_improvement is None else required_improvement
    )
    run_name = run_name or f"nightly-retrain-{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    # Provenance travels with the run so a registered model can be traced back
    # to the drift evaluation that caused it.
    params: dict[str, Any] = dict(evaluation.trained.forecaster.params)
    if max_psi is not None:
        params["drift_max_psi"] = round(float(max_psi), 6)

    if not register_in_registry:
        # Evaluate-only mode: apply the policy, touch no registry state.
        decision = evaluation.predicted_decision(improvement)
        run_log.info(f"Registration disabled; gate decision would be {decision.action}")
        return PromotionOutcome(
            decision=decision, challenger_version=None, run_id=None, tracking_uri=tracking_uri or ""
        )

    result = await asyncio.to_thread(
        evaluate_and_register,
        experiment_name=experiment_name or settings.mlflow_experiment_name,
        run_name=run_name,
        metrics=evaluation.trained.report.as_metrics(),
        params=params,
        artifacts=evaluation.trained.forecaster.artifacts(),
        tags={
            "feature_module": "app.ml.features.build_features",
            "split": "chronological_80_20",
            "triggered_by": "drift-detector",
        },
        register=True,
        model_name=registry_name,
        tracking_uri=tracking_uri,
    )
    run_log.info(f"Promotion gate: {result.decision.action} — {result.decision.reason}")
    return PromotionOutcome(
        decision=result.decision,
        challenger_version=result.model_version,
        run_id=result.run_id,
        tracking_uri=result.tracking_uri,
    )


@task(name="audit-log", retries=0)
async def audit_log_task(log_ids: Sequence[str], session_factory: Any = None) -> tuple[str, ...]:
    """Mark the drift rows that triggered this run as ``retraining_triggered``.

    Applied *after* the decision so a clean night that skips retraining keeps
    ``retraining_triggered = False`` — the audit trail distinguishes "drift
    seen, nothing to do" from "drift seen, model retrained".
    """
    run_log = run_logger()
    async with resolve_session_factory(session_factory)() as session:
        updated = await mark_retraining_triggered(session, list(log_ids))
    run_log.info(f"Audit: flagged {updated} drift_logs rows as retraining_triggered")
    return tuple(log_ids)


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


@flow(name="clusterops-nightly-retrain", log_prints=True)
async def retrain_flow(
    force: bool = False,
    *,
    reference_days: int = DEFAULT_REFERENCE_WINDOW_DAYS,
    current_days: int = DEFAULT_CURRENT_WINDOW_DAYS,
    window_days: int = RETRAIN_WINDOW_DAYS,
    n_jobs: int = TRAINING_N_JOBS,
    register_in_registry: bool = True,
    session_factory: Any = None,
    tracking_uri: str | None = None,
    registry_name: str = MODEL_NAME,
    experiment_name: str | None = None,
    required_improvement: float | None = None,
    end_date: date | None = None,
    lightgbm_params: dict[str, Any] | None = None,
) -> RetrainOutcome:
    """Detect drift and, if warranted, retrain and gate a challenger model.

    Parameters
    ----------
    force:
        Retrain even when no feature reached ``DRIFT_DETECTED``.  The drift
        evaluation still runs and is still logged, so the reason for the run is
        on record either way.
    window_days:
        Length of the training window ingested for the challenger.
    register_in_registry:
        ``False`` evaluates the gate without touching the MLflow registry.
    session_factory:
        Injection seam for tests; ``None`` uses the application factory.
    registry_name:
        MLflow registered model name (named to avoid pydantic's ``model_``
        protected namespace, which Prefect uses for flow parameter schemas).
    lightgbm_params:
        LightGBM overrides for the challenger, e.g. a reduced ``n_estimators``
        for a fast verification run.

    Returns
    -------
    RetrainOutcome
        A complete, serialisable account of the run — including the ``ran``
        flag, so a clean night is distinguishable from a failed one.
    """
    run_log = run_logger()

    # 1 + 2. Drift evaluation and the decision that gates everything after it.
    check = await check_drift_task(
        reference_days=reference_days,
        current_days=current_days,
        session_factory=session_factory,
        end_date=end_date,
    )
    decision = await decision_task(check, force)

    if not decision.should_retrain:
        run_log.info(NO_DRIFT_MESSAGE)
        return RetrainOutcome(
            ran=False,
            reason=decision.reason,
            forced=decision.forced,
            max_psi=decision.max_psi,
            drifting_features=decision.drifting_features,
            drift_log_ids=check.log_ids,
        )

    # 3. Ingest the most recent window.
    panel = await extract_data_task(days=window_days, session_factory=session_factory, end_date=end_date)
    panel_stats = panel_summary(panel)

    # 4. Shared feature pipeline (zero train/serve skew).
    features = await feature_pipeline_task(panel)
    feature_stats = {"rows": int(len(features)), "source_rows": int(len(panel))}

    # 5. Train the challenger on one thread.
    trained = await train_challenger_task(panel, features, n_jobs, extra_params=lightgbm_params)

    # 6. Score it against the naive baseline and the active champion.
    evaluation = await evaluate_challenger_task(trained, tracking_uri, registry_name)

    # 7. The 3 % gate, plus the registry transitions it authorises.
    promotion = await promotion_gate_task(
        evaluation,
        experiment_name=experiment_name,
        tracking_uri=tracking_uri,
        registry_name=registry_name,
        required_improvement=required_improvement,
        register_in_registry=register_in_registry,
        max_psi=decision.max_psi,
    )

    # 8. Close the audit loop.
    audit_ids = await audit_log_task(check.log_ids, session_factory)

    return RetrainOutcome(
        ran=True,
        reason=decision.reason,
        forced=decision.forced,
        max_psi=decision.max_psi,
        drifting_features=decision.drifting_features,
        drift_log_ids=check.log_ids,
        audit_log_ids=audit_ids,
        panel=panel_stats,
        features=feature_stats,
        challenger_mae=evaluation.challenger_mae,
        baseline_mae=evaluation.trained.baseline_mae,
        vs_baseline_pct=evaluation.trained.improvement_pct,
        production_mae=evaluation.production_mae,
        production_version=evaluation.production.version if evaluation.production else None,
        promotion=promotion,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m app.pipelines.retrain_flow`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m app.pipelines.retrain_flow",
        description="Run the ClusterOps nightly drift-detection and retraining flow. "
        "Synthetic data only.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--force", action="store_true", help="Retrain even when no drift was detected.")
    parser.add_argument(
        "--reference-days", type=int, default=DEFAULT_REFERENCE_WINDOW_DAYS, help="Baseline window length."
    )
    parser.add_argument(
        "--current-days", type=int, default=DEFAULT_CURRENT_WINDOW_DAYS, help="Window under evaluation."
    )
    parser.add_argument("--window-days", type=int, default=RETRAIN_WINDOW_DAYS, help="Training window length.")
    parser.add_argument(
        "--n-jobs", type=int, default=TRAINING_N_JOBS, help="LightGBM thread count for the challenger."
    )
    parser.add_argument("--register", action="store_true", help="Apply the gate in the MLflow registry.")
    parser.add_argument("--registry-name", default=MODEL_NAME, help="MLflow registered model name.")
    parser.add_argument("--experiment", default=None, help="MLflow experiment name.")
    parser.add_argument("--tracking-uri", default=None, help="MLflow tracking URI.")
    parser.add_argument(
        "--required-improvement",
        type=float,
        default=None,
        help="Promotion gate margin as a fraction (default: settings.promotion_gate_improvement = 0.03).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the run outcome as JSON.")
    parser.add_argument("--quiet", action="store_true", help="Only log warnings and errors.")
    parser.add_argument(
        "--n-estimators", type=int, default=None, help="Override LightGBM n_estimators for the challenger."
    )
    parser.add_argument("--num-leaves", type=int, default=None, help="Override LightGBM num_leaves.")
    parser.add_argument("--learning-rate", type=float, default=None, help="Override LightGBM learning_rate.")
    return parser


def format_outcome(outcome: RetrainOutcome) -> str:
    """Render a run outcome for the console."""
    lines = [
        "",
        "=" * 74,
        " ClusterOps — nightly retraining flow (synthetic data, demonstration purposes)",
        "=" * 74,
        f" Retrained              : {outcome.ran}",
        f" Reason                 : {outcome.reason}",
        f" Forced                 : {outcome.forced}",
        f" Max PSI                : {outcome.max_psi:.6f}",
        f" Drifting features      : {', '.join(outcome.drifting_features) or 'none'}",
        f" drift_logs rows written: {len(outcome.drift_log_ids)}",
    ]
    if outcome.ran:
        lines += [
            "-" * 74,
            f" Panel                  : {outcome.panel.get('rows', 0):,} rows | "
            f"{outcome.panel.get('series', 0):,} series | "
            f"{outcome.panel.get('start_date')}..{outcome.panel.get('end_date')}",
            f" Feature rows           : {outcome.features.get('rows', 0):,}",
            f" Challenger MAE         : {outcome.challenger_mae:.4f}",
            f" Naive MAE (t-7)        : {outcome.baseline_mae:.4f}",
            f" Improvement vs naive   : {outcome.vs_baseline_pct:+.2f}%",
            " Production MAE         : "
            + ("none" if outcome.production_mae is None else f"{outcome.production_mae:.4f}")
            + (f" (v{outcome.production_version})" if outcome.production_version else ""),
        ]
        if outcome.promotion:
            lines += [
                f" Promotion gate         : {outcome.promotion.decision.action} — "
                f"{outcome.promotion.decision.reason}",
                f" Challenger version     : {outcome.promotion.challenger_version or 'not registered'}",
            ]
    lines += ["=" * 74, ""]
    return "\n".join(lines)


def _model_params(args: argparse.Namespace) -> dict[str, Any]:
    """LightGBM overrides requested on the command line."""
    overrides = {
        key: value
        for key, value in (
            ("n_estimators", args.n_estimators),
            ("num_leaves", args.num_leaves),
            ("learning_rate", args.learning_rate),
        )
        if value is not None
    }
    return overrides


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    args = build_parser().parse_args(argv)
    configure_logging()
    logger.setLevel(logging.WARNING if args.quiet else logging.INFO)

    outcome = asyncio.run(
        retrain_flow(
            force=args.force,
            reference_days=args.reference_days,
            current_days=args.current_days,
            window_days=args.window_days,
            n_jobs=args.n_jobs,
            register_in_registry=args.register,
            tracking_uri=args.tracking_uri,
            registry_name=args.registry_name,
            experiment_name=args.experiment,
            required_improvement=args.required_improvement,
            lightgbm_params=_model_params(args),
        )
    )

    if args.json:
        import json as _json

        print(_json.dumps(outcome.to_dict(), indent=2, default=str))
    else:
        print(format_outcome(outcome))
    return 0


__all__ = [
    "FORCED_MESSAGE",
    "NO_DRIFT_MESSAGE",
    "RETRAIN_WINDOW_DAYS",
    "TRAINING_N_JOBS",
    "ChallengerEvaluation",
    "DriftCheck",
    "PromotionOutcome",
    "RetrainDecision",
    "RetrainOutcome",
    "TrainedChallenger",
    "audit_log_task",
    "build_parser",
    "check_drift_task",
    "decision_task",
    "evaluate_challenger_task",
    "extract_data_task",
    "feature_pipeline_task",
    "format_outcome",
    "main",
    "promotion_gate_task",
    "resolve_session_factory",
    "retrain_flow",
    "train_challenger_task",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())