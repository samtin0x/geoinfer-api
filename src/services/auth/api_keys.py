"""API key management service with proper error handling."""

import secrets
from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import delete, select, update

from src.api.core.constants import GEO_API_KEY_PREFIX
from src.database.models import ApiKey, User
from src.cache import cached
from src.services.base import BaseService
from src.utils.hashing import HashingService


class ApiKeyManagementService(BaseService):
    """Service for API key management operations."""

    async def create_api_key(self, user_id: UUID, name: str) -> tuple[ApiKey, str]:
        # Generate secure API key
        api_key_body = secrets.token_urlsafe(32)
        plain_key = f"{GEO_API_KEY_PREFIX}{api_key_body}"

        # Hash the key for storage using secure bcrypt hashing
        key_hash = HashingService.hash_api_key(plain_key)

        # Create API key record
        api_key = ApiKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
        )

        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)

        self.logger.info(f"Created API key '{name}' for user {user_id}")
        return api_key, plain_key

    @cached(300)  # Cache API key verification for 5 minutes
    async def verify_api_key(self, plain_key: str) -> tuple[ApiKey, User] | None:
        """Verify an API key and return (api_key, user) tuple."""
        if not plain_key.startswith(GEO_API_KEY_PREFIX):
            self.logger.warning("API key verification failed: invalid format")
            return None

        # Hash the plain key for database lookup
        key_hash = HashingService.hash_api_key(plain_key)

        # Query for API key with matching hash, including user data
        stmt = select(ApiKey, User).join(User).where(ApiKey.key_hash == key_hash)

        result = await self.db.execute(stmt)
        row = result.first()

        if row:
            api_key, user = row
            # Update last used timestamp
            api_key.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()

            self.logger.info(f"API key verified for user {user.id}")
            return api_key, user

        # No matching key found
        self.logger.warning("API key verification failed: key not found")
        return None

    @cached(300)  # Cache API key lookup for 5 minutes
    async def get_api_key_by_key(self, plain_key: str) -> ApiKey | None:
        """Get API key object by plain key for authentication context."""
        if not plain_key.startswith(GEO_API_KEY_PREFIX):
            return None

        # Hash the plain key for database lookup
        key_hash = HashingService.hash_api_key(plain_key)

        # Query for API key with matching hash
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)

        result = await self.db.execute(stmt)
        api_key = result.scalar_one_or_none()

        if api_key:
            # Update last used timestamp
            api_key.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()

            self.logger.info(f"API key object retrieved for key {api_key.id}")
            return api_key

        # No matching key found
        return None

    async def list_user_api_keys(self, user_id: UUID) -> list[ApiKey]:
        """List all API keys for a user."""
        stmt = (
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        )

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_api_key(self, api_key_id: UUID, user_id: UUID) -> bool:
        """Delete an API key."""
        stmt = delete(ApiKey).where(ApiKey.id == api_key_id, ApiKey.user_id == user_id)

        result = await self.db.execute(stmt)
        await self.db.commit()

        if result.rowcount > 0:
            self.logger.info(f"Deleted API key {api_key_id}")
            return True
        return False

    async def regenerate_api_key(
        self, api_key_id: UUID, user_id: UUID
    ) -> tuple[ApiKey, str] | None:
        """Regenerate an API key with a new secret."""
        # First get the existing key to preserve name
        existing_key = await self.get_api_key(api_key_id, user_id)
        if not existing_key:
            return None

        # Generate new key
        plain_key = f"{GEO_API_KEY_PREFIX}{token_urlsafe(32)}"
        key_hash = HashingService.hash_api_key(plain_key)

        # Update the existing key with new hash
        stmt = (
            update(ApiKey)
            .where(ApiKey.id == api_key_id, ApiKey.user_id == user_id)
            .values(key_hash=key_hash, last_used_at=None)
            .returning(ApiKey)
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        updated_key = result.scalar_one_or_none()
        if updated_key:
            self.logger.info(f"Regenerated API key {api_key_id} for user {user_id}")
            return updated_key, plain_key

        return None

    async def get_api_key(self, api_key_id: UUID, user_id: UUID) -> ApiKey | None:
        """Get API key by ID for a specific user."""
        stmt = select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.user_id == user_id)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
