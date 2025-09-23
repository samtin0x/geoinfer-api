import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from src.utils.settings.database import DatabaseSettings

logger = logging.getLogger(__name__)

sync_engine = create_engine(DatabaseSettings().DATABASE_URL, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

async_engine = create_async_engine(DatabaseSettings().DATABASE_URL_ASYNC, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


def get_sync_db() -> Session:
    """Get synchronous database session for migrations."""
    db = SyncSessionLocal()
    try:
        return db
    finally:
        db.close()


@asynccontextmanager
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Get asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session."""
    async with get_async_db() as session:
        yield session
