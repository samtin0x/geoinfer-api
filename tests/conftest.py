import os
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from uuid import uuid4
from typing import Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from testcontainers.postgres import PostgresContainer


from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from uuid import UUID

from src.database.models import Base, User, Organization
from src.database.models import PlanTier
from src.api.core.constants import JWT_ALGORITHM
from src.utils.settings.auth import AuthSettings


# Test Data Factories
def create_test_user(user_id: UUID = None, email: str = "test@example.com") -> User:
    """Factory to create test user objects."""
    return User(
        id=user_id or uuid4(),
        email=email,
        name="Test User",
        organization_id=uuid4(),  # Will be overridden by fixture
        avatar_url=None,
        locale="en",
    )


def create_test_organization(
    org_id: UUID = None, plan_tier: PlanTier = PlanTier.FREE
) -> Organization:
    """Factory to create test organization objects."""
    return Organization(
        id=org_id or uuid4(),
        name="Test Organization",
        logo_url=None,
        plan_tier=plan_tier,
    )


@pytest.fixture(autouse=True)
def disable_external_cache(monkeypatch):
    """Stub cache helpers so tests do not require Redis."""

    async def _noop_get_cache(*_args, **_kwargs):
        return None

    async def _noop_set_cache(*_args, **_kwargs):
        return True

    async def _noop_invalidate(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.cache.decorator._get_cache", _noop_get_cache)
    monkeypatch.setattr("src.cache.decorator._set_cache", _noop_set_cache)
    monkeypatch.setattr(
        "src.cache.decorator._invalidate_cache_pattern", _noop_invalidate
    )


@contextmanager
def _postgres_container() -> Generator[str, None, None]:
    """Yield a PostgreSQL connection URL using testcontainers or env override."""
    existing_url = os.getenv("TEST_DATABASE_URL")
    if existing_url:
        yield existing_url
        return

    image = os.getenv("TEST_POSTGRES_IMAGE", "postgres:17-alpine")
    with PostgresContainer(image) as container:
        container.start()
        yield container.get_connection_url()


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """Provision a postgres-backed async engine for tests."""
    with _postgres_container() as sync_url:
        url = make_url(sync_url)
        async_url = url.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        )
        engine = create_async_engine(async_url, echo=False, future=True)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Match metadata change to allow deferred organization assignment
            await conn.execute(
                text("ALTER TABLE users ALTER COLUMN organization_id DROP NOT NULL")
            )

        yield engine

        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session wrapped in a rollback to isolate tests."""
    async_session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async with async_session_factory() as session:
        try:
            yield session
        finally:
            # Rollback any uncommitted changes to isolate tests
            await session.rollback()


@pytest.fixture()
def sample_user_id() -> str:
    """Generate a sample UUID string for test users."""
    return str(uuid4())


# Factory fixtures that create objects without committing
@pytest_asyncio.fixture
async def test_organization_factory():
    """Factory to create test organizations without committing."""

    def create_org():
        org = create_test_organization()
        return org

    return create_org


@pytest_asyncio.fixture
async def test_user_factory(test_organization_factory):
    """Factory to create test users without committing."""

    def create_user(organization_id=None):
        if organization_id is None:
            org = test_organization_factory()
            organization_id = org.id

        user = create_test_user()
        user.organization_id = organization_id
        return user

    return create_user


@pytest_asyncio.fixture
async def app():
    """Create FastAPI application with lifespan manager for testing."""
    from src.main import app

    async with LifespanManager(app):
        yield app


@pytest.fixture()
def jwt_token_factory() -> Callable[[str, str], str]:
    """Factory for creating JWT tokens for test users."""
    auth_settings = AuthSettings()

    def create_token(user_id: str, email: str, name: str = "Test User") -> str:
        """Create a JWT token for testing."""
        payload = {
            "sub": user_id,
            "email": email,
            "role": "authenticated",
            "aud": "authenticated",
            "user_metadata": {
                "full_name": name,
                "name": name,
                "email_verified": True,
                "phone_verified": False,
            },
            "app_metadata": {"provider": "email", "providers": ["email"]},
            "is_anonymous": False,
        }

        # Use the same JWT secret as configured in the app, with fallback for tests
        jwt_secret = (
            auth_settings.SUPABASE_JWT_SECRET or "test-jwt-secret-key-for-testing-only"
        )
        token = jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)
        return token

    return create_token


@pytest_asyncio.fixture
async def test_user(test_organization_factory):
    """Create a test user for testing."""
    org = test_organization_factory()
    user = create_test_user()
    user.organization_id = org.id
    return user


@pytest.fixture
def user_token(test_user: User, jwt_token_factory: Callable[[str, str], str]) -> str:
    """Create a JWT token for the test user."""
    return jwt_token_factory(str(test_user.id), test_user.email, test_user.name)


@pytest_asyncio.fixture
async def public_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client for testing FastAPI endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def authorized_client(
    app: FastAPI, user_token: str
) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client with JWT authorization headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"Authorization": f"Bearer {user_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def api_key_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client with API key authorization headers."""
    # Create a test API key
    test_api_key = f"geo_test_{uuid4().hex[:32]}"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"X-GeoInfer-Key": test_api_key},
    ) as ac:
        yield ac
