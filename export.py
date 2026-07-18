"""Export d'une session GuideExpress en guide autonome (HTML) ou en Markdown."""

from __future__ import annotations

import base64
import io
from pathlib import Path

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
        png_bytes = _step_to_png_bytes(step)
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

    lines = [f"# {title}", "", f"{len(steps)} etape(s).", ""]
    for step in steps:
        image_name = f"etape-{step.index:03d}.png"
        (images_dir / image_name).write_bytes(_step_to_png_bytes(step))
        lines.append(f"## Etape {step.index}")
        lines.append("")
        lines.append(escape_markdown(step.display_description()))
        lines.append("")
        lines.append(f"![Etape {step.index}](images/{image_name})")
        lines.append("")

    md_path = output_dir / "guide.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
