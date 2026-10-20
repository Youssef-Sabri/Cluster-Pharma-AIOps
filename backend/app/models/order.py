"""``orders`` and ``order_items`` — the synthetic order ledger and review queue.

Every row is produced by :mod:`app.pipelines.data_generator`; no real order,
pharmacy, or prescriber data is stored anywhere in this project.

``order_items`` doubles as the **human-in-the-loop review queue**: any matched
item whose final confidence is below the safety threshold (0.50) is persisted
with ``needs_review = True`` for manual verification.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

#: ``match_method`` values produced by the two-stage matcher.
MATCH_METHOD_FUZZY: str = "fuzzy"
MATCH_METHOD_LLM: str = "llm"
MATCH_METHOD_EXACT: str = "exact"
VALID_MATCH_METHODS: frozenset[str] = frozenset({MATCH_METHOD_FUZZY, MATCH_METHOD_LLM, MATCH_METHOD_EXACT})


class Order(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A single restock order submitted by one pharmacy.

    ``raw_text`` keeps the free-form order as the customer wrote it
    (English / Arabizi / Franco-Arabic), which is what the matcher consumes.

    Two indexes are kept on purpose: ``ix_orders_created_at`` serves global
    time-window scans (drift windows, retention), while the composite
    ``(pharmacy_id, created_at)`` serves the per-pharmacy forecasting and
    training-window queries without a sort.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_pharmacy_id_created_at", "pharmacy_id", "created_at"),
    )

    pharmacy_id: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def total_units(self) -> int:
        """Total units requested across all items of the order."""
        return sum(item.quantity for item in self.items)


class OrderItem(UUIDPrimaryKeyMixin, Base):
    """One matched (or unmatched) line of an order.

    Attributes
    ----------
    raw_token:
        The fragment of :attr:`Order.raw_text` that produced this item.
    confidence:
        Final matcher confidence in ``[0, 1]``.  Values below the review
        threshold must be surfaced to a human (rule: *Human-in-the-Loop Pharma
        Safety*).
    needs_review:
        ``True`` whenever ``confidence < 0.50``; cleared only once
        ``reviewed_by`` / ``reviewed_at`` are populated.
    """

    __tablename__ = "order_items"
    __table_args__ = (
        # ON DELETE CASCADE on the FK keeps the ledger free of orphan lines.
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_catalogue_id", "catalogue_id"),
        Index("ix_order_items_needs_review", "needs_review"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_token: Mapped[str | None] = mapped_column(Text)
    catalogue_id: Mapped[str | None] = mapped_column(String(100))
    catalogue_name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(20))
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))

    order: Mapped[Order] = relationship(back_populates="items", lazy="selectin")


__all__ = [
    "MATCH_METHOD_EXACT",
    "MATCH_METHOD_FUZZY",
    "MATCH_METHOD_LLM",
    "VALID_MATCH_METHODS",
    "Order",
    "OrderItem",
]