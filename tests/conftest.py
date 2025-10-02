"""Global test configuration and fixtures for GeoInfer API."""

import os
from collections.abc import AsyncGenerator
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy_utils import create_database, database_exists, drop_database

from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt

from src.database.models import (
    Base,
    User,
    Organization,
    ApiKey,
    Subscription,
    PlanTier,
    OrganizationRole,
)
from src.api.core.constants import JWT_ALGORITHM
from src.utils.settings.auth import AuthSettings

# Import all factories
from tests.factories import (
    UserFactory,
    OrganizationFactory,
    ApiKeyFactory,
    UserOrganizationRoleFactory,
    SubscriptionFactory,
)


@pytest.fixture
def user_factory():
    return UserFactory


@pytest.fixture
def organization_factory():
    return OrganizationFactory


@pytest.fixture
def subscription_factory():
    return SubscriptionFactory


@pytest.fixture
def api_key_factory():
    return ApiKeyFactory


@pytest.fixture
def role_factory():
    return UserOrganizationRoleFactory


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


@pytest.fixture(scope="session")
def worker_id(request):
    """Get pytest-xdist worker ID or 'main' for single process."""
    if hasattr(request.config, "workerinput"):
        return request.config.workerinput["workerid"]
    return "main"


@pytest.fixture(scope="session")
def test_database_uri(worker_id):
    """Create a test database per worker for parallel testing."""
    # Get base database URL from environment or default
    base_database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://geoinfer:geoinfer_dev_password@localhost:5433/geoinfer",
    )

    # Parse and create test database name
    parsed = urlparse(base_database_url)
    test_database_name = f"test_geoinfer_{worker_id}"
    test_database = parsed._replace(path=f"/{test_database_name}")

    # Create sync URL for database operations
    sync_dsn = test_database._replace(scheme="postgresql+psycopg2").geturl()
    async_dsn = test_database._replace(scheme="postgresql+asyncpg").geturl()

    # Drop existing test database if it exists
    if database_exists(sync_dsn):
        drop_database(sync_dsn)

    # Create new test database
    create_database(sync_dsn)

    # Create all tables using sync engine
    sync_engine = create_engine(sync_dsn)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    yield async_dsn

    # Clean up: drop test database with retry mechanism
    if database_exists(sync_dsn):
        try:
            drop_database(sync_dsn)
        except Exception as e:
            # If drop fails due to active connections, try to force disconnect and retry
            print(f"Warning: Failed to drop test database {test_database_name}: {e}")
            try:
                # Connect to postgres database to kill connections
                base_postgres_url = parsed._replace(path="/postgres")
                base_sync_dsn = base_postgres_url._replace(
                    scheme="postgresql+psycopg2"
                ).geturl()
                temp_engine = create_engine(base_sync_dsn)
                with temp_engine.connect() as conn:
                    # Terminate all connections to the test database
                    conn.execute(
                        text(
                            f"""
                        SELECT pg_terminate_backend(pid) 
                        FROM pg_stat_activity 
                        WHERE datname = '{test_database_name}' AND pid <> pg_backend_pid()
                    """
                        )
                    )
                    conn.commit()
                temp_engine.dispose()
                # Now try to drop again
                drop_database(sync_dsn)
            except Exception as e2:
                print(
                    f"Warning: Could not clean up test database {test_database_name}: {e2}"
                )


