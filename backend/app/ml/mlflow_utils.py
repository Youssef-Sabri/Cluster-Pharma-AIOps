"""MLflow tracking, model registration and the 3 % promotion gate.

Rule (from the engineering guidelines): a challenger model may only replace the
production model when its test MAE is at least 3 % lower::

    challenger_mae < production_mae * 0.97

Otherwise it is archived and the rejection reason is logged.  The decision
itself lives in the pure function :func:`evaluate_promotion`, so the policy can
be unit-tested without a tracking server; :func:`evaluate_and_register` only
performs the MLflow side effects.

Synthetic data only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Sequence

import mlflow
import mlflow.lightgbm
from mlflow.entities.model_registry import ModelVersion
from mlflow.exceptions import MlflowException, RestException
from mlflow.tracking import MlflowClient

from app.config import Settings, settings
from app.ml.features import describe_features

logger: Final[logging.Logger] = logging.getLogger("clusterops.ml.mlflow_utils")

#: Registry name of the demand forecaster.
MODEL_NAME: Final[str] = settings.mlflow_model_name

#: Default experiment name.
EXPERIMENT_NAME: Final[str] = settings.mlflow_experiment_name

#: Model-version stages used by the registry (the API contract exposes a
#: ``stage`` field, so stages remain the source of truth).  MLflow 2.9+
#: deprecates stages in favour of aliases, so the production marker is *also*
#: mirrored onto an alias to stay forward compatible.
STAGE_PRODUCTION: Final[str] = "Production"
STAGE_ARCHIVED: Final[str] = "Archived"
STAGE_NONE: Final[str] = "None"

#: Alias mirroring the Production stage.
PRODUCTION_ALIAS: Final[str] = "champion"

#: MLflow experiment lifecycle stage (``deleted`` experiments are restorable).
LIFECYCLE_ACTIVE: Final[str] = "active"

#: Tag carrying the test MAE of a registered version — the number the promotion
#: gate compares.  MLflow stages carry no metrics, so the tag *is* the contract.
TAG_TEST_MAE: Final[str] = "test_mae"
TAG_PROMOTED_AT: Final[str] = "promoted_at"
TAG_GATE_RULE: Final[str] = "promotion_gate"
TAG_PROMOTION_REASON: Final[str] = "promotion_reason"
TAG_TRAINED_AT: Final[str] = "trained_at"
TAG_BASELINE_MAE: Final[str] = "baseline_mae"
TAG_IMPROVEMENT_PCT: Final[str] = "vs_baseline_improvement_pct"

#: Minimum relative MAE improvement required to take over production.
DEFAULT_REQUIRED_IMPROVEMENT: Final[float] = 0.03


class MlflowUnavailableError(RuntimeError):
    """Raised when the tracking server cannot be reached."""


# ---------------------------------------------------------------------------
# Promotion policy (pure, no I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Outcome of applying the promotion gate to a challenger."""

    action: Literal["PROMOTE", "ARCHIVE"]
    reason: str
    challenger_mae: float
    production_mae: float | None
    required_improvement: float
    improvement_pct: float | None = None
    previous_version: str | None = None

    @property
    def promoted(self) -> bool:
        """``True`` when the challenger may serve traffic."""
        return self.action == "PROMOTE"


