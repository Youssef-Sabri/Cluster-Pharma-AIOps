"""``POST /api/v1/retrain`` — dispatch the nightly retraining flow.

Returns **202 Accepted** immediately and runs the flow in a background task, so
a caller is never blocked for the minutes a retraining run takes.  The flow name
and behaviour are unchanged from the CLI: this endpoint only *schedules* it.

Test seam
---------
:func:`set_flow_runner` replaces the coroutine the background task awaits.  It
exists so the endpoint contract (202, tracking id, no blocking) can be tested
without a real training run; production leaves it at :func:`default_flow_runner`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Final

from fastapi import APIRouter, BackgroundTasks, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.schemas.registry import RetrainRequest, RetrainResponse

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.retrain")

router = APIRouter(prefix="/api/v1", tags=["aiops"])

#: Wall-clock estimate returned to the caller: the drift check is seconds, the
#: LightGBM fit and MLflow upload dominate.
ESTIMATED_DURATION_SECONDS: Final[int] = 180


async def default_flow_runner(**kwargs: Any) -> Any:
    """Run the real Prefect retraining flow (the production path)."""
    from app.pipelines.retrain_flow import retrain_flow

    return await retrain_flow(**kwargs)


#: Overridable so tests can assert the dispatch contract without training.
_flow_runner: Callable[..., Awaitable[Any]] = default_flow_runner


def set_flow_runner(runner: Callable[..., Awaitable[Any]] | None) -> None:
    """Replace the coroutine the background task awaits; ``None`` restores it."""
    global _flow_runner

    _flow_runner = runner or default_flow_runner


def get_flow_runner() -> Callable[..., Awaitable[Any]]:
    """Return the currently installed flow runner."""
    return _flow_runner


@router.post(
    "/retrain",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger the nightly retraining flow",
    description=(
        "Submits the `clusterops-nightly-retrain` Prefect flow in the background and "
        "returns **202 Accepted** straight away with a tracking id. The flow "
        "re-evaluates drift, trains a challenger only if drift was detected (or "
        "`force` is set), and promotes it only through the strict 3% gate.\n\n"
        "Progress is observable through `GET /api/v1/model-registry` (a new version "
        "appears) and `GET /api/v1/drift-status` (`retraining_triggered` flips)."
    ),
    response_model=RetrainResponse,
    responses={
        202: {"description": "Flow submitted.", "model": RetrainResponse},
        422: {"description": "Request body failed validation."},
    },
)
async def trigger_retrain(
    request: RetrainRequest, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Dispatch the flow and return 202 without waiting for it."""
    flow_run_id = str(uuid.uuid4())
    runner = get_flow_runner()

    async def _run() -> None:
        """Execute the flow, swallowing failures.

        The response has already been sent, so an exception here could not be
        reported to the caller — it is logged and recorded on the drift rows
        instead, which is exactly the audit trail `audit_log_task` maintains.
        """
        try:
            outcome = await runner(
                force=request.force,
                window_days=request.window_days or 90,
                tracking_uri=settings.mlflow_tracking_uri,
                registry_name=settings.mlflow_model_name,
            )
            logger.info(
                "Retraining flow finished",
                extra={"flow_run_id": flow_run_id, "ran": getattr(outcome, "ran", None)},
            )
        except Exception as exc:  # noqa: BLE001 - background task cannot report to the client
            logger.error(
                "Retraining flow failed",
                exc_info=True,
                extra={"flow_run_id": flow_run_id, "error": str(exc)},
            )

    background_tasks.add_task(_run)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=RetrainResponse(
            flow_run_id=flow_run_id,
            status="SUBMITTED",
            message="Retraining flow submitted. Check /api/v1/model-registry for results.",
            estimated_duration_seconds=ESTIMATED_DURATION_SECONDS,
            force=request.force,
        ).model_dump(mode="json"),
    )


__all__ = [
    "ESTIMATED_DURATION_SECONDS",
    "default_flow_runner",
    "get_flow_runner",
    "router",
    "set_flow_runner",
    "trigger_retrain",
]