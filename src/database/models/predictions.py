"""Prediction model for tracking geospatial predictions."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .usage import ModelType


class Prediction(Base):
    """Model for tracking geospatial predictions."""

    __tablename__ = "predictions"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    processing_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    credits_consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_type: Mapped[ModelType | None] = mapped_column(
        String, nullable=True, default=ModelType.GLOBAL
    )
    model_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="predictions")
    organization = relationship("Organization", back_populates="predictions")
    api_key = relationship("ApiKey", back_populates="predictions")
    shared_items = relationship(
        "SharedPrediction",
        back_populates="prediction",
        uselist=False,
        cascade="all, delete-orphan",
    )
