import structlog
from dataclasses import asdict
from fastapi import Request, status

from src.api.core.constants import (
    API_KEY_HEADER,
    SKIP_AUTH_PATHS,
    API_KEY_ALLOWED_ENDPOINTS,
)
from src.utils.path_helpers import path_matches
from src.api.core.messages import MessageCode
from src.api.core.exceptions.base import GeoInferException
from src.database.connection import get_async_db
from src.modules.user.auth_handlers import (
    handle_api_key_auth,
    handle_jwt_auth,
)
from src.redis.client import get_redis_client

logger = structlog.get_logger(__name__)


async def auth_middleware(request: Request, call_next):
    """
    Simplified middleware that handles both JWT and API key authentication.

    Uses dedicated handlers: handle_jwt_auth and handle_api_key_auth
    """
    logger.debug(
        "Auth middleware started",
        path=request.url.path,
        method=request.method,
        headers={
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ["authorization", "x-api-key"]
        },
    )

    # Skip authentication for certain endpoints
    if path_matches(request.url.path, SKIP_AUTH_PATHS):
        logger.debug(
            "Skipping auth for path", path=request.url.path, skip_paths=SKIP_AUTH_PATHS
        )
        request.state.user = None
        request.state.api_key = None
        return await call_next(request)

    # Get required headers
    api_key = request.headers.get(API_KEY_HEADER)
    authorization = request.headers.get("Authorization", "")

    logger.debug(
        "Auth headers extracted",
        has_api_key=bool(api_key),
        has_authorization=bool(authorization),
        api_key_header=API_KEY_HEADER,
        auth_header="Authorization",
    )

    # Require some form of authentication
    if not api_key and not authorization:
        logger.debug("No authentication provided - rejecting request")
        raise GeoInferException(
            MessageCode.AUTH_REQUIRED,
            status.HTTP_401_UNAUTHORIZED,
            {"description": f"Provide either '{API_KEY_HEADER}' header or use the FE"},
        )

    # Check if API key is allowed for this endpoint
    if api_key and not path_matches(request.url.path, API_KEY_ALLOWED_ENDPOINTS):
        logger.debug(
            "API key not allowed for endpoint",
            path=request.url.path,
            allowed_endpoints=API_KEY_ALLOWED_ENDPOINTS,
        )
        raise GeoInferException(
            MessageCode.UNAUTHORIZED,
            status.HTTP_401_UNAUTHORIZED,
            {
                "description": "API keys not allowed for this endpoint. Use frontend application."
            },
        )

    # Get DB and Redis connections
    logger.debug("Getting DB and Redis connections")
    async with get_async_db() as db:
        redis_client = await get_redis_client()
        try:
            auth_data = None

            # Handle API key authentication
            if api_key:
                logger.debug("Processing API key authentication")
                auth_data = await handle_api_key_auth(
                    request, db, redis_client, api_key
                )
                logger.debug(
                    "API key auth completed",
                    has_auth_data=bool(auth_data),
                    auth_data_keys=(
                        list(asdict(auth_data).keys()) if auth_data else None
                    ),
                )

            # Handle JWT authentication
            elif authorization:
                logger.debug("Processing JWT authentication")
                # Extract token from Authorization header
                auth_parts = authorization.split(" ")
                if len(auth_parts) != 2 or auth_parts[0].lower() != "bearer":
                    logger.debug(
                        "Invalid authorization header format",
                        auth_parts_count=len(auth_parts),
                        first_part=auth_parts[0] if auth_parts else None,
                    )
                    raise GeoInferException(
                        MessageCode.INVALID_TOKEN,
                        status.HTTP_401_UNAUTHORIZED,
                        {
                            "description": "Authorization header must be 'Bearer <token>'"
                        },
                    )

                token = auth_parts[1]
                logger.debug("Extracted JWT token", token_length=len(token))
                auth_data = await handle_jwt_auth(request, db, redis_client, token)
                logger.debug(
                    "JWT auth completed",
                    has_auth_data=bool(auth_data),
                    auth_data_keys=(
                        list(asdict(auth_data).keys()) if auth_data else None
                    ),
                )

            # Set request state from auth data
            if auth_data:
                logger.debug("Setting request state from auth data")

                # Set request state with consistent structure
                request.state.api_key = auth_data.api_key
                request.state.organization = auth_data.organization
                request.state.user = auth_data.user

                logger.debug(
                    "Request state set",
                    user_id=request.state.user.id,
                    has_user=bool(request.state.user),
                    has_api_key=bool(request.state.api_key),
                    organization_id=request.state.organization.id,
                )
            else:
                logger.debug("No auth data received from handlers")
                raise GeoInferException(
                    MessageCode.AUTH_REQUIRED,
                    status.HTTP_401_UNAUTHORIZED,
                    {
                        "description": "Authentication failed - no valid authentication data"
                    },
                )

        except GeoInferException as e:
            logger.debug(
                "GeoInferException during auth",
                message_code=e.message_code,
                status_code=e.status_code,
                details=e.details,
            )
            raise  # Re-raise our custom exceptions
        except Exception as e:
            logger.error(
                "Unexpected authentication error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise GeoInferException(
                MessageCode.AUTH_REQUIRED,
                status.HTTP_401_UNAUTHORIZED,
                {"description": "Authentication failed"},
            )

    logger.debug("Auth middleware completed successfully, proceeding to endpoint")
    response = await call_next(request)
    logger.debug("Request completed", status_code=response.status_code)
    return response
