"""API Key model."""

import uuid
from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.api.core.constants import GEO_API_KEY_PREFIX
from src.utils.hashing import HashingService
from .base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="api_keys")

    @classmethod
    def create_key(cls, name: str, user_id: UUID) -> tuple["ApiKey", str]:
        """Create a new API key and return the model instance and plain key."""
        # Generate a secure random key
        plain_key = f"{GEO_API_KEY_PREFIX}{token_urlsafe(32)}"

        key_hash = HashingService.hash_api_key(plain_key)

        api_key = cls(
            name=name,
            key_hash=key_hash,
            user_id=user_id,
        )

        return api_key, plain_key

    @staticmethod
    def verify_key(plain_key: str, stored_hash: str) -> bool:
        """Verify a plain key against stored hash using secure verification."""
        return HashingService.verify_api_key(plain_key, stored_hash)
