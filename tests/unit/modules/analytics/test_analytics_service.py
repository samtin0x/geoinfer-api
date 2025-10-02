import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import select, and_

from src.analytics.service import AnalyticsService
from src.database.models import UsageRecord, User, Organization, UsageType


@pytest.mark.asyncio
async def test_get_usage_timeseries_daily_grouping(db_session):
    """Test daily grouping in usage timeseries works with PostgreSQL."""
    # Create test organization
    org = Organization(id=uuid4(), name="Test Organization", created_at=datetime.now())
    db_session.add(org)

    # Create test user
    user = User(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        organization_id=org.id,
        created_at=datetime.now(),
    )
    db_session.add(user)

    # Create usage records for different days
    now = datetime.now()
    usage_records = []

    for i in range(3):
        record_date = now - timedelta(days=i)
        record = UsageRecord(
            id=uuid4(),
            user_id=user.id,
            organization_id=org.id,
            credits_consumed=10 + i,
            usage_type=UsageType.GEOINFER_GLOBAL_0_0_1,
            created_at=record_date,
            api_key_id=None,
        )
        usage_records.append(record)
        db_session.add(record)

    await db_session.commit()

    # Test the analytics service
    service = AnalyticsService(db_session)
    result = await service.get_usage_timeseries(days=7, group_by="day")

    # Verify results
    assert len(result) == 3  # Should have 3 days of data
    assert all("period" in item for item in result)
    assert all("predictions" in item for item in result)
    assert all("credits_consumed" in item for item in result)
    assert all("unique_users" in item for item in result)

    # Verify data is sorted by period
    periods = [item["period"] for item in result]
    assert periods == sorted(periods)  # Should be sorted chronologically


@pytest.mark.asyncio
async def test_get_usage_timeseries_hourly_grouping(db_session):
    """Test hourly grouping in usage timeseries works with PostgreSQL."""
    # Create test organization and user
    org = Organization(id=uuid4(), name="Test Organization", created_at=datetime.now())
    db_session.add(org)

    user = User(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        organization_id=org.id,
        created_at=datetime.now(),
    )
    db_session.add(user)

    # Create usage records for the same day, different hours
    now = datetime.now()
    usage_records = []

    for i in range(3):
        record_time = now.replace(hour=9 + i, minute=0, second=0, microsecond=0)
        record = UsageRecord(
            id=uuid4(),
            user_id=user.id,
            organization_id=org.id,
            credits_consumed=5 + i,
            usage_type="geoinfer_global_0_0_1",
            created_at=record_time,
            api_key_id=None,
        )
        usage_records.append(record)
        db_session.add(record)

    await db_session.commit()

    # Test the analytics service with hourly grouping
    service = AnalyticsService(db_session)
    result = await service.get_usage_timeseries(days=1, group_by="hour")

    # Verify results
    assert len(result) == 3  # Should have 3 hours of data
    assert all("period" in item for item in result)
    assert all(
        "hour" in item["period"] for item in result
    )  # Should include hour format

    # Verify data is sorted by period
    periods = [item["period"] for item in result]
    assert periods == sorted(periods)  # Should be sorted chronologically


@pytest.mark.asyncio
async def test_get_usage_timeseries_weekly_grouping(db_session):
    """Test weekly grouping in usage timeseries works with PostgreSQL."""
    # Create test organization and user
    org = Organization(id=uuid4(), name="Test Organization", created_at=datetime.now())
    db_session.add(org)

    user = User(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        organization_id=org.id,
        created_at=datetime.now(),
    )
    db_session.add(user)

    # Create usage records for different weeks
    now = datetime.now()
    usage_records = []

    for i in range(2):
        # Create records for different weeks
        record_date = now - timedelta(weeks=i, days=1)
        record = UsageRecord(
            id=uuid4(),
            user_id=user.id,
            organization_id=org.id,
            credits_consumed=20 + i,
            usage_type="geoinfer_global_0_0_1",
            created_at=record_date,
            api_key_id=None,
        )
        usage_records.append(record)
        db_session.add(record)

    await db_session.commit()

    # Test the analytics service with weekly grouping
    service = AnalyticsService(db_session)
    result = await service.get_usage_timeseries(days=30, group_by="week")

    # Verify results
    assert len(result) >= 1  # Should have at least 1 week of data
    assert all("period" in item for item in result)

    # Verify data is sorted by period
    periods = [item["period"] for item in result]
    assert periods == sorted(periods)  # Should be sorted chronologically


