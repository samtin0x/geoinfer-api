"""API key management tests."""

import pytest
from httpx import AsyncClient
from fastapi import status
import uuid

from src.database.models.organizations import PlanTier
from src.api.keys.requests import KeyCreateRequest


@pytest.mark.asyncio
async def test_create_api_key_enterprise_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful API key creation with enterprise permissions."""
    # Make user enterprise tier
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify API key data in response
    key_data = data["data"]
    assert key_data["name"] == "Test API Key"
    assert "key" in key_data
    assert "id" in key_data
    assert "created_at" in key_data
    assert len(key_data["key"]) > 0  # Should return actual key
    assert key_data["name"] == "Test API Key"


@pytest.mark.asyncio
async def test_create_api_key_trial_fails(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that trial users cannot create API keys."""
    test_user.plan_tier = PlanTier.FREE
    db_session.add(test_user)
    await db_session.commit()

    create_data = KeyCreateRequest(name="Test API Key", description="Test description")

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_api_key_invalid_data(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test API key creation with invalid data."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # Test with empty name
    response = await authorized_client.post("/v1/keys/", json={"name": ""})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Test with name too long
    long_name = "a" * 256
    response = await authorized_client.post("/v1/keys/", json={"name": long_name})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_list_api_keys_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful API key listing."""
    # Make user enterprise tier
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # Create multiple API keys
    keys_created = []
    for i in range(3):
        create_data = KeyCreateRequest(
            name=f"Test API Key {i}", description=f"Test key {i} description"
        )

        response = await authorized_client.post(
            "/v1/keys/", json=create_data.model_dump()
        )

        if response.status_code == status.HTTP_201_CREATED:
            keys_created.append(response.json()["data"]["id"])

    # List API keys
    response = await authorized_client.get("/v1/keys/")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "data" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    api_keys = data["data"]
    assert isinstance(api_keys, list)
    assert len(api_keys) >= 3

    # Verify all created keys are in the list
    returned_key_ids = [key["id"] for key in api_keys]
    for key_id in keys_created:
        assert key_id in returned_key_ids

    # Verify key data structure (should not include actual key hash)
    for key in api_keys:
        assert "id" in key
        assert "name" in key
        assert "created_at" in key
        assert "is_active" in key
        assert "key" not in key  # Should not expose actual key
        assert "key_hash" not in key  # Should not expose key hash


@pytest.mark.asyncio
async def test_list_api_keys_trial_fails(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that trial users cannot list API keys."""
    test_user.plan_tier = PlanTier.FREE
    db_session.add(test_user)
    await db_session.commit()

    response = await authorized_client.get("/v1/keys/")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_regenerate_api_key_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful API key regeneration."""
    # Make user enterprise tier
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # First create a key to regenerate
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    create_response = await authorized_client.post(
        "/v1/keys/", json=create_data.model_dump()
    )

    assert create_response.status_code == status.HTTP_201_CREATED

    key_data = create_response.json()["data"]
    key_id = key_data["id"]
    original_key = key_data["key"]

    # Regenerate the key
    response = await authorized_client.post(f"/v1/keys/{key_id}/regenerate")

    assert response.status_code == status.HTTP_200_OK

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
    assert len(new_key) > 0


@pytest.mark.asyncio
async def test_regenerate_nonexistent_api_key(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test regenerating non-existent API key."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    non_existent_key_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.post(
        f"/v1/keys/{non_existent_key_id}/regenerate"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_api_key_success(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test successful API key deletion."""
    # Make user enterprise tier
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    # First create a key to delete
    create_data = KeyCreateRequest(
        name="Test API Key", description="Test key description"
    )

    create_response = await authorized_client.post(
        "/v1/keys/", json=create_data.model_dump()
    )

    assert create_response.status_code == status.HTTP_201_CREATED

    key_data = create_response.json()["data"]
    key_id = key_data["id"]

    # Delete the key
    response = await authorized_client.delete(f"/v1/keys/{key_id}")

    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "message" in data
    assert "message_code" in data
    assert data["message_code"] == "success"

    # Verify the key is actually deleted
    list_response = await authorized_client.get("/v1/keys/")
    assert list_response.status_code == status.HTTP_200_OK

    list_data = list_response.json()
    remaining_key_ids = [key["id"] for key in list_data["data"]]
    assert key_id not in remaining_key_ids


@pytest.mark.asyncio
async def test_delete_nonexistent_api_key(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test deleting non-existent API key."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    non_existent_key_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    response = await authorized_client.delete(f"/v1/keys/{non_existent_key_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_api_key_name_uniqueness_per_user(
    app, authorized_client: AsyncClient, test_user, db_session
):
    """Test that API key names must be unique per user."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    create_data = KeyCreateRequest(
        name="Duplicate API Key Name", description="Test key description"
    )

    # Try to create the same key twice
    response1 = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    if response1.status_code == status.HTTP_201_CREATED:
        response2 = await authorized_client.post(
            "/v1/keys/", json=create_data.model_dump()
        )

        # Second creation should fail due to uniqueness constraint
        assert response2.status_code != status.HTTP_201_CREATED


@pytest.mark.parametrize(
    "name",
    [
        "Test API Key",
        "My API Key 123",
        "Production Key",
        "Test-Key_With-Underscores",
        "test_key_123",
        "API Key for Testing",
        "Data Processing Key",
    ],
)
@pytest.mark.asyncio
async def test_api_key_creation_with_various_names(
    app, authorized_client: AsyncClient, test_user, db_session, name: str
):
    """Test API key creation with various valid names."""
    test_user.plan_tier = PlanTier.ENTERPRISE
    db_session.add(test_user)
    await db_session.commit()

    create_data = KeyCreateRequest(name=name, description="Test key description")

    response = await authorized_client.post("/v1/keys/", json=create_data.model_dump())

    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["data"]["name"] == name
    assert len(data["data"]["key"]) > 0
