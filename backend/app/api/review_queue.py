"""``GET``/``PATCH /api/v1/orders/review-queue`` — the pharmacist's work queue.

This is where the human-in-the-loop safety rule is *closed*: the Phase 3 matcher
flags anything below 0.50 confidence with ``needs_review = True``, and a
pharmacist resolves it here.  Until then such a line must never be fulfilled
automatically.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.state import state
from app.config import settings
from app.database import get_db
from app.models import DrugCatalogue, Order, OrderItem
from app.schemas.review_queue import (
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewQueueItemResponse,
    ReviewQueueResponse,
)

logger: Final[logging.Logger] = logging.getLogger("clusterops.api.review_queue")

router = APIRouter(prefix="/api/v1/orders", tags=["human-in-the-loop"])

#: Defaults chosen so an operator's first request cannot pull the whole queue.
DEFAULT_LIMIT: Final[int] = 50
MAX_LIMIT: Final[int] = 500


def _to_item(item: OrderItem, order: Order | None) -> ReviewQueueItemResponse:
    """Adapt an ``order_items`` row joined to its order."""
    return ReviewQueueItemResponse(
        item_id=str(item.id),
        order_id=str(item.order_id),
        pharmacy_id=order.pharmacy_id if order is not None else "unknown",
        raw_token=item.raw_token or "",
        proposed_catalogue_id=item.catalogue_id,
        proposed_catalogue_name=item.catalogue_name,
        quantity=item.quantity,
        confidence=float(item.confidence) if item.confidence is not None else None,
        match_method=item.match_method,
        order_created_at=order.created_at if order is not None else None,
        # `order_items` has no separate "flagged_at" column — the line is written
        # in the same transaction as its order, so the order timestamp is the
        # honest available proxy for when review was requested.
        flagged_at=order.created_at if order is not None else None,
        reviewed_at=item.reviewed_at,
        reviewed_by=item.reviewed_by,
    )


@router.get(
    "/review-queue",
    response_model=ReviewQueueResponse,
    summary="Order lines awaiting pharmacist review",
    description=(
        "Returns `order_items` rows still flagged `needs_review = true` — every "
        "matcher line whose confidence fell below "
        f"**{settings.review_confidence_threshold:.2f}**.\n\n"
        "Items are ordered oldest first so the queue is drained in arrival order. "
        "`pending_total` reports the full unresolved backlog even when `limit` "
        "truncates the page."
    ),
    responses={
        200: {"description": "Review queue page.", "model": ReviewQueueResponse},
        422: {"description": "Query parameters failed validation."},
    },
)
async def list_review_queue(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Maximum rows to return."),
    offset: int = Query(default=0, ge=0, description="Rows to skip, for paging."),
    pharmacy_id: str | None = Query(default=None, description="Restrict to one pharmacy."),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    """Page through the unresolved review queue."""
    statement = (
        select(OrderItem, Order)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.needs_review.is_(True))
        .order_by(Order.created_at.asc(), OrderItem.id.asc())
    )
    if pharmacy_id:
        statement = statement.where(Order.pharmacy_id == pharmacy_id)

    rows = (await db.execute(statement.offset(offset).limit(limit))).all()
    pending = (
        await db.execute(select(func.count()).select_from(OrderItem).where(OrderItem.needs_review.is_(True)))
    ).scalar_one()

    return ReviewQueueResponse(
        items=[_to_item(item, order) for item, order in rows],
        total=len(rows),
        pending_total=int(pending),
    )


@router.patch(
    "/review-queue/{item_id}",
    response_model=ReviewActionResponse,
    summary="Resolve a flagged order line",
    description=(
        "Applies a pharmacist's decision and clears `needs_review`:\n\n"
        "* `accept` — keep the matcher's proposed product\n"
        "* `correct` — replace it with `corrected_catalogue_id` (must exist in the catalogue)\n"
        "* `dismiss` — discard the line entirely (sets the catalogue id to null)\n\n"
        "Sets `reviewed_by` and `reviewed_at` for the audit trail. Returns **404** "
        "for an unknown item or one that is not awaiting review, and **409** when a "
        "corrected id is not in the catalogue."
    ),
    responses={
        200: {"description": "Item resolved.", "model": ReviewActionResponse},
        404: {"description": "Unknown item, or the item is not awaiting review."},
        409: {"description": "`corrected_catalogue_id` is not a known catalogue id."},
        422: {"description": "Request body failed validation."},
    },
)
async def resolve_review_item(
    item_id: uuid.UUID,
    action: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewActionResponse:
    """Record a pharmacist's decision on one flagged line."""
    item = (
        await db.execute(select(OrderItem).where(OrderItem.id == item_id).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no review item with id {item_id}"
        )
    if not item.needs_review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"item {item_id} is not awaiting review; it was resolved by {item.reviewed_by!r}",
        )

    catalogue_name: str | None = item.catalogue_name
    if action.action == "correct":
        assert action.corrected_catalogue_id is not None  # guaranteed by validate_action
        entry = state.catalogue.get(action.corrected_catalogue_id) if state.catalogue else None
        if entry is None:
            exists = (
                await db.execute(
                    select(func.count())
                    .select_from(DrugCatalogue)
                    .where(DrugCatalogue.catalogue_id == action.corrected_catalogue_id)
                )
            ).scalar_one()
            if not exists:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"corrected_catalogue_id {action.corrected_catalogue_id!r} is not a known "
                        "catalogue id; a pharmacist may only correct to a real product"
                    ),
                )
        item.catalogue_id = action.corrected_catalogue_id
        catalogue_name = entry.display_name if entry is not None else action.corrected_catalogue_id
    elif action.action == "dismiss":
        item.catalogue_id = None
        catalogue_name = None

    item.catalogue_name = catalogue_name
    item.needs_review = False
    item.reviewed_at = datetime.now(tz=timezone.utc)
    item.reviewed_by = action.reviewed_by
    await db.commit()
    await db.refresh(item)

    logger.info(
        "Review item resolved",
        extra={
            "item_id": str(item.id),
            "action": action.action,
            "reviewed_by": action.reviewed_by,
            "catalogue_id": item.catalogue_id,
        },
    )
    return ReviewActionResponse(
        item_id=str(item.id),
        action=action.action,
        catalogue_id=item.catalogue_id,
        catalogue_name=item.catalogue_name,
        needs_review=item.needs_review,
        reviewed_at=item.reviewed_at,
        reviewed_by=action.reviewed_by or "",
        note=action.note,
    )


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "list_review_queue", "resolve_review_item", "router"]