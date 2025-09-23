"""Tests for rate limiting functionality."""

from unittest.mock import MagicMock, patch

from src.api.core.models.rate_limit import (
    ClientIdentifier,
    RateLimitClientType,
)
from src.api.core.decorators.rate_limit import create_rate_limit_key


def test_client_identifier_creation_api_key():
    """Test creating client identifier for API key."""
    # Mock request with API key
    mock_request = MagicMock()
    mock_api_key = MagicMock()
    mock_api_key.id = "test-key-123"
    mock_request.state.api_key = mock_api_key
    mock_request.state.user = None

    result = create_rate_limit_key(mock_request)

    assert isinstance(result, ClientIdentifier)
    assert result.client_type == RateLimitClientType.API_KEY
    assert result.client_id == "test-key-123"
    assert result.to_cache_key() == "rate_limit:api_key:test-key-123"
    assert str(result) == "api_key:test-key-123"


def test_client_identifier_creation_user():
    """Test creating client identifier for user."""
    # Mock request with user
    mock_request = MagicMock()
    mock_request.state.api_key = None
    mock_request.state.user = {"sub": "user-123"}

    result = create_rate_limit_key(mock_request)

    assert isinstance(result, ClientIdentifier)
    assert result.client_type == RateLimitClientType.USER
    assert result.client_id == "user-123"
    assert result.to_cache_key() == "rate_limit:user:user-123"
    assert str(result) == "user:user-123"


def test_client_identifier_creation_ip_fallback():
    """Test creating client identifier for IP (fallback)."""
    # Mock request with no auth and not a trial endpoint
    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url.path = "/prediction/predict"  # Not a trial endpoint
    mock_request.state.api_key = None
    mock_request.state.user = None
    mock_request.client.host = "127.0.0.1"

    # Mock the get_client_ip function to return the expected IP
    with patch(
        "src.api.core.decorators.rate_limit.get_client_ip", return_value="127.0.0.1"
    ):
        result = create_rate_limit_key(mock_request)

    assert isinstance(result, ClientIdentifier)
    assert result.client_type == RateLimitClientType.IP
    assert result.client_id == "127.0.0.1"
    assert result.to_cache_key() == "rate_limit:ip:127.0.0.1"
    assert str(result) == "ip:127.0.0.1"


def test_client_identifier_creation_trial_endpoint():
    """Test creating client identifier for trial endpoint."""
    # Mock request for trial endpoint with no auth
    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url.path = "/prediction/trial"  # Trial endpoint
    mock_request.state.api_key = None
    mock_request.state.user = None
    mock_request.client.host = "127.0.0.1"

    # Mock the get_client_ip function to return the expected IP
    with patch(
        "src.api.core.decorators.rate_limit.get_client_ip", return_value="127.0.0.1"
    ):
        result = create_rate_limit_key(mock_request)

    assert isinstance(result, ClientIdentifier)
    assert result.client_type == RateLimitClientType.TRIAL
    assert result.client_id == "127.0.0.1"
    assert result.to_cache_key() == "rate_limit:trial:127.0.0.1"
    assert str(result) == "trial:127.0.0.1"


def test_priority_order_api_key_over_user():
    """Test that API key takes priority over user ID."""
    # Mock request with both API key and user
    mock_request = MagicMock()
    mock_api_key = MagicMock()
    mock_api_key.id = "test-key-123"
    mock_request.state.api_key = mock_api_key
    mock_request.state.user = {"sub": "user-123"}

    result = create_rate_limit_key(mock_request)

    # Should use API key, not user
    assert isinstance(result, ClientIdentifier)
    assert result.client_type == RateLimitClientType.API_KEY
    assert result.client_id == "test-key-123"
    assert result.to_cache_key() == "rate_limit:api_key:test-key-123"
    assert str(result) == "api_key:test-key-123"
