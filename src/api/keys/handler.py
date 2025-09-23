"""Keys domain handlers."""

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import status

from src.api.core.messages import APIResponse, MessageCode
from src.api.core.exceptions.base import GeoInferException
from src.services.auth import ApiKeyManagementService
from src.utils.logger import get_logger
from .models import KeyModel, KeyWithSecret
from .requests import (
    KeyCreateRequest,
    KeyCreateResponse,
    KeyDeleteResponse,
    KeyListResponse,
)

logger = get_logger(__name__)


async def create_key_handler(
    db: AsyncSession,
    key_data: KeyCreateRequest,
    user_id: UUID,
) -> KeyCreateResponse:
    """Create a new API key."""
    service = ApiKeyManagementService(db)

    api_key, plain_key = await service.create_api_key(
        user_id=user_id,
        name=key_data.name,
    )

    logger.info(f"Created API key '{key_data.name}' for user {user_id}")

    # Create response with the secret key using ORM model
    key_model = KeyModel.model_validate(api_key)
    key_with_secret = KeyWithSecret(**key_model.model_dump(), key=plain_key)

    return APIResponse.success(
        message_code=MessageCode.API_KEY_CREATED, data=key_with_secret
    )


async def list_keys_handler(
    db: AsyncSession,
    user_id: UUID,
) -> KeyListResponse:
    """List all API keys for a user."""
    service = ApiKeyManagementService(db)

    keys = await service.list_user_api_keys(user_id)

    key_list = [KeyModel.model_validate(key) for key in keys]

    return APIResponse.success(data={"keys": key_list, "total": len(key_list)})


async def delete_key_handler(
    db: AsyncSession,
    key_id: UUID,
    user_id: UUID,
) -> KeyDeleteResponse:
    """Delete an API key."""
    service = ApiKeyManagementService(db)

    success = await service.delete_api_key(key_id, user_id)

    if not success:
        raise GeoInferException(
            MessageCode.API_KEY_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": f"API key {key_id} not found or access denied"},
        )

    logger.info(f"Deleted API key {key_id} for user {user_id}")

    return APIResponse.success(
        message_code=MessageCode.API_KEY_DELETED, data={"deleted": True}
    )


async def regenerate_key_handler(
    db: AsyncSession,
    key_id: UUID,
    user_id: UUID,
) -> KeyCreateResponse:
    """Regenerate an API key."""
    service = ApiKeyManagementService(db)

    result = await service.regenerate_api_key(key_id, user_id)

    if not result:
        raise GeoInferException(
            MessageCode.API_KEY_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
            {"description": f"API key {key_id} not found or access denied"},
        )

    api_key, plain_key = result
    logger.info(f"Regenerated API key {key_id} for user {user_id}")

    # Create response with the new secret key
    key_model = KeyModel.model_validate(api_key)
    key_with_secret = KeyWithSecret(**key_model.model_dump(), key=plain_key)

    return APIResponse.success(
        message_code=MessageCode.API_KEY_CREATED, data=key_with_secret
    )
