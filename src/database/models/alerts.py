"""Alert models for usage monitoring and notifications."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy import DateTime, String, Float, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AlertSettings(Base):
    """Alert configuration for subscriptions."""

    __tablename__ = "alert_settings"

    id: Mapped[SQLAlchemyUUID] = mapped_column(
        SQLAlchemyUUID, primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[SQLAlchemyUUID] = mapped_column(
        SQLAlchemyUUID,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_thresholds: Mapped[list[float]] = mapped_column(
        JSON, default=list, nullable=False
    )  # List of percentages like [0.8, 0.9, 0.95]
    alert_destinations: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )  # List of email addresses like ["admin@example.com"]
    alerts_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    locale: Mapped[str] = mapped_column(String, default="en", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    subscription = relationship("Subscription", back_populates="alert_settings")


class Alert(Base):
    """Generic alert table for all types of alerts."""

    __tablename__ = "alerts"

    id: Mapped[SQLAlchemyUUID] = mapped_column(
        SQLAlchemyUUID, primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[SQLAlchemyUUID] = mapped_column(
        SQLAlchemyUUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_id: Mapped[SQLAlchemyUUID] = mapped_column(
        SQLAlchemyUUID,
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=True,
    )
    alert_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # "usage", "billing", "system", etc.
    alert_category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # "threshold", "overage", "payment", etc.
    threshold_percentage: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # For threshold-based alerts
    alert_message: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(
        String, default="info", nullable=False
    )  # "info", "warning", "error", "critical"
    locale: Mapped[str] = mapped_column(String, default="en", nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    organization = relationship("Organization", back_populates="alerts")
    subscription = relationship("Subscription", back_populates="alerts")
