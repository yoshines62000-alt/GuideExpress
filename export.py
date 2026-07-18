"""Export d'une session GuideExpress en guide autonome (HTML), en Markdown,
ou en PDF (pret a imprimer/partager sans visionneuse HTML)."""

from __future__ import annotations

import base64
import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from capture import render_step_image, html_escape, escape_markdown


def _step_to_png_bytes(step, zoom: bool = False) -> bytes:
    img = render_step_image(step, zoom=zoom)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def export_html(steps: list, title: str, output_path: Path) -> None:
    """Genere un fichier HTML autonome (images encodees en base64 - un seul
    fichier a partager, rien a oublier)."""
    sections = []
    for step in steps:
        png_bytes = _step_to_png_bytes(step, zoom=step.zoom)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        sections.append(
            "<section class=\"step\">"
            f"<h2>Etape {step.index}</h2>"
            f"<p>{html_escape(step.display_description())}</p>"
            f"<img src=\"data:image/png;base64,{b64}\" alt=\"Etape {step.index}\">"
            "</section>"
        )

    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>{html_escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 0.5rem; }}
.step {{ margin: 2rem 0; padding-bottom: 1.5rem; border-bottom: 1px solid #ddd; }}
.step h2 {{ color: #2563eb; margin-bottom: 0.3rem; }}
.step img {{ max-width: 100%; border: 1px solid #ccc; border-radius: 6px; margin-top: 0.5rem; }}
</style></head>
<body>
<h1>{html_escape(title)}</h1>
<p>{len(steps)} etape(s).</p>
{''.join(sections)}
</body></html>
"""
    output_path.write_text(html, encoding="utf-8")


def export_markdown(steps: list, title: str, output_dir: Path) -> Path:
    """Genere un fichier Markdown (.md) accompagne d'un sous-dossier d'images.
    Renvoie le chemin du fichier .md cree."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Reexporter un guide plus court vers le meme dossier laisserait sinon
    # trainer d'anciennes images (etape-004.png, etc.) qu'aucun guide.md ne
    # reference plus. On ne supprime que nos propres fichiers reconnaissables
    # (motif etape-NNN.png), jamais un fichier place la par l'utilisateur.
    for stale in images_dir.glob("etape-*.png"):
        stale.unlink(missing_ok=True)

    lines = [f"# {escape_markdown(title)}", "", f"{len(steps)} etape(s).", ""]
    for step in steps:
        image_name = f"etape-{step.index:03d}.png"
        (images_dir / image_name).write_bytes(_step_to_png_bytes(step, zoom=step.zoom))
        lines.append(f"## Etape {step.index}")
        lines.append("")
        lines.append(escape_markdown(step.display_description()))
        lines.append("")
        lines.append(f"![Etape {step.index}](images/{image_name})")
        lines.append("")

    md_path = output_dir / "guide.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


_PDF_PAGE_MAX_WIDTH = 1400
_PDF_TEXT_AREA_HEIGHT = 140


def _latin1_safe(text: str) -> str:
    """PIL utilise la police bitmap integree par defaut (jeu de caracteres
    Latin-1) pour ImageDraw.text sans police externe fournie - un caractere
    hors de ce jeu (emoji, certains guillemets typographiques) doit degrader
    proprement (remplace par '?') plutot que de lever une exception."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _step_to_pdf_page(step, title_prefix: str) -> Image.Image:
    """Compose une page image : capture de l'etape en haut, titre et
    description en dessous sur fond blanc (pret a etre assemble en PDF)."""
    screenshot = render_step_image(step, zoom=step.zoom).convert("RGB")
    if screenshot.width > _PDF_PAGE_MAX_WIDTH:
        ratio = _PDF_PAGE_MAX_WIDTH / screenshot.width
        screenshot = screenshot.resize((_PDF_PAGE_MAX_WIDTH, max(1, int(screenshot.height * ratio))))

    page = Image.new("RGB", (screenshot.width, screenshot.height + _PDF_TEXT_AREA_HEIGHT), color="white")
    page.paste(screenshot, (0, 0))
    draw = ImageDraw.Draw(page)
    draw.text((20, screenshot.height + 15), _latin1_safe(f"{title_prefix} {step.index}"), fill=(30, 30, 30))
    wrapped = textwrap.wrap(_latin1_safe(step.display_description()), width=110) or [""]
    for line_index, line in enumerate(wrapped[:3]):
        draw.text((20, screenshot.height + 45 + line_index * 22), line, fill=(60, 60, 60))
    return page


def export_pdf(steps: list, title: str, output_path: Path) -> None:
    """Genere un PDF autonome (une page par etape, capture + description),
    via Pillow uniquement - aucune dependance PDF supplementaire."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not steps:
        # Une page de titre minimale plutot que planter, coherent avec le
        # comportement de export_html/export_markdown sur une liste vide.
        page = Image.new("RGB", (900, 200), color="white")
        ImageDraw.Draw(page).text((20, 20), _latin1_safe(title) or "Guide", fill=(30, 30, 30))
        page.save(output_path, format="PDF")
        return

    pages = [_step_to_pdf_page(step, "Etape") for step in steps]
    pages[0].save(output_path, format="PDF", save_all=True, append_images=pages[1:])
