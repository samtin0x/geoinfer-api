"""Usage tracking models."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UsageType(str, Enum):
    GEOINFER_GLOBAL_0_0_1 = "geoinfer_global_0_0_1"


class OperationType(str, Enum):
    CONSUMPTION = "consumed"
    GRANT = "granted"


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=True
    )
    credits_consumed: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_type: Mapped[UsageType] = mapped_column(
        String, nullable=False, default=UsageType.GEOINFER_GLOBAL_0_0_1
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    subscription_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=True
    )
    topup_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=True
    )
    operation_type: Mapped[OperationType] = mapped_column(
        String, nullable=False, default=OperationType.CONSUMPTION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
