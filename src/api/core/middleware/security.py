from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.settings.app import AppSettings
from src.api.core.exceptions.base import GeoInferException
from src.api.core.messages import MessageCode
from src.api.core.constants import API_VERSION_HEADER


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    def __init__(self, app, is_production: bool = False):
        super().__init__(app)
        self.is_production = is_production
        self.app_settings = AppSettings()

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Security headers (avoid CORS-related headers that conflict with CORSMiddleware)
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
        }

        # Skip CORP/COEP/COOP headers to avoid CORS conflicts in production
        # These can interfere with cross-origin requests from the frontend

        # Add CSP in production
        if self.is_production:
            headers["Content-Security-Policy"] = self._get_csp()

        # Add HSTS in production for HTTPS
        if self.is_production and request.url.scheme == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Add custom security headers
        headers.update(
            {
                API_VERSION_HEADER: self.app_settings.API_VERSION,
                "X-Permitted-Cross-Domain-Policies": "none",
            }
        )

        # Apply headers to response, but don't override CORS headers
        cors_headers = {
            "Access-Control-Allow-Origin",
            "Access-Control-Allow-Methods",
            "Access-Control-Allow-Headers",
            "Access-Control-Allow-Credentials",
            "Access-Control-Expose-Headers",
            "Access-Control-Max-Age",
        }

        for key, value in headers.items():
            # Don't override CORS headers that may have been set by CORSMiddleware
            if key not in response.headers and key not in cors_headers:
                response.headers[key] = value

        return response

    def _get_csp(self) -> str:
        """Generate Content Security Policy."""
        csp = {
            "default-src": ["'self'"],
            "script-src": ["'self'", "'unsafe-inline'", "https://js.stripe.com"],
            "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
            "font-src": ["'self'", "https://fonts.gstatic.com"],
            "img-src": ["'self'", "data:", "https:", "blob:"],
            "connect-src": [
                "'self'",
                "https://api.stripe.com",
                "https://js.stripe.com",
                "https://app.geoinfer.com",
                "https://geoinfer.com",
            ],
            "frame-src": ["https://js.stripe.com", "https://hooks.stripe.com"],
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
        }

        csp_parts = []
        for directive, sources in csp.items():
            csp_parts.append(f"{directive} {' '.join(sources)}")

        return "; ".join(csp_parts)


class PayloadSizeMiddleware(BaseHTTPMiddleware):
    """Enforce request and response size limits."""

    def __init__(
        self,
        app,
        max_request_size: int | None = None,
        max_response_size: int | None = None,
    ):
        super().__init__(app)
        # Use settings if not provided as parameters
        app_settings = AppSettings()
        self.max_request_size = max_request_size or app_settings.MAX_REQUEST_SIZE
        self.max_response_size = max_response_size or app_settings.MAX_RESPONSE_SIZE

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check request size
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > self.max_request_size:
            from src.utils.logger import get_logger

            logger = get_logger(__name__)
            logger.warning(
                f"Request too large: {content_length} bytes from {request.client.host if request.client else 'unknown'}"
            )

            raise GeoInferException(
                MessageCode.BAD_REQUEST,
                413,  # Request Entity Too Large
                details={
                    "description": f"Request size ({content_length} bytes) exceeds maximum allowed ({self.max_request_size} bytes)"
                },
            )

        # For responses, we would need to intercept the response stream
        # This is more complex and would require response streaming interception

        response = await call_next(request)
        return response


class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect HTTP to HTTPS in production."""

    def __init__(self, app, is_production: bool = False):
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            self.is_production
            and request.url.scheme == "http"
            and not request.url.path.startswith(
                "/health"
            )  # Allow health checks over HTTP
        ):
            https_url = request.url.replace(scheme="https")
            return Response(
                status_code=301,
                headers={"Location": str(https_url)},
            )

        return await call_next(request)
