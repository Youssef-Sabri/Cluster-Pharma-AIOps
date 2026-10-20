"""SQLAlchemy ORM models for the ClusterOps schema.

Importing this package registers all five tables on :class:`Base.metadata`, which
is what ``alembic/env.py`` uses as ``target_metadata`` for autogeneration.

Synthetic data only — demonstration purposes.
"""

from __future__ import annotations

from app.models.base import NAMING_CONVENTION, Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.drift_log import (
    MONITORED_FEATURES,
    STATUS_DRIFT_DETECTED,
    STATUS_OK,
    STATUS_WARNING,
    VALID_DRIFT_STATUSES,
    DriftLog,
)
from app.models.drug_catalogue import (
    CATEGORY_COSMETIC,
    CATEGORY_OTC,
    CATEGORY_PRESCRIPTION,
    VALID_CATEGORIES,
    DrugCatalogue,
)
from app.models.order import (
    MATCH_METHOD_EXACT,
    MATCH_METHOD_FUZZY,
    MATCH_METHOD_LLM,
    VALID_MATCH_METHODS,
    Order,
    OrderItem,
)
from app.models.prediction import Prediction

__all__ = [
    "CATEGORY_COSMETIC",
    "CATEGORY_OTC",
    "CATEGORY_PRESCRIPTION",
    "MATCH_METHOD_EXACT",
    "MATCH_METHOD_FUZZY",
    "MATCH_METHOD_LLM",
    "MONITORED_FEATURES",
    "NAMING_CONVENTION",
    "STATUS_DRIFT_DETECTED",
    "STATUS_OK",
    "STATUS_WARNING",
    "VALID_CATEGORIES",
    "VALID_DRIFT_STATUSES",
    "VALID_MATCH_METHODS",
    "Base",
    "CreatedAtMixin",
    "DrugCatalogue",
    "DriftLog",
    "Order",
    "OrderItem",
    "Prediction",
    "UUIDPrimaryKeyMixin",
]