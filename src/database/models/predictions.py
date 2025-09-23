"""Prediction model for tracking geospatial predictions."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Prediction(Base):
    """Model for tracking geospatial predictions."""

    __tablename__ = "predictions"

    id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    input_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'url' or 'upload'
    input_data: Mapped[str] = mapped_column(Text, nullable=False)  # URL or file path
    prediction_result: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON result
    processing_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        Text, default="completed"
    )  # 'completed', 'failed', 'processing'
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="predictions")
    organization = relationship("Organization", back_populates="predictions")
