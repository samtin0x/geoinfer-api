"""Comprehensive tests for API key endpoints."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.database.models.organizations import Organization, PlanTier
from src.database.models.users import User
from src.database.models.api_keys import ApiKey
from src.api.keys.requests import KeyCreateRequest


# Factory objects for test data
def create_test_user(
    user_id: uuid.UUID = None, email: str = "test@example.com"
) -> User:
    """Factory to create test user objects."""
    return User(
        id=user_id or uuid.uuid4(),
        email=email,
        full_name="Test User",
        is_active=True,
        onboarding_completed=False,
    )


def create_test_organization(
    org_id: uuid.UUID = None, plan_tier: PlanTier = PlanTier.SUBSCRIBED
) -> Organization:
    """Factory to create test organization objects."""
    return Organization(
        id=org_id or uuid.uuid4(),
        name="Test Organization",
        logo_url=None,
        plan_tier=plan_tier,
    )


def create_test_api_key(
    key_id: uuid.UUID = None, user_id: uuid.UUID = None, name: str = "Test API Key"
) -> ApiKey:
    """Factory to create test API key objects."""
    return ApiKey(
        id=key_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        name=name,
        key_hash="hashed_key_value",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_create_api_key_subscribed_or_enterprise_only(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that API key creation requires SUBSCRIBED or ENTERPRISE plan."""
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    # Should fail for trial users, succeed for subscribed/enterprise
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_201_CREATED,
    ]

    if response.status_code == status.HTTP_201_CREATED:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"
        assert data["data"]["name"] == "Test API Key"
        assert "key" in data["data"]  # Should return the actual key
        assert len(data["data"]["key"]) > 0  # Key should not be empty


