"""Factory for Subscription and TopUp models."""

import factory
from src.database.models import Subscription, TopUp, SubscriptionStatus, GrantType
from .base import AsyncSQLAlchemyModelFactory, UUIDFactory
from .organizations import OrganizationFactory


class SubscriptionFactory(AsyncSQLAlchemyModelFactory[Subscription]):
    """Factory for creating Subscription instances."""

    class Meta:
        model = Subscription

    id = UUIDFactory()
    organization_id = factory.SubFactory(OrganizationFactory)
    stripe_subscription_id = factory.Faker("bothify", text="sub_??????????")
    stripe_customer_id = factory.Faker("bothify", text="cus_??????????")
    description = factory.Faker("sentence")
    price_paid = factory.Faker(
        "pydecimal", left_digits=3, right_digits=2, positive=True
    )
    monthly_allowance = factory.Faker("random_int", min=1000, max=100000)
    status = factory.Faker("enum", enum_cls=SubscriptionStatus)
    current_period_start = factory.Faker("past_datetime", start_date="-30d")
    current_period_end = factory.Faker("future_datetime", end_date="+30d")
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")


class TopUpFactory(AsyncSQLAlchemyModelFactory[TopUp]):
    """Factory for creating TopUp instances."""

    class Meta:
        model = TopUp

    id = UUIDFactory()
    organization_id = factory.SubFactory(OrganizationFactory)
    stripe_payment_intent_id = factory.Faker("bothify", text="pi_??????????")
    description = factory.Faker("sentence")
    price_paid = factory.Faker(
        "pydecimal", left_digits=3, right_digits=2, positive=True
    )
    credits_purchased = factory.Faker("random_int", min=100, max=10000)
    package_type = GrantType.TOPUP
    expires_at = factory.Faker("future_datetime", end_date="+365d")
    created_at = factory.Faker("date_time_this_year")
    updated_at = factory.Faker("date_time_this_year")
