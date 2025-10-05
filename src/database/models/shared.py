from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String, Boolean, UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SharedPrediction(Base):
    __tablename__ = "shared_predictions"

    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    result_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    image_key: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    prediction = relationship("Prediction", back_populates="shared_items")
