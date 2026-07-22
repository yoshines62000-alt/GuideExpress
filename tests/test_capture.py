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

    def test_right_click_marker_uses_a_distinct_color(self):
        step = self._step(click_x=200, click_y=150, button="right")
        img = cap.render_step_image(step)
        r = cap.CLICK_MARKER_RADIUS
        pixel_on_ring = img.getpixel((200 + r, 150))
        self.assertEqual(pixel_on_ring, cap.RIGHT_CLICK_MARKER_COLOR)
        self.assertNotEqual(cap.RIGHT_CLICK_MARKER_COLOR, cap.CLICK_MARKER_COLOR)

    def test_left_click_default_description_mentions_left_click_only(self):
        step = self._step(window_title="Bloc-notes")
        self.assertEqual(step.default_description(), "Cliquez dans Bloc-notes.")

    def test_right_click_default_description_mentions_right_click(self):
        step = self._step(window_title="Bloc-notes", button="right")
        self.assertEqual(step.default_description(), "Cliquez droit dans Bloc-notes.")

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


class RenderStepThumbnailTestCase(unittest.TestCase):
    """Trouvaille d'audit, dimension 16 : le marqueur de clic doit rester
    nettement visible dans la miniature de l'ecran de relecture, meme apres
    une forte reduction, sans changer la fidelite du rendu pleine resolution
    utilise par l'export et l'editeur de redaction (render_step_image,
    inchange par ce correctif)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.max_size = (220, 150)

    def _step(self, raw_image_path, **overrides):
        defaults = dict(
            index=1, raw_image_path=raw_image_path, click_x=800, click_y=450,
            window_title="Google Chrome", timestamp="2026-01-01 10:00:00",
        )
        defaults.update(overrides)
        return cap.Step(**defaults)

    def _marker_pixel_count(self, img, color):
        width, height = img.size
        return sum(
            1 for y in range(height) for x in range(width)
            if img.getpixel((x, y)) == color
        )

    def test_thumbnail_marker_stays_visible_on_a_highly_reduced_image(self):
        # Capture large (facteur de reduction ~7.3x vers 220x150) : avant ce
        # correctif, dessiner le marqueur en pleine resolution PUIS reduire
        # faisait tomber l'anneau a quelques pixels a peine (trouvaille
        # d'audit). THUMBNAIL_MARKER_RADIUS/WIDTH garantissent desormais une
        # taille minimale, independamment du facteur de reduction.
        raw_path = self.tmp / "big.png"
        Image.new("RGB", (1600, 900), color=(255, 255, 255)).save(raw_path)
        step = self._step(raw_path, click_x=800, click_y=450)
        thumb = cap.render_step_thumbnail(step, self.max_size)
        count = self._marker_pixel_count(thumb, cap.CLICK_MARKER_COLOR)
        # Anneau de rayon THUMBNAIL_MARKER_RADIUS/largeur THUMBNAIL_MARKER_WIDTH :
        # nettement plus que les quelques pixels obtenus par simple reduction
        # d'un marqueur pleine resolution (CLICK_MARKER_RADIUS=22 reduit par
        # ~7.3x donnerait un anneau d'environ 3px de rayon).
        self.assertGreater(count, 50)

    def test_thumbnail_size_never_exceeds_max_size(self):
        raw_path = self.tmp / "big.png"
        Image.new("RGB", (1600, 900), color=(255, 255, 255)).save(raw_path)
        step = self._step(raw_path)
        thumb = cap.render_step_thumbnail(step, self.max_size)
        self.assertLessEqual(thumb.width, self.max_size[0])
        self.assertLessEqual(thumb.height, self.max_size[1])

    def test_thumbnail_marker_uses_right_click_color_when_relevant(self):
        raw_path = self.tmp / "big.png"
        Image.new("RGB", (1600, 900), color=(255, 255, 255)).save(raw_path)
        step = self._step(raw_path, button="right")
        thumb = cap.render_step_thumbnail(step, self.max_size)
        count = self._marker_pixel_count(thumb, cap.RIGHT_CLICK_MARKER_COLOR)
        self.assertGreater(count, 50)

    def test_thumbnail_marker_visible_with_zoom_crop_too(self):
        # Le marqueur doit rester visible et rester attache a la position
        # reelle du clic meme apres le recadrage zoome (les coordonnees du
        # clic changent de repere une fois l'image recadree).
        raw_path = self.tmp / "big.png"
        Image.new("RGB", (1600, 900), color=(255, 255, 255)).save(raw_path)
        step = self._step(raw_path, click_x=800, click_y=450, zoom=True)
        thumb = cap.render_step_thumbnail(step, self.max_size, zoom=True)
        count = self._marker_pixel_count(thumb, cap.CLICK_MARKER_COLOR)
        self.assertGreater(count, 20)

    def test_thumbnail_leaves_raw_file_on_disk_unmodified(self):
        raw_path = self.tmp / "raw.png"
        Image.new("RGB", (400, 300), color=(255, 255, 255)).save(raw_path)
        original_bytes = raw_path.read_bytes()
        step = self._step(raw_path, click_x=200, click_y=150)
        cap.render_step_thumbnail(step, self.max_size)
        self.assertEqual(raw_path.read_bytes(), original_bytes)

    def test_thumbnail_raises_a_clear_error_when_raw_file_is_missing(self):
        step = self._step(self.tmp / "n_existe_pas.png")
        with self.assertRaises((OSError, ValueError)):
            cap.render_step_thumbnail(step, self.max_size)


class HudMonitorPositioningTestCase(unittest.TestCase):
    """Trouvaille d'audit, dimension 15 : positionnement du HUD sur le
    moniteur qui contient le curseur, plutot que systematiquement sur
    l'ecran principal Windows en configuration multi-ecrans."""

    def test_get_cursor_pos_returns_a_pair_of_ints_on_windows(self):
        pos = cap.get_cursor_pos()
        if pos is None:
            self.skipTest("GetCursorPos indisponible dans cet environnement")
        x, y = pos
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)

    def test_get_monitor_work_area_at_point_returns_a_sane_rectangle(self):
        area = cap.get_monitor_work_area_at_point(0, 0)
        if area is None:
            self.skipTest("GetMonitorInfoW indisponible dans cet environnement")
        left, top, right, bottom = area
        self.assertLess(left, right)
        self.assertLess(top, bottom)

    def test_get_cursor_pos_returns_none_on_os_error(self):
        with mock.patch.object(cap, "_user32") as mock_user32:
            mock_user32.GetCursorPos.side_effect = OSError("echec simule")
            self.assertIsNone(cap.get_cursor_pos())

    def test_get_cursor_pos_returns_none_when_user32_unavailable(self):
        with mock.patch.object(cap, "_user32", None):
            self.assertIsNone(cap.get_cursor_pos())

    def test_get_monitor_work_area_returns_none_on_os_error(self):
        with mock.patch.object(cap, "_user32") as mock_user32:
            mock_user32.MonitorFromPoint.side_effect = OSError("echec simule")
            self.assertIsNone(cap.get_monitor_work_area_at_point(0, 0))

    def test_get_monitor_work_area_returns_none_when_monitorinfo_unavailable(self):
        with mock.patch.object(cap, "_MONITORINFO", None):
            self.assertIsNone(cap.get_monitor_work_area_at_point(0, 0))


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

    def test_duplicate_step_inserts_copy_right_after_and_renumbers(self):
        steps = self._steps(3)
        original_second = steps[1]
        cap.duplicate_step(steps, 1)
        self.assertEqual(len(steps), 4)
        self.assertIs(steps[1], original_second)
        self.assertIsNot(steps[2], original_second)
        self.assertEqual(steps[2].raw_image_path, original_second.raw_image_path)
        self.assertEqual([s.index for s in steps], [1, 2, 3, 4])

    def test_duplicate_step_copies_description_and_zoom(self):
        steps = self._steps(2)
        steps[0].description = "Cliquez ici"
        steps[0].zoom = True
        cap.duplicate_step(steps, 0)
        self.assertEqual(steps[1].description, "Cliquez ici")
        self.assertTrue(steps[1].zoom)

    def test_duplicate_step_redactions_are_an_independent_copy(self):
        steps = self._steps(2)
        steps[0].redactions = [(1, 1, 2, 2)]
        cap.duplicate_step(steps, 0)
        steps[1].redactions.append((5, 5, 6, 6))
        self.assertEqual(steps[0].redactions, [(1, 1, 2, 2)])  # l'original n'est jamais touche
        self.assertEqual(steps[1].redactions, [(1, 1, 2, 2), (5, 5, 6, 6)])

    def test_duplicate_out_of_range_is_a_no_op(self):
        steps = self._steps(2)
        cap.duplicate_step(steps, 99)
        self.assertEqual(len(steps), 2)

    def test_duplicate_step_assigns_a_distinct_uid_to_the_copy(self):
        # Un uid distinct est ce qui permet a gui.py._retake_step d'isoler
        # le dossier de reprise de chaque etape : sans lui, reprendre l'une
        # des deux etapes ecraserait le fichier de reprise de l'autre (bug
        # trouve a l'audit, les deux etapes calculant le meme dossier de
        # reprise a partir du nom de fichier brut partage).
        steps = self._steps(2)
        original_uid = steps[0].uid
        cap.duplicate_step(steps, 0)
        self.assertNotEqual(steps[1].uid, original_uid)

    def test_each_captured_step_gets_a_distinct_uid_by_default(self):
        steps = self._steps(3)
        uids = {s.uid for s in steps}
        self.assertEqual(len(uids), 3)


class SessionSerializationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.session_dir = self.tmp / "session"
        self.session_dir.mkdir()

    def _step(self, **overrides):
        raw_path = self.session_dir / "step_0001_raw.png"
        raw_path.write_bytes(b"fake-png")
        defaults = dict(
            index=1, raw_image_path=raw_path, click_x=10, click_y=20,
            window_title="Bloc-notes", timestamp="2026-01-01 10:00:00",
            description="Cliquez ici", redactions=[(1, 2, 3, 4)], zoom=True,
        )
        defaults.update(overrides)
        return cap.Step(**defaults)

    def test_round_trip_preserves_all_fields(self):
        step = self._step(button="right")
        data = cap.step_to_dict(step, self.session_dir)
        restored = cap.step_from_dict(data, self.session_dir)
        self.assertEqual(restored.index, step.index)
        self.assertEqual(restored.raw_image_path, step.raw_image_path)
        self.assertEqual(restored.click_x, step.click_x)
        self.assertEqual(restored.click_y, step.click_y)
        self.assertEqual(restored.button, "right")
        self.assertEqual(restored.window_title, step.window_title)
        self.assertEqual(restored.description, step.description)
        self.assertEqual(restored.redactions, step.redactions)
        self.assertEqual(restored.zoom, step.zoom)
        self.assertEqual(restored.uid, step.uid)

    def test_raw_image_path_is_stored_relative_to_session_dir(self):
        step = self._step()
        data = cap.step_to_dict(step, self.session_dir)
        self.assertEqual(data["raw_image_path"], "step_0001_raw.png")
        self.assertNotIn(str(self.session_dir), data["raw_image_path"])

    def test_relative_path_resolves_correctly_under_a_retake_subfolder(self):
        retake_dir = self.session_dir / "retakes" / "abc123"
        retake_dir.mkdir(parents=True)
        raw_path = retake_dir / "step_0001_raw.png"
        raw_path.write_bytes(b"fake-png")
        step = self._step(raw_image_path=raw_path, uid="abc123")
        data = cap.step_to_dict(step, self.session_dir)
        self.assertEqual(data["raw_image_path"], str(Path("retakes") / "abc123" / "step_0001_raw.png"))
        restored = cap.step_from_dict(data, self.session_dir)
        self.assertEqual(restored.raw_image_path, raw_path)

    def test_from_dict_tolerates_unknown_keys(self):
        data = cap.step_to_dict(self._step(), self.session_dir)
        data["un_champ_du_futur"] = "peu importe"
        restored = cap.step_from_dict(data, self.session_dir)  # ne doit pas lever
        self.assertEqual(restored.index, 1)

    def test_from_dict_tolerates_missing_optional_keys(self):
        minimal = {"raw_image_path": "step_0001_raw.png"}
        restored = cap.step_from_dict(minimal, self.session_dir)
        self.assertEqual(restored.description, "")
        self.assertEqual(restored.redactions, [])
        self.assertFalse(restored.zoom)
        self.assertEqual(restored.button, "left")
        self.assertTrue(restored.uid)  # un uid est genere si absent

    def test_redactions_round_trip_as_tuples(self):
        step = self._step(redactions=[(1, 2, 3, 4), (5, 6, 7, 8)])
        data = cap.step_to_dict(step, self.session_dir)
        restored = cap.step_from_dict(data, self.session_dir)
        self.assertEqual(restored.redactions, [(1, 2, 3, 4), (5, 6, 7, 8)])
        for r in restored.redactions:
            self.assertIsInstance(r, tuple)


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

    def test_very_long_title_is_truncated(self):
        # Trouvaille d'audit, dimension 31 : un titre demesurement long,
        # combine a une destination d'export deja profonde, pourrait
        # approcher la limite historique MAX_PATH (260) de Windows pour un
        # chemin COMPLET.
        result = cap.sanitize_filename("A" * 500)
        self.assertLessEqual(len(result), cap._MAX_FILENAME_LENGTH)
        self.assertTrue(result)

    def test_truncation_does_not_leave_a_trailing_space_or_dot(self):
        # Couper au milieu d'un nom peut laisser un espace ou un point en fin
        # de chaine juste apres la troncature - egalement invalides comme
        # dernier caractere d'un nom de fichier/dossier Windows.
        name = "A" * (cap._MAX_FILENAME_LENGTH - 1) + "   .   trailing garbage"
        result = cap.sanitize_filename(name)
        self.assertFalse(result.endswith(" "))
        self.assertFalse(result.endswith("."))

    def test_short_titles_are_never_truncated(self):
        title = "Guide utilisateur assez long mais raisonnable pour un titre normal"
        self.assertLess(len(title), cap._MAX_FILENAME_LENGTH)
        self.assertEqual(cap.sanitize_filename(title), title)


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
