"""Prediction feedback model."""

from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import DateTime, ForeignKey, String, Text, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FeedbackType(str, Enum):
    """Feedback type enum."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    CLOSE = "close"


class PredictionFeedback(Base):
    """User feedback on predictions."""

    __tablename__ = "prediction_feedback"

    prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    feedback: Mapped[FeedbackType] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    prediction = relationship("Prediction", backref="feedback")
