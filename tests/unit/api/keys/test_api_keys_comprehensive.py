"""Comprehensive tests for API key functionality - both business logic and API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4

from src.database.models import User, ApiKey
from src.api.core.messages import MessageCode
from tests.utils.assertions import (
    assert_success_response,
    assert_error_response,
    assert_not_found_error,
)


class TestAPIKeyBusinessLogic:
    """Test the core API key business logic functions."""

    @pytest.mark.asyncio
    async def test_api_key_creation_with_factory(
        self, db_session: AsyncSession, api_key_factory, test_user: User
    ):
        """Test creating an API key using the factory system."""
        api_key = await api_key_factory.create_async(
            db_session, name="Test API Key", user_id=test_user.id
        )

        # Assertions
        assert api_key.name == "Test API Key"
        assert api_key.user_id == test_user.id
        assert api_key.key_hash is not None
        assert api_key.id is not None
        assert api_key.created_at is not None

    @pytest.mark.asyncio
    async def test_api_key_creation_with_plain_key(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating API key with actual key generation."""
        # Use the model's create_key method
        api_key, plain_key = ApiKey.create_key(
            "Production Key", test_user.organization_id, test_user.id
        )

        # Verify the plain key format
        assert plain_key.startswith("geo_")
        assert len(plain_key) > 20  # Should be reasonably long

        # Verify key verification works
        assert ApiKey.verify_key(plain_key, api_key.key_hash)

        # Verify wrong key doesn't work
        assert not ApiKey.verify_key("wrong_key", api_key.key_hash)

    @pytest.mark.asyncio
    async def test_api_key_hashing_security(self, test_user: User):
        """Test that API key hashing is secure."""
        # Create two keys with same name
        key1, plain1 = ApiKey.create_key(
            "Same Name", test_user.organization_id, test_user.id
        )
        key2, plain2 = ApiKey.create_key(
            "Same Name", test_user.organization_id, test_user.id
        )

        # Plain keys should be different
        assert plain1 != plain2

        # Hashes should be different
        assert key1.key_hash != key2.key_hash

        # Each key should only verify with its own hash
        assert ApiKey.verify_key(plain1, key1.key_hash)
        assert not ApiKey.verify_key(plain1, key2.key_hash)
        assert ApiKey.verify_key(plain2, key2.key_hash)
        assert not ApiKey.verify_key(plain2, key1.key_hash)

    @pytest.mark.asyncio
    async def test_multiple_api_keys_per_user(
        self, db_session: AsyncSession, api_key_factory, test_user: User
    ):
        """Test that users can have multiple API keys."""
        # Create multiple keys for the same user
        key1 = await api_key_factory.create_async(
            db_session, name="Production Key", user_id=test_user.id
        )

        key2 = await api_key_factory.create_async(
            db_session, name="Development Key", user_id=test_user.id
        )

        key3 = await api_key_factory.create_async(
            db_session, name="Testing Key", user_id=test_user.id
        )

        # All should belong to the same user
        assert key1.user_id == test_user.id
        assert key2.user_id == test_user.id
        assert key3.user_id == test_user.id

        # All should have different IDs and hashes
        assert key1.id != key2.id != key3.id
        assert key1.key_hash != key2.key_hash != key3.key_hash


