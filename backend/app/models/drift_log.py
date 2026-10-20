"""``drift_logs`` — append-only PSI audit trail from the drift detector.

Each check writes one row per monitored feature (``daily_units_sold``,
``order_frequency``, ``avg_order_value_egp``, ``match_confidence``) so that
Phase 4/5 endpoints can render drift history without recomputing anything.

Synthetic data only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import Boolean, DateTime, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

#: PSI status vocabulary shared with :mod:`app.ml.drift_detector`.
STATUS_OK: Final[str] = "OK"
STATUS_WARNING: Final[str] = "WARNING"
STATUS_DRIFT_DETECTED: Final[str] = "DRIFT_DETECTED"
VALID_DRIFT_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_OK, STATUS_WARNING, STATUS_DRIFT_DETECTED}
)

#: Features monitored by the production drift job.
MONITORED_FEATURES: Final[tuple[str, ...]] = (
    "daily_units_sold",
    "order_frequency",
    "avg_order_value_egp",
    "match_confidence",
)


class DriftLog(UUIDPrimaryKeyMixin, Base):
    """One PSI observation for one feature at one point in time.

    Attributes
    ----------
    checked_at:
        Timezone-aware UTC timestamp of the drift evaluation.
    psi_score:
        Population Stability Index for ``feature_name``.
    status:
        ``OK`` (< 0.10), ``WARNING`` (0.10–0.20) or ``DRIFT_DETECTED`` (>= 0.20).
    retraining_triggered:
        ``True`` when this observation caused the Prefect retraining flow to fire.
    """

    __tablename__ = "drift_logs"
    __table_args__ = (
        Index("ix_drift_logs_checked_at_feature_name", "checked_at", "feature_name"),
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    feature_name: Mapped[str | None] = mapped_column(String(100))
    psi_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(20))
    retraining_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )


__all__ = [
    "MONITORED_FEATURES",
    "STATUS_DRIFT_DETECTED",
    "STATUS_OK",
    "STATUS_WARNING",
    "VALID_DRIFT_STATUSES",
    "DriftLog",
]