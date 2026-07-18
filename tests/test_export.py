"""Tests pour export.py : generation des guides HTML/Markdown."""

import base64
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap
import export as exp


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.raw_path = self.tmp / "raw.png"
        Image.new("RGB", (200, 150), color=(10, 20, 30)).save(self.raw_path)
        self.steps = [
            cap.Step(
                index=1, raw_image_path=self.raw_path, click_x=50, click_y=50,
                window_title="Bloc-notes", timestamp="t1",
                description="Ouvrez le fichier",
            ),
            cap.Step(
                index=2, raw_image_path=self.raw_path, click_x=60, click_y=60,
                window_title="Bloc-notes", timestamp="t2",
                description="",  # doit utiliser la description par defaut
            ),
        ]

    def test_export_html_creates_single_self_contained_file(self):
        out = self.tmp / "guide.html"
        exp.export_html(self.steps, "Mon Guide", out)
        content = out.read_text(encoding="utf-8")
        self.assertIn("Mon Guide", content)
        self.assertIn("Etape 1", content)
        self.assertIn("Etape 2", content)
        self.assertIn("Ouvrez le fichier", content)
        self.assertIn("data:image/png;base64,", content)
        # Le fichier est bien autonome : aucune reference a un fichier image externe.
        self.assertNotIn('src="images/', content)
        self.assertNotIn("src='raw.png'", content)

    def test_export_html_embeds_valid_png_data(self):
        out = self.tmp / "guide.html"
        exp.export_html(self.steps, "Titre", out)
        content = out.read_text(encoding="utf-8")
        start = content.index("base64,") + len("base64,")
        end = content.index('"', start)
        b64_data = content[start:end]
        decoded = base64.b64decode(b64_data)
        self.assertTrue(decoded.startswith(b"\x89PNG"))

    def test_export_html_escapes_description(self):
        self.steps[0].description = "<img src=x onerror=alert(1)>"
        out = self.tmp / "guide.html"
        exp.export_html(self.steps, "Titre", out)
        content = out.read_text(encoding="utf-8")
        self.assertNotIn("<img src=x onerror=alert(1)>", content)
        self.assertIn("&lt;img", content)

    def test_export_markdown_writes_file_and_images(self):
        out_dir = self.tmp / "export_md"
        md_path = exp.export_markdown(self.steps, "Mon Guide MD", out_dir)
        self.assertTrue(md_path.exists())
        content = md_path.read_text(encoding="utf-8")
        self.assertIn("Mon Guide MD", content)
        self.assertIn("etape-001.png", content)
        self.assertIn("etape-002.png", content)
        self.assertTrue((out_dir / "images" / "etape-001.png").exists())
        self.assertTrue((out_dir / "images" / "etape-002.png").exists())

    def test_export_markdown_escapes_special_characters(self):
        self.steps[0].description = "Cliquez sur *Fichier* [ici]"
        out_dir = self.tmp / "export_md2"
        md_path = exp.export_markdown(self.steps, "Titre", out_dir)
        content = md_path.read_text(encoding="utf-8")
        self.assertNotIn("*Fichier*", content)
        self.assertIn("\\*Fichier\\*", content)

    def test_export_uses_default_description_when_empty(self):
        out = self.tmp / "guide.html"
        exp.export_html(self.steps, "Titre", out)
        content = out.read_text(encoding="utf-8")
        self.assertIn("Bloc-notes", content)  # description par defaut de l'etape 2


if __name__ == "__main__":
    unittest.main()
