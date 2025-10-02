"""Tests for cache invalidation functionality."""

import pytest
from uuid import uuid4

from src.cache import (
    invalidate_user_cache,
    invalidate_organization_cache,
    invalidate_user_auth_cache,
    invalidate_user_roles_cache,
    invalidate_user_permissions_cache,
    invalidate_plan_tier_cache,
)


@pytest.mark.asyncio
async def test_invalidate_user_cache_can_be_called():
    """Test that invalidating user cache doesn't error."""
    user_id = uuid4()
    count = await invalidate_user_cache(user_id)
    assert count >= 0


@pytest.mark.asyncio
async def test_invalidate_organization_cache_can_be_called():
    """Test that invalidating org cache doesn't error."""
    org_id = uuid4()
    count = await invalidate_organization_cache(org_id)
    assert count >= 0


@pytest.mark.asyncio
async def test_invalidate_user_auth_cache_can_be_called():
    """Test that invalidate_user_auth_cache doesn't error."""
    user_id = uuid4()
    count = await invalidate_user_auth_cache(user_id)
    assert count >= 0


@pytest.mark.asyncio
async def test_invalidate_user_roles_cache_can_be_called():
    """Test that invalidating user roles cache doesn't error."""
    user_id = uuid4()
    org_id = uuid4()
    await invalidate_user_roles_cache(user_id, org_id)


@pytest.mark.asyncio
async def test_invalidate_user_permissions_cache_can_be_called():
    """Test that invalidating permissions cache doesn't error."""
    user_id = uuid4()
    org_id = uuid4()
    await invalidate_user_permissions_cache(user_id, org_id)


@pytest.mark.asyncio
async def test_invalidate_plan_tier_cache_can_be_called():
    """Test that invalidating plan tier cache doesn't error."""
    user_id = uuid4()
    org_id = uuid4()
    await invalidate_plan_tier_cache(user_id, org_id)