def evaluate_promotion(
    challenger_mae: float,
    production_mae: float | None,
    *,
    required_improvement: float = DEFAULT_REQUIRED_IMPROVEMENT,
    previous_version: str | None = None,
) -> PromotionDecision:
    """Apply the strict promotion gate to a challenger model.

    Parameters
    ----------
    challenger_mae:
        Test MAE of the freshly trained model.
    production_mae:
        Test MAE of the model currently in ``Production``.  ``None`` means the
        registry has no active production model — the challenger is then
        promoted unconditionally (bootstrap case).
    required_improvement:
        Fractional improvement demanded over production.  Defaults to 3 %.

    Returns
    -------
    PromotionDecision
        ``PROMOTE`` only when ``challenger_mae < production_mae * (1 - 0.03)``.
    """
    if not 0.0 <= required_improvement < 1.0:
        raise ValueError(f"required_improvement must be in [0, 1), got {required_improvement}")
    if challenger_mae < 0:
        raise ValueError(f"challenger_mae must be non-negative, got {challenger_mae}")

    if production_mae is None:
        return PromotionDecision(
            action="PROMOTE",
            reason="No active Production model found — challenger promoted as the first production model.",
            challenger_mae=challenger_mae,
            production_mae=None,
            required_improvement=required_improvement,
            previous_version=previous_version,
        )

    improvement = (production_mae - challenger_mae) / production_mae
    threshold = production_mae * (1.0 - required_improvement)
    if challenger_mae < threshold:
        return PromotionDecision(
            action="PROMOTE",
            reason=(
                f"Challenger MAE {challenger_mae:.4f} is {improvement:.2%} better than production "
                f"{production_mae:.4f} (required {required_improvement:.0%}, threshold {threshold:.4f})."
            ),
            challenger_mae=challenger_mae,
            production_mae=production_mae,
            required_improvement=required_improvement,
            improvement_pct=improvement,
            previous_version=previous_version,
        )

    return PromotionDecision(
        action="ARCHIVE",
        reason=(
            f"Challenger MAE {challenger_mae:.4f} did not beat production {production_mae:.4f} by the "
            f"required {required_improvement:.0%} (threshold {threshold:.4f}); "
            f"actual improvement {improvement:.2%}."
        ),
        challenger_mae=challenger_mae,
        production_mae=production_mae,
        required_improvement=required_improvement,
        improvement_pct=improvement,
        previous_version=previous_version,
    )


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegisteredModelVersion:
    """A model version plus the metrics needed to judge it."""

    name: str
    version: str
    stage: str
    test_mae: float | None
    run_id: str | None
    source: str | None


def configure_mlflow(db_settings: Settings | None = None, *, tracking_uri: str | None = None) -> str:
    """Point MLflow at ``tracking_uri`` (or the configured server) and return it."""
    db_settings = db_settings or settings
    uri = tracking_uri or db_settings.mlflow_tracking_uri
    mlflow.set_tracking_uri(uri)
    logger.debug("MLflow tracking URI configured", extra={"tracking_uri": uri})
    return uri


def build_client(tracking_uri: str | None = None) -> MlflowClient:
    """Create an :class:`MlflowClient` against ``tracking_uri`` or the server."""
    uri = configure_mlflow(tracking_uri=tracking_uri)
    try:
        return MlflowClient(tracking_uri=uri)
    except (MlflowException, RestException) as exc:  # pragma: no cover - connection failure
        raise MlflowUnavailableError(f"cannot create an MLflow client for {uri!r}: {exc}") from exc


def is_server_reachable(tracking_uri: str | None = None) -> bool:
    """``True`` when the tracking backend answers a round trip.

    Used to skip integration tests instead of failing them when no tracking
    server is running.
    """
    try:
        build_client(tracking_uri).search_experiments(max_results=1)
    except Exception:  # noqa: BLE001 - a reachability probe must never raise
        logger.info("MLflow tracking backend is not reachable", extra={"tracking_uri": tracking_uri})
        return False
    return True


def ensure_experiment(name: str = EXPERIMENT_NAME, client: MlflowClient | None = None) -> str:
    """Return the experiment id, creating or restoring the experiment as needed.

    ``get_experiment_by_name`` also returns experiments in the ``deleted``
    lifecycle state, and MLflow then rejects any run started against them
    ("experiment must be in the 'active' state").  A deleted experiment is
    therefore restored, which also keeps its historical runs intact.
    """
    client = client or build_client()
    experiment = client.get_experiment_by_name(name)
    if experiment is None:
        return client.create_experiment(name)

    if str(experiment.lifecycle_stage).lower() != LIFECYCLE_ACTIVE:
        try:
            client.restore_experiment(experiment.experiment_id)
            logger.info(
                "Restored a deleted MLflow experiment",
                extra={"experiment": name, "experiment_id": experiment.experiment_id},
            )
        except MlflowException as exc:  # pragma: no cover - depends on the backend
            logger.warning(
                "Could not restore the deleted experiment, creating a new one",
                extra={"experiment": name, "error": str(exc)},
            )
            return client.create_experiment(name)
    return experiment.experiment_id


