"""Request/response schemas for ``POST /api/v1/match-order``.

Synthetic data only — orders are generated, never real pharmacy traffic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

#: Longest accepted order.  Anything larger is rejected before the matcher runs;
#: the fuzzy stage is O(catalogue) per token, so an unbounded body would let one
#: caller pin the event loop.
MAX_RAW_TEXT_LENGTH: int = 4_000


class MatchOrderRequest(ApiModel):
    """Submit a free-form restock order for matching against the catalogue."""

    raw_text: str = Field(
        min_length=1,
        max_length=MAX_RAW_TEXT_LENGTH,
        description=(
            "The order as the customer wrote it. Mixing scripts and separators is expected, e.g. "
            "`10 panadol and 5 augmentn 625, 2 boxes brufen 400` or `عشره علب بانادول اكسترا`."
        ),
        examples=["10 panadol and 5 augmentn 625, 2 boxes brufen 400"],
    )
    pharmacy_id: str = Field(
        min_length=1,
        max_length=50,
        description="Pharmacy placing the order; stored on the `orders` row.",
        examples=["PH-001"],
    )
    persist: bool = Field(
        default=True,
        description="Write the order and its items to PostgreSQL. Set false for a dry-run match.",
    )

    @field_validator("raw_text")
    @classmethod
    def _must_contain_something_matchable(cls, value: str) -> str:
        """Reject text with no alphanumeric content before matching.

        Punctuation-only input yields zero items rather than an error, which is
        confusing for a caller who sent a malformed request; 422 at the boundary
        is clearer.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_text must not be blank")
        if not any(character.isalnum() for character in stripped):
            raise ValueError("raw_text contains no letters or digits to match")
        return stripped

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {"raw_text": "10 panadol and 5 augmentn 625", "pharmacy_id": "PH-001", "persist": True}
            ]
        },
    }


class MatchedItem(ApiModel):
    """One matched line of an order."""

    raw_token: str = Field(description="The fragment of the order that produced this line.")
    catalogue_id: str | None = Field(default=None, description="Resolved catalogue id, or null when unmatched.")
    catalogue_name: str | None = Field(default=None, description="Display name of the resolved product.")
    quantity: int = Field(ge=0, description="Units requested on this line.")
    unit: str | None = Field(default=None, description="Pack unit when the text named one (علب / boxes / strips).")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Final matcher confidence. Below 0.50 the item is queued for review."
    )
    match_method: Literal["fuzzy", "llm"] = Field(
        description="`fuzzy` = accepted by rapidfuzz; `llm` = decided by the Gemini re-ranker."
    )
    stage: str = Field(description="Pipeline stage that decided the line: fuzzy, llm or fallback.")
    needs_review: bool = Field(
        description="True whenever confidence < 0.50 — the human-in-the-loop pharma safety rule."
    )
    rationale: str = Field(default="", description="Why the matcher chose this product.")
    item_id: str | None = Field(
        default=None, description="Database id of the persisted `order_items` row, when persisted."
    )

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "raw_token": "panadol",
                    "catalogue_id": "panadol-extra-500",
                    "catalogue_name": "Panadol Extra 500mg",
                    "quantity": 10,
                    "unit": None,
                    "confidence": 1.0,
                    "match_method": "fuzzy",
                    "stage": "fuzzy",
                    "needs_review": False,
                    "rationale": "rapidfuzz token_set_ratio=1.00 on 'panadol extra 500mg'",
                    "item_id": None,
                }
            ]
        },
    }


class MatchOrderResponse(ApiModel):
    """200 response for ``POST /api/v1/match-order``."""

    order_id: str | None = Field(
        default=None, description="Database id of the persisted order, or null for a dry run."
    )
    pharmacy_id: str = Field(description="Pharmacy that placed the order.")
    items: list[MatchedItem] = Field(description="Every line the matcher could extract.")
    overall_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Quantity-weighted mean confidence across the matched lines.",
    )
    items_needing_review: int = Field(ge=0, description="Count of lines flagged needs_review.")
    total_units: int = Field(ge=0, description="Total units across all matched lines.")
    persisted: bool = Field(description="Whether the order was written to PostgreSQL.")
    matched_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    model_config = {
        "extra": "forbid",
        "protected_namespaces": (),
        "json_schema_extra": {
            "examples": [
                {
                    "order_id": "1f0d0f6e-0d8f-4a4e-9a2a-2f5f9d1e3a44",
                    "pharmacy_id": "PH-001",
                    "items": [],
                    "overall_confidence": 0.0,
                    "items_needing_review": 0,
                    "total_units": 0,
                    "persisted": True,
                    "matched_at": "2026-10-17T18:00:00Z",
                }
            ]
        },
    }


__all__ = [
    "MAX_RAW_TEXT_LENGTH",
    "MatchOrderRequest",
    "MatchOrderResponse",
    "MatchedItem",
]