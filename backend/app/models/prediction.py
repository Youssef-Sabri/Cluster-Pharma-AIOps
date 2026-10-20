"""``predictions`` — persisted demand forecasts produced by the LightGBM model.

One row per (pharmacy, product, forecast_date).  The composite index in the
technical plan serves both the per-pharmacy forecast endpoint and the nightly
retraining window queries.

Synthetic data only.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Prediction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A single point forecast with its prediction interval.

    Attributes
    ----------
    forecast_date:
        The calendar day being forecast (not the run date).
    predicted_units / lower_bound / upper_bound:
        Point estimate and the 10th/90th percentile interval produced by
        LightGBM quantile regression.
    model_version:
        MLflow model version that generated the row, e.g. ``lgbm-demand-forecast/3``.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_pharmacy_id_product_id_forecast_date", "pharmacy_id", "product_id", "forecast_date"),
    )

    pharmacy_id: Mapped[str | None] = mapped_column(String(50))
    product_id: Mapped[str | None] = mapped_column(String(100))
    forecast_date: Mapped[date | None] = mapped_column(Date)
    predicted_units: Mapped[float | None] = mapped_column(Float)
    lower_bound: Mapped[float | None] = mapped_column(Float)
    upper_bound: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(50))


__all__ = ["Prediction"]