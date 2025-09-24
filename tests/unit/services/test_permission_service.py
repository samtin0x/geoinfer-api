from uuid import uuid4

import pytest

from src.database.models import PlanTier
from src.database.models.organizations import OrganizationPermission, OrganizationRole
from src.modules.organization.permissions import PermissionService
from src.modules.organization.use_cases import OrganizationService
from src.modules.user.onboarding import UserOnboardingService


@pytest.mark.asyncio(loop_scope="session")
async def test_permission_checks_for_admin_and_member(db_session):
    onboarding_service = UserOnboardingService(db_session)
    permission_service = PermissionService(db_session)
    organization_service = OrganizationService(db_session)

    admin_id = uuid4()
    admin_email = "admin@example.com"
    admin_user, admin_org = await onboarding_service.ensure_user_onboarded(
        user_id=admin_id,
        email=admin_email,
        name="Admin User",
        plan_tier=PlanTier.ENTERPRISE,
    )

    # Admin (owner alias) should have manage members permission
    has_manage_members = await permission_service.check_user_permission(
        user_id=str(admin_id),
        organization_id=str(admin_org.id),
        permission=OrganizationPermission.MANAGE_MEMBERS,
    )
    assert has_manage_members is True

    member_id = uuid4()
    member_email = "member@example.com"
    member_user, _ = await onboarding_service.ensure_user_onboarded(
        user_id=member_id,
        email=member_email,
        name="Member User",
        plan_tier=PlanTier.FREE,
    )

    # Add member user to admin's organization with MEMBER role
    await organization_service.add_user_to_organization(
        organization_id=str(admin_org.id),
        user_id=str(member_user.id),
        requesting_user_id=str(admin_user.id),
        role=OrganizationRole.MEMBER,
    )

    # Member should not have manage members permission
    member_manage_members = await permission_service.check_user_permission(
        user_id=str(member_user.id),
        organization_id=str(admin_org.id),
        permission=OrganizationPermission.MANAGE_MEMBERS,
    )
    assert member_manage_members is False

    # Member can still view organization
    member_view_org = await permission_service.check_user_permission(
        user_id=str(member_user.id),
        organization_id=str(admin_org.id),
        permission=OrganizationPermission.VIEW_ORGANIZATION,
    )
    assert member_view_org is True
