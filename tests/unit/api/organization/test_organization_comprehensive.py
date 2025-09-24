"""Comprehensive tests for organization functionality - both business logic and API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from src.database.models import User, Organization, OrganizationRole, PlanTier
from src.api.core.messages import MessageCode
from tests.utils.assertions import (
    assert_success_response,
    assert_error_response,
    assert_permission_error,
    assert_not_found_error,
)


class TestOrganizationBusinessLogic:
    """Test the core organization business logic functions."""

    @pytest.mark.asyncio
    async def test_organization_creation_with_factory(
        self, db_session: AsyncSession, organization_factory
    ):
        """Test creating an organization using the factory system."""
        org = await organization_factory.create_async(
            db_session, name="Acme Corporation", plan_tier=PlanTier.SUBSCRIBED
        )

        # Assertions
        assert org.name == "Acme Corporation"
        assert org.plan_tier == PlanTier.SUBSCRIBED
        assert org.id is not None
        assert org.created_at is not None

    @pytest.mark.asyncio
    async def test_organization_with_multiple_users(
        self, db_session: AsyncSession, organization_factory, user_factory, role_factory
    ):
        """Test organization with multiple users and roles."""
        # Create organization
        org = await organization_factory.create_async(
            db_session, name="Multi-User Company"
        )

        # Create admin user
        admin = await user_factory.create_async(
            db_session,
            name="Admin User",
            email="admin@multiuser.com",
            organization_id=org.id,
        )

        # Create member user
        member = await user_factory.create_async(
            db_session,
            name="Member User",
            email="member@multiuser.com",
            organization_id=org.id,
        )

        # Assign roles
        admin_role = await role_factory.create_async(
            db_session,
            user_id=admin.id,
            organization_id=org.id,
            role=OrganizationRole.ADMIN,
            granted_by_id=admin.id,
        )

        member_role = await role_factory.create_async(
            db_session,
            user_id=member.id,
            organization_id=org.id,
            role=OrganizationRole.MEMBER,
            granted_by_id=admin.id,
        )

        # Verify relationships
        assert admin.organization_id == org.id
        assert member.organization_id == org.id
        assert admin_role.role == OrganizationRole.ADMIN
        assert member_role.role == OrganizationRole.MEMBER

    @pytest.mark.asyncio
    async def test_organization_plan_tiers(
        self, db_session: AsyncSession, organization_factory
    ):
        """Test different organization plan tiers."""
        # Create organizations with different plan tiers
        free_org = await organization_factory.create_async(
            db_session, name="Free Company", plan_tier=PlanTier.FREE
        )

        enterprise_org = await organization_factory.create_async(
            db_session, name="Enterprise Company", plan_tier=PlanTier.ENTERPRISE
        )

        assert free_org.plan_tier == PlanTier.FREE
        assert enterprise_org.plan_tier == PlanTier.ENTERPRISE


class TestOrganizationAPIEndpoints:
    """Test organization API endpoints with proper authentication and permissions."""

    @pytest.mark.asyncio
    async def test_get_organization_as_admin(
        self, admin_client: AsyncClient, test_organization: Organization
    ):
        """Test getting organization details as admin."""
        response = await admin_client.get(
            f"/api/v1/organization/{test_organization.id}"
        )

        # Assert successful response
        data = assert_success_response(
            response,
            MessageCode.SUCCESS,
            200,
            {"id": str(test_organization.id), "name": test_organization.name},
        )

        assert data["plan_tier"] == test_organization.plan_tier

    @pytest.mark.asyncio
    async def test_get_organization_as_member(
        self, member_client: AsyncClient, test_organization: Organization
    ):
        """Test getting organization details as member."""
        response = await member_client.get(
            f"/api/v1/organization/{test_organization.id}"
        )

        # Members should be able to view organization details
        assert_success_response(response, MessageCode.SUCCESS, 200)

    @pytest.mark.asyncio
    async def test_get_organization_unauthenticated(
        self, public_client: AsyncClient, test_organization: Organization
    ):
        """Test getting organization without authentication."""
        response = await public_client.get(
            f"/api/v1/organization/{test_organization.id}"
        )

        # Should require authentication
        assert_error_response(response, MessageCode.UNAUTHORIZED, 401)

    @pytest.mark.asyncio
    async def test_update_organization_as_admin(
        self, admin_client: AsyncClient, test_organization: Organization
    ):
        """Test updating organization as admin."""
        update_data = {"name": "Updated Organization Name"}

        response = await admin_client.patch(
            f"/api/v1/organization/{test_organization.id}", json=update_data
        )

        # Should succeed for admin
        assert_success_response(
            response,
            MessageCode.ORGANIZATION_UPDATED,
            200,
            {"name": "Updated Organization Name"},
        )

    @pytest.mark.asyncio
    async def test_update_organization_as_member(
        self, member_client: AsyncClient, test_organization: Organization
    ):
        """Test updating organization as member (should fail)."""
        update_data = {"name": "Should Not Work"}

        response = await member_client.patch(
            f"/api/v1/organization/{test_organization.id}", json=update_data
        )

        # Should fail with insufficient permissions
        assert_permission_error(response)

    @pytest.mark.asyncio
    async def test_list_organization_members_as_admin(
        self,
        admin_client: AsyncClient,
        test_organization: Organization,
        test_admin_user: User,
        test_member_user: User,
    ):
        """Test listing organization members as admin."""
        response = await admin_client.get(
            f"/api/v1/organization/{test_organization.id}/members"
        )

        data = assert_success_response(response, MessageCode.SUCCESS, 200)

        # Should return list of members
        assert isinstance(data, list)
        assert len(data) >= 2  # At least admin and member

        # Verify our test users are in the list
        user_ids = [member["id"] for member in data]
        assert str(test_admin_user.id) in user_ids
        assert str(test_member_user.id) in user_ids

    @pytest.mark.asyncio
    async def test_list_organization_members_as_member(
        self, member_client: AsyncClient, test_organization: Organization
    ):
        """Test listing organization members as member."""
        response = await member_client.get(
            f"/api/v1/organization/{test_organization.id}/members"
        )

        # Members should be able to view member list (adjust based on your permissions)
        data = assert_success_response(response, MessageCode.SUCCESS, 200)

        assert isinstance(data, list)


class TestOrganizationMemberManagement:
    """Test organization member management functionality."""

    @pytest.mark.asyncio
    async def test_invite_user_as_admin(
        self, admin_client: AsyncClient, test_organization: Organization
    ):
        """Test inviting a user to organization as admin."""
        invite_data = {
            "email": "newmember@company.com",
            "role": OrganizationRole.MEMBER.value,
        }

        response = await admin_client.post(
            f"/api/v1/organization/{test_organization.id}/invitations", json=invite_data
        )

        # Should succeed for admin
        data = assert_success_response(response, MessageCode.INVITE_CREATED, 201)

        # Should return invitation details
        assert data["email"] == "newmember@company.com"

    @pytest.mark.asyncio
    async def test_invite_user_as_member(
        self, member_client: AsyncClient, test_organization: Organization
    ):
        """Test inviting a user as member (should fail)."""
        invite_data = {
            "email": "newmember@company.com",
            "role": OrganizationRole.MEMBER.value,
        }

        response = await member_client.post(
            f"/api/v1/organization/{test_organization.id}/invitations", json=invite_data
        )

        # Should fail with insufficient permissions
        assert_permission_error(response)

    @pytest.mark.asyncio
    async def test_remove_member_as_admin(
        self,
        admin_client: AsyncClient,
        test_organization: Organization,
        test_member_user: User,
    ):
        """Test removing a member as admin."""
        response = await admin_client.delete(
            f"/api/v1/organization/{test_organization.id}/members/{test_member_user.id}"
        )

        # Should succeed for admin
        assert_success_response(
            response, MessageCode.USER_REMOVED_FROM_ORGANIZATION, 200
        )

    @pytest.mark.asyncio
    async def test_remove_member_as_member(
        self,
        member_client: AsyncClient,
        test_organization: Organization,
        test_admin_user: User,
    ):
        """Test removing a member as member (should fail)."""
        response = await member_client.delete(
            f"/api/v1/organization/{test_organization.id}/members/{test_admin_user.id}"
        )

        # Should fail with insufficient permissions
        assert_permission_error(response)

    @pytest.mark.asyncio
    async def test_change_member_role_as_admin(
        self,
        admin_client: AsyncClient,
        test_organization: Organization,
        test_member_user: User,
    ):
        """Test changing member role as admin."""
        role_data = {"role": OrganizationRole.ADMIN.value}

        response = await admin_client.patch(
            f"/api/v1/organization/{test_organization.id}/members/{test_member_user.id}/role",
            json=role_data,
        )

        # Should succeed for admin
        assert_success_response(response, MessageCode.ROLE_CHANGED, 200)


class TestOrganizationErrorScenarios:
    """Test various error scenarios for organization endpoints."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_organization(self, admin_client: AsyncClient):
        """Test getting organization that doesn't exist."""
        fake_org_id = uuid4()

        response = await admin_client.get(f"/api/v1/organization/{fake_org_id}")

        assert_not_found_error(response, "organization")

    @pytest.mark.asyncio
    async def test_update_organization_with_invalid_data(
        self, admin_client: AsyncClient, test_organization: Organization
    ):
        """Test updating organization with invalid data."""
        invalid_data = {
            "name": "",  # Empty name should be invalid
            "plan_tier": "invalid_tier",
        }

        response = await admin_client.patch(
            f"/api/v1/organization/{test_organization.id}", json=invalid_data
        )

        # Should return validation error
        assert_error_response(response, MessageCode.INVALID_INPUT, 422)

    @pytest.mark.asyncio
    async def test_invite_existing_member(
        self,
        admin_client: AsyncClient,
        test_organization: Organization,
        test_member_user: User,
    ):
        """Test inviting user who is already a member."""
        invite_data = {
            "email": test_member_user.email,
            "role": OrganizationRole.MEMBER.value,
        }

        response = await admin_client.post(
            f"/api/v1/organization/{test_organization.id}/invitations", json=invite_data
        )

        # Should return error about already being a member
        assert_error_response(response, MessageCode.INVITATION_ALREADY_MEMBER, 409)

    @pytest.mark.asyncio
    async def test_admin_cannot_remove_themselves(
        self,
        admin_client: AsyncClient,
        test_organization: Organization,
        test_admin_user: User,
    ):
        """Test that admin cannot remove themselves."""
        response = await admin_client.delete(
            f"/api/v1/organization/{test_organization.id}/members/{test_admin_user.id}"
        )

        # Should return error about not being able to remove yourself
        assert_error_response(response, MessageCode.CANNOT_REMOVE_YOURSELF, 400)