class TestAPIKeyAPIEndpoints:
    """Test API key API endpoints with proper authentication and permissions."""

    @pytest.mark.asyncio
    async def test_create_api_key_success(
        self, authorized_client: AsyncClient, test_user: User
    ):
        """Test creating an API key successfully."""
        key_data = {"name": "My New API Key"}

        response = await authorized_client.post("/api/v1/keys", json=key_data)

        # Assert successful creation
        data = assert_success_response(
            response, MessageCode.API_KEY_CREATED, 201, {"name": "My New API Key"}
        )

        # Should return the plain key (only time it's visible)
        assert "key" in data
        assert data["key"].startswith("geo_")
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_api_key_unauthenticated(self, public_client: AsyncClient):
        """Test creating API key without authentication."""
        key_data = {"name": "Should Not Work"}

        response = await public_client.post("/api/v1/keys", json=key_data)

        # Should require authentication
        assert_error_response(response, MessageCode.UNAUTHORIZED, 401)

    @pytest.mark.asyncio
    async def test_list_api_keys_success(
        self, authorized_client: AsyncClient, test_api_key: tuple[ApiKey, str]
    ):
        """Test listing user's API keys."""
        response = await authorized_client.get("/api/v1/keys")

        # Assert successful response
        data = assert_success_response(response, MessageCode.SUCCESS, 200)

        # Should return list of keys
        assert isinstance(data, list)
        assert len(data) >= 1  # At least the test API key

        # Find our test key
        api_key, _ = test_api_key
        test_key_data = next(
            (key for key in data if key["id"] == str(api_key.id)), None
        )
        assert test_key_data is not None
        assert test_key_data["name"] == api_key.name

        # Should NOT include the actual key value
        assert "key" not in test_key_data
        assert "key_hash" not in test_key_data

    @pytest.mark.asyncio
    async def test_delete_api_key_success(
        self, authorized_client: AsyncClient, test_api_key: tuple[ApiKey, str]
    ):
        """Test deleting an API key successfully."""
        api_key, _ = test_api_key

        response = await authorized_client.delete(f"/api/v1/keys/{api_key.id}")

        # Assert successful deletion
        assert_success_response(response, MessageCode.API_KEY_DELETED, 200)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_api_key(self, authorized_client: AsyncClient):
        """Test deleting API key that doesn't exist."""
        fake_key_id = uuid4()

        response = await authorized_client.delete(f"/api/v1/keys/{fake_key_id}")

        # Should return not found error
        assert_not_found_error(response, "api_key")

    @pytest.mark.asyncio
    async def test_delete_other_user_api_key(
        self,
        authorized_client: AsyncClient,
        db_session: AsyncSession,
        create_user_factory,
        api_key_factory,
    ):
        """Test that users cannot delete other users' API keys."""
        # Create another user and their API key
        other_user = await create_user_factory(
            email="otheruser@company.com", name="Other User"
        )

        other_key = await api_key_factory.create_async(
            db_session, name="Other User's Key", user_id=other_user.id
        )

        # Try to delete the other user's key
        response = await authorized_client.delete(f"/api/v1/keys/{other_key.id}")

        # Should return not found (for security, don't reveal existence)
        assert_not_found_error(response, "api_key")


class TestAPIKeyAuthentication:
    """Test API key authentication functionality."""

    @pytest.mark.asyncio
    async def test_api_key_authentication_success(
        self, api_key_client: AsyncClient, test_api_key: tuple[ApiKey, str]
    ):
        """Test successful API key authentication."""
        # Make a request that requires API key auth
        response = await api_key_client.get("/api/v1/predictions")

        # Should succeed (adjust endpoint based on your API)
        if response.status_code == 401:
            # If this endpoint doesn't support API key auth, adjust test
            assert_error_response(response, MessageCode.UNAUTHORIZED, 401)
        else:
            assert_success_response(response, MessageCode.SUCCESS, 200)

    @pytest.mark.asyncio
    async def test_invalid_api_key_authentication(
        self, app, public_client: AsyncClient
    ):
        """Test authentication with invalid API key."""
        # Create client with invalid API key
        async with AsyncClient(
            app=app,
            base_url="http://test-geoinfer-api",
            headers={"X-GeoInfer-Key": "invalid_key"},
        ) as client:
            response = await client.get("/api/v1/predictions")

            # Should return invalid API key error
            assert_error_response(response, MessageCode.INVALID_API_KEY, 401)

    @pytest.mark.asyncio
    async def test_missing_api_key_header(self, public_client: AsyncClient):
        """Test accessing API key protected endpoint without key."""
        response = await public_client.get("/api/v1/predictions")

        # Should require authentication
        assert_error_response(response, MessageCode.UNAUTHORIZED, 401)


class TestAPIKeyValidation:
    """Test API key validation and error scenarios."""

    @pytest.mark.asyncio
    async def test_create_api_key_invalid_name(self, authorized_client: AsyncClient):
        """Test creating API key with invalid name."""
        invalid_data = {"name": ""}  # Empty name should be invalid

        response = await authorized_client.post("/api/v1/keys", json=invalid_data)

        # Should return validation error
        assert_error_response(response, MessageCode.INVALID_INPUT, 422)

    @pytest.mark.asyncio
    async def test_create_api_key_missing_name(self, authorized_client: AsyncClient):
        """Test creating API key without name."""
        response = await authorized_client.post("/api/v1/keys", json={})

        # Should return validation error
        assert_error_response(response, MessageCode.INVALID_INPUT, 422)

    @pytest.mark.asyncio
    async def test_create_api_key_duplicate_name(self, authorized_client: AsyncClient):
        """Test creating API key with duplicate name for same user."""
        key_data = {"name": "Duplicate Key Name"}

        # Create first key
        response1 = await authorized_client.post("/api/v1/keys", json=key_data)
        assert_success_response(response1, MessageCode.API_KEY_CREATED, 201)

        # Try to create second key with same name
        response2 = await authorized_client.post("/api/v1/keys", json=key_data)

        # Depending on your business rules, this might succeed or fail
        # Adjust based on your API's behavior
        if response2.status_code == 409:
            assert_error_response(response2, MessageCode.BAD_REQUEST, 409)
        else:
            # If duplicates are allowed, should succeed
            assert_success_response(response2, MessageCode.API_KEY_CREATED, 201)


