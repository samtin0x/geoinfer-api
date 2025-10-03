import pytest

from src.emails.render import render_email


class TestEmailRender:
    def test_render_invite_email_en(self):
        """Test rendering invite email in English."""
        email_data = render_email(template_name="invite", locale="en")

        assert email_data["subject"] == "Welcome to GeoInfer Beta"
        assert email_data["html"]
        assert email_data["reply_to"] == "support@geoinfer.com"
        assert "from_" not in email_data

    @pytest.mark.parametrize(
        "locale,expected_subject",
        [
            ("en", "Welcome to GeoInfer Beta"),
            ("de", "Willkommen bei GeoInfer Beta"),
            ("es", "Bienvenido a GeoInfer Beta"),
            ("fr", "Bienvenue sur GeoInfer Beta"),
            ("it", "Benvenuto su GeoInfer Beta"),
            ("ja", "GeoInfer ベータ版へようこそ"),
            ("pt", "Bem-vindo ao GeoInfer Beta"),
            ("zh", "欢迎使用 GeoInfer 测试版"),
        ],
    )
    def test_render_invite_email_all_locales(self, locale: str, expected_subject: str):
        """Test rendering invite email in all supported locales."""
        email_data = render_email(template_name="invite", locale=locale)

        assert email_data["subject"] == expected_subject
        assert email_data["html"]
        assert email_data["reply_to"] == "support@geoinfer.com"
