"""Usage tracking models."""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Integer, String, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelType(str, Enum):
    """Model types for tracking and pricing predictions."""

    GLOBAL = "global"
    ACCURACY = "accuracy"
    PROPERTY = "property"
    CARS = "cars"


class OperationType(str, Enum):
    CONSUMPTION = "consumed"
    GRANT = "granted"


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID | None] = mapped_column(UUID, nullable=True)
    credits_consumed: Mapped[int] = mapped_column(Integer, nullable=False)
    model_type: Mapped[ModelType] = mapped_column(
        String, nullable=False, default=ModelType.GLOBAL
    )
    model_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    api_key_id: Mapped[UUID | None] = mapped_column(UUID, nullable=True)
    organization_id: Mapped[UUID] = mapped_column(UUID, nullable=False)
    subscription_id: Mapped[UUID | None] = mapped_column(UUID, nullable=True)
    topup_id: Mapped[UUID | None] = mapped_column(UUID, nullable=True)
    operation_type: Mapped[OperationType] = mapped_column(
        String, nullable=False, default=OperationType.CONSUMPTION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
