"""Pydantic v2 request/response schemas for the ClusterOps API.

Every endpoint has explicit models — no endpoint handler builds a raw dict
response (rule: *API & Validation*).
"""

from app.schemas.common import (
    ApiModel,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    MessageResponse,
    utc_now,
)
from app.schemas.drift import DriftFeatureItem, DriftStatus, DriftStatusResponse
from app.schemas.forecast import (
    ForecastItem,
    ForecastRequest,
    ForecastResponse,
    ForecastUnavailableResponse,
)
from app.schemas.match_order import MatchedItem, MatchOrderRequest, MatchOrderResponse
from app.schemas.registry import (
    ModelMetadataItem,
    ModelRegistryResponse,
    RetrainRequest,
    RetrainResponse,
)
from app.schemas.review_queue import (
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewQueueItemResponse,
    ReviewQueueResponse,
)

__all__ = [
    "ApiModel",
    "DriftFeatureItem",
    "DriftStatus",
    "DriftStatusResponse",
    "ErrorDetail",
    "ErrorResponse",
    "ForecastItem",
    "ForecastRequest",
    "ForecastResponse",
    "ForecastUnavailableResponse",
    "HealthResponse",
    "MatchOrderRequest",
    "MatchOrderResponse",
    "MatchedItem",
    "MessageResponse",
    "ModelMetadataItem",
    "ModelRegistryResponse",
    "RetrainRequest",
    "RetrainResponse",
    "ReviewActionRequest",
    "ReviewActionResponse",
    "ReviewQueueItemResponse",
    "ReviewQueueResponse",
    "utc_now",
]