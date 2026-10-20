"""Schemas for the human-in-the-loop review queue.

This is the endpoint that closes the pharma safety loop: a pharmacist resolves
every item the Phase 3 matcher flagged with ``needs_review = True``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel

#: A pharmacy order must be resolvable to something a human can act on, and the
#: confidence floor is fixed at 0.50 by the engineering rules.
MAX_RAW_TOKEN_LENGTH: int = 500
MAX_REVIEWER_LENGTH: int = 100
MAX_CATALOGUE_ID_LENGTH: int = 100


class ReviewQueueItemResponse(ApiModel):
    """One ``order_items`` row awaiting a pharmacist's decision."""

    item_id: str = Field(description="Database id of the flagged order line.")
    order_id: str = Field(description="Order the line belongs to.")
    pharmacy_id: str = Field(description="Pharmacy that placed the order.")
    raw_token: str = Field(description="The original text fragment the matcher could not resolve confidently.")
    proposed_catalogue_id: str | None = Field(
        default=None, description="Best fuzzy candidate, which the matcher was not confident about."
    )
    proposed_catalogue_name: str | None = Field(default=None, description="Display name of that candidate.")
    quantity: int | None = Field(default=None, description="Units requested on the line.")
    confidence: float | None = Field(default=None, description="Matcher confidence, below the 0.50 review threshold.")
    match_method: str | None = Field(default=None, description="Stage that produced the candidate.")
    order_created_at: datetime | None = Field(default=None, description="When the order was submitted.")
    flagged_at: datetime | None = Field(default=None, description="When the line was flagged for review.")
    reviewed_at: datetime | None = Field(default=None, description="When a pharmacist resolved it.")
    reviewed_by: str | None = Field(default=None, description="Who resolved it.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "item_id": "3a1c5b90-2f4d-4a11-9a55-9f8f2b1d4c77",
                    "order_id": "1f0d0f6e-0d8f-4a4e-9a2a-2f5f9d1e3a44",
                    "pharmacy_id": "PH-001",
                    "raw_token": "ketolak",
                    "proposed_catalogue_id": "ketoderm-cream-2",
                    "proposed_catalogue_name": "Ketoderm Cream 2%",
                    "quantity": 2,
                    "confidence": 0.47,
                    "match_method": "fuzzy",
                    "order_created_at": "2026-10-17T09:12:00Z",
                    "flagged_at": None,
                    "reviewed_at": None,
                    "reviewed_by": None,
                }
            ]
        },
    }


class ReviewQueueResponse(ApiModel):
    """200 response for ``GET /api/v1/orders/review-queue``."""

    items: list[ReviewQueueItemResponse] = Field(description="Flagged lines, oldest first.")
    total: int = Field(ge=0, description="Number of items returned.")
    pending_total: int = Field(ge=0, description="Total unresolved items, including any beyond `limit`.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {"examples": [{"items": [], "total": 0, "pending_total": 0}]},
    }


class ReviewActionRequest(ApiModel):
    """A pharmacist's decision on one flagged line."""

    action: Literal["accept", "correct", "dismiss"] = Field(
        description=(
            "`accept` keeps the proposed catalogue id, `correct` replaces it with "
            "`corrected_catalogue_id`, `dismiss` discards the line entirely."
        )
    )
    corrected_catalogue_id: str | None = Field(
        default=None,
        max_length=MAX_CATALOGUE_ID_LENGTH,
        description="Required when action is `correct`; must be a known catalogue id.",
    )
    reviewed_by: str = Field(
        min_length=1,
        max_length=MAX_REVIEWER_LENGTH,
        description="Pharmacist or operator resolving the item.",
    )
    note: str | None = Field(
        default=None,
        max_length=MAX_RAW_TOKEN_LENGTH,
        description="Optional free-text rationale retained for the audit trail.",
    )

    @field_validator("corrected_catalogue_id")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_action_pairing(self) -> "ReviewActionRequest":
        """Cross-field rule: ``correct`` is meaningless without a target id.

        Declared as a pydantic validator rather than a plain method so FastAPI
        converts the failure into a **422**.  A ``ValueError`` raised inside the
        handler would bypass the request-validation path and surface as a 500.
        """
        if self.action == "correct" and not self.corrected_catalogue_id:
            raise ValueError("corrected_catalogue_id is required when action is 'correct'")
        if self.action != "correct" and self.corrected_catalogue_id:
            raise ValueError("corrected_catalogue_id is only valid when action is 'correct'")
        return self

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {"action": "correct", "corrected_catalogue_id": "ketoderm-cream-2", "reviewed_by": "pharmacist-1"}
            ]
        },
    }


class ReviewActionResponse(ApiModel):
    """200 response for ``PATCH /api/v1/orders/review-queue/{item_id}``."""

    item_id: str = Field(description="Resolved order line.")
    action: Literal["accept", "correct", "dismiss"] = Field(description="What was applied.")
    catalogue_id: str | None = Field(description="Final catalogue id, or null when dismissed.")
    catalogue_name: str | None = Field(default=None, description="Display name of the final product.")
    needs_review: bool = Field(description="Always false after a successful review.")
    reviewed_at: datetime = Field(description="When the item was resolved.")
    reviewed_by: str = Field(description="Who resolved it.")
    note: str | None = Field(default=None, description="Pharmacist's note, when supplied.")

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "item_id": "3a1c5b90-2f4d-4a11-9a55-9f8f2b1d4c77",
                    "action": "correct",
                    "catalogue_id": "ketoderm-cream-2",
                    "catalogue_name": "Ketoderm Cream 2%",
                    "needs_review": False,
                    "reviewed_at": "2026-10-17T18:05:00Z",
                    "reviewed_by": "pharmacist-1",
                    "note": None,
                }
            ]
        },
    }


__all__ = [
    "ReviewActionRequest",
    "ReviewActionResponse",
    "ReviewQueueItemResponse",
    "ReviewQueueResponse",
]