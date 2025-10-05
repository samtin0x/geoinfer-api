"""Database models for GeoInfer API."""

from .alerts import Alert, AlertSettings
from .api_keys import ApiKey
from .base import Base
from .credit_grants import CreditGrant, GrantType
from .invitations import Invitation, InvitationStatus
from .organizations import (
    Organization,
    OrganizationPermission,
    OrganizationRole,
    PlanTier,
)
from .predictions import Prediction
from .shared import SharedPrediction
from .feedback import PredictionFeedback, FeedbackType
from .roles import UserOrganizationRole
from .subscriptions import TopUp, Subscription, SubscriptionStatus, UsagePeriod
from .usage import OperationType, UsageRecord, UsageType
from .users import User

# Export all models and enums
__all__ = [
    # Base
    "Base",
    # Enums
    "PlanTier",
    "UsageType",
    "SubscriptionStatus",
    "InvitationStatus",
    "OrganizationRole",
    "OrganizationPermission",
    "GrantType",
    "OperationType",
    # Models
    "User",
    "Organization",
    "ApiKey",
    "UsageRecord",
    "Subscription",
    "TopUp",
    "UsagePeriod",
    "AlertSettings",
    "Alert",
    "Invitation",
    "UserOrganizationRole",
    "Prediction",
    "SharedPrediction",
    "PredictionFeedback",
    "FeedbackType",
    "CreditGrant",
]
