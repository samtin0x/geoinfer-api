"""Tests for hashing utilities."""

import pytest

from src.utils.hashing import HashingService


def test_hash_api_key_creates_different_hashes_for_same_input():
    """Test that hashing the same key twice produces different hashes due to salt."""
    plain_key = "test_api_key_123"

    hash1 = HashingService.hash_api_key(plain_key)
    hash2 = HashingService.hash_api_key(plain_key)

    # Hashes should be different due to random salt
    assert hash1 != hash2
    # But both should be valid bcrypt hashes
    assert hash1.startswith("$2b$")
    assert hash2.startswith("$2b$")


def test_verify_api_key_with_correct_key_returns_true():
    """Test that verification succeeds with the correct key."""
    plain_key = "test_api_key_456"
    hashed_key = HashingService.hash_api_key(plain_key)

    assert HashingService.verify_api_key(plain_key, hashed_key) is True


def test_verify_api_key_with_incorrect_key_returns_false():
    """Test that verification fails with an incorrect key."""
    plain_key = "test_api_key_789"
    wrong_key = "wrong_api_key_123"
    hashed_key = HashingService.hash_api_key(plain_key)

    assert HashingService.verify_api_key(wrong_key, hashed_key) is False


def test_verify_api_key_with_invalid_hash_returns_false():
    """Test that verification fails gracefully with invalid hash format."""
    plain_key = "test_api_key_abc"
    invalid_hash = "not_a_valid_bcrypt_hash"

    assert HashingService.verify_api_key(plain_key, invalid_hash) is False


def test_verify_api_key_with_empty_inputs_returns_false():
    """Test that verification fails gracefully with empty inputs."""
    assert HashingService.verify_api_key("", "") is False
    assert HashingService.verify_api_key("key", "") is False
    assert HashingService.verify_api_key("", "hash") is False


def test_hash_password_creates_different_hashes_for_same_input():
    """Test that hashing the same password twice produces different hashes due to salt."""
    password = "test_password_123"

    hash1 = HashingService.hash_password(password)
    hash2 = HashingService.hash_password(password)

    # Hashes should be different due to random salt
    assert hash1 != hash2
    # But both should be valid bcrypt hashes
    assert hash1.startswith("$2b$")
    assert hash2.startswith("$2b$")


def test_verify_password_with_correct_password_returns_true():
    """Test that password verification succeeds with the correct password."""
    password = "secure_password_456"
    hashed_password = HashingService.hash_password(password)

    assert HashingService.verify_password(password, hashed_password) is True


def test_verify_password_with_incorrect_password_returns_false():
    """Test that password verification fails with an incorrect password."""
    password = "secure_password_789"
    wrong_password = "wrong_password_123"
    hashed_password = HashingService.hash_password(password)

    assert HashingService.verify_password(wrong_password, hashed_password) is False


def test_verify_password_with_invalid_hash_returns_false():
    """Test that password verification fails gracefully with invalid hash format."""
    password = "test_password_def"
    invalid_hash = "not_a_valid_bcrypt_hash"

    assert HashingService.verify_password(password, invalid_hash) is False


@pytest.mark.parametrize(
    "key",
    [
        "short",
        "a_very_long_api_key_that_exceeds_normal_length_expectations_and_contains_many_characters",
        "key-with-special-chars!@#$%^&*()",
        "key_with_unicode_ñ_characters_🔑",
        "123456789",
    ],
)
def test_hash_and_verify_with_various_key_formats(key: str):
    """Test hashing and verification with various key formats and lengths."""
    hashed = HashingService.hash_api_key(key)
    assert HashingService.verify_api_key(key, hashed) is True
    assert HashingService.verify_api_key(key + "x", hashed) is False


def test_hash_api_key_is_deterministic_for_verification():
    """Test that the same key always verifies correctly against its hash."""
    plain_key = "consistent_verification_test"
    hashed_key = HashingService.hash_api_key(plain_key)

    # Verify multiple times to ensure consistency
    for _ in range(10):
        assert HashingService.verify_api_key(plain_key, hashed_key) is True


def test_different_keys_do_not_verify_against_each_other():
    """Test that different keys never verify against each other's hashes."""
    key1 = "api_key_one"
    key2 = "api_key_two"

    hash1 = HashingService.hash_api_key(key1)
    hash2 = HashingService.hash_api_key(key2)

    # Each key should only verify against its own hash
    assert HashingService.verify_api_key(key1, hash1) is True
    assert HashingService.verify_api_key(key2, hash2) is True
    assert HashingService.verify_api_key(key1, hash2) is False
    assert HashingService.verify_api_key(key2, hash1) is False
