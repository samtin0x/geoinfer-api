from fastapi import APIRouter

from src.api.analytics.router import router as analytics_router
from src.api.billing.router import router as billing_router
from src.api.email.router import router as email_router
from src.api.health.router import router as health_router, root_router
from src.api.credits.router import router as credits_router
from src.api.invitation.router import router as invitation_router
from src.api.keys.router import router as keys_router
from src.api.organization.router import router as organization_router
from src.api.prediction.router import router as prediction_router
from src.api.role.router import router as role_router
from src.api.stripe.router import router as stripe_router
from src.api.support.router import router as support_router
from src.api.user.router import router as user_router

# V1 API router
v1_router = APIRouter(prefix="/v1")

# Include domain routers
v1_router.include_router(analytics_router)
v1_router.include_router(billing_router)
v1_router.include_router(credits_router)
v1_router.include_router(email_router)
v1_router.include_router(invitation_router)
v1_router.include_router(organization_router)
v1_router.include_router(keys_router)
v1_router.include_router(prediction_router)
v1_router.include_router(role_router)
v1_router.include_router(support_router)
v1_router.include_router(user_router)

# Main API router
api_router = APIRouter()
api_router.include_router(root_router)
api_router.include_router(health_router)
api_router.include_router(stripe_router)
api_router.include_router(v1_router)