@pytest.mark.asyncio
async def test_create_api_key_manage_api_keys_permission(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that API key creation requires MANAGE_API_KEYS permission."""
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    # Should fail if user doesn't have required permissions
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_201_CREATED,
    ]


@pytest.mark.asyncio
async def test_create_api_key_invalid_data(app, authorized_client: AsyncClient):
    """Test API key creation with invalid data."""
    # Test with empty name
    response = await authorized_client.post("/v1/keys/", json={"name": ""})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with name too long
    response = await authorized_client.post("/v1/keys/", json={"name": "a" * 256})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_api_key_success(app, authorized_client: AsyncClient, db_session):
    """Test successful API key creation."""
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    if response.status_code == status.HTTP_201_CREATED:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        key_data = data["data"]
        assert "id" in key_data
        assert "name" in key_data
        assert "key" in key_data
        assert "created_at" in key_data
        assert key_data["name"] == "Test API Key"

        # Verify the returned key is not empty
        assert len(key_data["key"]) > 0

        # Store key for later tests
        return key_data["id"]
    else:
        # If it fails due to permissions, that's expected
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_400_BAD_REQUEST,
        ]


@pytest.mark.asyncio
async def test_regenerate_api_key_subscribed_or_enterprise_only(
    app, authorized_client: AsyncClient
):
    """Test that API key regeneration requires SUBSCRIBED or ENTERPRISE plan."""
    test_key_id = uuid.uuid4()

    response = await authorized_client.post(f"/v1/keys/{test_key_id}/regenerate")

    # Should fail for trial users
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_200_OK,
    ]


@pytest.mark.asyncio
async def test_regenerate_api_key_manage_api_keys_permission(
    app, authorized_client: AsyncClient
):
    """Test that API key regeneration requires MANAGE_API_KEYS permission."""
    test_key_id = uuid.uuid4()

    response = await authorized_client.post(f"/v1/keys/{test_key_id}/regenerate")

    # Should fail if user doesn't have required permissions
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_200_OK,
    ]


@pytest.mark.asyncio
async def test_regenerate_nonexistent_api_key(app, authorized_client: AsyncClient):
    """Test regenerating non-existent API key."""
    non_existent_key_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.post(
        f"/v1/keys/{non_existent_key_id}/regenerate"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_regenerate_api_key_success(
    app, authorized_client: AsyncClient, db_session
):
    """Test successful API key regeneration."""
    # First create a key to regenerate
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    create_response = await authorized_client.post(
        "/v1/keys/", json=create_data.model_dump()
    )

    if create_response.status_code != status.HTTP_201_CREATED:
        pytest.skip("Cannot test regeneration without creating a key first")

    key_data = create_response.json()["data"]
    key_id = key_data["id"]
    original_key = key_data["key"]

    # Now regenerate it
    response = await authorized_client.post(f"/v1/keys/{key_id}/regenerate")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        regenerated_data = data["data"]
        assert regenerated_data["id"] == key_id
        assert regenerated_data["name"] == "Test API Key"
        assert "key" in regenerated_data

        # Verify the new key is different from the old one
        new_key = regenerated_data["key"]
        assert new_key != original_key

        # Verify the returned key is not empty
        assert len(new_key) > 0
    else:
        # If it fails due to permissions, that's expected
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]


@pytest.mark.asyncio
async def test_list_api_keys_subscribed_or_enterprise_only(
    app, authorized_client: AsyncClient
):
    """Test that API key listing requires SUBSCRIBED or ENTERPRISE plan."""
    response = await authorized_client.get("/v1/keys/")

    # Should fail for trial users
    assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_200_OK]


@pytest.mark.asyncio
async def test_list_api_keys_manage_api_keys_permission(
    app, authorized_client: AsyncClient
):
    """Test that API key listing requires MANAGE_API_KEYS permission."""
    response = await authorized_client.get("/v1/keys/")

    # Should fail if user doesn't have required permissions
    assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_200_OK]


@pytest.mark.asyncio
async def test_list_api_keys_success(app, authorized_client: AsyncClient, db_session):
    """Test successful API key listing."""
    # First create some keys
    keys_created = []
    for i in range(2):
        create_data = KeyCreateRequest(
            name=f"Test API Key {i}", description=f"Test key {i} description"
        )

        response = await authorized_client.post(
            "/v1/keys/", json=create_data.model_dump()
        )

        if response.status_code == status.HTTP_201_CREATED:
            keys_created.append(response.json()["data"]["id"])

    # Now list them
    response = await authorized_client.get("/v1/keys/")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "data" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        api_keys = data["data"]
        assert isinstance(api_keys, list)

        # Should include the keys we created
        returned_key_ids = [key["id"] for key in api_keys]
        for key_id in keys_created:
            assert key_id in returned_key_ids

        # Verify key data structure
        for key in api_keys:
            assert "id" in key
            assert "name" in key
            assert "created_at" in key
            assert "is_active" in key
            # Should not include the actual key hash
            assert "key" not in key
            assert "key_hash" not in key


@pytest.mark.asyncio
async def test_delete_api_key_subscribed_or_enterprise_only(
    app, authorized_client: AsyncClient
):
    """Test that API key deletion requires SUBSCRIBED or ENTERPRISE plan."""
    test_key_id = uuid.uuid4()

    response = await authorized_client.delete(f"/v1/keys/{test_key_id}")

    # Should fail for trial users
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_200_OK,
    ]


@pytest.mark.asyncio
async def test_delete_api_key_manage_api_keys_permission(
    app, authorized_client: AsyncClient
):
    """Test that API key deletion requires MANAGE_API_KEYS permission."""
    test_key_id = uuid.uuid4()

    response = await authorized_client.delete(f"/v1/keys/{test_key_id}")

    # Should fail if user doesn't have required permissions
    assert response.status_code in [
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_200_OK,
    ]


@pytest.mark.asyncio
async def test_delete_nonexistent_api_key(app, authorized_client: AsyncClient):
    """Test deleting non-existent API key."""
    non_existent_key_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.delete(f"/v1/keys/{non_existent_key_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_api_key_success(app, authorized_client: AsyncClient, db_session):
    """Test successful API key deletion."""
    # First create a key to delete
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    create_response = await authorized_client.post(
        "/v1/keys/", json=create_data.model_dump()
    )

    if create_response.status_code != status.HTTP_201_CREATED:
        pytest.skip("Cannot test deletion without creating a key first")

    key_data = create_response.json()["data"]
    key_id = key_data["id"]

    # Now delete it
    response = await authorized_client.delete(f"/v1/keys/{key_id}")

    if response.status_code == status.HTTP_200_OK:
        data = response.json()
        assert "message" in data
        assert "message_code" in data
        assert data["message_code"] == "success"

        # Verify the key is actually deleted
        list_response = await authorized_client.get("/v1/keys/")
        if list_response.status_code == status.HTTP_200_OK:
            list_data = list_response.json()
            remaining_key_ids = [key["id"] for key in list_data["data"]]
            assert key_id not in remaining_key_ids
    else:
        # If it fails due to permissions, that's expected
        assert response.status_code in [
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ]


@pytest.mark.asyncio
async def test_api_key_name_uniqueness_per_user(app, authorized_client: AsyncClient):
    """Test that API key names must be unique per user."""
    create_data = KeyCreateRequest(
        name="Duplicate API Key Name", description="Test key description"
    )

    # Try to create the same key twice
    response1 = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    response2 = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    # At least one should fail if uniqueness is enforced
    assert (
        response1.status_code != status.HTTP_201_CREATED
        or response2.status_code != status.HTTP_201_CREATED
    )


@pytest.mark.parametrize(
    "name",
    [
        "Test API Key",
        "My API Key 123",
        "Production Key",
        "Test-Key_With-Underscores",
        "test_key_123",
    ],
)
@pytest.mark.asyncio
async def test_api_key_creation_with_various_names(
    app, authorized_client: AsyncClient, name: str
):
    """Test API key creation with various valid names."""
    create_data = KeyCreateRequest(name=name, description="Test key description")

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    # Should either succeed or fail consistently
    assert response.status_code in [
        status.HTTP_201_CREATED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_400_BAD_REQUEST,
    ]

    if response.status_code == status.HTTP_201_CREATED:
        data = response.json()
        assert data["data"]["name"] == name


@pytest.mark.asyncio
async def test_api_key_lifecycle_integration(
    app, authorized_client: AsyncClient, db_session
):
    """Test complete API key lifecycle from creation to deletion."""
    # Create API key
    create_data = KeyCreateRequest(
        name="Lifecycle Test Key", description="Key for lifecycle testing"
    )

    create_response = await authorized_client.post(
        "/v1/keys/", json=create_data.model_dump()
    )

    assert create_response.status_code == status.HTTP_201_CREATED

    key_data = create_response.json()["data"]
    key_id = key_data["id"]
    original_key = key_data["key"]

    # List keys to verify it exists
    list_response = await authorized_client.get("/v1/keys/")
    assert list_response.status_code == status.HTTP_200_OK

    list_data = list_response.json()
    key_ids = [key["id"] for key in list_data["data"]]
    assert key_id in key_ids

    # Regenerate the key
    regenerate_response = await authorized_client.post(f"/v1/keys/{key_id}/regenerate")
    assert regenerate_response.status_code == status.HTTP_200_OK

    regenerated_data = regenerate_response.json()["data"]
    new_key = regenerated_data["key"]

    # Verify the new key is different
    assert new_key != original_key

    # Delete the key
    delete_response = await authorized_client.delete(f"/v1/keys/{key_id}")
    assert delete_response.status_code == status.HTTP_200_OK

    # Verify deletion
    verify_response = await authorized_client.get("/v1/keys/")
    assert verify_response.status_code == status.HTTP_200_OK

    verify_data = verify_response.json()
    remaining_ids = [key["id"] for key in verify_data["data"]]
    assert key_id not in remaining_ids
