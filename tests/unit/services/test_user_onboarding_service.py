from uuid import uuid4
from unittest.mock import patch, MagicMock

import pytest

from src.database.models import Organization, PlanTier
from src.modules.user.onboarding import UserOnboardingService


@pytest.mark.asyncio(loop_scope="session")
async def test_ensure_user_onboarded_creates_user_and_org(db_session):
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "new-user@example.com"

    user, organization = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="New User",
        plan_tier=PlanTier.FREE,
    )

    assert user.id == user_id
    assert user.email == email
    assert organization.plan_tier == PlanTier.FREE
    assert user.organization_id == organization.id

    assert organization.id == user_id
    assert organization.name == email
    # Organization is active for the user since user.organization_id points to it


@pytest.mark.asyncio(loop_scope="session")
async def test_ensure_user_onboarded_creates_stripe_customer(db_session):
    """Test that user onboarding creates a Stripe customer for the organization."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "stripe-user@example.com"

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("src.utils.settings.stripe.StripeSettings") as mock_stripe_settings,
    ):

        # Mock Stripe settings
        mock_settings = MagicMock()
        mock_settings.STRIPE_SECRET_KEY.get_secret_value.return_value = "sk_test_fake"
        mock_stripe_settings.return_value = mock_settings

        # Mock Stripe customer creation
        mock_customer = MagicMock()
        mock_customer.id = "cus_onboarding_test_123"
        mock_customer_create.return_value = mock_customer

        user, organization = await service.ensure_user_onboarded(
            user_id=user_id,
            email=email,
            name="Stripe User",
            plan_tier=PlanTier.FREE,
        )

        # Verify Stripe customer was created
        mock_customer_create.assert_called_once()
        call_args = mock_customer_create.call_args[1]
        assert call_args["email"] == email
        assert call_args["name"] == email  # organization name defaults to email
        assert call_args["metadata"]["organization_id"] == str(organization.id)

        # Verify customer ID was stored in organization
        assert organization.stripe_customer_id == "cus_onboarding_test_123"


@pytest.mark.asyncio(loop_scope="session")
async def test_onboarding_continues_if_stripe_customer_creation_fails(db_session):
    """Test that onboarding continues even if Stripe customer creation fails."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "failing-stripe@example.com"

    with (
        patch("stripe.Customer.create") as mock_customer_create,
        patch("src.utils.settings.stripe.StripeSettings") as mock_stripe_settings,
    ):

        # Mock Stripe settings
        mock_settings = MagicMock()
        mock_settings.STRIPE_SECRET_KEY.get_secret_value.return_value = "sk_test_fake"
        mock_stripe_settings.return_value = mock_settings

        # Mock Stripe customer creation failure
        mock_customer_create.side_effect = Exception("Stripe API error")

        # Should not raise exception
        user, organization = await service.ensure_user_onboarded(
            user_id=user_id,
            email=email,
            name="Failing User",
            plan_tier=PlanTier.FREE,
        )

        # User and organization should still be created
        assert user.id == user_id
        assert user.email == email
        assert organization.plan_tier == PlanTier.FREE

        # Customer ID should be None since creation failed
        assert organization.stripe_customer_id is None


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_organizations_filters_inactive(db_session):
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "org-user@example.com"

    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Org User",
        plan_tier=PlanTier.FREE,
    )

    # Create an organization that the user is NOT a member of
    inactive_org = Organization(
        id=uuid4(),
        name="Inactive Org",
        logo_url=None,
        plan_tier=PlanTier.FREE,
    )
    db_session.add(inactive_org)
    await db_session.commit()

    active_orgs = await service.get_user_organizations(user_id=user_id)
    assert len(active_orgs) == 1  # User should only get their own organization

    # The inactive org should not be included since user is not a member
    assert all(org.id == user.organization_id for org in active_orgs)


