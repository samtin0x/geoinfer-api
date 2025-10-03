import sys
from pathlib import Path
from typing import cast

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.emails import LocaleType, TemplateType, render_email  # noqa: E402


def generate_preview(
    template_name: str, locale: str, output_path: Path | None = None
) -> str:
    """Generate and optionally save email preview to HTML file."""
    email_data = render_email(
        template_name=cast(TemplateType, template_name),
        locale=cast(LocaleType, locale),
    )

    if output_path:
        output_path.write_text(email_data["html"])
        print(f"✓ Preview saved ({locale}): {output_path.name}")

    return email_data["html"]


if __name__ == "__main__":
    preview_dir = Path(__file__).parent / "previews"
    preview_dir.mkdir(exist_ok=True)

    locales = ["de", "en", "es", "fr", "it", "ja", "pt", "zh"]

    for locale in locales:
        output_file = preview_dir / f"invite_preview_{locale}.html"
        generate_preview(
            template_name="invite",
            locale=locale,
            output_path=output_file,
        )

    print(f"\n✓ Generated {len(locales)} preview files")
    print("\nOpen previews in your browser:")
    print(f"  file://{preview_dir.absolute()}/invite_preview_en.html")
