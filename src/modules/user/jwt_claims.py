def extract_user_data_from_jwt(payload: dict) -> dict:
    """Extract user data from JWT claims for database sync."""
    user_id = payload.get("sub", "")

    user_metadata = payload.get("user_metadata", {})

    name = user_metadata.get("full_name") or user_metadata.get("name", "")

    avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")

    locale = user_metadata.get("locale") or payload.get("locale")

    return {
        "user_id": user_id,
        "email": payload.get("email", ""),
        "name": name,
        "avatar_url": avatar_url,
        "locale": locale,
    }
