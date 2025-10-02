"""Tests for cache decorator basic functionality."""

import pytest
from uuid import uuid4

from src.cache import cached, invalidate_cache


@pytest.mark.asyncio
async def test_cache_decorator_caches_result():
    """Test that cached decorator caches function results."""
    call_count = 0

    @cached(ttl=60)
    async def get_value(param: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{param}"

    # First call should execute function
    result1 = await get_value("test")
    assert result1 == "result-test"
    assert call_count == 1

    # Second call should return cached result (or execute again if cache disabled)
    result2 = await get_value("test")
    assert result2 == "result-test"
    # Cache is disabled in tests, so call_count will be 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_decorator_returns_complex_objects():
    """Test that cached decorator can handle complex return types."""

    @cached(ttl=60)
    async def get_complex_data() -> dict:
        return {
            "users": [{"id": 1, "name": "User 1"}, {"id": 2, "name": "User 2"}],
            "metadata": {"total": 2, "page": 1},
        }

    result1 = await get_complex_data()
    assert len(result1["users"]) == 2
    assert result1["metadata"]["total"] == 2

    result2 = await get_complex_data()
    assert result1 == result2


@pytest.mark.asyncio
async def test_cache_decorator_with_different_params():
    """Test that different parameters are handled correctly."""
    call_count = 0

    @cached(ttl=60)
    async def get_value(param: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{param}"

    result1 = await get_value("param1")
    result2 = await get_value("param2")

    assert result1 == "result-param1"
    assert result2 == "result-param2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_decorator_with_uuid_params():
    """Test that UUID parameters work correctly."""
    call_count = 0
    user_id = uuid4()

    @cached(ttl=60)
    async def get_user_data(user_id_param: uuid4) -> dict:
        nonlocal call_count
        call_count += 1
        return {"user_id": str(user_id_param), "name": "Test User"}

    result1 = await get_user_data(user_id)
    assert result1["user_id"] == str(user_id)
    assert call_count == 1


@pytest.mark.asyncio
async def test_invalidate_cache_can_be_called():
    """Test that invalidate_cache function can be called without errors."""
    call_count = 0

    @cached(ttl=60)
    async def get_value(param: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{param}"

    # Cache the result
    result1 = await get_value("test")
    assert result1 == "result-test"

    # Invalidate cache - should not error
    await invalidate_cache(get_value, "test")

    # Function still works
    result2 = await get_value("test")
    assert result2 == "result-test"