@pytest.mark.asyncio(loop_scope="session")
async def test_user_name_preservation_on_jwt_refresh(db_session):
    """Test that user name is preserved once set, even on JWT refresh."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "preserve-name@example.com"

    # First onboarding - set initial name
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Initial Name",
        plan_tier=PlanTier.FREE,
    )

    assert user.name == "Initial Name"

    # Simulate JWT refresh with different name - should preserve existing name
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="JWT Name Override",  # This should NOT override existing name
        plan_tier=PlanTier.FREE,
    )

    # Name should remain unchanged
    assert updated_user.name == "Initial Name"
    assert updated_user.name != "JWT Name Override"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_name_update_when_null(db_session):
    """Test that user name can be set when it's currently null/empty."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "set-null-name@example.com"

    # First onboarding - set empty name
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="",  # Empty name
        plan_tier=PlanTier.FREE,
    )

    assert user.name == ""

    # Simulate JWT refresh with actual name - should set the name
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="JWT Name Set",  # This SHOULD set the name since current is empty
        plan_tier=PlanTier.FREE,
    )

    # Name should be updated since it was empty
    assert updated_user.name == "JWT Name Set"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_name_update_when_empty_string(db_session):
    """Test that user name can be set when it's currently an empty string."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "set-empty-name@example.com"

    # Create user and organization directly (simulating legacy user)
    from src.database.models import User, Organization

    # First create the organization
    organization = Organization(
        id=user_id,
        name=email,
        plan_tier=PlanTier.FREE,
    )
    db_session.add(organization)

    # Then create user
    user = User(
        id=user_id,
        email=email,
        name="",  # Empty string (allowed by DB schema)
        organization_id=user_id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.name == ""

    # Now onboard with a name - should set the name
    service = UserOnboardingService(db_session)
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="JWT Name Set",  # This SHOULD set the name since current is empty
        plan_tier=PlanTier.FREE,
    )

    # Name should be updated since it was empty
    assert updated_user.name == "JWT Name Set"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_locale_preservation_on_jwt_refresh(db_session):
    """Test that user locale is preserved once set, even on JWT refresh."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "preserve-locale@example.com"

    # First onboarding - set initial locale
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        locale="en-US",
    )

    assert user.locale == "en-US"

    # Simulate JWT refresh with different locale - should preserve existing locale
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        locale="es-ES",  # This should NOT override existing locale
    )

    # Locale should remain unchanged
    assert updated_user.locale == "en-US"
    assert updated_user.locale != "es-ES"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_locale_update_when_null(db_session):
    """Test that user locale can be set when it's currently None."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "set-null-locale@example.com"

    # First onboarding - set None locale
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        locale=None,  # None locale
    )

    assert user.locale is None

    # Simulate JWT refresh with actual locale - should set the locale
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        locale="fr-FR",  # This SHOULD set the locale since current is None
    )

    # Locale should be updated since it was None
    assert updated_user.locale == "fr-FR"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_avatar_url_preservation_on_jwt_refresh(db_session):
    """Test that user avatar_url is preserved once set, even on JWT refresh."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "preserve-avatar@example.com"

    # First onboarding - set initial avatar URL
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url="https://example.com/avatar1.jpg",
    )

    assert user.avatar_url == "https://example.com/avatar1.jpg"

    # Simulate JWT refresh with different avatar URL - should preserve existing avatar
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url="https://example.com/avatar2.jpg",  # This should NOT override existing avatar
    )

    # Avatar URL should remain unchanged
    assert updated_user.avatar_url == "https://example.com/avatar1.jpg"
    assert updated_user.avatar_url != "https://example.com/avatar2.jpg"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_avatar_url_update_when_null(db_session):
    """Test that user avatar_url can be set when it's currently None."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "set-null-avatar@example.com"

    # First onboarding - set None avatar URL
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url=None,  # None avatar URL
    )

    assert user.avatar_url is None

    # Simulate JWT refresh with actual avatar URL - should set the avatar URL
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url="https://example.com/new-avatar.jpg",  # This SHOULD set the avatar URL since current is None
    )

    # Avatar URL should be updated since it was None
    assert updated_user.avatar_url == "https://example.com/new-avatar.jpg"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_avatar_url_update_when_empty_string(db_session):
    """Test that user avatar_url can be set when it's currently an empty string."""
    service = UserOnboardingService(db_session)

    user_id = uuid4()
    email = "set-empty-avatar@example.com"

    # First onboarding - set empty string avatar URL
    user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url="",  # Empty string avatar URL
    )

    assert user.avatar_url == ""

    # Simulate JWT refresh with actual avatar URL - should set the avatar URL
    updated_user, _ = await service.ensure_user_onboarded(
        user_id=user_id,
        email=email,
        name="Test User",
        plan_tier=PlanTier.FREE,
        avatar_url="https://example.com/new-avatar.jpg",  # This SHOULD set the avatar URL since current is empty
    )

    # Avatar URL should be updated since it was empty
    assert updated_user.avatar_url == "https://example.com/new-avatar.jpg"


@pytest.mark.asyncio(loop_scope="session")
async def test_name_preservation_logic_edge_cases(db_session):
    """Test edge cases for name preservation logic: not user.name and name"""
    service = UserOnboardingService(db_session)

    # Test 1: Empty string should be updated
    user_id1 = uuid4()
    email1 = "empty-string-test@example.com"

    user1, _ = await service.ensure_user_onboarded(
        user_id=user_id1,
        email=email1,
        name="",  # Empty string
        plan_tier=PlanTier.FREE,
    )

    # Verify empty string condition: not "" is True, so it should update
    updated_user1, _ = await service.ensure_user_onboarded(
        user_id=user_id1,
        email=email1,
        name="New Name",  # Should update because current is ""
        plan_tier=PlanTier.FREE,
    )

    assert updated_user1.name == "New Name"

    # Test 2: Non-empty string should NOT be updated
    user_id2 = uuid4()
    email2 = "non-empty-test@example.com"

    user2, _ = await service.ensure_user_onboarded(
        user_id=user_id2,
        email=email2,
        name="Existing Name",  # Non-empty string
        plan_tier=PlanTier.FREE,
    )

    # Verify non-empty string condition: not "Existing Name" is False, so it should NOT update
    updated_user2, _ = await service.ensure_user_onboarded(
        user_id=user_id2,
        email=email2,
        name="JWT Override Name",  # Should NOT update because current is not empty
        plan_tier=PlanTier.FREE,
    )

    assert updated_user2.name == "Existing Name"  # Should preserve existing name
    assert updated_user2.name != "JWT Override Name"