def get_production_model(name: str = MODEL_NAME, client: MlflowClient | None = None) -> RegisteredModelVersion | None:
    """Return the model version currently serving production traffic, if any.

    Prefers the forward-compatible ``champion`` alias and falls back to the
    ``Production`` stage so versions registered before the alias existed are
    still discovered.
    """
    client = client or build_client()

    try:
        alias_version = client.get_model_version_by_alias(name, PRODUCTION_ALIAS)
    except MlflowException:
        alias_version = None
    if alias_version is not None:
        return _as_registered_version(alias_version)

    versions = client.search_model_versions(
        f"name='{name}'",
        # NB: MLflow's filter grammar uses the singular `attribute.` prefix.
        order_by=["attribute.last_updated_timestamp DESC"],
        max_results=100,
    )
    for version in versions:
        if str(version.current_stage).lower() == STAGE_PRODUCTION.lower():
            return _as_registered_version(version)
    return None


def _as_registered_version(version: ModelVersion) -> RegisteredModelVersion:
    """Adapt an MLflow ``ModelVersion`` entity to the local dataclass."""
    return RegisteredModelVersion(
        name=version.name,
        version=version.version,
        stage=str(version.current_stage),
        test_mae=_parse_float((version.tags or {}).get(TAG_TEST_MAE)),
        run_id=version.run_id,
        source=version.source,
    )


def _parse_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric MLflow tag", extra={"value": value})
        return None


def register_version(
    *,
    run_id: str,
    name: str = MODEL_NAME,
    description: str = "",
    client: MlflowClient | None = None,
) -> ModelVersion:
    """Register ``run_id``'s model artifact as a new version of ``name``."""
    client = client or build_client()
    return client.create_model_version(
        name=name,
        source=f"runs:/{run_id}/model",
        run_id=run_id,
        description=description,
        tags={"source": "clusterops-forecaster"},
    )


def apply_decision(
    decision: PromotionDecision,
    *,
    name: str = MODEL_NAME,
    version: str,
    client: MlflowClient | None = None,
) -> None:
    """Move model versions between stages according to ``decision``."""
    client = client or build_client()
    client.set_model_version_tag(name, version, TAG_PROMOTION_REASON, decision.reason)
    client.set_model_version_tag(name, version, TAG_GATE_RULE, f"mae < production_mae * {1 - decision.required_improvement:.2f}")

    if decision.action == "PROMOTE":
        if decision.previous_version is not None:
            # Only one Production version may exist at a time.
            client.transition_model_version_stage(name, decision.previous_version, STAGE_ARCHIVED)
            client.set_model_version_tag(
                name, decision.previous_version, TAG_PROMOTION_REASON, f"Superseded by version {version}."
            )
        client.transition_model_version_stage(name, version, STAGE_PRODUCTION)
        client.set_model_version_tag(name, version, TAG_PROMOTED_AT, _utc_now_iso())
        # Mirror the stage onto an alias (MLflow's forward-compatible mechanism).
        _set_production_alias(client, name, version)
    else:
        client.transition_model_version_stage(name, version, STAGE_ARCHIVED)
        # The alias must never point at an archived version.
        try:
            current = client.get_model_version_by_alias(name, PRODUCTION_ALIAS)
            if str(current.version) == str(version):
                client.delete_registered_model_alias(name, PRODUCTION_ALIAS)
        except MlflowException:
            logger.debug("No production alias to clear", extra={"model_name": name})


