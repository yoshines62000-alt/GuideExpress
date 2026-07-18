"""Tests de la logique pure de capture.py (rendu, reordonnancement, echappement).

Aucun test ici ne depend d'un vrai clic souris ou d'une vraie capture d'ecran :
les images de test sont generees en memoire (PIL.Image.new), pour rester rapides
et deterministes.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap


class RenderStepImageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)
        self.raw_path = self.tmp / "raw.png"
        Image.new("RGB", (400, 300), color=(255, 255, 255)).save(self.raw_path)

    def _cleanup(self):
        pass

    def _step(self, **overrides):
        defaults = dict(
            index=1,
            raw_image_path=self.raw_path,
            click_x=200,
            click_y=150,
            window_title="Bloc-notes",
            timestamp="2026-01-01 10:00:00",
        )
        defaults.update(overrides)
        return cap.Step(**defaults)

    def test_render_does_not_modify_raw_file_on_disk(self):
        original_bytes = self.raw_path.read_bytes()
        step = self._step()
        cap.render_step_image(step)
        cap.render_step_image(step, zoom=True)
        self.assertEqual(self.raw_path.read_bytes(), original_bytes)

    def test_click_marker_is_drawn_at_click_position(self):
        step = self._step(click_x=200, click_y=150)
        img = cap.render_step_image(step)
        # Le contour du marqueur (cercle rouge) doit apparaitre a une distance
        # du centre egale a peu pres au rayon configure.
        r = cap.CLICK_MARKER_RADIUS
        pixel_on_ring = img.getpixel((200 + r, 150))
        self.assertEqual(pixel_on_ring, cap.CLICK_MARKER_COLOR)
        # Le centre exact du clic, lui, ne doit pas etre repeint (cercle = contour
        # non rempli), pour ne pas cacher ce sur quoi l'utilisateur a clique.
        pixel_at_center = img.getpixel((200, 150))
        self.assertNotEqual(pixel_at_center, cap.CLICK_MARKER_COLOR)

    def test_redaction_produces_solid_opaque_block(self):
        step = self._step(redactions=[(50, 50, 150, 120)])
        img = cap.render_step_image(step)
        for point in [(60, 60), (100, 90), (140, 110)]:
            self.assertEqual(img.getpixel(point), cap.REDACTION_COLOR)
        # En dehors du rectangle : image blanche d'origine, non affectee.
        self.assertEqual(img.getpixel((350, 250)), (255, 255, 255))

    def test_redaction_handles_reversed_coordinates(self):
        # L'utilisateur peut dessiner le rectangle de redaction dans n'importe
        # quel sens (glisser de droite a gauche, de bas en haut).
        step = self._step(redactions=[(150, 120, 50, 50)])
        img = cap.render_step_image(step)
        self.assertEqual(img.getpixel((100, 90)), cap.REDACTION_COLOR)

    def test_zoom_crops_around_click(self):
        # Image plus petite que la fenetre de recadrage : aucun recadrage
        # possible, l'image entiere est renvoyee (comportement du code pour
        # ce cas, deja verifie par les bornes ci-dessous).
        step = self._step(click_x=200, click_y=150)
        img = cap.render_step_image(step, zoom=True)
        self.assertLessEqual(img.width, 400)
        self.assertLessEqual(img.height, 300)

    def test_zoom_crop_math_near_corners_and_center(self):
        # Image nettement plus grande que la fenetre de recadrage : exerce
        # reellement le calcul de bornes (evite les coordonnees negatives ou
        # une zone de recadrage qui deborderait de l'image, notamment pour un
        # clic tout pres d'un coin).
        big_raw = self.tmp / "big.png"
        Image.new("RGB", (1000, 800), color=(0, 128, 255)).save(big_raw)
        expected_size = 2 * 260  # cf. capture._crop_zoomed_region half_size par defaut

        for cx, cy in [(5, 5), (995, 795), (500, 400), (0, 0), (999, 799)]:
            step = self._step(raw_image_path=big_raw, click_x=cx, click_y=cy)
            img = cap.render_step_image(step, zoom=True)
            self.assertEqual(img.size, (expected_size, expected_size), f"echec pour le clic ({cx},{cy})")

    def test_default_description_mentions_window_title(self):
        step = self._step(window_title="Google Chrome")
        self.assertIn("Google Chrome", step.default_description())

    def test_display_description_falls_back_to_default_when_empty(self):
        step = self._step(window_title="Explorateur de fichiers", description="   ")
        self.assertEqual(step.display_description(), step.default_description())

    def test_display_description_uses_custom_text_when_set(self):
        step = self._step(description="Ouvrez le menu Fichier")
        self.assertEqual(step.display_description(), "Ouvrez le menu Fichier")

    def test_render_raises_a_clear_error_when_raw_file_is_missing(self):
        # Le fichier de capture brute peut avoir ete supprime/deplace apres
        # l'enregistrement (nettoyage manuel du dossier de session). L'appelant
        # (gui.py) attrape (OSError, ValueError) : verifie que c'est bien le
        # type d'exception effectivement leve, pas un type inattendu.
        step = self._step(raw_image_path=self.tmp / "n_existe_pas.png")
        with self.assertRaises((OSError, ValueError)):
            cap.render_step_image(step)


class ReorderingTestCase(unittest.TestCase):
    def _steps(self, n):
        return [
            cap.Step(index=i, raw_image_path=Path("x"), click_x=0, click_y=0,
                     window_title="w", timestamp="t")
            for i in range(1, n + 1)
        ]

    def test_move_step_up(self):
        steps = self._steps(3)
        original_second = steps[1]
        cap.move_step(steps, 1, -1)
        self.assertIs(steps[0], original_second)
        self.assertEqual([s.index for s in steps], [1, 2, 3])

    def test_move_step_down(self):
        steps = self._steps(3)
        original_first = steps[0]
        cap.move_step(steps, 0, +1)
        self.assertIs(steps[1], original_first)

    def test_move_first_step_up_is_a_no_op(self):
        steps = self._steps(3)
        before = list(steps)
        cap.move_step(steps, 0, -1)
        self.assertEqual(steps, before)

    def test_move_last_step_down_is_a_no_op(self):
        steps = self._steps(3)
        before = list(steps)
        cap.move_step(steps, len(steps) - 1, +1)
        self.assertEqual(steps, before)

    def test_move_step_to_moves_directly_to_target_position(self):
        steps = self._steps(5)
        original_first = steps[0]
        cap.move_step_to(steps, 0, 3)
        self.assertEqual(steps.index(original_first), 3)
        self.assertEqual([s.index for s in steps], [1, 2, 3, 4, 5])

    def test_move_step_to_moving_backward_shifts_others_down(self):
        steps = self._steps(5)
        original_last = steps[4]
        cap.move_step_to(steps, 4, 0)
        self.assertIs(steps[0], original_last)
        self.assertEqual([s.index for s in steps], [1, 2, 3, 4, 5])

    def test_move_step_to_same_index_is_a_no_op(self):
        steps = self._steps(3)
        before = list(steps)
        cap.move_step_to(steps, 1, 1)
        self.assertEqual(steps, before)

    def test_move_step_to_rejects_out_of_range_indices(self):
        steps = self._steps(3)
        before = list(steps)
        cap.move_step_to(steps, 0, 10)
        self.assertEqual(steps, before)
        cap.move_step_to(steps, -1, 1)
        self.assertEqual(steps, before)

    def test_delete_step_renumbers_remaining(self):
        steps = self._steps(4)
        cap.delete_step(steps, 1)  # supprime l'etape d'index 2
        self.assertEqual(len(steps), 3)
        self.assertEqual([s.index for s in steps], [1, 2, 3])

    def test_delete_out_of_range_is_a_no_op(self):
        steps = self._steps(2)
        cap.delete_step(steps, 99)
        self.assertEqual(len(steps), 2)


class EscapingTestCase(unittest.TestCase):
    def test_markdown_escape_neutralizes_special_characters(self):
        text = "Cliquez sur *Fichier* puis [Ouvrir](menu) - #1"
        escaped = cap.escape_markdown(text)
        self.assertNotIn("*Fichier*", escaped)
        self.assertIn("\\*Fichier\\*", escaped)
        self.assertIn("\\[Ouvrir\\]\\(menu\\)", escaped)

    def test_html_escape_neutralizes_tags(self):
        text = "<script>alert(1)</script> & \"citation\""
        escaped = cap.html_escape(text)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;script&gt;", escaped)
        self.assertIn("&amp;", escaped)
        self.assertIn("&quot;", escaped)


class SanitizeFilenameTestCase(unittest.TestCase):
    def test_replaces_invalid_windows_filename_characters(self):
        result = cap.sanitize_filename('Guide: "Config" <prod>/backup\\test*?|')
        for bad_char in '<>:"/\\|?*':
            self.assertNotIn(bad_char, result)

    def test_falls_back_to_default_when_empty(self):
        self.assertEqual(cap.sanitize_filename(""), "guide")
        self.assertEqual(cap.sanitize_filename("   "), "guide")

    def test_leaves_normal_titles_unchanged(self):
        self.assertEqual(cap.sanitize_filename("Guide utilisateur 2026"), "Guide utilisateur 2026")

    def test_windows_reserved_device_names_are_suffixed(self):
        # CON, NUL, COM1... sont invalides comme nom de fichier/dossier
        # Windows meme sans aucun caractere par ailleurs interdit.
        for reserved in ("CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            result = cap.sanitize_filename(reserved)
            self.assertNotEqual(result.upper(), reserved.upper(), f"echec pour {reserved!r}")

    def test_name_containing_reserved_word_is_not_affected(self):
        # Seul le nom EXACT est reserve ; un titre qui le contient simplement
        # ne doit pas etre modifie inutilement.
        self.assertEqual(cap.sanitize_filename("Configuration"), "Configuration")


class WindowLookupErrorHandlingTestCase(unittest.TestCase):
    """Les appels Win32 (ctypes) doivent degrader proprement (chaine vide /
    0) si l'OS renvoie une erreur, plutot que de laisser l'exception se
    propager jusque dans le thread d'ecoute globale des clics."""

    def test_get_window_at_point_returns_zero_on_os_error(self):
        with mock.patch.object(cap, "_user32") as mock_user32:
            mock_user32.WindowFromPoint.side_effect = OSError("echec simule")
            self.assertEqual(cap.get_window_at_point(10, 10), 0)

    def test_get_window_title_at_point_returns_empty_string_on_error(self):
        with mock.patch.object(cap, "_user32") as mock_user32:
            mock_user32.WindowFromPoint.side_effect = OSError("echec simule")
            self.assertEqual(cap.get_window_title_at_point(10, 10), "")

    def test_get_window_text_returns_empty_string_when_user32_unavailable(self):
        with mock.patch.object(cap, "_user32", None):
            self.assertEqual(cap._get_window_text(12345), "")

    def test_get_window_at_point_returns_zero_when_user32_unavailable(self):
        with mock.patch.object(cap, "_user32", None):
            self.assertEqual(cap.get_window_at_point(10, 10), 0)


if __name__ == "__main__":
    unittest.main()