@pytest_asyncio.fixture
async def async_engine(test_database_uri):
    """Create async engine for the test database."""
    engine = create_async_engine(
        test_database_uri, echo=False, future=True, pool_pre_ping=True, pool_recycle=300
    )
    yield engine
    # Ensure all connections are properly closed
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session with proper transaction isolation."""
    # Create a connection and start a transaction
    connection = await async_engine.connect()
    transaction = await connection.begin()

    # Create a session bound to the connection
    async_session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    async with async_session_factory() as session:
        try:
            yield session
        finally:
            # Close the session first
            await session.close()
            # Rollback the transaction
            await transaction.rollback()
            # Close the connection
            await connection.close()


@pytest_asyncio.fixture
async def app():
    """Create FastAPI application with lifespan manager for testing."""
    from src.main import app

    async with LifespanManager(app):
        yield app


# Test Data Fixtures
@pytest_asyncio.fixture
async def test_organization(
    db_session: AsyncSession, organization_factory
) -> Organization:
    """Create a test organization."""
    from uuid import uuid4

    org = await organization_factory.create_async(
        db_session, id=uuid4(), name="Test Organization", plan_tier=PlanTier.FREE
    )
    return org


@pytest_asyncio.fixture
async def test_user(
    db_session: AsyncSession, user_factory, test_organization: Organization
) -> User:
    """Create a test user associated with test organization."""
    from uuid import uuid4

    user_uuid = uuid4()
    user = await user_factory.create_async(
        db_session,
        id=user_uuid,
        name="Test User",
        email=f"test-{user_uuid.hex[:8]}@example.com",  # Unique email per test
        organization_id=test_organization.id,
    )
    return user


@pytest_asyncio.fixture
async def test_subscription(
    db_session: AsyncSession,
    subscription_factory,
    test_organization: Organization,
) -> Subscription:
    """Create a test subscription for the test organization."""
    from datetime import datetime, timezone, timedelta

    subscription = await subscription_factory.create_async(
        db_session,
        organization_id=test_organization.id,
        status="active",
        monthly_allowance=1000,
        overage_enabled=False,
        price_paid=60.0,
        description="Test Subscription",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    return subscription


@pytest_asyncio.fixture
async def test_admin_user(
    db_session: AsyncSession,
    user_factory,
    role_factory,
    test_organization: Organization,
) -> User:
    """Create a test admin user with admin role."""
    from uuid import uuid4

    user_uuid = uuid4()
    user = await user_factory.create_async(
        db_session,
        id=user_uuid,
        name="Admin User",
        email=f"admin-{user_uuid.hex[:8]}@example.com",  # Unique email per test
        organization_id=test_organization.id,
    )

    # Assign admin role
    await role_factory.create_async(
        db_session,
        user_id=user.id,
        organization_id=test_organization.id,
        role=OrganizationRole.ADMIN,
        granted_by_id=user.id,  # Self-granted for test
    )

    return user


@pytest_asyncio.fixture
async def test_member_user(
    db_session: AsyncSession,
    user_factory,
    role_factory,
    test_organization: Organization,
    test_admin_user: User,
) -> User:
    """Create a test member user with member role."""
    from uuid import uuid4

    user_uuid = uuid4()
    user = await user_factory.create_async(
        db_session,
        id=user_uuid,
        name="Member User",
        email=f"member-{user_uuid.hex[:8]}@example.com",  # Unique email per test
        organization_id=test_organization.id,
    )

    # Assign member role
    await role_factory.create_async(
        db_session,
        user_id=user.id,
        organization_id=test_organization.id,
        role=OrganizationRole.MEMBER,
        granted_by_id=test_admin_user.id,
    )

    return user


@pytest_asyncio.fixture
async def test_api_key(db_session: AsyncSession, test_user: User) -> tuple[ApiKey, str]:
    """Create a test API key for the test user."""
    api_key, plain_key = ApiKey.create_key(
        "Test API Key", test_user.organization_id, test_user.id
    )
    db_session.add(api_key)
    await db_session.flush()
    return api_key, plain_key


# JWT Token Fixtures
@pytest.fixture()
def jwt_token_factory() -> Callable[[str, str, str], str]:
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
async def user_token(
    test_user: User, jwt_token_factory: Callable[[str, str, str], str]
) -> str:
    """Create a JWT token for the test user."""
    return jwt_token_factory(str(test_user.id), test_user.email, test_user.name)


@pytest_asyncio.fixture
async def admin_token(
    test_admin_user: User, jwt_token_factory: Callable[[str, str, str], str]
) -> str:
    """Create a JWT token for the admin user."""
    return jwt_token_factory(
        str(test_admin_user.id), test_admin_user.email, test_admin_user.name
    )


@pytest_asyncio.fixture
async def member_token(
    test_member_user: User, jwt_token_factory: Callable[[str, str, str], str]
) -> str:
    """Create a JWT token for the member user."""
    return jwt_token_factory(
        str(test_member_user.id), test_member_user.email, test_member_user.name
    )


# HTTP Client Fixtures
@pytest_asyncio.fixture
async def public_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client for testing public endpoints."""
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
async def admin_client(
    app: FastAPI, admin_token: str
) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client with admin JWT authorization headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def member_client(
    app: FastAPI, member_token: str
) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client with member JWT authorization headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"Authorization": f"Bearer {member_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def api_key_client(
    app: FastAPI, test_api_key: tuple[ApiKey, str]
) -> AsyncGenerator[AsyncClient, None]:
    """Create HTTP client with API key authorization headers."""
    _, plain_key = test_api_key

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test-geoinfer-api",
        headers={"X-GeoInfer-Key": plain_key},
    ) as ac:
        yield ac


# Helper fixtures for creating clients with different users
@pytest.fixture
def client_factory(app: FastAPI, jwt_token_factory):
    """Factory for creating HTTP clients with different user contexts."""

    async def create_client_for_user(user: User) -> AsyncClient:
        """Create an authorized client for a specific user."""
        token = jwt_token_factory(str(user.id), user.email, user.name)
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test-geoinfer-api",
            headers={"Authorization": f"Bearer {token}"},
        )

    return create_client_for_user


@pytest.fixture
def create_user_factory(
    db_session: AsyncSession, user_factory, test_organization: Organization
):
    """Factory for creating users with different configurations for testing flows."""

    async def create_user(
        email: str | None = None,
        name: str | None = None,
        organization: Organization | None = None,
        role: OrganizationRole | None = None,
    ) -> User:
        """Create a user with optional configuration."""
        user = await user_factory.create_async(
            db_session,
            id=uuid4(),
            email=email or f"user-{uuid4().hex[:8]}@example.com",
            name=name or f"Test User {uuid4().hex[:8]}",
            organization_id=(organization or test_organization).id,
        )

        if role:
            from tests.factories import UserOrganizationRoleFactory

            await UserOrganizationRoleFactory.create_async(
                db_session,
                user_id=user.id,
                organization_id=user.organization_id,
                role=role,
                granted_by_id=user.id,  # Self-granted for test
            )

        return user

    return create_user
