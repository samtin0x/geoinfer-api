import importlib
from pathlib import Path
from typing import Literal, TypedDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

TemplateType = Literal["invite"]
LocaleType = Literal["de", "en", "es", "fr", "it", "ja", "pt", "zh"]


class EmailData(TypedDict):
    html: str
    subject: str
    reply_to: str


TEMPLATE_DIR = Path(__file__).parent / "template"
BASE_APP_URL = "https://app.geoinfer.com"

jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def get_localized_url(locale: str, path: str = "signin") -> str:
    """Generate localized URL for GeoInfer app."""
    return f"{BASE_APP_URL}/{locale}/{path}"


def render_email(
    template_name: TemplateType,
    locale: LocaleType = "en",
) -> EmailData:
    translations_module = importlib.import_module(
        f"src.emails.template.{template_name}.translations"
    )
    default_translations = translations_module.DEFAULT_TRANSLATIONS

    translations = default_translations.get(locale, default_translations["en"])

    template = jinja_env.get_template(f"{template_name}/{template_name}.html")

    html_content = template.render(translations=translations)

    return EmailData(
        html=html_content,
        subject=translations["subject"],
        reply_to=translations.get("reply_to", "support@geoinfer.com"),
    )
