"""Organization model and related enums."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PlanTier(str, Enum):
    FREE = "free"
    SUBSCRIBED = "subscribed"
    ENTERPRISE = "enterprise"


class OrganizationRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationPermission(str, Enum):
    # Organization management
    MANAGE_ORGANIZATION = "manage_organization"

    # Member management
    MANAGE_MEMBERS = "manage_members"
    MANAGE_ROLES = "manage_roles"
    VIEW_MEMBERS = "view_members"

    # Billing and usage
    MANAGE_BILLING = "manage_billing"
    VIEW_ANALYTICS = "view_analytics"

    # API access
    MANAGE_API_KEYS = "manage_api_keys"

    # Content access
    VIEW_ORGANIZATION = "view_organization"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_tier: Mapped[PlanTier] = mapped_column(
        String, default=PlanTier.FREE, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships (defined via string references to avoid circular imports)
    members = relationship(
        "User", foreign_keys="User.organization_id", back_populates="organization"
    )
    subscriptions = relationship(
        "Subscription", back_populates="organization", cascade="all, delete-orphan"
    )
    topups = relationship(
        "TopUp", back_populates="organization", cascade="all, delete-orphan"
    )
    invitations = relationship(
        "Invitation", back_populates="organization", cascade="all, delete-orphan"
    )
    user_roles = relationship(
        "UserOrganizationRole",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    predictions = relationship(
        "Prediction",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    credit_grants = relationship(
        "CreditGrant",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    api_keys = relationship(
        "ApiKey",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
