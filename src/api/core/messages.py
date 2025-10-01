"""Centralized message codes and default messages for API responses."""

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel


class MessageCode(str, Enum):
    """Centralized message codes for API responses."""

    # Success codes
    SUCCESS = "SUCCESS"
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"

    # Authentication & Authorization
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_API_KEY = "INVALID_API_KEY"
    AUTH_INSUFFICIENT_ROLE_PERMISSIONS = "AUTH_INSUFFICIENT_ROLE_PERMISSIONS"
    AUTH_INSUFFICIENT_PLAN_TIER = "AUTH_INSUFFICIENT_PLAN_TIER"
    AUTH_MISSING_CONTEXT = "AUTH_MISSING_CONTEXT"

    # User management
    USER_UPDATED = "USER_UPDATED"
    USER_NOT_FOUND = "USER_NOT_FOUND"

    # Organization management
    ORGANIZATION_CREATED = "ORGANIZATION_CREATED"
    ORGANIZATION_UPDATED = "ORGANIZATION_UPDATED"
    ORGANIZATION_NOT_FOUND = "ORGANIZATION_NOT_FOUND"
    ORGANIZATION_LIMIT_EXCEEDED = "ORGANIZATION_LIMIT_EXCEEDED"

    # Invitation management
    INVITE_CREATED = "INVITE_CREATED"
    INVITE_ACCEPTED = "INVITE_ACCEPTED"
    INVITE_DECLINED = "INVITE_DECLINED"
    INVITE_NOT_FOUND = "INVITE_NOT_FOUND"
    INVITE_CANCELLED = "INVITE_CANCELLED"
    INVITE_ALREADY_PENDING = "INVITE_ALREADY_PENDING"
    INVITATION_INVALID = "INVITATION_INVALID"
    INVITATION_ALREADY_MEMBER = "INVITATION_ALREADY_MEMBER"
    INVITATION_ALREADY_USED = "INVITATION_ALREADY_USED"
    INVITATION_EXPIRED = "INVITATION_EXPIRED"

    # API Key management
    API_KEY_CREATED = "API_KEY_CREATED"
    API_KEY_DELETED = "API_KEY_DELETED"
    API_KEY_NOT_FOUND = "API_KEY_NOT_FOUND"
    API_KEY_INVALID = "API_KEY_INVALID"

    # Credit management
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"

    # Rate limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_INVALID_INPUT = "VALIDATION_INVALID_INPUT"
    INVALID_INPUT = "INVALID_INPUT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"

    # Permission errors
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    ROLE_GRANTED = "ROLE_GRANTED"
    ROLE_REVOKED = "ROLE_REVOKED"
    ROLE_CHANGED = "ROLE_CHANGED"
    CANNOT_CHANGE_OWN_ROLE = "CANNOT_CHANGE_OWN_ROLE"

    # Service Errors
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

    # Prediction errors
    PREDICTION_FAILED = "PREDICTION_FAILED"
    IMAGE_PROCESSING_ERROR = "IMAGE_PROCESSING_ERROR"

    # Organization & User Management (additional)
    ORG_NOT_FOUND = "ORG_NOT_FOUND"
    USER_REMOVED_FROM_ORGANIZATION = "USER_REMOVED_FROM_ORGANIZATION"
    CANNOT_REMOVE_YOURSELF = "CANNOT_REMOVE_YOURSELF"
    USER_NOT_MEMBER_OF_ORGANIZATION = "USER_NOT_MEMBER_OF_ORGANIZATION"

    # Billing errors
    SUBSCRIPTION_NOT_FOUND = "SUBSCRIPTION_NOT_FOUND"
    ALERT_SETTINGS_NOT_CONFIGURED = "ALERT_SETTINGS_NOT_CONFIGURED"
    NO_ALERT_DESTINATIONS = "NO_ALERT_DESTINATIONS"

    # Generic errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"


