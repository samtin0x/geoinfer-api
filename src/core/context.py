"""Authentication context model for typed user authentication."""

from dataclasses import dataclass

from src.database.models.users import User
from src.database.models.organizations import Organization
from src.database.models.api_keys import ApiKey


@dataclass
class AuthenticatedUserContext:
    """Context containing authenticated user, organization, and API key information."""

    user: User
    organization: Organization
    api_key: ApiKey | None

    def __post_init__(self):
        """Ensure all required fields are present and valid."""
        if not self.user:
            raise ValueError("User is required in authentication context")
        if not self.organization:
            raise ValueError("Organization is required in authentication context")
