import hashlib
from passlib.context import CryptContext

BCRYPT_ROUNDS: int = 12

pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=BCRYPT_ROUNDS
)


class HashingService:
    """Service for secure hashing and verification of sensitive data."""

    @staticmethod
    def hash_api_key(plain_key: str) -> str:
        """
        Hash an API key using bcrypt with salt.
        For keys longer than 72 bytes, pre-hash with SHA-256 to avoid bcrypt truncation.

        Args:
            plain_key: The plain text API key to hash

        Returns:
            The hashed key as a string
        """
        # bcrypt truncates inputs at 72 bytes, so pre-hash long keys
        if len(plain_key.encode("utf-8")) > 72:
            plain_key = hashlib.sha256(plain_key.encode("utf-8")).hexdigest()
        return pwd_context.hash(plain_key)

    @staticmethod
    def verify_api_key(plain_key: str, hashed_key: str) -> bool:
        """
        Verify a plain API key against its hash.
        For keys longer than 72 bytes, pre-hash with SHA-256 to match hashing behavior.

        Args:
            plain_key: The plain text API key to verify
            hashed_key: The stored hash to check against

        Returns:
            True if the key matches, False otherwise
        """
        try:
            # Apply same pre-hashing logic as in hash_api_key
            if len(plain_key.encode("utf-8")) > 72:
                plain_key = hashlib.sha256(plain_key.encode("utf-8")).hexdigest()
            return pwd_context.verify(plain_key, hashed_key)
        except (ValueError, TypeError):
            # Handle any verification errors
            return False

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt with salt.

        Args:
            password: The plain text password to hash

        Returns:
            The hashed password as a string
        """
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, hashed_password: str) -> bool:
        """
        Verify a plain password against its hash.

        Args:
            password: The plain text password to verify
            hashed_password: The stored hash to check against

        Returns:
            True if the password matches, False otherwise
        """
        try:
            return pwd_context.verify(password, hashed_password)
        except (ValueError, TypeError):
            return False
