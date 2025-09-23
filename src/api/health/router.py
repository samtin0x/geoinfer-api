"""Health check endpoints for debugging and monitoring."""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from src.api.core.dependencies import AsyncSessionDep
from src.services.health.service import HealthService, OverallHealthStatus
from src.services.redis_service import get_redis_client
import redis.asyncio as redis
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Create separate routers for root and health endpoints
root_router = APIRouter()
router = APIRouter(prefix="/health", tags=["health"])


@root_router.get("/")
async def root():
    """Root endpoint with minimal HTML landing page."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GeoInfer API</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                min-height: 100vh;
                background: #f8f9fa;
                color: #1a1a1a;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                text-align: center;
                padding: 2rem;
            }

            .container {
                max-width: 600px;
                width: 100%;
            }

            .logo {
                font-size: 3rem;
                font-weight: bold;
                color: #1a1a1a;
                margin-bottom: 1rem;
                text-decoration: none;
                letter-spacing: -0.02em;
            }


            .links {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                width: 100%;
                max-width: 300px;
                margin: 0 auto;
            }

            .link {
                display: block;
                padding: 1rem 2rem;
                font-size: 1.1rem;
                text-decoration: none;
                border-radius: 0;
                transition: all 0.2s ease;
                font-weight: 500;
                border: none;
                cursor: pointer;
            }

            .link-primary {
                background: #1a1a1a;
                color: #ffffff;
            }

            .link-primary:hover {
                background: #333333;
                transform: translateY(-1px);
            }

            .link-secondary {
                background: #6c757d;
                color: #ffffff;
            }

            .link-secondary:hover {
                background: #5a6268;
                transform: translateY(-1px);
            }

            .footer {
                position: absolute;
                bottom: 2rem;
                color: #999;
                font-size: 0.9rem;
            }

            @media (max-width: 768px) {
                .logo {
                    font-size: 2.5rem;
                }

                .subtitle {
                    font-size: 1rem;
                    margin-bottom: 2rem;
                }

                .links {
                    max-width: 280px;
                }

                .link {
                    padding: 0.875rem 1.5rem;
                    font-size: 1rem;
                }
            }
        </style>
    </head>
    <body>
            <div class="container">
            <div class="logo">GeoInfer API</div>

            <div class="links">
                <a href="https://app.geoinfer.com" class="link link-primary">
                    Launch App
                </a>
                <a href="https://geoinfer.com" class="link link-secondary">
                    Visit Landing Page
                </a>
            </div>
        </div>

        <div class="footer">
            <span id="year">© 2025</span> GeoInfer. All rights reserved.
        </div>

        <script>
            // Update year automatically
            document.getElementById('year').textContent = '© ' + new Date().getFullYear();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, media_type="text/html")


@router.get("/")
async def health_check(
    db: AsyncSessionDep,
    redis: redis.Redis = Depends(get_redis_client),
) -> OverallHealthStatus:
    """Comprehensive health check for all services."""
    health_service = HealthService(db, redis)
    return await health_service.run_all_checks()


@router.get("/liveness")
async def liveness_check():
    """Simple liveness check - indicates if service is running."""
    return {"status": "alive", "service": "geoinfer-api"}
