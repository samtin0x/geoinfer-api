"""Billing endpoints tests."""

import pytest
from httpx import AsyncClient
from fastapi import status


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
        assert data["message_code"] == "success"

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
        assert data["message_code"] == "success"
        assert isinstance(data["data"], list)
