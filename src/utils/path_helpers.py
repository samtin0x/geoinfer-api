import re
from uuid import UUID

from src.api.prediction.schemas import CoordinatePrediction


def build_prediction_metadata(
    top_prediction: CoordinatePrediction | None,
    prediction_id: UUID | None = None,
    model_id: str = "geoinfer_global_0_0_1",
) -> dict[str, str]:
    """Build metadata dictionary for prediction uploads."""
    metadata: dict[str, str] = {"model-id": model_id}

    if prediction_id:
        metadata["prediction-id"] = str(prediction_id)

    if top_prediction:
        metadata["latitude"] = str(top_prediction.latitude)
        metadata["longitude"] = str(top_prediction.longitude)

    return metadata


def path_matches(path: str, allowed_paths: set[str]) -> bool:
    """Check if path matches any allowed path, handling trailing slashes.

    Returns True if:
    - path exactly matches an allowed path, OR
    - path with trailing slash added/removed matches an allowed path

    Args:
        path: The request path to check
        allowed_paths: Set of allowed paths

    Returns:
        True if path matches any allowed path (with trailing slash handling)
    """
    # Check exact match first
    if path in allowed_paths:
        return True

    # Check with trailing slash added (if path doesn't have one)
    if not path.endswith("/"):
        path_with_slash = path + "/"
        if path_with_slash in allowed_paths:
            return True

    # Check with trailing slash removed (if path has one)
    if path.endswith("/"):
        path_without_slash = path[:-1]
        if path_without_slash in allowed_paths:
            return True

    return False


def path_matches_pattern(
    path: str, patterns: list[tuple[str | None, str]], method: str | None = None
) -> bool:
    """Check if path matches any regex pattern, optionally filtering by HTTP method.

    Args:
        path: The request path to check
        patterns: List of (method, pattern) tuples. method can be None to match any method.
        method: The HTTP method to check (e.g., 'GET', 'POST')

    Returns:
        True if path matches any pattern with compatible method
    """
    for allowed_method, pattern in patterns:
        # If pattern has a specific method requirement, check it
        if allowed_method is not None and method is not None:
            if allowed_method.upper() != method.upper():
                continue

        # Check if path matches the pattern
        if re.match(pattern, path):
            return True
    return False
