API_VERSION_HEADER = "X-GeoInfer-Version"

# API Key Configuration
GEO_API_KEY_PREFIX = "geo_"
API_KEY_HEADER = "X-GeoInfer-Key"

# JWT Configuration
JWT_ALGORITHM = "HS256"

# Rate limiting settings (daily/hourly limits)
PRODUCTION_PREDICT_RATE_LIMIT = 30  # requests per minute
PRODUCTION_PREDICT_WINDOW_SECONDS = 60  # 1 minute

PUBLIC_TRIAL_FREE_PREDICTIONS = 3  # requests per day for public trial endpoints
PUBLIC_TRIAL_FREE_PREDICTIONS_WINDOW_SECONDS = 86400  # 24 hours

# Token costs
GLOBAL_MODEL_CREDIT_COST = 1

# credits granted to new trial users during onboarding
FREE_TRIAL_SIGNUP_CREDIT_AMOUNT = 15
TRIAL_CREDIT_EXPIRY_DAYS = 15

SHOULD_SEND_WELCOME_EMAIL = True

# Prediction parameters
MIN_TOP_K = 1
MAX_TOP_K = 10
DEFAULT_TOP_K = 5

PREDICTION_DATA_TYPES = [
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/octet-stream",  # Some HEIC files are sent as this
]

HEIC_HEIF_EXTENSIONS = (".heic", ".heif")

# Authentication endpoints configuration
SKIP_AUTH_PATHS = {
    "/openapi.json",
    "/docs",
    "/redoc",
    "/health",
    "/health/liveness",
    "/",
    "/stripe/webhook",
    "/v1/prediction/trial",
    "/v1/billing/catalog",
}

SKIP_AUTH_PATTERNS: list = [
    (
        "GET",
        r"^/v1/prediction/[a-fA-F0-9-]+/share$",
    ),  # GET shared prediction (public viewing)
]

API_KEY_ALLOWED_ENDPOINTS = {
    "/v1/prediction/predict",
}

# Pagination
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 30


class RateLimitKeys:
    """Typed rate limiting cache key generators."""

    @staticmethod
    def prediction_api_key(api_key_id: str) -> str:
        """Generate rate limit key for API key prediction requests."""
        return f"rate_limit:prediction:api_key:{api_key_id}"

    @staticmethod
    def prediction_user(user_id: str) -> str:
        """Generate rate limit key for user prediction requests."""
        return f"rate_limit:prediction:user:{user_id}"

    @staticmethod
    def prediction_ip(ip_address: str) -> str:
        """Generate rate limit key for IP-based prediction requests."""
        return f"rate_limit:prediction:ip:{ip_address}"

    @staticmethod
    def trial_ip(ip_address: str) -> str:
        """Generate rate limit key for IP-based trial requests."""
        return f"rate_limit:trial:ip:{ip_address}"
