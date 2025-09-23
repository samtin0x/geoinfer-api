"""Global exception handlers for the FastAPI application."""

import traceback

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..messages import MessageCode, get_default_message
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GeoInferException(Exception):
    """Base exception for GeoInfer API with unified message codes."""

    def __init__(
        self,
        message_code: MessageCode,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict | None = None,
        headers: dict | None = None,
    ):
        self.message_code = message_code
        self.status_code = status_code
        self.message: str = get_default_message(message_code)
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(self.message)

    def to_response_dict(self) -> dict:
        """Convert exception to API response format."""
        return {
            "message_code": self.message_code,
            "message": self.message,
            "details": self.details,
        }


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers with the FastAPI app."""

    @app.exception_handler(GeoInferException)
    async def geoinfer_exception_handler(
        request: Request, exc: GeoInferException
    ) -> JSONResponse:
        """Handle custom GeoInfer exceptions."""
        logger.error(
            f"GeoInfer exception: {exc.message_code.value}",
            extra={
                "path": request.url.path,
                "method": request.method,
                "message_code": exc.message_code.value,
                "details": exc.details,
            },
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response_dict(),
            headers=exc.headers,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        """Handle FastAPI HTTP exceptions."""
        logger.warning(
            f"HTTP exception {exc.status_code}: {exc.detail}",
            extra={
                "path": request.url.path,
                "method": request.method,
            },
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message_code": MessageCode.INTERNAL_SERVER_ERROR,
                "message": str(exc.detail),
                "details": {"description": "HTTP exception occurred"},
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Handle Starlette HTTP exceptions."""
        logger.warning(
            f"Starlette HTTP exception {exc.status_code}: {exc.detail}",
            extra={
                "path": request.url.path,
                "method": request.method,
            },
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "message_code": MessageCode.INTERNAL_ERROR,
                "message": str(exc.detail),
                "details": {"description": "HTTP exception occurred"},
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle request validation errors."""
        # Convert errors to a serializable format
        try:
            errors = exc.errors()
            # Convert datetime objects to strings
            serializable_errors = []
            for error in errors:
                error_dict = dict(error)
                if "input" in error_dict and hasattr(error_dict["input"], "isoformat"):
                    error_dict["input"] = error_dict["input"].isoformat()
                serializable_errors.append(error_dict)
        except Exception:
            serializable_errors = [
                {"msg": "Validation error occurred", "type": "validation_error"}
            ]

        logger.warning(
            "Validation error occurred",
            extra={
                "path": request.url.path,
                "method": request.method,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "message_code": MessageCode.INVALID_INPUT,
                "message": get_default_message(MessageCode.INVALID_INPUT),
                "details": {
                    "description": "Request validation failed",
                    "validation_errors": serializable_errors,
                },
            },
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_exception_handler(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors."""
        # Convert errors to a serializable format
        try:
            errors = exc.errors()
            # Convert datetime objects to strings
            serializable_errors = []
            for error in errors:
                error_dict = dict(error)
                if "input" in error_dict and hasattr(error_dict["input"], "isoformat"):
                    error_dict["input"] = error_dict["input"].isoformat()
                serializable_errors.append(error_dict)
        except Exception:
            serializable_errors = [
                {"msg": "Validation error occurred", "type": "validation_error"}
            ]

        logger.warning(
            "Pydantic validation error occurred",
            extra={
                "path": request.url.path,
                "method": request.method,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "message_code": MessageCode.VALIDATION_ERROR,
                "message": "Validation failed",
                "details": {
                    "validation_errors": serializable_errors,
                },
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        """Handle SQLAlchemy database errors."""
        logger.error(
            f"Database error: {str(exc)}",
            extra={
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
            },
        )

        # Handle specific SQLAlchemy errors
        if isinstance(exc, IntegrityError):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "message_code": MessageCode.BAD_REQUEST,
                    "message": "Data integrity constraint violated",
                    "details": {"database_error": "Constraint violation"},
                },
            )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message_code": MessageCode.INTERNAL_ERROR,
                "message": "Database error occurred",
                "details": {"database_error": "Internal database error"},
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle all other unhandled exceptions."""
        if isinstance(exc, GeoInferException):
            return await geoinfer_exception_handler(request, exc)

        logger.error(
            f"Unhandled exception: {str(exc)}",
            extra={
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "message_code": MessageCode.INTERNAL_ERROR,
                "message": "Internal server error",
                "details": {"error_type": type(exc).__name__},
            },
        )