def _set_production_alias(client: MlflowClient, name: str, version: str) -> None:
    """Point the ``champion`` alias at ``version``; never fatal."""
    try:
        client.set_registered_model_alias(name, PRODUCTION_ALIAS, version)
    except MlflowException as exc:  # pragma: no cover - depends on the backend
        logger.warning("Could not set the production alias", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Training-run logging
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrainingArtifacts:
    """The three fitted boosters plus their metadata."""

    point_model: Any
    lower_model: Any
    upper_model: Any
    feature_names: Sequence[str]
    best_iterations: dict[str, int] = field(default_factory=dict)
    model_params: dict[str, Any] = field(default_factory=dict)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class RunResult:
    """Identifiers produced by a tracked training run."""

    experiment_id: str
    run_id: str
    model_version: str | None
    decision: PromotionDecision
    tracking_uri: str


def evaluate_and_register(
    *,
    experiment_name: str,
    run_name: str,
    metrics: dict[str, float],
    params: dict[str, Any],
    artifacts: TrainingArtifacts,
    tags: dict[str, str] | None = None,
    register: bool = True,
    model_name: str = MODEL_NAME,
    tracking_uri: str | None = None,
    client: MlflowClient | None = None,
) -> RunResult:
    """Log a training run, register the model and apply the promotion gate.

    The sequence follows the phase specification:

    1. log parameters, metrics and the feature manifest to the experiment,
    2. log the point model and both quantile models as artifacts,
    3. register ``model_name`` (creating the registered model if needed),
    4. read the current ``Production`` MAE and decide via the gate,
    5. transition stages and store the decision as a model-version tag.

    Returns
    -------
    RunResult
        Identifiers plus the promotion decision, whether or not the challenger
        was promoted.
    """
    uri = configure_mlflow(tracking_uri=tracking_uri or getattr(client, "tracking_uri", None))
    client = client or build_client(uri)
    experiment_id = ensure_experiment(experiment_name, client)
    metrics = {key: float(value) for key, value in metrics.items() if value is not None}
    tags = dict(tags or {})

    if not register:
        return _log_only(
            client=client,
            experiment_id=experiment_id,
            run_name=run_name,
            metrics=metrics,
            params=params,
            tags=tags,
            artifacts=artifacts,
            tracking_uri=uri,
        )

    with mlflow.start_run(experiment_id=experiment_id, run_name=run_name) as run:
        run_id = run.info.run_id
        mlflow.log_params({key: str(value) for key, value in params.items()})
        mlflow.log_metrics(metrics)
        # Run-level tags go through the client one by one: MLflow exposes
        # `set_tag`, and no `log_tags`/`set_tags` bulk helper.
        for key, value in {
            "model_name": model_name,
            "feature_manifest": _feature_manifest_json(),
            "split_strategy": "chronological_80_20",
            "feature_module": "app.ml.features.build_features",
            **tags,
        }.items():
            client.set_tag(run_id, key, str(value))
        for key, value in artifacts.best_iterations.items():
            mlflow.log_metric(f"best_iteration_{key}", float(value))

        signature = _signature(artifacts.feature_names)
        example = _input_example(artifacts.feature_names)
        # The three boosters share one feature matrix, so all three artifacts
        # carry the same signature — otherwise MLflow logs them undocumented.
        mlflow.lightgbm.log_model(
            artifacts.point_model,
            artifact_path="model",
            signature=signature,
            input_example=example,
        )
        mlflow.lightgbm.log_model(
            artifacts.lower_model,
            artifact_path="lower_model",
            signature=signature,
            input_example=example,
        )
        mlflow.lightgbm.log_model(
            artifacts.upper_model,
            artifact_path="upper_model",
            signature=signature,
            input_example=example,
        )

    if not _registered_model_exists(model_name, client):
        client.create_registered_model(name=model_name)

    version = register_version(run_id=run_id, name=model_name, client=client, description=tags.get("description", ""))
    version_id = version.version
    client.set_model_version_tag(model_name, version_id, TAG_TEST_MAE, f"{metrics.get('mae', float('nan')):.6f}")
    client.set_model_version_tag(model_name, version_id, TAG_TRAINED_AT, _utc_now_iso())
    if "baseline_mae" in metrics:
        client.set_model_version_tag(model_name, version_id, TAG_BASELINE_MAE, f"{metrics['baseline_mae']:.6f}")
    if "vs_baseline_improvement_pct" in metrics:
        client.set_model_version_tag(
            model_name, version_id, TAG_IMPROVEMENT_PCT, f"{metrics['vs_baseline_improvement_pct']:.6f}"
        )

    production = get_production_model(model_name, client)
    decision = evaluate_promotion(
        challenger_mae=metrics["mae"],
        production_mae=production.test_mae if production else None,
        previous_version=production.version if production else None,
    )
    apply_decision(decision, name=model_name, version=version_id, client=client)

    if not decision.promoted:
        logger.warning("Challenger archived by the promotion gate", extra={"reason": decision.reason})
    else:
        logger.info("Challenger registered", extra={"version": version_id, "reason": decision.reason})

    return RunResult(
        experiment_id=experiment_id,
        run_id=run_id,
        model_version=version_id,
        decision=decision,
        tracking_uri=uri,
    )


def _log_only(
    *,
    client: MlflowClient,
    experiment_id: str,
    run_name: str,
    metrics: dict[str, float],
    params: dict[str, Any],
    tags: dict[str, str],
    artifacts: TrainingArtifacts,
    tracking_uri: str,
) -> RunResult:
    """Log a run without registering a model (``--train`` without ``--register``)."""
    with mlflow.start_run(experiment_id=experiment_id, run_name=run_name) as run:
        run_id = run.info.run_id
        mlflow.log_params({key: str(value) for key, value in params.items()})
        mlflow.log_metrics(metrics)
        for key, value in {
            "feature_manifest": _feature_manifest_json(),
            "split_strategy": "chronological_80_20",
            **tags,
        }.items():
            client.set_tag(run_id, key, str(value))
        mlflow.lightgbm.log_model(
            artifacts.point_model,
            artifact_path="model",
            signature=_signature(artifacts.feature_names),
            input_example=_input_example(artifacts.feature_names),
        )
    return RunResult(
        experiment_id=experiment_id,
        run_id=run_id,
        model_version=None,
        decision=evaluate_promotion(metrics["mae"], None),
        tracking_uri=tracking_uri,
    )


def _registered_model_exists(name: str, client: MlflowClient) -> bool:
    try:
        client.get_registered_model(name)
    except MlflowException:
        return False
    return True


def _feature_manifest_json() -> str:
    import json

    return json.dumps(describe_features())


def _signature(feature_names: Sequence[str]) -> Any:
    """Inference signature so the MLflow UI documents every logged artifact.

    All three boosters consume the identical feature matrix, so they share one
    signature.  Failure is non-fatal: logging must never break a training run.
    """
    try:
        import pandas as pd
        from mlflow.models import infer_signature

        sample = pd.DataFrame(
            {
                name: (["OTC"] if name == "product_category" else ["MEDIUM"] if name == "pharmacy_tier" else [1.0])
                for name in feature_names
            }
        )
        return infer_signature(sample, 1.0)
    except Exception:  # noqa: BLE001 - a convenience, never fatal
        logger.warning("Could not infer the model signature", exc_info=True)
        return None


def _input_example(feature_names: Sequence[str]) -> Any:
    """One synthetic row for the MLflow UI's "predict" tab (serving demo)."""
    try:
        import pandas as pd
        from app.ml.features import PHARMACY_TIER_DTYPE, PRODUCT_CATEGORY_DTYPE

        df = pd.DataFrame(
            {
                name: (["OTC"] if name == "product_category" else ["MEDIUM"] if name == "pharmacy_tier" else [0.0])
                for name in feature_names
            }
        )
        if "product_category" in df.columns:
            df["product_category"] = df["product_category"].astype(PRODUCT_CATEGORY_DTYPE)
        if "pharmacy_tier" in df.columns:
            df["pharmacy_tier"] = df["pharmacy_tier"].astype(PHARMACY_TIER_DTYPE)
        return df
    except Exception:  # noqa: BLE001
        return None


def load_booster_from_uri(model_uri: str) -> Any:
    """Load a logged LightGBM booster back from MLflow (serving path)."""
    import lightgbm as lgb

    model = mlflow.lightgbm.load_model(model_uri)
    booster = getattr(model, "booster_", None) or model
    return lgb.Booster(model_str=booster.model_to_string())


__all__ = [
    "DEFAULT_REQUIRED_IMPROVEMENT",
    "EXPERIMENT_NAME",
    "MODEL_NAME",
    "PRODUCTION_ALIAS",
    "STAGE_ARCHIVED",
    "STAGE_NONE",
    "STAGE_PRODUCTION",
    "TAG_BASELINE_MAE",
    "TAG_GATE_RULE",
    "TAG_IMPROVEMENT_PCT",
    "TAG_PROMOTED_AT",
    "TAG_PROMOTION_REASON",
    "TAG_TEST_MAE",
    "MlflowUnavailableError",
    "PromotionDecision",
    "RegisteredModelVersion",
    "RunResult",
    "TrainingArtifacts",
    "apply_decision",
    "build_client",
    "configure_mlflow",
    "ensure_experiment",
    "evaluate_and_register",
    "evaluate_promotion",
    "get_production_model",
    "is_server_reachable",
    "load_booster_from_uri",
    "register_version",
]