"""Organization domain models."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class OrganizationModel(BaseModel):
    """Core organization model."""

    id: UUID
    name: str
    logo_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {datetime: lambda v: v.isoformat()}
