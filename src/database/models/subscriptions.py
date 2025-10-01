"""Subscription and credit package models."""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .credit_grants import GrantType


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    UNPAID = "unpaid"
    TRIALING = "trialing"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_item_base_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_item_overage_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_price_base_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_price_overage_id: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    price_paid: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_allowance: Mapped[int] = mapped_column(Integer, nullable=False)
    overage_unit_price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    status: Mapped[SubscriptionStatus] = mapped_column(String, nullable=False)
    overage_enabled: Mapped[bool] = mapped_column(default=False)
    user_extra_cap: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    pause_access: Mapped[bool] = mapped_column(default=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False)
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    organization = relationship("Organization", back_populates="subscriptions")
    credit_grants = relationship(
        "CreditGrant", back_populates="subscription", cascade="all, delete-orphan"
    )
    usage_periods = relationship(
        "UsagePeriod", back_populates="subscription", cascade="all, delete-orphan"
    )
    alert_settings = relationship(
        "AlertSettings",
        back_populates="subscription",
        cascade="all, delete-orphan",
        uselist=False,
    )
    alerts = relationship(
        "Alert", back_populates="subscription", cascade="all, delete-orphan"
    )


class TopUp(Base):
    __tablename__ = "topups"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    price_paid: Mapped[float] = mapped_column(Float, nullable=False)
    credits_purchased: Mapped[int] = mapped_column(Integer, nullable=False)
    package_type: Mapped[GrantType] = mapped_column(
        String, nullable=False, default=GrantType.TOPUP
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    organization = relationship("Organization", back_populates="topups")
    credit_grants = relationship(
        "CreditGrant", back_populates="topup", cascade="all, delete-orphan"
    )


class UsagePeriod(Base):
    __tablename__ = "usage_periods"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    overage_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overage_reported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    subscription = relationship("Subscription", back_populates="usage_periods")
