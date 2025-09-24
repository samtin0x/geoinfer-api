"""API key management service with proper error handling."""

import secrets
from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import delete, select, update
from fastapi import status

from src.api.core.constants import GEO_API_KEY_PREFIX
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.database.models import ApiKey, User
from src.cache import cached
from src.core.base import BaseService
from src.utils.hashing import HashingService


class ApiKeyManagementService(BaseService):
    async def create_api_key(
        self, organization_id: UUID, user_id: UUID, name: str
    ) -> tuple[ApiKey, str]:
        api_key_body = secrets.token_urlsafe(32)
        plain_key = f"{GEO_API_KEY_PREFIX}{api_key_body}"
        key_hash = HashingService.hash_api_key(plain_key)
        api_key = ApiKey(
            organization_id=organization_id,
            user_id=user_id,
            name=name,
            key_hash=key_hash,
        )
        self.db.add(api_key)
        await self.db.commit()
        await self.db.refresh(api_key)
        return api_key, plain_key

    @cached(300)
    async def verify_api_key(self, plain_key: str) -> tuple[ApiKey, User] | None:
        if not plain_key.startswith(GEO_API_KEY_PREFIX):
            return None
        key_hash = HashingService.hash_api_key(plain_key)
        stmt = select(ApiKey, User).join(User).where(ApiKey.key_hash == key_hash)
        result = await self.db.execute(stmt)
        row = result.first()
        if row:
            api_key, user = row
            api_key.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()
            return api_key, user
        return None

    @cached(300)
    async def get_api_key_by_key(self, plain_key: str) -> ApiKey | None:
        if not plain_key.startswith(GEO_API_KEY_PREFIX):
            return None
        key_hash = HashingService.hash_api_key(plain_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        result = await self.db.execute(stmt)
        api_key = result.scalar_one_or_none()
        if api_key:
            api_key.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()
            return api_key
        return None

    async def list_organization_api_keys(self, organization_id: UUID) -> list[ApiKey]:
        stmt = (
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_api_key(self, api_key_id: UUID, organization_id: UUID) -> bool:
        stmt = delete(ApiKey).where(
            ApiKey.id == api_key_id, ApiKey.organization_id == organization_id
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def regenerate_api_key(
        self, api_key_id: UUID, organization_id: UUID
    ) -> tuple[ApiKey, str]:
        existing_key = await self.get_api_key(
            api_key_id=api_key_id, organization_id=organization_id
        )
        if not existing_key:
            raise GeoInferException(
                MessageCode.API_KEY_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
                {"description": f"API key {api_key_id} not found or access denied"},
            )
        plain_key = f"{GEO_API_KEY_PREFIX}{token_urlsafe(32)}"
        key_hash = HashingService.hash_api_key(plain_key)
        stmt = (
            update(ApiKey)
            .where(ApiKey.id == api_key_id, ApiKey.organization_id == organization_id)
            .values(key_hash=key_hash, last_used_at=None)
            .returning(ApiKey)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        updated_key = result.scalar_one_or_none()
        if updated_key:
            return updated_key, plain_key
        raise GeoInferException(
            MessageCode.API_KEY_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": f"API key {api_key_id} not found or access denied"},
        )

    async def get_api_key(
        self, api_key_id: UUID, organization_id: UUID
    ) -> ApiKey | None:
        stmt = select(ApiKey).where(
            ApiKey.id == api_key_id, ApiKey.organization_id == organization_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
