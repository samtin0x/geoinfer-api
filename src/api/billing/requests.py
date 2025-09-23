from src.api.billing.models import BillingProductsModel
from src.api.core.messages import APIResponse


BillingProductsResponse = APIResponse[BillingProductsModel]
