import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.core.exceptions.base import register_exception_handlers
from src.api.core.middleware.auth import auth_middleware
from src.api.core.middleware.logging import logging_middleware
from src.api.core.middleware.security import (
    SecurityHeadersMiddleware,
    PayloadSizeMiddleware,
)
from src.api.router import api_router
from src.database.connection import AsyncSessionLocal
from src.utils.settings.app import AppSettings
from src.utils.logger import setup_logging


is_production = AppSettings().ENVIRONMENT.upper() == "PROD"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup

    logger = setup_logging(is_production)
    logger.info("Starting GeoInfer API...")

    # Add session factory to app state
    app.state.session_factory = AsyncSessionLocal
    logger.info("Database session factory added to app state")

    yield

    # Shutdown
    logger.info("Shutting down GeoInfer API...")


# Create app with production settings
app = FastAPI(
    title="GeoInfer API",
    description="GPS coordinate prediction from images using AI",
    version=AppSettings().API_VERSION,
    lifespan=lifespan,
    # Security: Disable docs in production
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)

# Register global exception handlers
register_exception_handlers(app)


# Configure CORS middleware with explicit settings
app_settings = AppSettings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware, is_production=is_production)
app.add_middleware(
    PayloadSizeMiddleware,
    max_request_size=AppSettings().MAX_REQUEST_SIZE,
    max_response_size=AppSettings().MAX_RESPONSE_SIZE,
)
app.middleware("http")(auth_middleware)
app.middleware("http")(logging_middleware)

app.include_router(api_router)


def run_dev_server():
    """Run development server with auto-reload."""
    uvicorn.run(
        "src.main:app", host="0.0.0.0", port=8010, reload=True, access_log=False
    )


def run_prod_server():
    """Run production server."""
    uvicorn.run(
        "src.main:app", host="0.0.0.0", port=8010, reload=False, access_log=False
    )
