"""Tests pour export.py : generation des guides HTML/Markdown."""

import base64
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

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

    def test_export_markdown_escapes_title(self):
        # Le titre est saisi librement par l'utilisateur (Entry Tkinter),
        # tout comme les descriptions d'etape : il doit etre echappe de la
        # meme facon, pas seulement les descriptions.
        out_dir = self.tmp / "export_md3"
        md_path = exp.export_markdown(self.steps, "Guide *important* [confidentiel]", out_dir)
        content = md_path.read_text(encoding="utf-8")
        self.assertNotIn("# Guide *important* [confidentiel]", content)
        self.assertIn("\\*important\\*", content)
        self.assertIn("\\[confidentiel\\]", content)

    def test_export_uses_default_description_when_empty(self):
        out = self.tmp / "guide.html"
        exp.export_html(self.steps, "Titre", out)
        content = out.read_text(encoding="utf-8")
        self.assertIn("Bloc-notes", content)  # description par defaut de l'etape 2

    def test_export_html_respects_per_step_zoom_flag(self):
        # Une image assez grande pour qu'un recadrage zoome soit vraiment
        # plus petit que l'image complete (voir capture._crop_zoomed_region,
        # half_size=260 -> recadre a 520x520 max).
        big_raw = self.tmp / "big_raw.png"
        Image.new("RGB", (1000, 1000), color=(5, 5, 5)).save(big_raw)
        zoomed_step = cap.Step(
            index=1, raw_image_path=big_raw, click_x=500, click_y=500,
            window_title="Fenetre", timestamp="t1", zoom=True,
        )
        flat_step = cap.Step(
            index=2, raw_image_path=big_raw, click_x=500, click_y=500,
            window_title="Fenetre", timestamp="t2", zoom=False,
        )
        zoomed_png = exp._step_to_png_bytes(zoomed_step, zoom=zoomed_step.zoom)
        flat_png = exp._step_to_png_bytes(flat_step, zoom=flat_step.zoom)

        zoomed_img = Image.open(__import__("io").BytesIO(zoomed_png))
        flat_img = Image.open(__import__("io").BytesIO(flat_png))
        self.assertEqual(zoomed_img.size, (520, 520))
        self.assertEqual(flat_img.size, (1000, 1000))

    def test_export_markdown_uses_step_zoom_setting(self):
        big_raw = self.tmp / "big_raw2.png"
        Image.new("RGB", (1000, 1000), color=(5, 5, 5)).save(big_raw)
        zoomed_step = cap.Step(
            index=1, raw_image_path=big_raw, click_x=500, click_y=500,
            window_title="Fenetre", timestamp="t1", zoom=True,
        )
        out_dir = self.tmp / "export_zoom_md"
        exp.export_markdown([zoomed_step], "Titre", out_dir)
        with Image.open(out_dir / "images" / "etape-001.png") as img:
            self.assertEqual(img.size, (520, 520))

    def test_export_pdf_generates_one_page_per_step(self):
        out = self.tmp / "guide.pdf"
        exp.export_pdf(self.steps, "Mon Guide PDF", out)
        self.assertTrue(out.exists())
        content = out.read_bytes()
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(len(PdfReader(str(out)).pages), len(self.steps))

    def test_export_pdf_with_no_steps_still_produces_a_valid_file(self):
        out = self.tmp / "guide_vide.pdf"
        exp.export_pdf([], "Guide vide", out)
        self.assertTrue(out.exists())
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_export_pdf_with_non_latin1_description_does_not_crash(self):
        self.steps[0].description = "Étape spéciale — “test” ✨ 中文"
        out = self.tmp / "guide_unicode.pdf"
        exp.export_pdf(self.steps, "Titre", out)
        self.assertTrue(out.exists())
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_export_pdf_respects_per_step_zoom_flag(self):
        big_raw = self.tmp / "big_raw3.png"
        Image.new("RGB", (1000, 1000), color=(5, 5, 5)).save(big_raw)
        zoomed_step = cap.Step(
            index=1, raw_image_path=big_raw, click_x=500, click_y=500,
            window_title="Fenetre", timestamp="t1", zoom=True,
        )
        flat_step = cap.Step(
            index=2, raw_image_path=big_raw, click_x=500, click_y=500,
            window_title="Fenetre", timestamp="t2", zoom=False,
        )
        out = self.tmp / "guide_zoom.pdf"
        exp.export_pdf([zoomed_step, flat_step], "Titre", out)
        reader = PdfReader(str(out))
        zoomed_width = reader.pages[0].mediabox.width
        flat_width = reader.pages[1].mediabox.width
        # La page zoomee (recadree a 520px) doit etre nettement plus etroite
        # que la page non zoomee (recadree seulement a la largeur max de page).
        self.assertLess(zoomed_width, flat_width)

    def test_reexport_to_same_directory_removes_stale_images(self):
        # Un premier export avec 2 etapes, puis un reexport (meme dossier)
        # avec une seule etape : l'image de l'ancienne etape 2 ne doit pas
        # trainer indefiniment dans le dossier images/.
        out_dir = self.tmp / "export_reexport"
        exp.export_markdown(self.steps, "Guide complet", out_dir)
        self.assertTrue((out_dir / "images" / "etape-002.png").exists())

        exp.export_markdown(self.steps[:1], "Guide raccourci", out_dir)
        self.assertTrue((out_dir / "images" / "etape-001.png").exists())
        self.assertFalse((out_dir / "images" / "etape-002.png").exists())


if __name__ == "__main__":
    unittest.main()
