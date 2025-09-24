"""Keys API schemas (combined models/requests)."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from src.api.core.messages import APIResponse


class KeyModel(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyWithSecret(KeyModel):
    key: str


class KeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


KeyCreateResponse = APIResponse[KeyWithSecret]
KeyListResponse = APIResponse[dict[str, list[KeyModel] | int]]
KeyDeleteResponse = APIResponse[dict[str, bool]]
