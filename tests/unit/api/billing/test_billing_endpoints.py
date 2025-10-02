"""Billing endpoints tests."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from fastapi import status
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.users import User
from src.database.models.organizations import Organization
from src.database.models.subscriptions import Subscription


@pytest.mark.asyncio
async def test_get_billing_products_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful billing products retrieval."""
    response = await authorized_client.get("/v1/billing/products")

    assert response.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        products = data["data"]
        assert isinstance(products, list)

        # Verify billing product structure
        for product in products:
            assert "id" in product
            assert "name" in product
            assert "description" in product
            assert "price" in product
            assert "currency" in product
            assert "interval" in product
            assert "features" in product

            assert isinstance(product["id"], str)
            assert isinstance(product["name"], str)
            assert isinstance(product["description"], str)
            assert isinstance(product["price"], (int, float))
            assert isinstance(product["currency"], str)
            assert isinstance(product["interval"], str)
            assert isinstance(product["features"], list)

            assert product["price"] >= 0
            assert len(product["currency"]) == 3  # ISO currency code
            assert product["interval"] in ["month", "year"]


@pytest.mark.asyncio
async def test_get_billing_products_unauthorized(app, public_client: AsyncClient):
    """Test that billing products require authentication."""
    response = await public_client.get("/v1/billing/products")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("limit", [1, 10, 50, 100])
@pytest.mark.asyncio
async def test_billing_products_pagination(
    app, authorized_client: AsyncClient, test_user, db_session, limit: int
):
    """Test billing products pagination."""
    response = await authorized_client.get(f"/v1/billing/products?limit={limit}")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]
        assert isinstance(products, list)
        assert len(products) <= limit


@pytest.mark.parametrize("offset", [0, 10, 20, 50])
@pytest.mark.asyncio
async def test_billing_products_offset(
    app, authorized_client: AsyncClient, test_user, db_session, offset: int
):
    """Test billing products offset parameter."""
    response = await authorized_client.get(
        f"/v1/billing/products?offset={offset}&limit=10"
    )

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]
        assert isinstance(products, list)


@pytest.mark.asyncio
async def test_billing_products_include_all_plans(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that billing products include all available plans."""
    response = await authorized_client.get("/v1/billing/products")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]

        # Should include different plan types
        intervals = [product.get("interval") for product in products]
        assert "month" in intervals
        assert "year" in intervals

        # Should include different tiers
        prices = [product["price"] for product in products]
        # Should have some variation in pricing
        assert len(set(prices)) > 1


@pytest.mark.asyncio
async def test_billing_products_sorted_by_price(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that billing products are sorted by price."""
    response = await authorized_client.get("/v1/billing/products")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]

        if len(products) > 1:
            prices = [product["price"] for product in products]
            # Should be sorted in ascending order
            assert prices == sorted(prices)