# Default messages for each message code
DEFAULT_MESSAGES = {
    # Success messages
    MessageCode.SUCCESS: "Operation completed successfully",
    MessageCode.CREATED: "Resource created successfully",
    MessageCode.UPDATED: "Resource updated successfully",
    MessageCode.DELETED: "Resource deleted successfully",
    # Authentication & Authorization
    MessageCode.AUTH_REQUIRED: "Authentication required",
    MessageCode.UNAUTHORIZED: "Authentication required",
    MessageCode.FORBIDDEN: "Access denied",
    MessageCode.INVALID_TOKEN: "Invalid authentication token",
    MessageCode.INVALID_API_KEY: "Invalid or expired API key",
    MessageCode.AUTH_INSUFFICIENT_ROLE_PERMISSIONS: "Insufficient role permissions",
    MessageCode.AUTH_INSUFFICIENT_PLAN_TIER: "Insufficient plan tier",
    MessageCode.AUTH_MISSING_CONTEXT: "Authentication context required",
    # User management
    MessageCode.USER_UPDATED: "User updated successfully",
    MessageCode.USER_NOT_FOUND: "User not found",
    # Organization management
    MessageCode.ORGANIZATION_CREATED: "Organization created successfully",
    MessageCode.ORGANIZATION_UPDATED: "Organization updated successfully",
    MessageCode.ORGANIZATION_NOT_FOUND: "Organization not found",
    MessageCode.ORGANIZATION_LIMIT_EXCEEDED: "Maximum organization limit exceeded. Users can only create 1 enterprise organization.",
    # Invitation management
    MessageCode.INVITE_CREATED: "Invitation created successfully",
    MessageCode.INVITE_ACCEPTED: "Invitation accepted successfully",
    MessageCode.INVITE_DECLINED: "Invitation declined",
    MessageCode.INVITE_NOT_FOUND: "Invitation not found",
    MessageCode.INVITE_CANCELLED: "Invitation has been cancelled",
    MessageCode.INVITE_ALREADY_PENDING: "A pending invitation already exists for this email address",
    MessageCode.INVITATION_INVALID: "Invalid invitation",
    MessageCode.INVITATION_ALREADY_MEMBER: "User is already a member of the organization",
    MessageCode.INVITATION_ALREADY_USED: "Invitation has already been used",
    MessageCode.INVITATION_EXPIRED: "Invitation has expired",
    # API Key management
    MessageCode.API_KEY_CREATED: "API key created successfully",
    MessageCode.API_KEY_DELETED: "API key deleted successfully",
    MessageCode.API_KEY_NOT_FOUND: "API key not found",
    MessageCode.API_KEY_INVALID: "Invalid API key",
    # Credit management
    MessageCode.INSUFFICIENT_CREDITS: "Insufficient credits",
    # Rate limiting
    MessageCode.RATE_LIMIT_EXCEEDED: "Rate limit exceeded",
    # Validation errors
    MessageCode.VALIDATION_ERROR: "Validation failed",
    MessageCode.VALIDATION_INVALID_INPUT: "Invalid input provided",
    MessageCode.INVALID_INPUT: "Invalid input provided",
    MessageCode.FILE_TOO_LARGE: "File size too large",
    MessageCode.INVALID_FILE_TYPE: "Invalid file type",
    # Permission errors
    MessageCode.INSUFFICIENT_PERMISSIONS: "Insufficient permissions",
    MessageCode.ROLE_GRANTED: "Role granted successfully",
    MessageCode.ROLE_REVOKED: "Role revoked successfully",
    MessageCode.ROLE_CHANGED: "Role changed successfully",
    MessageCode.CANNOT_CHANGE_OWN_ROLE: "Cannot change your own role",
    # Service Errors
    MessageCode.EXTERNAL_SERVICE_ERROR: "External service error",
    # Prediction errors
    MessageCode.PREDICTION_FAILED: "Prediction failed",
    MessageCode.IMAGE_PROCESSING_ERROR: "Error processing image",
    # Organization & User Management (additional)
    MessageCode.ORG_NOT_FOUND: "Organization not found",
    MessageCode.USER_REMOVED_FROM_ORGANIZATION: "User removed from organization successfully",
    MessageCode.CANNOT_REMOVE_YOURSELF: "Cannot remove yourself from organization",
    MessageCode.USER_NOT_MEMBER_OF_ORGANIZATION: "User is not a member of this organization",
    # Billing errors
    MessageCode.SUBSCRIPTION_NOT_FOUND: "Subscription not found",
    MessageCode.ALERT_SETTINGS_NOT_CONFIGURED: "Alert settings not configured",
    MessageCode.NO_ALERT_DESTINATIONS: "No email destinations configured for alerts",
    # Generic errors
    MessageCode.INTERNAL_ERROR: "Internal server error",
    MessageCode.INTERNAL_SERVER_ERROR: "Internal server error",
    MessageCode.RESOURCE_NOT_FOUND: "Resource not found",
    MessageCode.BAD_REQUEST: "Bad request",
    MessageCode.NOT_FOUND: "Resource not found",
}

T = TypeVar("T")


class PaginationInfo(BaseModel):
    """Common pagination information."""

    total: int
    limit: int
    offset: int
    has_more: bool


class Paginated(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    pagination: PaginationInfo


class APIResponse(BaseModel, Generic[T]):
    """Base API response model with consistent structure and proper typing."""

    message_code: MessageCode
    message: str
    data: T | None = None

    @classmethod
    def success(
        cls,
        message_code: MessageCode = MessageCode.SUCCESS,
        message: str | None = None,
        data: T | None = None,
    ) -> "APIResponse[T]":
        """Create a success response."""
        return cls(
            message_code=message_code,
            message=message or DEFAULT_MESSAGES.get(message_code, "Success"),
            data=data,
        )

    @classmethod
    def error(
        cls,
        message_code: MessageCode,
        message: str | None = None,
        data: T | None = None,
    ) -> "APIResponse[T]":
        """Create an error response."""
        return cls(
            message_code=message_code,
            message=message or DEFAULT_MESSAGES.get(message_code, "Error occurred"),
            data=data,
        )


def get_default_message(message_code: MessageCode) -> str:
    """Get default message for a message code."""
    return DEFAULT_MESSAGES.get(message_code, "Operation completed")
