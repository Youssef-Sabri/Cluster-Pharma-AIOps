"""``GET /api/v1/drift-status`` — the latest PSI evaluation from ``drift_logs``."""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import DriftLog
from app.models.drift_log import STATUS_DRIFT_DETECTED, STATUS_OK, STATUS_WARNING, VALID_DRIFT_STATUSES
from app.monitoring import metrics
from app.schemas.drift import DriftFeatureItem, DriftStatusResponse

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.drift")

router = APIRouter(prefix="/api/v1", tags=["aiops"])


def _worst_status(statuses: list[str]) -> str:
    """Overall verdict: the most severe status across the monitored features.

    Severity order is ``DRIFT_DETECTED > WARNING > OK``.  An earlier version
    short-circuited to ``OK`` whenever no feature was clean, which meant a window
    where *every* feature drifted reported ``OK`` — exactly backwards.
    """
    for candidate in (STATUS_DRIFT_DETECTED, STATUS_WARNING, STATUS_OK):
        if candidate in statuses:
            return candidate
    return STATUS_OK


@router.get(
    "/drift-status",
    response_model=DriftStatusResponse,
    summary="Latest statistical drift evaluation",
    description=(
        "Returns the most recent PSI score per monitored feature, read from "
        "`drift_logs`. Feature rows share a `checked_at` timestamp because they "
        "are written by one evaluation.\n\n"
        "Bands: `< 0.10` OK, `0.10–0.20` WARNING, `>= 0.20` DRIFT_DETECTED (which "
        "is what triggers the retraining flow). When nothing has been evaluated "
        "yet the response reports `evaluated: false` rather than pretending the "
        "data is healthy."
    ),
    responses={
        200: {"description": "Latest drift evaluation.", "model": DriftStatusResponse},
        422: {"description": "Query parameter failed validation."},
    },
)
async def drift_status(db: AsyncSession = Depends(get_db)) -> DriftStatusResponse:
    """Read the newest drift evaluation and refresh the PSI gauges."""
    # `max()` rather than `select(desc(...))`: a descending *select expression*
    # carries no ORDER BY, so the database may return the rows in any order and
    # the endpoint would report an arbitrary (often stale) evaluation.
    newest = (await db.execute(select(func.max(DriftLog.checked_at)))).scalar_one_or_none()
    if newest is None:
        return DriftStatusResponse(
            checked_at=None,
            overall_status=STATUS_OK,
            max_psi=0.0,
            psi_threshold=settings.drift_psi_alert,
            features=[],
            retraining_triggered=False,
            evaluated=False,
        )

    rows = (
        await db.execute(
            select(DriftLog).where(DriftLog.checked_at == newest).order_by(DriftLog.feature_name)
        )
    ).scalars().all()

    features = [
        DriftFeatureItem(
            feature_name=row.feature_name or "unknown",
            psi_score=float(row.psi_score or 0.0),
            status=row.status if row.status in VALID_DRIFT_STATUSES else STATUS_OK,
            checked_at=row.checked_at,
        )
        for row in rows
    ]
    per_feature = {item.feature_name: item.psi_score for item in features}
    metrics.set_drift_psi(per_feature)

    statuses = [item.status for item in features]
    return DriftStatusResponse(
        checked_at=features[0].checked_at if features else newest,
        overall_status=_worst_status(statuses),
        max_psi=max(per_feature.values(), default=0.0),
        psi_threshold=settings.drift_psi_alert,
        features=features,
        retraining_triggered=any(row.retraining_triggered for row in rows),
        evaluated=True,
    )


__all__ = ["drift_status", "router"]