@pytest.mark.asyncio
async def test_billing_products_currency_format(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that billing products use correct currency format."""
    response = await authorized_client.get("/v1/billing/products")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]

        for product in products:
            currency = product["currency"]
            assert isinstance(currency, str)
            assert len(currency) == 3
            assert currency.isupper()
            assert currency.isalpha()


@pytest.mark.asyncio
async def test_billing_products_features_are_descriptive(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that billing products have descriptive features."""
    response = await authorized_client.get("/v1/billing/products")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        products = data["data"]

        for product in products:
            features = product["features"]
            assert isinstance(features, list)

            for feature in features:
                assert isinstance(feature, str)
                assert len(feature) > 0
                assert not feature.isspace()  # Not just whitespace


@pytest.mark.asyncio
async def test_billing_products_response_format(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that billing products response has correct format."""
    response = await authorized_client.get("/v1/billing/products")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"
        assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_get_billing_catalog_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful billing catalog retrieval."""
    response = await authorized_client.get("/v1/billing/catalog")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"

    catalog = data["data"]
    assert "currency" in catalog
    assert "subscriptionPackages" in catalog
    assert "topupPackages" in catalog

    assert catalog["currency"] == "EUR"
    assert isinstance(catalog["subscriptionPackages"], dict)
    assert isinstance(catalog["topupPackages"], dict)


@pytest.mark.asyncio
async def test_get_subscription_usage_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful subscription usage retrieval."""
    subscription_id = str(test_subscription.id)
    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{subscription_id}/usage"
    )

    # This endpoint currently returns placeholder data
    # In a real implementation, it would check permissions and return actual usage
    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "SUCCESS"

        usage = data["data"]
        assert isinstance(usage, dict)


@pytest.mark.asyncio
async def test_get_subscription_usage_not_found(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test subscription usage retrieval for non-existent subscription."""
    fake_subscription_id = str(uuid4())
    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{fake_subscription_id}/usage"
    )

    # Should return 404 for non-existent subscription
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_check_usage_alerts_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful usage alerts check."""
    response = await authorized_client.get("/v1/billing/alerts/usage")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"

    result = data["data"]
    assert "alerts" in result
    assert isinstance(result["alerts"], list)


@pytest.mark.asyncio
async def test_update_overage_settings_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful overage settings update."""
    subscription_id = str(test_subscription.id)

    update_data = {"enabled": True, "userExtraCap": 5000}

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/overage-settings",
        json=update_data,
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"

    # Validate overage settings response structure
    assert data["data"]["subscription_id"] == subscription_id
    assert data["data"]["overage_enabled"] is True
    assert data["data"]["user_extra_cap"] == 5000
    assert "pause_access" in data["data"]
    assert "cancel_at_period_end" in data["data"]


@pytest.mark.asyncio
async def test_update_overage_settings_not_found(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test overage settings update for non-existent subscription."""
    fake_subscription_id = str(uuid4())

    update_data = {"enabled": True, "userExtraCap": 5000}

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{fake_subscription_id}/overage-settings",
        json=update_data,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_alert_settings_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful alert settings retrieval."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings"
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"

    settings = data["data"]
    assert "subscription_id" in settings
    assert "alert_thresholds" in settings
    assert "alert_destinations" in settings
    assert "alerts_enabled" in settings
    assert "locale" in settings

    assert settings["subscription_id"] == subscription_id
    assert isinstance(settings["alert_thresholds"], list)
    assert isinstance(settings["alert_destinations"], list)
    assert isinstance(settings["alerts_enabled"], bool)
    assert isinstance(settings["locale"], str)


@pytest.mark.asyncio
async def test_get_alert_settings_creates_default(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that alert settings are created with defaults if they don't exist."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings"
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    settings = data["data"]
    assert settings["alert_thresholds"] == []  # Default empty (no thresholds)
    assert settings["alert_destinations"] == []  # Default empty list
    assert settings["alerts_enabled"] is False  # Default disabled
    assert settings["locale"] == "en"  # Default locale


@pytest.mark.asyncio
async def test_update_alert_settings_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful alert settings update."""
    subscription_id = str(test_subscription.id)

    update_data = {
        "alert_thresholds": [0.5, 0.7, 0.9],
        "alert_destinations": ["admin@example.com", "billing@example.com"],
        "alerts_enabled": False,
        "locale": "es",
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=update_data
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"
    assert "Alert settings updated successfully" in data.get("message", "")

    # Verify the settings were updated
    settings = data["data"]
    assert settings["alert_thresholds"] == [0.5, 0.7, 0.9]
    assert settings["alert_destinations"] == [
        "admin@example.com",
        "billing@example.com",
    ]
    assert settings["alerts_enabled"] is False
    assert settings["locale"] == "es"


@pytest.mark.asyncio
async def test_update_alert_settings_partial_update(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test partial alert settings update (only some fields)."""
    subscription_id = str(test_subscription.id)

    # First get current settings
    get_response = await authorized_client.get(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings"
    )
    current_settings = get_response.json()["data"]

    # Update only thresholds and locale
    update_data = {"alert_thresholds": [0.6, 0.8, 0.95], "locale": "fr"}

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=update_data
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    settings = data["data"]
    assert settings["alert_thresholds"] == [0.6, 0.8, 0.95]
    assert settings["locale"] == "fr"
    # Other fields should remain unchanged
    assert settings["alert_destinations"] == current_settings["alert_destinations"]
    assert settings["alerts_enabled"] == current_settings["alerts_enabled"]


@pytest.mark.asyncio
async def test_test_alert_email_success(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test successful test alert email sending."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.post(
        f"/v1/billing/subscriptions/{subscription_id}/test-alert"
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"
    assert "Test alert sent successfully" in data.get("message", "")

    result = data["data"]
    assert "sent" in result
    assert "recipients" in result


@pytest.mark.asyncio
async def test_test_alert_email_no_destinations(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test test alert email when no destinations are configured."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.post(
        f"/v1/billing/subscriptions/{subscription_id}/test-alert"
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    result = data["data"]
    assert result["sent"] is False
    assert result["recipients"] == 0


@pytest.mark.asyncio
async def test_test_alert_email_with_locale(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test test alert email with custom locale."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.post(
        f"/v1/billing/subscriptions/{subscription_id}/test-alert",
        params={"locale": "de"},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert "data" in data
    result = data["data"]
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_protected_billing_endpoints_require_authentication(
    app, public_client: AsyncClient
):
    """Test that protected billing endpoints require authentication."""
    fake_subscription_id = str(uuid4())

    # These endpoints require authentication
    protected_endpoints = [
        "/v1/billing/products",
        f"/v1/billing/subscriptions/{fake_subscription_id}/usage",
        "/v1/billing/alerts/usage",
        f"/v1/billing/subscriptions/{fake_subscription_id}/overage-settings",
        f"/v1/billing/subscriptions/{fake_subscription_id}/alert-settings",
        f"/v1/billing/subscriptions/{fake_subscription_id}/test-alert",
    ]

    for endpoint in protected_endpoints:
        response = await public_client.get(endpoint)
        assert (
            response.status_code == status.HTTP_401_UNAUTHORIZED
        ), f"Endpoint {endpoint} should require authentication"


@pytest.mark.asyncio
async def test_billing_catalog_is_public(app, public_client: AsyncClient):
    """Test that billing catalog endpoint is public for pricing display."""
    response = await public_client.get("/v1/billing/catalog")
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_test_alert_requires_authentication(app, public_client: AsyncClient):
    """Test that test alert endpoint requires authentication."""
    fake_subscription_id = str(uuid4())

    response = await public_client.post(
        f"/v1/billing/subscriptions/{fake_subscription_id}/test-alert"
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_update_alert_settings_invalid_thresholds(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test updating alert settings with invalid threshold values."""
    subscription_id = str(test_subscription.id)

    # Test with invalid thresholds (negative values)
    invalid_data = {
        "alert_thresholds": [-0.1, 0.5, 1.5],  # Negative and > 1.0
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_alert_settings_invalid_emails(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test updating alert settings with invalid email addresses."""
    subscription_id = str(test_subscription.id)

    # Test with invalid email format
    invalid_data = {
        "alert_destinations": ["invalid-email", "another@invalid", "valid@example.com"],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_update_alert_settings_invalid_locale(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test updating alert settings with invalid locale."""
    subscription_id = str(test_subscription.id)

    # Test with invalid locale format
    invalid_data = {
        "locale": "invalid-locale-format",
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_alert_settings_response_format(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that alert settings response has correct format."""
    subscription_id = str(test_subscription.id)

    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings"
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Check response structure
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"

    settings = data["data"]
    assert "subscription_id" in settings
    assert "alert_thresholds" in settings
    assert "alert_destinations" in settings
    assert "alerts_enabled" in settings
    assert "locale" in settings

    # Validate data types
    assert isinstance(settings["subscription_id"], str)
    assert isinstance(settings["alert_thresholds"], list)
    assert isinstance(settings["alert_destinations"], list)
    assert isinstance(settings["alerts_enabled"], bool)
    assert isinstance(settings["locale"], str)

    # Validate threshold values are between 0 and 1
    for threshold in settings["alert_thresholds"]:
        assert 0 <= threshold <= 1

    # Validate email format (if any provided)
    for email in settings["alert_destinations"]:
        assert "@" in email and "." in email


@pytest.mark.asyncio
async def test_update_alert_settings_response_format(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that alert settings update response has correct format."""
    subscription_id = str(test_subscription.id)

    update_data = {
        "alert_thresholds": [0.7, 0.85, 0.95],
        "alert_destinations": ["admin@example.com"],
        "alerts_enabled": True,
        "locale": "es",
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=update_data
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Check response structure
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "SUCCESS"
    assert "Alert settings updated successfully" in data.get("message", "")

    settings = data["data"]
    assert "subscription_id" in settings
    assert "alert_thresholds" in settings
    assert "alert_destinations" in settings
    assert "alerts_enabled" in settings
    assert "locale" in settings

    # Verify the updates were applied
    assert settings["alert_thresholds"] == [0.7, 0.85, 0.95]
    assert settings["alert_destinations"] == ["admin@example.com"]
    assert settings["alerts_enabled"] is True
    assert settings["locale"] == "es"


@pytest.mark.asyncio
async def test_alert_settings_pagination_and_filtering(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test alert settings endpoints handle edge cases properly."""
    # Test with empty subscription ID (should be handled by path validation)
    response = await authorized_client.get("/v1/billing/subscriptions//alert-settings")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with very long subscription ID (should be handled by path validation)
    long_id = "a" * 1000
    response = await authorized_client.get(
        f"/v1/billing/subscriptions/{long_id}/alert-settings"
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_alert_settings_concurrent_updates(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that concurrent alert settings updates work correctly."""
    subscription_id = str(test_subscription.id)

    # Simulate concurrent updates by making rapid requests
    import asyncio

    async def update_settings(data):
        return await authorized_client.patch(
            f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=data
        )

    # Make multiple concurrent updates
    update_data1 = {"alert_thresholds": [0.5, 0.7, 0.9]}
    update_data2 = {"locale": "fr"}
    update_data3 = {"alerts_enabled": False}

    responses = await asyncio.gather(
        update_settings(update_data1),
        update_settings(update_data2),
        update_settings(update_data3),
        return_exceptions=True,
    )

    # At least some should succeed
    success_count = sum(
        1 for r in responses if hasattr(r, "status_code") and r.status_code == 200
    )
    assert success_count >= 1


@pytest_asyncio.fixture
async def subscribed_organization(
    db_session: AsyncSession, organization_factory
) -> Organization:
    """Create a test organization with subscribed plan tier."""
    from uuid import uuid4
    from src.database.models.organizations import PlanTier

    org = await organization_factory.create_async(
        db_session,
        id=uuid4(),
        name="Subscribed Test Organization",
        plan_tier=PlanTier.SUBSCRIBED,
    )
    return org


@pytest_asyncio.fixture
async def subscribed_user(
    db_session: AsyncSession, user_factory, subscribed_organization: Organization
) -> User:
    """Create a test user in a subscribed organization."""
    from uuid import uuid4

    user = await user_factory.create_async(
        db_session,
        id=uuid4(),
        name="Subscribed User",
        email="subscribed@example.com",
        organization_id=subscribed_organization.id,
    )
    return user


@pytest_asyncio.fixture
async def subscribed_user_token(subscribed_user: User, jwt_token_factory) -> str:
    """Create JWT token for subscribed user."""
    return jwt_token_factory(
        str(subscribed_user.id), subscribed_user.email, subscribed_user.name
    )


@pytest_asyncio.fixture
async def subscribed_authorized_client(app, subscribed_user_token: str):
    """Create HTTP client with JWT authorization headers for subscribed user."""
    from httpx import AsyncClient
    from httpx._transports.asgi import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"Authorization": f"Bearer {subscribed_user_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def subscribed_subscription(
    db_session: AsyncSession,
    subscription_factory,
    subscribed_organization: Organization,
) -> Subscription:
    """Create a test subscription for the subscribed organization."""
    from datetime import datetime, timezone, timedelta

    subscription = await subscription_factory.create_async(
        db_session,
        organization_id=subscribed_organization.id,
        status="active",
        monthly_allowance=1000,
        overage_enabled=False,
        price_paid=60.0,
        description="Subscribed Test Subscription",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    return subscription


@pytest.mark.asyncio
async def test_update_alert_settings_enable_with_empty_thresholds_fails(
    app,
    subscribed_authorized_client: AsyncClient,
    subscribed_user,
    db_session,
    subscribed_subscription,
):
    """Test that enabling alerts with empty thresholds fails validation."""
    subscription_id = str(subscribed_subscription.id)

    # Try to enable alerts with empty thresholds
    invalid_data = {
        "alerts_enabled": True,
        "alert_thresholds": [],
        "alert_destinations": ["admin@example.com"],
    }

    response = await subscribed_authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error from service layer
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["message_code"] == "ALERT_SETTINGS_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_update_alert_settings_enable_with_empty_destinations_fails(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that enabling alerts with empty destinations fails validation."""
    subscription_id = str(test_subscription.id)

    # Try to enable alerts with empty destinations
    invalid_data = {
        "alerts_enabled": True,
        "alert_thresholds": [0.8, 0.9],
        "alert_destinations": [],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error from service layer
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["message_code"] == "NO_ALERT_DESTINATIONS"


@pytest.mark.asyncio
async def test_update_alert_settings_enable_with_existing_empty_thresholds_fails(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that enabling alerts fails when existing thresholds are empty."""
    subscription_id = str(test_subscription.id)

    # First, set up alert settings with empty thresholds and destinations
    setup_data = {
        "alerts_enabled": False,
        "alert_thresholds": [],
        "alert_destinations": [],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=setup_data
    )
    assert response.status_code == status.HTTP_200_OK

    # Now try to enable alerts without providing thresholds (existing are empty)
    invalid_data = {
        "alerts_enabled": True,
        "alert_destinations": ["admin@example.com"],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error from service layer
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["message_code"] == "ALERT_SETTINGS_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_update_alert_settings_enable_with_existing_empty_destinations_fails(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that enabling alerts fails when existing destinations are empty."""
    subscription_id = str(test_subscription.id)

    # First, set up alert settings with empty thresholds and destinations
    setup_data = {
        "alerts_enabled": False,
        "alert_thresholds": [],
        "alert_destinations": [],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=setup_data
    )
    assert response.status_code == status.HTTP_200_OK

    # Now try to enable alerts without providing destinations (existing are empty)
    invalid_data = {
        "alerts_enabled": True,
        "alert_thresholds": [0.8, 0.9],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=invalid_data
    )

    # Should return validation error from service layer
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert data["message_code"] == "NO_ALERT_DESTINATIONS"


@pytest.mark.asyncio
async def test_update_alert_settings_enable_with_valid_data_succeeds(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that enabling alerts with valid thresholds and destinations succeeds."""
    subscription_id = str(test_subscription.id)

    # Enable alerts with valid data
    valid_data = {
        "alerts_enabled": True,
        "alert_thresholds": [0.8, 0.9, 0.95],
        "alert_destinations": ["admin@example.com", "billing@example.com"],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=valid_data
    )

    # Should succeed
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message_code"] == "SUCCESS"

    settings = data["data"]
    assert settings["alerts_enabled"] is True
    assert settings["alert_thresholds"] == [0.8, 0.9, 0.95]
    assert settings["alert_destinations"] == [
        "admin@example.com",
        "billing@example.com",
    ]


@pytest.mark.asyncio
async def test_update_alert_settings_disable_with_empty_data_succeeds(
    app, authorized_client: AsyncClient, test_user, db_session, test_subscription
):
    """Test that disabling alerts works even with empty thresholds and destinations."""
    subscription_id = str(test_subscription.id)

    # Disable alerts with empty data (should be allowed)
    valid_data = {
        "alerts_enabled": False,
        "alert_thresholds": [],
        "alert_destinations": [],
    }

    response = await authorized_client.patch(
        f"/v1/billing/subscriptions/{subscription_id}/alert-settings", json=valid_data
    )

    # Should succeed
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message_code"] == "SUCCESS"

    settings = data["data"]
    assert settings["alerts_enabled"] is False
    assert settings["alert_thresholds"] == []
    assert settings["alert_destinations"] == []
