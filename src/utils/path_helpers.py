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
