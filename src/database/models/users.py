"""User model and related enums."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, comment="Supabase Auth User ID"
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    locale: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships (defined via string references to avoid circular imports)
    organization = relationship(
        "Organization", foreign_keys=[organization_id], back_populates="members"
    )
    api_keys = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    sent_invitations = relationship(
        "Invitation",
        foreign_keys="Invitation.invited_by_id",
        back_populates="invited_by",
        cascade="all, delete-orphan",
    )
    organization_roles = relationship(
        "UserOrganizationRole",
        foreign_keys="UserOrganizationRole.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    predictions = relationship(
        "Prediction",
        back_populates="user",
        cascade="all, delete-orphan",
    )
