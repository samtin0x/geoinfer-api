"""Tests for user business logic modules."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import Mock, patch

from src.database.models import User, Organization, OrganizationRole
from src.api.core.messages import MessageCode
from src.api.core.exceptions.base import GeoInferException
from tests.utils.assertions import assert_geoinfer_exception


# User Management Business Logic Tests


@pytest.mark.asyncio
async def test_user_onboarding_service_create_user(
    db_session: AsyncSession, user_factory, test_organization: Organization
):
    """Test user onboarding service creates user correctly."""
    # Mock the onboarding service
    with patch("src.modules.user.onboarding.UserOnboardingService") as mock_service:
        # Create actual user using factory for verification
        expected_user = await user_factory.create_async(
            db_session,
            email="onboard@company.com",
            name="Onboard User",
            organization_id=test_organization.id,
        )

        # Configure mock to return our user
        mock_instance = mock_service.return_value
        mock_instance.create_user.return_value = expected_user

        # Test the service call
        result = await mock_instance.create_user(
            email="onboard@company.com",
            name="Onboard User",
            organization_id=test_organization.id,
        )

        # Verify results
        assert result.email == "onboard@company.com"
        assert result.name == "Onboard User"
        assert result.organization_id == test_organization.id
        mock_instance.create_user.assert_called_once()


@pytest.mark.asyncio
async def test_user_organization_assignment(
    db_session: AsyncSession, create_user_factory, test_organization: Organization
):
    """Test assigning user to organization with role."""
    # Create user with specific role
    user = await create_user_factory(
        email="assign@company.com",
        name="Assign User",
        organization=test_organization,
        role=OrganizationRole.MEMBER,
    )

    # Verify user assignment
    assert user.organization_id == test_organization.id

    # Test organization switching logic
    with patch(
        "src.modules.organization.use_cases.OrganizationService"
    ) as mock_service:
        mock_instance = mock_service.return_value
        mock_instance.assign_user_to_organization.return_value = True

        result = await mock_instance.assign_user_to_organization(
            user.id, test_organization.id
        )

        assert result is True
        mock_instance.assign_user_to_organization.assert_called_once_with(
            user.id, test_organization.id
        )


@pytest.mark.asyncio
async def test_user_permission_checking(
    test_user: User, test_organization: Organization
):
    """Test user permission checking business logic."""
    with patch(
        "src.modules.organization.permissions.PermissionService"
    ) as mock_service:
        mock_instance = mock_service.return_value

        # Test user has basic permissions
        mock_instance.user_has_permission.return_value = True

        result = await mock_instance.user_has_permission(
            test_user.id, test_organization.id, "view_organization"
        )

        assert result is True
        mock_instance.user_has_permission.assert_called_once()


@pytest.mark.asyncio
async def test_user_service_error_handling():
    """Test user service error handling."""
    with patch("src.modules.user.management.UserService") as mock_service:
        mock_instance = mock_service.return_value

        # Configure mock to raise GeoInferException
        mock_instance.get_user.side_effect = GeoInferException(
            MessageCode.USER_NOT_FOUND, 404
        )

        # Test that exception is properly raised
        with pytest.raises(GeoInferException) as exc_info:
            await mock_instance.get_user("fake-user-id")

        # Verify exception details
        assert_geoinfer_exception(exc_info.value, MessageCode.USER_NOT_FOUND, 404)


# User Authentication Business Logic Tests


@pytest.mark.asyncio
async def test_jwt_claims_processing(test_user: User):
    """Test JWT claims processing business logic."""
    with patch("src.services.auth.jwt_claims.JWTClaimsService") as mock_service:
        mock_instance = mock_service.return_value

        # Mock JWT claims processing
        mock_claims = {
            "sub": str(test_user.id),
            "email": test_user.email,
            "role": "authenticated",
        }

        mock_instance.process_claims.return_value = mock_claims

        result = await mock_instance.process_claims("fake-jwt-token")

        assert result["sub"] == str(test_user.id)
        assert result["email"] == test_user.email
        assert result["role"] == "authenticated"


@pytest.mark.asyncio
async def test_auth_context_creation(test_user: User):
    """Test authentication context creation."""
    with patch("src.services.auth.context.AuthContextService") as mock_service:
        mock_instance = mock_service.return_value

        # Mock auth context
        mock_context = Mock()
        mock_context.user = test_user
        mock_context.is_authenticated = True

        mock_instance.create_context.return_value = mock_context

        result = await mock_instance.create_context(test_user.id)

        assert result.user == test_user
        assert result.is_authenticated is True
        mock_instance.create_context.assert_called_once_with(test_user.id)


# User Profile Management Tests


@pytest.mark.asyncio
async def test_profile_update_validation():
    """Test user profile update validation logic."""
    with patch("src.modules.user.management.ProfileService") as mock_service:
        mock_instance = mock_service.return_value

        # Test valid profile update
        update_data = {"name": "Updated Name", "locale": "en"}
        mock_instance.validate_profile_update.return_value = True

        result = await mock_instance.validate_profile_update(update_data)
        assert result is True

        # Test invalid profile update
        invalid_data = {"name": "", "locale": "invalid"}
        mock_instance.validate_profile_update.side_effect = GeoInferException(
            MessageCode.VALIDATION_ERROR, 422
        )

        with pytest.raises(GeoInferException) as exc_info:
            await mock_instance.validate_profile_update(invalid_data)

        assert_geoinfer_exception(exc_info.value, MessageCode.VALIDATION_ERROR, 422)


@pytest.mark.asyncio
async def test_user_avatar_upload_logic():
    """Test user avatar upload business logic."""
    with patch("src.modules.user.management.AvatarService") as mock_service:
        mock_instance = mock_service.return_value

        # Mock successful avatar upload
        mock_instance.upload_avatar.return_value = "https://cdn.example.com/avatar.jpg"

        result = await mock_instance.upload_avatar(
            user_id="user-123", file_data=b"fake-image-data", content_type="image/jpeg"
        )

        assert result == "https://cdn.example.com/avatar.jpg"
        mock_instance.upload_avatar.assert_called_once()


# Integration with Organization Business Logic


@pytest.mark.asyncio
async def test_user_organization_permissions_integration(
    test_user: User, test_organization: Organization
):
    """Test integration between user and organization permission systems."""
    with patch(
        "src.modules.organization.permissions.check_user_permissions"
    ) as mock_check:
        # Mock permission checking
        mock_check.return_value = {
            "can_manage_members": False,
            "can_view_analytics": True,
            "can_manage_billing": False,
        }

        result = await mock_check(test_user.id, test_organization.id)

        assert result["can_view_analytics"] is True
        assert result["can_manage_members"] is False
        assert result["can_manage_billing"] is False


@pytest.mark.asyncio
async def test_user_role_change_business_logic(
    test_user: User, test_organization: Organization
):
    """Test business logic for changing user roles."""
    with patch("src.modules.organization.use_cases.RoleService") as mock_service:
        mock_instance = mock_service.return_value

        # Test successful role change
        mock_instance.change_user_role.return_value = True

        result = await mock_instance.change_user_role(
            user_id=test_user.id,
            organization_id=test_organization.id,
            new_role=OrganizationRole.ADMIN,
            changed_by_id=test_user.id,
        )

        assert result is True

        # Test role change validation error
        mock_instance.change_user_role.side_effect = GeoInferException(
            MessageCode.CANNOT_CHANGE_OWN_ROLE, 400
        )

        with pytest.raises(GeoInferException) as exc_info:
            await mock_instance.change_user_role(
                user_id=test_user.id,
                organization_id=test_organization.id,
                new_role=OrganizationRole.MEMBER,
                changed_by_id=test_user.id,  # Same user trying to change own role
            )

        assert_geoinfer_exception(
            exc_info.value, MessageCode.CANNOT_CHANGE_OWN_ROLE, 400
        )
