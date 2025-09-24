# GeoInfer API Test Structure

This document describes the improved test structure for the GeoInfer API, which now mirrors the `src/` directory structure and includes powerful factory-based test data generation.

## Directory Structure

The test structure is organized with unit tests in the `unit/` directory that mirrors the source code structure:

```
tests/
├── conftest.py                 # Global test configuration and fixtures
├── factories/                  # SQLAlchemy model factories
│   ├── __init__.py
│   ├── base.py                # Base factory classes
│   ├── users.py               # User model factory
│   ├── organizations.py       # Organization model factory
│   ├── api_keys.py            # API key factory
│   ├── invitations.py         # Invitation factory
│   ├── predictions.py         # Prediction factory
│   ├── credit_grants.py       # Credit grant factory
│   ├── subscriptions.py       # Subscription and TopUp factories
│   ├── roles.py               # User organization role factory
│   └── usage.py               # Usage record factory
├── unit/                      # Unit tests organized by source structure
│   ├── conftest.py            # Unit test specific fixtures
│   ├── api/                   # API endpoint tests (mirrors src/api/)
│   │   ├── analytics/
│   │   ├── billing/
│   │   ├── core/
│   │   ├── credits/
│   │   ├── health/
│   │   ├── invitation/
│   │   ├── keys/
│   │   ├── organization/
│   │   ├── prediction/
│   │   ├── role/
│   │   ├── stripe/
│   │   ├── support/
│   │   └── user/
│   ├── modules/               # Business logic tests (mirrors src/modules/)
│   │   ├── analytics/
│   │   ├── billing/
│   │   ├── health/
│   │   ├── keys/
│   │   ├── organization/
│   │   ├── prediction/
│   │   └── user/
│   ├── services/              # Service layer tests (mirrors src/services/)
│   │   └── auth/
│   ├── utils/                 # Utility tests (mirrors src/utils/)
│   │   └── settings/
│   ├── database/              # Database-specific tests
│   ├── cache/                 # Cache-related tests
│   └── core/                  # Core functionality tests
└── integration/               # Integration tests
```

## Key Improvements

### 1. Factory-Based Test Data

We now use `factory-boy` to create test data. This provides:

- **Consistent test data**: Factories generate realistic, consistent data
- **Easy customization**: Override specific fields as needed
- **Relationship handling**: Automatically handles foreign key relationships
- **Batch creation**: Create multiple related objects efficiently

### 2. Enhanced Fixtures

The new `conftest.py` provides several types of fixtures:

#### Database Fixtures
- `db_session`: Isolated database session for each test
- `async_engine`: SQLite in-memory database engine

#### User Fixtures
- `test_user`: Basic user with organization
- `test_admin_user`: User with admin role
- `test_member_user`: User with member role
- `test_api_key`: API key for authentication

#### HTTP Client Fixtures
- `public_client`: Unauthenticated HTTP client
- `authorized_client`: Client with user JWT token
- `admin_client`: Client with admin JWT token
- `member_client`: Client with member JWT token
- `api_key_client`: Client with API key authentication

#### Factory Fixtures
- `user_factory`: Factory for creating users
- `organization_factory`: Factory for creating organizations
- `create_user_factory`: Helper for creating users with roles
- `client_factory`: Helper for creating clients for specific users

## Usage Examples

### Basic Factory Usage

```python
@pytest.mark.asyncio
async def test_create_user(db_session: AsyncSession, user_factory):
    """Create a user using the factory."""
    user = await user_factory.create_async(
        db_session,
        name="John Doe",
        email="john@example.com"
    )
    assert user.name == "John Doe"
```

### Creating Related Objects

```python
@pytest.mark.asyncio
async def test_user_with_organization(
    db_session: AsyncSession, 
    user_factory, 
    organization_factory
):
    """Create user with specific organization."""
    org = await organization_factory.create_async(
        db_session,
        name="Test Company",
        plan_tier=PlanTier.SUBSCRIBED
    )
    
    user = await user_factory.create_async(
        db_session,
        organization_id=org.id,
        email="user@testcompany.com"
    )
    
    assert user.organization_id == org.id
```

### Using Different Client Types

```python
@pytest.mark.asyncio
async def test_admin_endpoint(admin_client: AsyncClient):
    """Test endpoint that requires admin access."""
    response = await admin_client.get("/api/v1/admin/users")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_member_endpoint(member_client: AsyncClient):
    """Test endpoint accessible to members."""
    response = await member_client.get("/api/v1/user/profile")
    assert response.status_code == 200
```

### Testing User Flows

```python
@pytest.mark.asyncio
async def test_invitation_flow(
    admin_client: AsyncClient,
    create_user_factory,
    client_factory
):
    """Test inviting and accepting user invitation."""
    # Admin sends invitation
    response = await admin_client.post("/api/v1/invitations", json={
        "email": "newuser@company.com",
        "role": "member"
    })
    
    # Later, create user and test their access
    new_user = await create_user_factory(
        email="newuser@company.com",
        role=OrganizationRole.MEMBER
    )
    
    user_client = await client_factory(new_user)
    profile_response = await user_client.get("/api/v1/user/profile")
    assert profile_response.status_code == 200
```

### Batch Creation

```python
@pytest.mark.asyncio
async def test_multiple_users(db_session: AsyncSession, user_factory):
    """Create multiple users at once."""
    users = await user_factory.create_batch_async(
        db_session,
        5,  # Create 5 users
        organization_id=some_org_id
    )
    
    assert len(users) == 5
    assert all(user.organization_id == some_org_id for user in users)
```

## Database Testing

The test setup now uses SQLite in-memory databases instead of testcontainers:

- **Faster**: No Docker overhead
- **Isolated**: Each test gets a fresh database
- **Simpler**: No external dependencies
- **Reliable**: Consistent across different environments

## Running Tests

Tests can be run in several ways:

```bash
# Run all tests
just test

# Run specific module tests
just test tests/unit/api/user/

# Run specific test
just test tests/unit/api/user/test_user_endpoints.py::test_get_user_profile

# Run with coverage
just test-cov
```

## Best Practices

1. **Use factories**: Prefer factories over manual object creation
2. **Use appropriate fixtures**: Choose the right client type for your test
3. **Test permissions**: Use different user roles to test authorization
4. **Isolate tests**: Each test should be independent
5. **Clear test names**: Use descriptive test method names
6. **Group related tests**: Use test classes to group related functionality

## Migration from Old Structure

If you have existing tests in the old structure:

1. Move test files to match the new directory structure
2. Update imports to use the new factories
3. Replace manual object creation with factory usage
4. Use the new client fixtures instead of creating clients manually
5. Update any hardcoded test data to use factories

This new structure provides a more maintainable, scalable, and powerful testing framework for the GeoInfer API.
