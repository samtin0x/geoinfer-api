"""Prediction model for tracking geospatial predictions."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .usage import UsageType


class Prediction(Base):
    """Model for tracking geospatial predictions."""

    __tablename__ = "predictions"

    id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), primary_key=True)
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
    usage_type: Mapped[UsageType | None] = mapped_column(
        String, nullable=True, default=UsageType.GEOINFER_GLOBAL_0_0_1
    )
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
