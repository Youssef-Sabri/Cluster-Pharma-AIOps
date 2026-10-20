"""``drug_catalogue`` — the canonical product master used for order matching.

The catalogue is loaded from the curated synthetic list defined in
:mod:`app.pipelines.data_generator`.  Brand names are the well-known public
trade names commonly listed in the Egyptian market so that fuzzy matching is
exercised realistically; **all prices, demand weights and volumes are invented
for demonstration purposes** — nothing here reflects real commercial data.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: Retail segment, mirroring the ``product_category`` forecast feature.
CATEGORY_OTC: Final[str] = "OTC"
CATEGORY_PRESCRIPTION: Final[str] = "PRESCRIPTION"
CATEGORY_COSMETIC: Final[str] = "COSMETIC"
VALID_CATEGORIES: Final[frozenset[str]] = frozenset({CATEGORY_OTC, CATEGORY_PRESCRIPTION, CATEGORY_COSMETIC})


class DrugCatalogue(Base):
    """One sellable SKU.

    Attributes
    ----------
    catalogue_id:
        Stable slug-style identifier, e.g. ``panadol-extra-500``. This is the
        value returned by the order matcher as ``catalogue_id``.
    franco_arabic:
        Transliterated spelling customers actually type (``panadol``,
        ``augmentyn``, ``kattaflam``). Indexed for the fuzzy-matching hot path.
    category / therapeutic_class:
        Derived segments required by the Phase 2 feature module and by the
        demand-shock simulation (antibiotic / antipyretic targeting).
    """

    __tablename__ = "drug_catalogue"
    __table_args__ = (
        Index("ix_drug_catalogue_brand_name", "brand_name"),
        Index("ix_drug_catalogue_franco_arabic", "franco_arabic"),
    )

    catalogue_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    generic_name: Mapped[str | None] = mapped_column(String(200))
    arabic_name: Mapped[str | None] = mapped_column(String(200))
    franco_arabic: Mapped[str | None] = mapped_column(String(200))
    form: Mapped[str | None] = mapped_column(String(50))
    strength: Mapped[str | None] = mapped_column(String(50))
    unit_price_egp: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(32))
    therapeutic_class: Mapped[str | None] = mapped_column(String(32))


__all__ = ["CATEGORY_COSMETIC", "CATEGORY_OTC", "CATEGORY_PRESCRIPTION", "VALID_CATEGORIES", "DrugCatalogue"]