@pytest.mark.asyncio
async def test_api_key_usage_excluded_from_user_analytics(db_session):
    """Test that API key usage is excluded from user analytics."""
    # Create test organization
    org = Organization(id=uuid4(), name="Test Organization", created_at=datetime.now())
    db_session.add(org)

    # Create test user
    user = User(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        organization_id=org.id,
        created_at=datetime.now(),
    )
    db_session.add(user)

    # Create API key
    from src.database.models.api_keys import ApiKey

    api_key = ApiKey.create_key("Service API Key", user.id)[0]
    db_session.add(api_key)

    await db_session.commit()

    # Create usage records - some user usage, some API key usage
    now = datetime.now()

    # User usage (should be counted)
    user_record = UsageRecord(
        id=uuid4(),
        user_id=user.id,
        organization_id=org.id,
        credits_consumed=10,
        usage_type="geoinfer_global_0_0_1",
        created_at=now - timedelta(days=1),
        api_key_id=None,
    )
    db_session.add(user_record)

    # API key usage (should be counted separately with API key name)
    api_key_record = UsageRecord(
        id=uuid4(),
        user_id=user.id,  # Still tracks the user who owns the API key
        organization_id=org.id,
        credits_consumed=20,
        usage_type="geoinfer_global_0_0_1",
        created_at=now - timedelta(days=1),
        api_key_id=api_key.id,  # This indicates API key usage
    )
    db_session.add(api_key_record)

    await db_session.commit()

    # Test the analytics service
    service = AnalyticsService(db_session)
    result = await service.get_organization_user_usage(
        org.id, days=7, limit=10, offset=0
    )

    # Verify both user usage and API key usage are included as separate entities
    assert len(result.items) == 2  # Should have user and API key records
    # Check if we have both user and API key usage
    user_usage = next((item for item in result.items if item.name == "Test User"), None)
    api_key_usage = next(
        (item for item in result.items if item.name == "Service API Key"), None
    )

    assert user_usage is not None, "User usage should be included"
    assert api_key_usage is not None, "API key usage should be included"
    assert user_usage.prediction_count == 1
    assert user_usage.credits_consumed == 10
    assert api_key_usage.prediction_count == 1
    assert api_key_usage.credits_consumed == 20


@pytest.mark.asyncio
async def test_cost_decorator_creates_correct_usage_records(db_session):
    """Test that the cost decorator creates usage records with correct user_id attribution."""
    from src.database.models.api_keys import ApiKey
    from src.modules.billing.credits import CreditConsumptionService

    # Create test organization and user
    org = Organization(id=uuid4(), name="Test Organization", created_at=datetime.now())
    db_session.add(org)

    user = User(
        id=uuid4(),
        name="Test User",
        email="test@example.com",
        organization_id=org.id,
        created_at=datetime.now(),
    )
    db_session.add(user)

    # Create API key for the user
    api_key = ApiKey.create_key("Test API Key", user.id)[0]
    db_session.add(api_key)

    await db_session.commit()

    # Test credit service
    credit_service = CreditConsumptionService(db_session)

    # Test user authentication creates usage record with user_id
    await credit_service.consume_credits(
        organization_id=org.id,
        credits_to_consume=5,
        user_id=user.id,
        api_key_id=None,
        usage_type="geoinfer_global_0_0_1",
    )

    # Test API key authentication creates usage record with user_id = None
    await credit_service.consume_credits(
        organization_id=org.id,
        credits_to_consume=10,
        user_id=None,
        api_key_id=api_key.id,
        usage_type="geoinfer_global_0_0_1",
    )

    await db_session.commit()

    # Verify usage records were created correctly

    # Check user usage record
    user_usage = await db_session.execute(
        select(UsageRecord).where(
            and_(UsageRecord.user_id == user.id, UsageRecord.api_key_id.is_(None))
        )
    )
    user_usage_record = user_usage.scalar_one_or_none()
    assert user_usage_record is not None, "User usage record should exist"
    assert user_usage_record.user_id == user.id, "User usage should have user_id set"
    assert (
        user_usage_record.api_key_id is None
    ), "User usage should have api_key_id = None"
    assert user_usage_record.credits_consumed == 5
    assert user_usage_record.usage_type == "geoinfer_global_0_0_1"

    # Check API key usage record
    api_key_usage = await db_session.execute(
        select(UsageRecord).where(
            and_(UsageRecord.api_key_id == api_key.id, UsageRecord.user_id.is_(None))
        )
    )
    api_key_usage_record = api_key_usage.scalar_one_or_none()
    assert api_key_usage_record is not None, "API key usage record should exist"
    assert (
        api_key_usage_record.user_id is None
    ), "API key usage should have user_id = None"
    assert (
        api_key_usage_record.api_key_id == api_key.id
    ), "API key usage should have api_key_id set"
    assert api_key_usage_record.credits_consumed == 10
    assert api_key_usage_record.usage_type == "geoinfer_global_0_0_1"

    # Test analytics service shows proper attribution
    service = AnalyticsService(db_session)
    result = await service.get_organization_user_usage(
        org.id, days=7, limit=10, offset=0
    )

    # Should have one user record and one API key record
    assert len(result.items) == 2

    # Find the records
    user_record = next(
        (item for item in result.items if item.user_id == str(user.id)), None
    )
    api_key_record = next(
        (item for item in result.items if item.name == "Test API Key"), None
    )

    assert user_record is not None, "User record should exist in analytics"
    assert api_key_record is not None, "API key record should exist in analytics"
    assert user_record.name == "Test User"
    assert api_key_record.name == "Test API Key"
