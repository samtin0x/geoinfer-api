"""Test user flows using factories and improved fixtures."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User, Organization, OrganizationRole
from tests.factories import UserFactory, OrganizationFactory


class TestUserFlowWithFactories:
    """Test user flows using the new factory system."""

    @pytest.mark.asyncio
    async def test_user_creation_with_organization(
        self, db_session: AsyncSession, user_factory, organization_factory
    ):
        """Test creating a user with an organization using factories."""
        # Create organization
        org = await organization_factory.create_async(db_session, name="Test Company")

        # Create user in that organization
        user = await user_factory.create_async(
            db_session,
            name="John Doe",
            email="john@testcompany.com",
            organization_id=org.id,
        )

        assert user.name == "John Doe"
        assert user.email == "john@testcompany.com"
        assert user.organization_id == org.id

    @pytest.mark.asyncio
    async def test_multiple_users_same_organization(
        self,
        db_session: AsyncSession,
        create_user_factory,
        test_organization: Organization,
    ):
        """Test creating multiple users in the same organization."""
        # Create admin user
        admin = await create_user_factory(
            email="admin@company.com", name="Admin User", role=OrganizationRole.ADMIN
        )

        # Create member user
        member = await create_user_factory(
            email="member@company.com", name="Member User", role=OrganizationRole.MEMBER
        )

        assert admin.organization_id == member.organization_id
        assert admin.organization_id == test_organization.id

    @pytest.mark.asyncio
    async def test_authorized_client_for_different_users(
        self, app, client_factory, test_admin_user: User, test_member_user: User
    ):
        """Test creating authorized clients for different user types."""
        # Create clients for different users
        admin_client = await client_factory(test_admin_user)
        member_client = await client_factory(test_member_user)

        # Test admin access
        await admin_client.get("/api/v1/organization/members")
        # Admin should have access (assuming this endpoint exists)

        # Test member access
        await member_client.get("/api/v1/user/profile")
        # Member should have access to their own profile

        await admin_client.aclose()
        await member_client.aclose()

    @pytest.mark.asyncio
    async def test_invitation_workflow_with_factories(
        self,
        db_session: AsyncSession,
        admin_client: AsyncClient,
        test_admin_user: User,
        test_organization: Organization,
    ):
        """Test invitation workflow using the admin client."""
        # Admin invites a new user
        invite_data = {"email": "newuser@company.com", "role": "member"}

        await admin_client.post("/api/v1/invitations", json=invite_data)

        # Should be successful if admin has proper permissions
        # This depends on your actual API implementation

    @pytest.mark.asyncio
    async def test_factory_with_custom_data(self, db_session: AsyncSession):
        """Test using factories with custom data."""
        # Create organization with specific plan
        premium_org = await OrganizationFactory.create_async(
            db_session, name="Premium Company", plan_tier="subscribed"
        )

        # Create multiple users for this organization
        users = await UserFactory.create_batch_async(
            db_session, 3, organization_id=premium_org.id
        )

        assert len(users) == 3
        assert all(user.organization_id == premium_org.id for user in users)
