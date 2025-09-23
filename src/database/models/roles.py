"""Role and permission models."""

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .organizations import OrganizationPermission, OrganizationRole


# Role-based permission mappings using pure Python logic
ROLE_PERMISSIONS = {
    OrganizationRole.ADMIN: {
        # Admins get ALL permissions
        OrganizationPermission.MANAGE_ORGANIZATION,
        OrganizationPermission.MANAGE_MEMBERS,
        OrganizationPermission.MANAGE_ROLES,
        OrganizationPermission.VIEW_MEMBERS,
        OrganizationPermission.MANAGE_BILLING,
        OrganizationPermission.VIEW_ANALYTICS,
        OrganizationPermission.MANAGE_API_KEYS,
        OrganizationPermission.VIEW_ORGANIZATION,
    },
    OrganizationRole.MEMBER: {
        # Members get basic access
        OrganizationPermission.VIEW_MEMBERS,
        OrganizationPermission.VIEW_ANALYTICS,
        OrganizationPermission.VIEW_ORGANIZATION,
        OrganizationPermission.MANAGE_API_KEYS,
    },
}


def get_permissions_for_role(role: OrganizationRole) -> set[OrganizationPermission]:
    """Get all permissions for a given role."""
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role: OrganizationRole, permission: OrganizationPermission) -> bool:
    """Check if a role has a specific permission."""
    return permission in get_permissions_for_role(role)


class UserOrganizationRole(Base):
    __tablename__ = "user_organization_roles"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrganizationRole] = mapped_column(String, nullable=False)
    granted_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship(
        "User", foreign_keys=[user_id], back_populates="organization_roles"
    )
    organization = relationship("Organization", back_populates="user_roles")
    granted_by = relationship("User", foreign_keys=[granted_by_id])

    __table_args__ = (
        # Enforce single role per user per organization
        UniqueConstraint(
            "user_id", "organization_id", name="unique_user_org_single_role"
        ),
    )
