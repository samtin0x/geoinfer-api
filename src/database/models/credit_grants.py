"""Credit grant models."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class GrantType(str, Enum):
    SUBSCRIPTION = "subscription"
    TOPUP = "topup"
    TRIAL = "trial"
    GEOINFER = "geoinfer"


class CreditGrant(Base):
    __tablename__ = "credit_grants"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    topup_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("topups.id", ondelete="SET NULL"), nullable=True
    )
    grant_type: Mapped[GrantType] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    organization = relationship("Organization", back_populates="credit_grants")
    subscription = relationship("Subscription", back_populates="credit_grants")
    topup = relationship("TopUp", back_populates="credit_grants")
