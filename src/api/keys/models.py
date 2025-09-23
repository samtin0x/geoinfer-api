"""API Key domain models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class KeyModel(BaseModel):
    """API key model."""

    id: UUID
    user_id: UUID
    name: str
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyWithSecret(KeyModel):
    """API key model with the actual key (only used during creation)."""

    key: str  # The actual API key - only returned once during creation