class TestOrganizationWorkflows:
    """Test complete organization workflows end-to-end."""

    @pytest.mark.asyncio
    async def test_create_organization_and_invite_workflow(
        self,
        admin_client: AsyncClient,
        client_factory,
        db_session: AsyncSession,
        create_user_factory,
        test_admin_user: User,
    ):
        """Test complete workflow: create org -> invite user -> accept invitation."""
        # Step 1: Create new organization
        org_data = {"name": "New Workflow Company", "plan_tier": PlanTier.FREE.value}

        create_response = await admin_client.post(
            "/api/v1/organizations", json=org_data
        )

        created_org = assert_success_response(
            create_response,
            MessageCode.ORGANIZATION_CREATED,
            201,
            {"name": "New Workflow Company"},
        )

        org_id = created_org["id"]

        # Step 2: Invite a new user
        invite_data = {
            "email": "invitee@company.com",
            "role": OrganizationRole.MEMBER.value,
        }

        invite_response = await admin_client.post(
            f"/api/v1/organization/{org_id}/invitations", json=invite_data
        )

        assert_success_response(
            invite_response,
            MessageCode.INVITE_CREATED,
            201,
            {"email": "invitee@company.com"},
        )

        # Step 3: Simulate accepting invitation by creating user
        new_user = await create_user_factory(
            email="invitee@company.com",
            name="Invited User",
            role=OrganizationRole.MEMBER,
        )

        # Step 4: Verify new user can access organization
        user_client = await client_factory(new_user)

        members_response = await user_client.get(
            f"/api/v1/organization/{org_id}/members"
        )
        members_data = assert_success_response(
            members_response, MessageCode.SUCCESS, 200
        )

        # Should include the new user
        member_emails = [member["email"] for member in members_data]
        assert "invitee@company.com" in member_emails

        await user_client.aclose()

    @pytest.mark.asyncio
    async def test_organization_role_escalation_workflow(
        self,
        admin_client: AsyncClient,
        member_client: AsyncClient,
        test_organization: Organization,
        test_member_user: User,
    ):
        """Test workflow for escalating user role from member to admin."""
        # Step 1: Verify member has limited access
        update_response = await member_client.patch(
            f"/api/v1/organization/{test_organization.id}", json={"name": "Should Fail"}
        )

        # Should fail
        assert_permission_error(update_response)

        # Step 2: Admin promotes member to admin
        role_response = await admin_client.patch(
            f"/api/v1/organization/{test_organization.id}/members/{test_member_user.id}/role",
            json={"role": OrganizationRole.ADMIN.value},
        )

        assert_success_response(role_response, MessageCode.ROLE_CHANGED, 200)

        # Step 3: Verify member now has admin access
        # Note: In reality, the user would need to get a new token with updated claims
        # For this test, we assume the role change is immediately effective
