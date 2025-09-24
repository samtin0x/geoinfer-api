"""Test utilities for asserting API responses and message codes."""

from typing import Any
from httpx import Response
from src.api.core.messages import MessageCode
from src.api.core.exceptions.base import GeoInferException


def assert_success_response(
    response: Response,
    expected_message_code: MessageCode = MessageCode.SUCCESS,
    expected_status: int = 200,
    data_assertions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assert that response is successful with expected message code.

    Args:
        response: HTTP response to check
        expected_message_code: Expected message code
        expected_status: Expected HTTP status code
        data_assertions: Optional dict of assertions to run on response data

    Returns:
        Response data for further assertions
    """
    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, got {response.status_code}. "
        f"Response: {response.text}"
    )

    json_data = response.json()

    # Check message code
    assert json_data.get("message_code") == expected_message_code.value, (
        f"Expected message_code {expected_message_code.value}, "
        f"got {json_data.get('message_code')}"
    )

    # Check that it's a success response (if status is success-like)
    if expected_status < 400:
        assert "message" in json_data, "Success response should have message"

    # Run additional data assertions if provided
    if data_assertions:
        data = json_data.get("data")
        for field, expected_value in data_assertions.items():
            if "." in field:  # Support nested field access like "user.email"
                current = data
                for part in field.split("."):
                    current = current[part]
                assert (
                    current == expected_value
                ), f"Expected {field} to be {expected_value}, got {current}"
            else:
                assert (
                    data[field] == expected_value
                ), f"Expected {field} to be {expected_value}, got {data[field]}"

    return json_data.get("data")


def assert_error_response(
    response: Response,
    expected_message_code: MessageCode,
    expected_status: int,
    expected_message: str | None = None,
) -> dict[str, Any]:
    """Assert that response is an error with expected message code.

    Args:
        response: HTTP response to check
        expected_message_code: Expected error message code
        expected_status: Expected HTTP status code
        expected_message: Optional expected error message

    Returns:
        Response data for further assertions
    """
    assert response.status_code == expected_status, (
        f"Expected status {expected_status}, got {response.status_code}. "
        f"Response: {response.text}"
    )

    json_data = response.json()

    # Check message code
    assert json_data.get("message_code") == expected_message_code.value, (
        f"Expected message_code {expected_message_code.value}, "
        f"got {json_data.get('message_code')}"
    )

    # Check message if provided
    if expected_message:
        assert json_data.get("message") == expected_message, (
            f"Expected message '{expected_message}', "
            f"got '{json_data.get('message')}'"
        )

    return json_data


def assert_validation_error(
    response: Response, field_errors: dict[str, str] | None = None
) -> dict[str, Any]:
    """Assert that response is a validation error.

    Args:
        response: HTTP response to check
        field_errors: Optional dict mapping field names to expected error types

    Returns:
        Response data for further assertions
    """
    json_data = assert_error_response(response, MessageCode.INVALID_INPUT, 422)

    if field_errors:
        details = json_data.get("details", {})
        validation_errors = details.get("validation_errors", [])

        for field, error_type in field_errors.items():
            field_error = next(
                (err for err in validation_errors if err.get("field") == field), None
            )
            assert field_error, f"Expected validation error for field '{field}'"
            assert field_error.get("type") == error_type, (
                f"Expected error type '{error_type}' for field '{field}', "
                f"got '{field_error.get('type')}'"
            )

    return json_data


def assert_permission_error(response: Response) -> dict[str, Any]:
    """Assert that response is a permission/authorization error."""
    return assert_error_response(response, MessageCode.FORBIDDEN, 403)


def assert_authentication_error(response: Response) -> dict[str, Any]:
    """Assert that response is an authentication error."""
    return assert_error_response(response, MessageCode.UNAUTHORIZED, 401)


def assert_not_found_error(
    response: Response, resource_type: str | None = None
) -> dict[str, Any]:
    """Assert that response is a not found error."""
    expected_code = MessageCode.RESOURCE_NOT_FOUND
    if resource_type == "user":
        expected_code = MessageCode.USER_NOT_FOUND
    elif resource_type == "organization":
        expected_code = MessageCode.ORGANIZATION_NOT_FOUND
    elif resource_type == "api_key":
        expected_code = MessageCode.API_KEY_NOT_FOUND
    elif resource_type == "invitation":
        expected_code = MessageCode.INVITE_NOT_FOUND

    return assert_error_response(response, expected_code, 404)


def assert_geoinfer_exception(
    exception: GeoInferException,
    expected_message_code: MessageCode,
    expected_status: int | None = None,
) -> None:
    """Assert that a GeoInferException has expected properties.

    Args:
        exception: The exception to check
        expected_message_code: Expected message code
        expected_status: Optional expected HTTP status code
    """
    assert exception.message_code == expected_message_code, (
        f"Expected message_code {expected_message_code}, "
        f"got {exception.message_code}"
    )

    if expected_status:
        assert exception.status_code == expected_status, (
            f"Expected status_code {expected_status}, " f"got {exception.status_code}"
        )


class ResponseHelper:
    """Helper class for common response assertions and data extraction."""

    @staticmethod
    def get_data(response: Response) -> Any:
        """Extract data from successful response."""
        assert response.status_code < 400, f"Response failed: {response.text}"
        return response.json().get("data")

    @staticmethod
    def get_message_code(response: Response) -> MessageCode:
        """Extract message code from response."""
        return MessageCode(response.json().get("message_code"))

    @staticmethod
    def get_message(response: Response) -> str:
        """Extract message from response."""
        return response.json().get("message", "")

    @staticmethod
    def assert_paginated_response(
        response: Response,
        expected_total: int | None = None,
        expected_page: int = 1,
        expected_page_size: int | None = None,
    ) -> list[Any]:
        """Assert paginated response structure and return items."""
        data = assert_success_response(response)

        assert "items" in data, "Paginated response should have 'items'"
        assert "pagination" in data, "Paginated response should have 'pagination'"

        pagination = data["pagination"]

        if expected_total is not None:
            assert (
                pagination["total"] == expected_total
            ), f"Expected total {expected_total}, got {pagination['total']}"

        assert (
            pagination["page"] == expected_page
        ), f"Expected page {expected_page}, got {pagination['page']}"

        if expected_page_size is not None:
            assert (
                pagination["page_size"] == expected_page_size
            ), f"Expected page_size {expected_page_size}, got {pagination['page_size']}"

        return data["items"]
