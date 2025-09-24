import pytest
from src.modules.user.jwt_claims import extract_user_data_from_jwt


def test_extract_google_user_data():
    """Test extracting data from Google user JWT claims."""
    google_payload = {
        "iss": "https://bpfjuhsdopcjyffccebj.supabase.co/auth/v1",
        "sub": "107428996114671035041",
        "aud": "authenticated",
        "exp": 1758634220,
        "iat": 1758630620,
        "email": "saulmartin1@gmail.com",
        "phone": "",
        "app_metadata": {"provider": "email", "providers": ["email", "google"]},
        "user_metadata": {
            "avatar_url": "https://lh3.googleusercontent.com/a/ACg8ocLKo1bQEmE9LvPNBflENJ2xpRoi9qt3xWSphCpyDKYAh_O0ragS=s96-c",
            "email": "saulmartin1@gmail.com",
            "email_verified": True,
            "full_name": "Saul Martinn",
            "iss": "https://accounts.google.com",
            "name": "Saul Martin",
            "phone_verified": False,
            "picture": "https://lh3.googleusercontent.com/a/ACg8ocLKo1bQEmE9LvPNBflENJ2xpRoi9qt3xWSphCpyDKYAh_O0ragS=s96-c",
            "provider_id": "107428996114671035041",
            "sub": "107428996114671035041",
        },
        "role": "authenticated",
        "aal": "aal2",
        "amr": [
            {"method": "totp", "timestamp": 1758482118},
            {"method": "oauth", "timestamp": 1758482090},
        ],
        "session_id": "b22d8937-8671-4251-b8b1-b1bb44b01e4c",
        "is_anonymous": False,
    }

    user_data = extract_user_data_from_jwt(google_payload)

    assert user_data["user_id"] == "107428996114671035041"
    assert user_data["email"] == "saulmartin1@gmail.com"
    assert user_data["name"] == "Saul Martinn"
    assert (
        user_data["avatar_url"]
        == "https://lh3.googleusercontent.com/a/ACg8ocLKo1bQEmE9LvPNBflENJ2xpRoi9qt3xWSphCpyDKYAh_O0ragS=s96-c"
    )
    assert user_data["locale"] is None


def test_extract_email_user_data():
    """Test extracting data from email user JWT claims."""
    email_payload = {
        "sub": "49583cbd-b4ef-43f8-ac3d-2fb113730947",
        "email": "davidviarhernandez@gmail.com",
        "app_metadata": {"provider": "email", "providers": ["email"]},
        "user_metadata": {
            "full_name": "Puto Putón",
            "name": "Puto Putón",
            "email_verified": True,
            "phone_verified": False,
        },
        "role": "authenticated",
    }

    user_data = extract_user_data_from_jwt(email_payload)

    assert user_data["user_id"] == "49583cbd-b4ef-43f8-ac3d-2fb113730947"
    assert user_data["email"] == "davidviarhernandez@gmail.com"
    assert user_data["name"] == "Puto Putón"
    assert user_data["avatar_url"] is None
    assert user_data["locale"] is None


@pytest.mark.parametrize(
    "payload,expected_name",
    [
        (
            {"user_metadata": {"full_name": "Full Name", "name": "Simple Name"}},
            "Full Name",
        ),
        ({"user_metadata": {"name": "Simple Name"}}, "Simple Name"),
        ({"user_metadata": {}}, ""),
    ],
)
def test_name_extraction_priority(payload, expected_name):
    """Test name extraction priority with different scenarios."""
    user_data = extract_user_data_from_jwt(payload)
    assert user_data["name"] == expected_name


@pytest.mark.parametrize(
    "payload,expected_user_id",
    [
        ({"sub": "user-id-123"}, "user-id-123"),
        ({}, ""),
    ],
)
def test_user_id_extraction(payload, expected_user_id):
    """Test user ID extraction with different scenarios."""
    user_data = extract_user_data_from_jwt(payload)
    assert user_data["user_id"] == expected_user_id
