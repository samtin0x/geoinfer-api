"""API Key domain requests and responses."""

from pydantic import BaseModel, Field

from src.api.core.messages import APIResponse
from .models import KeyModel, KeyWithSecret


# Request Models
class KeyCreateRequest(BaseModel):
    """Request for creating an API key."""

    name: str = Field(..., min_length=1, max_length=100)


# Response Types (using generic APIResponse)
KeyCreateResponse = APIResponse[KeyWithSecret]
KeyListResponse = APIResponse[dict[str, list[KeyModel] | int]]
KeyDeleteResponse = APIResponse[dict[str, bool]]
