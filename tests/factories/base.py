"""Base factory for async SQLAlchemy models."""

from typing import Any, TypeVar, Generic
from uuid import uuid4

import factory
from sqlalchemy.ext.asyncio import AsyncSession


T = TypeVar("T")


class AsyncSQLAlchemyModelFactory(factory.Factory, Generic[T]):
    """Base factory for async SQLAlchemy models."""

    class Meta:
        abstract = True

    _session: AsyncSession | None = None

    @classmethod
    def _create(cls, model_class: type[T], *args: Any, **kwargs: Any) -> T:
        """Create model instance without persisting to database."""
        return model_class(**kwargs)

    @classmethod
    async def create_async(cls, session: AsyncSession, **kwargs: Any) -> T:
        """Create and persist model instance to database."""
        instance = cls._create(cls._meta.model, **kwargs)
        session.add(instance)
        await session.flush()
        return instance

    @classmethod
    async def create_batch_async(
        cls, session: AsyncSession, size: int, **kwargs: Any
    ) -> list[T]:
        """Create and persist multiple model instances to database."""
        instances = []
        for _ in range(size):
            instance = cls._create(cls._meta.model, **kwargs)
            session.add(instance)
            instances.append(instance)
        await session.flush()
        return instances


class UUIDFactory(factory.LazyFunction):
    """Factory for generating UUIDs."""

    def __init__(self) -> None:
        super().__init__(uuid4)