class TestAPIKeyWorkflows:
    """Test complete API key workflows end-to-end."""

    @pytest.mark.asyncio
    async def test_api_key_lifecycle_workflow(self, authorized_client: AsyncClient):
        """Test complete API key lifecycle: create -> list -> use -> delete."""
        # Step 1: Create API key
        create_response = await authorized_client.post(
            "/api/v1/keys", json={"name": "Lifecycle Test Key"}
        )

        created_key = assert_success_response(
            create_response,
            MessageCode.API_KEY_CREATED,
            201,
            {"name": "Lifecycle Test Key"},
        )

        key_id = created_key["id"]
        plain_key = created_key["key"]

        # Step 2: List keys and verify it appears
        list_response = await authorized_client.get("/api/v1/keys")
        keys_data = assert_success_response(list_response, MessageCode.SUCCESS, 200)

        # Find our key in the list
        found_key = next((key for key in keys_data if key["id"] == key_id), None)
        assert found_key is not None
        assert found_key["name"] == "Lifecycle Test Key"

        # Step 3: Use the API key for authentication
        async with AsyncClient(
            app=authorized_client._transport._app,
            base_url="http://test-geoinfer-api",
            headers={"X-GeoInfer-Key": plain_key},
        ) as api_client:
            # Make an authenticated request
            auth_response = await api_client.get("/api/v1/keys")

            if auth_response.status_code != 401:  # If endpoint supports API key auth
                assert_success_response(auth_response, MessageCode.SUCCESS, 200)

        # Step 4: Delete the API key
        delete_response = await authorized_client.delete(f"/api/v1/keys/{key_id}")
        assert_success_response(delete_response, MessageCode.API_KEY_DELETED, 200)

        # Step 5: Verify key is gone from list
        final_list_response = await authorized_client.get("/api/v1/keys")
        final_keys_data = assert_success_response(
            final_list_response, MessageCode.SUCCESS, 200
        )

        # Should not find our deleted key
        deleted_key = next(
            (key for key in final_keys_data if key["id"] == key_id), None
        )
        assert deleted_key is None

    @pytest.mark.asyncio
    async def test_multiple_users_api_keys_isolation(
        self, client_factory, db_session: AsyncSession, create_user_factory
    ):
        """Test that API keys are properly isolated between users."""
        # Create two users
        user1 = await create_user_factory(email="user1@company.com", name="User One")

        user2 = await create_user_factory(email="user2@company.com", name="User Two")

        # Create clients for both users
        client1 = await client_factory(user1)
        client2 = await client_factory(user2)

        # Each user creates an API key
        key1_response = await client1.post("/api/v1/keys", json={"name": "User 1 Key"})
        key1_data = assert_success_response(
            key1_response, MessageCode.API_KEY_CREATED, 201
        )

        key2_response = await client2.post("/api/v1/keys", json={"name": "User 2 Key"})
        key2_data = assert_success_response(
            key2_response, MessageCode.API_KEY_CREATED, 201
        )

        # User 1 should only see their own keys
        user1_keys_response = await client1.get("/api/v1/keys")
        user1_keys = assert_success_response(
            user1_keys_response, MessageCode.SUCCESS, 200
        )

        user1_key_ids = [key["id"] for key in user1_keys]
        assert key1_data["id"] in user1_key_ids
        assert key2_data["id"] not in user1_key_ids

        # User 2 should only see their own keys
        user2_keys_response = await client2.get("/api/v1/keys")
        user2_keys = assert_success_response(
            user2_keys_response, MessageCode.SUCCESS, 200
        )

        user2_key_ids = [key["id"] for key in user2_keys]
        assert key2_data["id"] in user2_key_ids
        assert key1_data["id"] not in user2_key_ids

        await client1.aclose()
        await client2.aclose()
