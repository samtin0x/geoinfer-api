from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from fastapi import status
from src.database.models import (
    Invitation,
    InvitationStatus,
    Organization,
    User,
)
from src.services.base import BaseService
import email_normalize  # type: ignore[import-untyped]


class OrganizationInvitationService(BaseService):
    """Service for managing organization invitations with proper error handling.

    This service focuses on business logic while relying on API layer validation
    for authentication, permissions, plan tiers, and data format validation.
    """

    async def create_invitation(
        self,
        organization_id: UUID,
        email: str,
        invited_by_id: UUID,
        expires_in_days: int = 7,
    ) -> Invitation:
        """Create a new organization invitation.

        Note: API layer already validates email format, user permissions,
        and organization plan tier requirements. Service layer includes
        backup validation for security when called directly (e.g., tests).
        """
        # Backup validation: Check organization plan tier (should be handled by API layer)
        organization = await self.db.get(Organization, organization_id)
        if not organization:
            raise GeoInferException(MessageCode.RESOURCE_NOT_FOUND, 404)

        from src.database.models.organizations import PlanTier

        if organization.plan_tier == PlanTier.FREE:
            raise GeoInferException(MessageCode.AUTH_INSUFFICIENT_PLAN_TIER, 403)

        # Business logic: Check if user is already a member
        await self._ensure_user_not_member(email, organization_id)

        # Business logic: Check if there's already a pending invitation
        await self._ensure_no_pending_invitation(email, organization_id)

        # Create invitation
        invitation = Invitation(
            organization_id=organization_id,
            invited_by_id=invited_by_id,
            email=email,
            token=token_urlsafe(32),
            expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
        )

        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation)

        self.logger.info(
            f"Created invitation {invitation.id} for {email} to organization {organization_id}"
        )
        return invitation

    async def list_organization_invitations(
        self, organization_id: UUID, requesting_user_id: UUID | None = None
    ) -> list[Invitation]:
        """List all invitations for an organization.

        Note: API layer already validates user permissions and organization access.
        """
        stmt = (
            select(Invitation)
            .options(
                selectinload(Invitation.invited_by),
            )
            .where(Invitation.organization_id == organization_id)
            .order_by(Invitation.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_pending_invitations(self, user_email: str) -> list[Invitation]:
        """Get all pending invitations for a user by email.

        Note: API layer already validates user authentication and email format.
        """
        stmt = (
            select(Invitation)
            .options(
                selectinload(Invitation.organization),
                selectinload(Invitation.invited_by),
            )
            .where(
                and_(
                    Invitation.email.ilike(user_email.lower()),
                    Invitation.status == InvitationStatus.PENDING,
                    Invitation.expires_at > datetime.now(timezone.utc),
                )
            )
            .order_by(Invitation.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def respond_to_invitation(
        self, token: str, user_id: UUID, accept: bool = True
    ) -> Invitation:
        """Accept or decline an organization invitation.

        Note: API layer already validates token format and user authentication.
        """
        # Get invitation and validate
        stmt = (
            select(Invitation)
            .options(
                selectinload(Invitation.organization),
                selectinload(Invitation.invited_by),
            )
            .where(Invitation.token == token)
        )
        result = await self.db.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise GeoInferException(
                MessageCode.INVITE_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )
        await self._ensure_invitation_can_be_responded(invitation)

        # Get user and validate
        user = await self._get_user_by_id(user_id)
        await self._ensure_invitation_user_match(invitation, user)

        # Check if user is already a member
        if user.organization_id == invitation.organization_id:
            raise GeoInferException(
                MessageCode.INVITATION_ALREADY_MEMBER, status.HTTP_400_BAD_REQUEST
            )

        if accept:
            # Accept invitation - add user to organization as member
            from src.services.organization import OrganizationService
            from src.database.models import OrganizationRole

            org_service = OrganizationService(self.db)
            success = await org_service.add_user_to_organization(
                organization_id=invitation.organization_id,
                user_id=user_id,
                requesting_user_id=invitation.invited_by_id,
                role=OrganizationRole.MEMBER,  # Always assign MEMBER role for invitations
            )

            if not success:
                raise GeoInferException(
                    MessageCode.VALIDATION_INVALID_INPUT,
                    status.HTTP_400_BAD_REQUEST,
                    details={"description": "Failed to add user to organization"},
                )

            # Mark invitation as accepted
            await self.db.execute(
                update(Invitation)
                .where(Invitation.id == invitation.id)
                .values(
                    status=InvitationStatus.ACCEPTED,
                    accepted_at=datetime.now(timezone.utc),
                )
            )

            self.logger.info(
                f"User {user_id} accepted invitation {invitation.id} and was added as MEMBER"
            )
        else:
            # Decline invitation
            await self.db.execute(
                update(Invitation)
                .where(Invitation.id == invitation.id)
                .values(status=InvitationStatus.CANCELLED)
            )

            self.logger.info(f"User {user_id} declined invitation {invitation.id}")

        await self.db.commit()

        # Return updated invitation
        result = await self.db.execute(
            select(Invitation).where(Invitation.id == invitation.id)
        )
        return result.scalar_one()

    async def cancel_invitation(
        self, invitation_id: UUID, requesting_user_id: UUID
    ) -> Invitation:
        """Cancel an invitation.

        Note: API layer already validates user permissions and organization access.
        """
        # Get invitation with organization
        stmt = (
            select(Invitation)
            .options(selectinload(Invitation.organization))
            .where(Invitation.id == invitation_id)
        )
        result = await self.db.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise GeoInferException(
                MessageCode.INVITE_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )

        # Business logic: Validate invitation can be cancelled
        if invitation.status != InvitationStatus.PENDING:
            if invitation.status == InvitationStatus.CANCELLED:
                raise GeoInferException(
                    MessageCode.INVITE_CANCELLED, status.HTTP_400_BAD_REQUEST
                )
            elif invitation.status == InvitationStatus.EXPIRED:
                raise GeoInferException(
                    MessageCode.INVITATION_EXPIRED, status.HTTP_400_BAD_REQUEST
                )
            else:
                raise GeoInferException(
                    MessageCode.INVITATION_ALREADY_USED, status.HTTP_400_BAD_REQUEST
                )

        # Mark invitation as cancelled
        await self.db.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(status=InvitationStatus.CANCELLED)
        )

        await self.db.commit()

        self.logger.info(f"Cancelled invitation {invitation_id}")
        return invitation

    async def cleanup_expired_invitations(self) -> int:
        """Mark expired invitations as expired.

        Note: This is a background operation that doesn't rely on API validation.
        """
        result = await self.db.execute(
            update(Invitation)
            .where(
                and_(
                    Invitation.status == InvitationStatus.PENDING,
                    Invitation.expires_at < datetime.now(timezone.utc),
                )
            )
            .values(status=InvitationStatus.EXPIRED)
        )

        await self.db.commit()
        expired_count = result.rowcount

        if expired_count > 0:
            self.logger.info(f"Marked {expired_count} invitations as expired")

        return expired_count

    # Private helper methods

    async def _ensure_organization_exists(self, organization_id: UUID) -> Organization:
        """Get organization and verify it exists.

        Note: This method is kept for internal consistency but API layer
        should validate organization access through permissions.
        """
        stmt = select(Organization).where(Organization.id == organization_id)
        result = await self.db.execute(stmt)
        organization = result.scalar_one_or_none()

        if not organization:
            raise GeoInferException(
                MessageCode.ORG_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )

        return organization

    async def _get_user_by_email(self, email: str) -> User | None:
        """Get user by email.

        Note: API layer already validates email format.
        """
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, user_id: UUID) -> User:
        """Get user by ID.

        Note: API layer already validates user authentication and existence.
        """
        user = await self.db.get(User, user_id)
        if not user:
            raise GeoInferException(
                MessageCode.USER_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )
        return user

    async def _ensure_user_not_member(self, email: str, organization_id: UUID):
        """Business logic: Ensure user is not already a member."""
        stmt = select(User).where(
            and_(
                User.email.ilike(email.lower()), User.organization_id == organization_id
            )
        )
        result = await self.db.execute(stmt)
        existing_member = result.scalar_one_or_none()

        if existing_member:
            raise GeoInferException(
                MessageCode.INVITATION_ALREADY_MEMBER, status.HTTP_400_BAD_REQUEST
            )

    async def _ensure_no_pending_invitation(self, email: str, organization_id: UUID):
        """Business logic: Ensure no pending invitation exists for this email."""
        stmt = select(Invitation).where(
            and_(
                Invitation.organization_id == organization_id,
                Invitation.email.ilike(email.lower()),
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        result = await self.db.execute(stmt)
        existing_invitation = result.scalar_one_or_none()

        if existing_invitation:
            raise GeoInferException(
                MessageCode.INVITE_ALREADY_PENDING,
                status.HTTP_409_CONFLICT,
                details={
                    "email": email,
                    "existing_invitation_id": str(existing_invitation.id),
                },
            )

    async def _ensure_invitation_can_be_responded(self, invitation: Invitation):
        """Business logic: Ensure invitation can be accepted or declined."""
        if invitation.status != InvitationStatus.PENDING:
            if invitation.status == InvitationStatus.EXPIRED:
                raise GeoInferException(
                    MessageCode.INVITATION_EXPIRED, status.HTTP_400_BAD_REQUEST
                )
            elif invitation.status == InvitationStatus.CANCELLED:
                raise GeoInferException(
                    MessageCode.INVITE_CANCELLED, status.HTTP_400_BAD_REQUEST
                )
            else:
                raise GeoInferException(
                    MessageCode.INVITATION_ALREADY_USED, status.HTTP_400_BAD_REQUEST
                )

        # Check if expired
        if invitation.expires_at < datetime.now(timezone.utc):
            # Mark as expired in database
            await self.db.execute(
                update(Invitation)
                .where(Invitation.id == invitation.id)
                .values(status=InvitationStatus.EXPIRED)
            )
            await self.db.commit()
            raise GeoInferException(
                MessageCode.INVITATION_EXPIRED, status.HTTP_400_BAD_REQUEST
            )

    async def _ensure_invitation_user_match(self, invitation: Invitation, user: User):
        """Business logic: Ensure user matches the invitation."""
        # Verify email matches with proper normalization (handles Gmail dots, plus-addressing)
        try:
            user_result = email_normalize.normalize(user.email)
            invitation_result = email_normalize.normalize(invitation.email)
            emails_match = (
                user_result.normalized_address == invitation_result.normalized_address
            )
        except Exception:
            # Fallback to basic case-insensitive comparison if normalization fails
            emails_match = (
                user.email.lower().strip() == invitation.email.lower().strip()
            )

        if not emails_match:
            raise GeoInferException(
                MessageCode.VALIDATION_INVALID_INPUT,
                status.HTTP_400_BAD_REQUEST,
                details={
                    "field": "email",
                    "reason": "User email does not match invitation",
                },
            )
