"""API response models with unified error codes and messages."""

from typing import Generic, TypeVar

from pydantic import BaseModel

from ..messages import MessageCode, get_default_message

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Base API response model with consistent structure and proper typing."""

    success: bool
    code: MessageCode
    message: str
    data: T | None = None

    @classmethod
    def success_response(
        cls,
        data: T | None = None,
        code: MessageCode = MessageCode.SUCCESS,
        message: str | None = None,
    ) -> "APIResponse[T]":
        """Create a success response."""
        return cls(
            success=True,
            code=code,
            message=message or get_default_message(code),
            data=data,
        )

    @classmethod
    def error_response(
        cls,
        code: MessageCode,
        message: str | None = None,
        data: T | None = None,
    ) -> "APIResponse[T]":
        """Create an error response."""
        return cls(
            success=False,
            code=code,
            message=message or get_default_message(code),
            data=data,
        )
