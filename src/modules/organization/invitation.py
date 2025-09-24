from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload
from fastapi import status

from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.database.models import (
    Invitation,
    InvitationStatus,
    Organization,
    User,
)
from src.core.base import BaseService
import email_normalize  # type: ignore[import-untyped]
from src.modules.organization.use_cases import (
    OrganizationService,
)
from src.database.models import OrganizationRole


class OrganizationInvitationService(BaseService):
    async def create_invitation(
        self,
        organization_id: UUID,
        email: str,
        invited_by_id: UUID,
        expires_in_days: int = 7,
    ) -> Invitation:
        organization = await self.db.get(Organization, organization_id)
        if not organization:
            raise GeoInferException(MessageCode.RESOURCE_NOT_FOUND, 404)
        from src.database.models.organizations import PlanTier

        if organization.plan_tier == PlanTier.FREE:
            raise GeoInferException(MessageCode.AUTH_INSUFFICIENT_PLAN_TIER, 403)
        await self._ensure_user_not_member(email, organization_id)
        await self._ensure_no_pending_invitation(email, organization_id)
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
        return invitation

    async def list_organization_invitations(
        self, organization_id: UUID, requesting_user_id: UUID | None = None
    ) -> list[Invitation]:
        stmt = (
            select(Invitation)
            .options(selectinload(Invitation.invited_by))
            .where(Invitation.organization_id == organization_id)
            .order_by(Invitation.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_user_pending_invitations(self, user_email: str) -> list[Invitation]:
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
        user = await self._get_user_by_id(user_id)
        await self._ensure_invitation_user_match(invitation, user)
        if user.organization_id == invitation.organization_id:
            raise GeoInferException(
                MessageCode.INVITATION_ALREADY_MEMBER, status.HTTP_400_BAD_REQUEST
            )

        if accept:
            org_service = OrganizationService(self.db)
            success = await org_service.add_user_to_organization(
                organization_id=invitation.organization_id,
                user_id=user_id,
                requesting_user_id=invitation.invited_by_id,
                role=OrganizationRole.MEMBER,
            )
            if not success:
                raise GeoInferException(
                    MessageCode.VALIDATION_INVALID_INPUT,
                    status.HTTP_400_BAD_REQUEST,
                    details={"description": "Failed to add user to organization"},
                )
            await self.db.execute(
                update(Invitation)
                .where(Invitation.id == invitation.id)
                .values(
                    status=InvitationStatus.ACCEPTED,
                    accepted_at=datetime.now(timezone.utc),
                )
            )
        else:
            await self.db.execute(
                update(Invitation)
                .where(Invitation.id == invitation.id)
                .values(status=InvitationStatus.CANCELLED)
            )
        await self.db.commit()
        result = await self.db.execute(
            select(Invitation).where(Invitation.id == invitation.id)
        )
        return result.scalar_one()

    async def cancel_invitation(
        self, invitation_id: UUID, requesting_user_id: UUID
    ) -> Invitation:
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
        await self.db.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(status=InvitationStatus.CANCELLED)
        )
        await self.db.commit()
        return invitation

    async def preview_invitation(self, token: str) -> dict[str, str | bool]:
        """Preview invitation details without accepting it."""
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

        return {
            "organization_name": invitation.organization.name,
            "organization_logo": bool(invitation.organization.logo_url),
            "invited_by_name": invitation.invited_by.name,
            "invited_by_email": invitation.invited_by.email,
            "can_accept": True,
        }

    async def cleanup_expired_invitations(self) -> int:
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
        return result.rowcount

    async def _get_user_by_id(self, user_id: UUID) -> User:
        user = await self.db.get(User, user_id)
        if not user:
            raise GeoInferException(
                MessageCode.USER_NOT_FOUND, status.HTTP_404_NOT_FOUND
            )
        return user

    async def _ensure_user_not_member(self, email: str, organization_id: UUID):
        stmt = select(User).where(
            and_(
                User.email.ilike(email.lower()), User.organization_id == organization_id
            )
        )
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            raise GeoInferException(
                MessageCode.INVITATION_ALREADY_MEMBER, status.HTTP_400_BAD_REQUEST
            )

    async def _ensure_no_pending_invitation(self, email: str, organization_id: UUID):
        stmt = select(Invitation).where(
            and_(
                Invitation.organization_id == organization_id,
                Invitation.email.ilike(email.lower()),
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            raise GeoInferException(
                MessageCode.INVITE_ALREADY_PENDING,
                status.HTTP_409_CONFLICT,
                details={"email": email},
            )

    async def _ensure_invitation_can_be_responded(self, invitation: Invitation):
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
        if invitation.expires_at < datetime.now(timezone.utc):
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
        try:
            user_result = email_normalize.normalize(user.email)
            invitation_result = email_normalize.normalize(invitation.email)
            emails_match = (
                user_result.normalized_address == invitation_result.normalized_address
            )
        except Exception:
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
