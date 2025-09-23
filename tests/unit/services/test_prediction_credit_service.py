"""Tests for the PredictionCreditService consume_credits functionality."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy import select
from src.services.prediction.credits import PredictionCreditService
from src.database.models import (
    CreditGrant,
    GrantType,
    TopUp,
    Organization,
    Subscription,
    SubscriptionStatus,
    UsageRecord,
)


@pytest.mark.asyncio
async def test_subscription_priority_in_credit_grants(db_session):
    """Test that subscription grants are prioritized over top-up grants."""
    # Create test organization and grants
    org_id = uuid4()

    # Create a subscription grant (older) and a top-up grant (newer)
    subscription_grant = CreditGrant(
        id=uuid4(),
        organization_id=org_id,
        grant_type=GrantType.SUBSCRIPTION,
        description="Subscription Credits",
        amount=10,
        remaining_amount=10,
        created_at=datetime.now(timezone.utc) - timedelta(days=5),  # Older
    )

    topup_grant = CreditGrant(
        id=uuid4(),
        organization_id=org_id,
        grant_type=GrantType.TOPUP,
        description="Top-up Credits",
        amount=5,
        remaining_amount=5,
        created_at=datetime.now(timezone.utc),  # Newer
    )

    db_session.add_all([subscription_grant, topup_grant])
    await db_session.commit()

    # Create service and test the grant ordering
    credit_service = PredictionCreditService(db_session)

    # Test consuming 3 credits - should only use subscription grant
    used_grant_ids = await credit_service._update_credit_grants(org_id, 3)

    # Refresh from database
    await db_session.refresh(subscription_grant)
    await db_session.refresh(topup_grant)

    # Verify subscription grant was used (7 remaining), top-up untouched (5 remaining)
    assert subscription_grant.remaining_amount == 7
    assert topup_grant.remaining_amount == 5
    assert len(used_grant_ids) == 1
    assert used_grant_ids[0] == subscription_grant.id

    # Test consuming more credits - should finish subscription and start on top-up
    used_grant_ids = await credit_service._update_credit_grants(
        org_id, 10
    )  # 7 remaining from subscription + 3 more

    # Refresh from database
    await db_session.refresh(subscription_grant)
    await db_session.refresh(topup_grant)

    # Verify subscription is fully consumed (0 remaining), top-up partially consumed (2 remaining)
    assert subscription_grant.remaining_amount == 0
    assert topup_grant.remaining_amount == 2
    assert len(used_grant_ids) == 2
    assert subscription_grant.id in used_grant_ids
    assert topup_grant.id in used_grant_ids


@pytest.fixture
async def active_subscription(db_session, test_organization):
    """Create an active subscription with specified credits remaining."""
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        id=uuid4(),
        organization_id=test_organization.id,
        plan_tier="subscribed",
        status=SubscriptionStatus.ACTIVE,
        monthly_allowance=10,
        price_paid=29.99,
        current_period_start=now - timedelta(days=15),
        current_period_end=now + timedelta(days=15),
        created_at=now,
        updated_at=now,
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
async def inactive_subscription(db_session, test_organization):
    """Create an inactive subscription."""
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        id=uuid4(),
        organization_id=test_organization.id,
        plan_tier="subscribed",
        status=SubscriptionStatus.INACTIVE,
        monthly_allowance=10,
        price_paid=29.99,
        current_period_start=now - timedelta(days=30),
        current_period_end=now - timedelta(days=15),
        created_at=now - timedelta(days=30),
        updated_at=now - timedelta(days=30),
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
async def expired_subscription(db_session, test_organization):
    """Create an expired subscription."""
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        id=uuid4(),
        organization_id=test_organization.id,
        plan_tier="subscribed",
        status=SubscriptionStatus.ACTIVE,
        monthly_allowance=10,
        price_paid=29.99,
        current_period_start=now - timedelta(days=60),
        current_period_end=now - timedelta(days=30),
        created_at=now - timedelta(days=60),
        updated_at=now - timedelta(days=60),
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
async def partially_used_subscription(db_session, test_organization):
    """Create a subscription with some credits already used."""
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        id=uuid4(),
        organization_id=test_organization.id,
        plan_tier="subscribed",
        status=SubscriptionStatus.ACTIVE,
        monthly_allowance=10,
        price_paid=29.99,
        current_period_start=now - timedelta(days=15),
        current_period_end=now + timedelta(days=15),
        created_at=now,
        updated_at=now,
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
async def credit_package(db_session, test_organization):
    """Create a credit package (top-up) with specified credits."""
    package = TopUp(
        id=uuid4(),
        organization_id=test_organization.id,
        credits_purchased=5,
        price_paid=10.0,
        expires_at=None,  # Never expires
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)
    return package


@pytest.fixture
async def expired_credit_package(db_session, test_organization):
    """Create an expired credit package."""
    past_date = datetime.now(timezone.utc) - timedelta(days=30)
    package = TopUp(
        id=uuid4(),
        organization_id=test_organization.id,
        credits_purchased=5,
        price_paid=10.0,
        expires_at=past_date,  # Expired
        created_at=past_date,
    )
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)
    return package


@pytest.fixture
async def partially_used_credit_package(db_session, test_organization):
    """Create a credit package with some credits already used."""
    package = TopUp(
        id=uuid4(),
        organization_id=test_organization.id,
        credits_purchased=5,
        price_paid=10.0,
        expires_at=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(package)
    await db_session.commit()
    await db_session.refresh(package)
    return package


class TestConsumeCredits:
    """Test cases for the consume_credits method."""

    @pytest.mark.asyncio
    async def test_consume_credits_success_mixed_sources(
        self, db_session, test_organization, active_subscription, credit_package
    ):
        """Test consuming 2 credits with 1 from subscription and 1 from top-up."""
        # Verify initial state: 10 subscription credits + 5 top-up credits = 15 total
        credit_service = PredictionCreditService(db_session)
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        initial_balance = subscription_credits + top_up_credits
        assert initial_balance == 15

        # Consume 2 credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=2,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was updated (should have 8 credits remaining)
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package was updated (should have 4 credits remaining)
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

        # Verify usage record was created
        stmt = select(UsageRecord).where(
            UsageRecord.organization_id == test_organization.id
        )
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 1
        assert usage_records[0].credits_consumed == 2
        assert usage_records[0].subscription_id == active_subscription.id
        assert usage_records[0].topup_id == credit_package.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "credits_to_consume,expected_subscription_used,expected_topup_used",
        [
            # Test exact consumption from subscription
            (1, 1, 0),  # Only subscription
            (10, 10, 0),  # All subscription, none from top-up
            (12, 10, 2),  # All subscription + 2 from top-up
            (15, 10, 5),  # All subscription + all top-up
        ],
    )
    async def test_consume_credits_subscription_priority(
        self,
        db_session,
        test_organization,
        active_subscription,
        credit_package,
        credits_to_consume,
        expected_subscription_used,
        expected_topup_used,
    ):
        """Test that subscription credits are consumed before top-up credits."""
        credit_service = PredictionCreditService(db_session)

        # Consume credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=credits_to_consume,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription usage
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package usage
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_insufficient_credits(
        self, db_session, test_organization, active_subscription, credit_package
    ):
        """Test consuming more credits than available should fail."""
        credit_service = PredictionCreditService(db_session)

        # Try to consume more than available
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=20,  # More than 15 available
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify nothing was consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_subscription_only(
        self, db_session, test_organization, active_subscription
    ):
        """Test consuming credits when only subscription credits exist."""
        credit_service = PredictionCreditService(db_session)

        # Consume 3 credits from subscription only
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=3,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was updated
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify no usage records reference credit packages
        stmt = select(UsageRecord).where(
            UsageRecord.organization_id == test_organization.id
        )
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 1
        assert usage_records[0].subscription_id == active_subscription.id
        assert usage_records[0].topup_id is None

    @pytest.mark.asyncio
    async def test_consume_credits_topup_only(
        self, db_session, test_organization, credit_package
    ):
        """Test consuming credits when only top-up credits exist (no subscription)."""
        credit_service = PredictionCreditService(db_session)

        # Consume 2 credits from top-up only
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=2,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify credit package was updated
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

        # Verify usage record references credit package but no subscription
        stmt = select(UsageRecord).where(
            UsageRecord.organization_id == test_organization.id
        )
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 1
        assert usage_records[0].subscription_id is None
        assert usage_records[0].topup_id == credit_package.id

    @pytest.mark.asyncio
    async def test_consume_credits_expired_subscription_ignored(
        self, db_session, test_organization, expired_subscription, credit_package
    ):
        """Test that expired subscriptions are ignored in credit calculation."""
        credit_service = PredictionCreditService(db_session)

        # Verify only top-up credits are available (5), subscription should be ignored
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 5

        # Consume all available credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify expired subscription was not touched
        stmt = select(Subscription).where(Subscription.id == expired_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package was fully consumed
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_inactive_subscription_ignored(
        self, db_session, test_organization, inactive_subscription, credit_package
    ):
        """Test that inactive subscriptions are ignored in credit calculation."""
        credit_service = PredictionCreditService(db_session)

        # Verify only top-up credits are available (5), subscription should be ignored
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 5

        # Consume all available credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify inactive subscription was not touched
        stmt = select(Subscription).where(Subscription.id == inactive_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package was fully consumed
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_expired_topup_ignored(
        self, db_session, test_organization, active_subscription, expired_credit_package
    ):
        """Test that expired top-up credits are ignored in credit calculation."""
        credit_service = PredictionCreditService(db_session)

        # Verify only subscription credits are available (10), expired top-up ignored
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 10

        # Consume all available credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=10,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was fully consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify expired credit package was not touched
        stmt = select(TopUp).where(TopUp.id == expired_credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_partially_used_subscription(
        self, db_session, test_organization, partially_used_subscription, credit_package
    ):
        """Test consuming credits when subscription has some credits already used."""
        credit_service = PredictionCreditService(db_session)

        # Verify initial state: 5 subscription credits + 5 top-up credits = 10 total
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 10

        # Consume 3 credits (should use 3 from subscription, 0 from top-up)
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=3,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was updated (5 already used + 3 = 8 used, 2 remaining)
        stmt = select(Subscription).where(
            Subscription.id == partially_used_subscription.id
        )
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package was not touched
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_partially_used_topup(
        self,
        db_session,
        test_organization,
        active_subscription,
        partially_used_credit_package,
    ):
        """Test consuming credits when top-up has some credits already used."""
        credit_service = PredictionCreditService(db_session)

        # Verify initial state: 10 subscription credits + 2 top-up credits = 12 total
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 12

        # Consume 11 credits (should use all 10 subscription + 1 from top-up)
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=11,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was fully consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify credit package has 1 remaining
        stmt = select(TopUp).where(TopUp.id == partially_used_credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5

    @pytest.mark.asyncio
    async def test_consume_credits_multiple_topups(
        self, db_session, test_organization, active_subscription
    ):
        """Test consuming credits with multiple top-up packages."""
        # Create multiple credit packages
        package1 = TopUp(
            id=uuid4(),
            organization_id=test_organization.id,
            credits_purchased=3,
            price_paid=6.0,
            expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
        package2 = TopUp(
            id=uuid4(),
            organization_id=test_organization.id,
            credits_purchased=2,
            price_paid=4.0,
            expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add_all([package1, package2])
        await db_session.commit()

        credit_service = PredictionCreditService(db_session)

        # Verify initial state: 10 subscription + 3 + 2 = 15 total
        subscription_credits, top_up_credits = (
            await credit_service.get_organization_credits(test_organization.id)
        )
        balance = subscription_credits + top_up_credits
        assert balance == 15

        # Consume 12 credits (all subscription + 2 from top-ups)
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=12,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription fully consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify first package fully consumed
        stmt = select(TopUp).where(TopUp.id == package1.id)
        result = await db_session.execute(stmt)
        updated_package1 = result.scalar_one()
        assert updated_package1.credits_purchased == 3

        # Verify second package fully consumed
        stmt = select(TopUp).where(TopUp.id == package2.id)
        result = await db_session.execute(stmt)
        updated_package2 = result.scalar_one()
        assert updated_package2.credits_purchased == 2

    @pytest.mark.asyncio
    async def test_consume_credits_zero_credits(self, db_session, test_organization):
        """Test consuming zero credits should succeed."""
        credit_service = PredictionCreditService(db_session)

        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=0,
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify no usage records were created
        stmt = select(UsageRecord).where(
            UsageRecord.organization_id == test_organization.id
        )
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 0

    @pytest.mark.asyncio
    async def test_consume_credits_invalid_organization(self, db_session):
        """Test consuming credits with invalid organization should fail."""
        credit_service = PredictionCreditService(db_session)

        # Use a non-existent organization ID
        fake_org_id = uuid4()

        success = await credit_service.consume_credits(
            organization_id=fake_org_id,
            credits_to_consume=1,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify no usage records were created
        stmt = select(UsageRecord).where(UsageRecord.organization_id == fake_org_id)
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 0


class TestCreditAbusePatterns:
    """Test cases for potential abuse patterns in credit consumption."""

    @pytest.mark.asyncio
    async def test_concurrent_credit_consumption_race_condition(
        self, db_session, test_organization, active_subscription, credit_package
    ):
        """Test rapid concurrent credit consumption to detect race conditions."""
        credit_service = PredictionCreditService(db_session)

        # Consume all available credits first
        success1 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=10,  # All subscription credits
            user_id=None,
            api_key_id=None,
        )
        assert success1 is True

        # Try to consume more credits concurrently (should fail)
        success2 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=5,  # More than remaining top-up credits
            user_id=None,
            api_key_id=None,
        )
        assert success2 is False

        # Verify only 5 top-up credits were consumed, not 10
        stmt = select(TopUp).where(TopUp.id == credit_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 5  # All consumed

        # Verify no over-consumption occurred
        stmt = select(UsageRecord).where(
            UsageRecord.organization_id == test_organization.id
        )
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        total_consumed = sum(record.credits_consumed for record in usage_records)
        assert total_consumed == 15  # 10 subscription + 5 top-up

    @pytest.mark.asyncio
    async def test_credit_consumption_with_negative_amounts(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: attempting to consume negative credits."""
        credit_service = PredictionCreditService(db_session)

        # Attempt to consume negative credits (should fail)
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=-5,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify no credits were consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_with_extremely_large_amounts(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: attempting to consume extremely large credit amounts."""
        credit_service = PredictionCreditService(db_session)

        # Attempt to consume massive amount of credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=1_000_000,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify no credits were consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_with_manipulated_organization_id(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: using organization ID from another user's organization."""
        credit_service = PredictionCreditService(db_session)

        # Create another organization
        other_org = Organization(
            id=uuid4(),
            name="Other Organization",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(other_org)
        await db_session.commit()

        # Try to consume credits using the other organization's ID
        success = await credit_service.consume_credits(
            organization_id=other_org.id,  # Different org than subscription belongs to
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify original organization's credits were not affected
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_with_sql_injection_like_organization_id(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: organization ID with special characters."""
        credit_service = PredictionCreditService(db_session)

        # Try to consume credits with a malformed UUID-like string
        malformed_org_id = "00000000-0000-0000-0000-000000000000'--"

        success = await credit_service.consume_credits(
            organization_id=malformed_org_id,  # type: ignore
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )

        # Should fail gracefully without SQL injection
        assert success is False

        # Verify original organization's credits were not affected
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_timing_attack(
        self, db_session, test_organization, active_subscription, credit_package
    ):
        """Test timing attack: measuring response time differences."""
        credit_service = PredictionCreditService(db_session)
        import time

        # Test with sufficient credits - should be fast
        start_time = time.time()
        success1 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=2,
            user_id=None,
            api_key_id=None,
        )
        sufficient_time = time.time() - start_time
        assert success1 is True

        # Test with insufficient credits - should also be fast (no timing leak)
        start_time = time.time()
        success2 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=1000,  # More than available
            user_id=None,
            api_key_id=None,
        )
        insufficient_time = time.time() - start_time
        assert success2 is False

        # Response times should be similar (no timing attack vector)
        # Allow some tolerance for system variance
        assert (
            abs(sufficient_time - insufficient_time) < 0.1
        )  # Less than 100ms difference

    @pytest.mark.asyncio
    async def test_credit_consumption_with_suspended_organization(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: credit consumption from suspended organization."""
        # Simulate organization suspension by cancelling the subscription
        active_subscription.status = SubscriptionStatus.CANCELLED
        await db_session.commit()

        credit_service = PredictionCreditService(db_session)

        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify no credits were consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_with_stale_subscription_data(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: using stale subscription data."""
        credit_service = PredictionCreditService(db_session)

        # Consume some credits
        success1 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=5,
            user_id=None,
            api_key_id=None,
        )
        assert success1 is True

        # Try to consume more credits than remaining using stale knowledge
        success2 = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=10,  # More than remaining 5
            user_id=None,
            api_key_id=None,
        )
        assert success2 is False

        # Verify only 5 credits were consumed total
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_dos_attempt(
        self, db_session, test_organization, active_subscription
    ):
        """Test DoS pattern: rapid repeated credit consumption attempts."""
        credit_service = PredictionCreditService(db_session)
        import asyncio

        # Attempt multiple rapid consumptions
        tasks = []
        for i in range(10):
            task = credit_service.consume_credits(
                organization_id=test_organization.id,
                credits_to_consume=2,
                user_id=None,
                api_key_id=None,
            )
            tasks.append(task)

        # Execute all rapidly
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Should have mix of successes and failures, but no system crash
        success_count = sum(1 for r in results if r is True)
        failure_count = sum(1 for r in results if r is False)

        assert success_count > 0  # Some should succeed
        assert failure_count > 0  # Some should fail when credits are exhausted

        # Verify total consumption doesn't exceed available credits
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

    @pytest.mark.asyncio
    async def test_credit_consumption_with_empty_organization(self, db_session):
        """Test abuse pattern: credit consumption from organization with no subscriptions or top-ups."""
        # Create organization with no credits
        empty_org = Organization(
            id=uuid4(),
            name="Empty Organization",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(empty_org)
        await db_session.commit()

        credit_service = PredictionCreditService(db_session)

        # Try to consume credits from empty organization
        success = await credit_service.consume_credits(
            organization_id=empty_org.id,
            credits_to_consume=1,
            user_id=None,
            api_key_id=None,
        )

        assert success is False

        # Verify no usage records were created
        stmt = select(UsageRecord).where(UsageRecord.organization_id == empty_org.id)
        result = await db_session.execute(stmt)
        usage_records = result.scalars().all()
        assert len(usage_records) == 0

    @pytest.mark.asyncio
    async def test_credit_consumption_with_manipulated_credit_package(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: manipulating credit package data."""
        credit_service = PredictionCreditService(db_session)

        # Create a credit package with manipulated data
        manipulated_package = TopUp(
            id=uuid4(),
            organization_id=test_organization.id,
            credits_purchased=100,  # Large amount
            price_paid=1000.0,
            expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(manipulated_package)
        await db_session.commit()

        # Try to consume credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=50,  # Large amount
            user_id=None,
            api_key_id=None,
        )

        # Should succeed but be limited by subscription credits
        assert success is True

        # Verify subscription was fully consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify only subscription credits were consumed, not manipulated package
        stmt = select(TopUp).where(TopUp.id == manipulated_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert updated_package.credits_purchased == 500  # Unchanged

    @pytest.mark.asyncio
    async def test_credit_consumption_with_future_expiry_manipulation(
        self, db_session, test_organization, active_subscription
    ):
        """Test abuse pattern: manipulating credit package expiry to future date."""
        credit_service = PredictionCreditService(db_session)

        # Create a credit package that should be expired but manipulate expiry
        past_date = datetime.now(timezone.utc) - timedelta(days=60)
        future_date = datetime.now(timezone.utc) + timedelta(days=60)

        expired_package = TopUp(
            id=uuid4(),
            organization_id=test_organization.id,
            credits_purchased=5,
            price_paid=10.0,
            expires_at=future_date,  # Manipulated to future despite being "expired"
            created_at=past_date,
        )
        db_session.add(expired_package)
        await db_session.commit()

        # Try to consume credits
        success = await credit_service.consume_credits(
            organization_id=test_organization.id,
            credits_to_consume=12,  # 10 subscription + 2 from "expired" package
            user_id=None,
            api_key_id=None,
        )

        assert success is True

        # Verify subscription was fully consumed
        stmt = select(Subscription).where(Subscription.id == active_subscription.id)
        result = await db_session.execute(stmt)
        updated_subscription = result.scalar_one()
        assert updated_subscription.monthly_allowance == 10

        # Verify the "expired" package was not consumed (expiry check works)
        stmt = select(TopUp).where(TopUp.id == expired_package.id)
        result = await db_session.execute(stmt)
        updated_package = result.scalar_one()
        assert (
            updated_package.credits_purchased == 5
        )  # Unchanged, expiry check prevented use
