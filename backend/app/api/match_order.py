"""``POST /api/v1/match-order`` — match a raw order and record it.

This is the write path into the ledger: the matched order and every line are
persisted to ``orders`` / ``order_items``, which is also what feeds the Phase 4
drift detector's ``match_confidence`` feature and the human review queue.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Final, Sequence

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.state import state
from app.database import get_db
from app.models import Order, OrderItem
from app.monitoring import metrics
from app.schemas.match_order import MatchedItem, MatchOrderRequest, MatchOrderResponse

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.match_order")

router = APIRouter(prefix="/api/v1", tags=["order-matching"])


def _weighted_confidence(results: Sequence[Any]) -> float:
    """Quantity-weighted mean confidence across the matched lines.

    Weighting by quantity rather than taking a plain mean stops one low-volume
    ambiguous line from dominating the headline number for a large order.
    """
    if not results:
        return 0.0
    total_units = sum(result.quantity for result in results)
    if total_units <= 0:
        return float(sum(result.confidence for result in results) / len(results))
    return float(sum(result.confidence * max(result.quantity, 1) for result in results) / total_units)


async def _persist(
    db: AsyncSession, request: MatchOrderRequest, results: Sequence[Any]
) -> tuple[uuid.UUID | None, list[uuid.UUID | None]]:
    """Write the order and its lines, returning the order id and per-line ids.

    Orders the matcher could not decompose at all are not persisted: a row with
    no lines and no matched product carries no signal and would only pollute the
    Phase 4 drift window.
    """
    if not results:
        return None, []

    order = Order(
        pharmacy_id=request.pharmacy_id,
        raw_text=request.raw_text,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(order)
    await db.flush()

    items = [
        OrderItem(
            order_id=order.id,
            raw_token=result.raw_token,
            catalogue_id=result.catalogue_id,
            catalogue_name=result.catalogue_name,
            quantity=result.quantity,
            confidence=result.confidence,
            match_method=result.match_method,
            needs_review=result.needs_review,
        )
        for result in results
    ]
    db.add_all(items)
    await db.commit()
    await db.refresh(order)

    # Re-read so the ids are the ones PostgreSQL assigned (defaults are
    # server-side), preserving the order the matcher produced.
    stored = (
        await db.execute(
            select(OrderItem.id, OrderItem.raw_token).where(OrderItem.order_id == order.id)
        )
    ).all()
    by_token = {raw_token: item_id for item_id, raw_token in stored}

    logger.info(
        "Order persisted",
        extra={
            "order_id": str(order.id),
            "pharmacy_id": request.pharmacy_id,
            "items": len(results),
            "needs_review": sum(1 for result in results if result.needs_review),
        },
    )
    return order.id, [by_token.get(result.raw_token) for result in results]


@router.post(
    "/match-order",
    response_model=MatchOrderResponse,
    summary="Match a raw order against the catalogue",
    description=(
        "Parses a free-form order (English, Arabizi, Arabic script, Franco-Arabic), "
        "matches each line with rapidfuzz and re-ranks only the ambiguous remainder "
        "with Gemini, then records the order in `orders` / `order_items`.\n\n"
        "Lines whose final confidence is below **0.50** are returned with "
        "`needs_review = true` and queued for pharmacist review — automated "
        "certainty is never fabricated for a clinical product. Set `persist=false` "
        "for a dry run that touches no database rows."
    ),
    responses={
        200: {"description": "Order matched.", "model": MatchOrderResponse},
        422: {"description": "Request body failed validation."},
        503: {"description": "The order catalogue is not loaded."},
    },
)
async def match_order(
    request: MatchOrderRequest, db: AsyncSession = Depends(get_db)
) -> MatchOrderResponse:
    """Match a raw order and persist the result."""
    matcher = state.require_matcher()
    results = matcher.match_text(request.raw_text)

    for result in results:
        metrics.record_match(result.confidence, result.needs_review)

    order_id: uuid.UUID | None = None
    item_ids: list[uuid.UUID | None] = []
    if request.persist:
        order_id, item_ids = await _persist(db, request, results)

    reviewable = [result for result in results if result.needs_review]
    return MatchOrderResponse(
        order_id=str(order_id) if order_id else None,
        pharmacy_id=request.pharmacy_id,
        items=[
            MatchedItem(
                raw_token=result.raw_token,
                catalogue_id=result.catalogue_id,
                catalogue_name=result.catalogue_name,
                quantity=result.quantity,
                unit=result.unit,
                confidence=result.confidence,
                match_method=result.match_method,
                stage=result.stage,
                needs_review=result.needs_review,
                rationale=result.rationale,
                item_id=str(item_ids[index]) if index < len(item_ids) and item_ids[index] else None,
            )
            for index, result in enumerate(results)
        ],
        overall_confidence=_weighted_confidence(results),
        items_needing_review=len(reviewable),
        total_units=sum(result.quantity for result in results),
        persisted=order_id is not None,
    )


__all__ = ["match_order", "router"]