"""Tests pour recorder.py : l'ecriture disque est deleguee a un thread separe
(pour ne jamais bloquer le callback du hook souris bas-niveau), ces tests
verifient que ce decouplage ne perd ni ne desordonne aucune etape, et que
toute erreur (capture ou ecriture) est remontee plutot que de disparaitre.

Le vrai crochet global pynput n'est jamais declenche ici : on appelle
directement `_on_click`, ce qui exerce toute la logique du Recorder sans
accrocher la souris reelle de la machine qui fait tourner les tests. La
capture d'ecran elle-meme (`_grab_screenshot`) est simulee (image en memoire
minuscule) pour rester rapide et deterministe : un vrai ImageGrab.grab()
peut echouer ou se comporter differemment sur une machine sans session
graphique active (CI, bureau distant deconnecte).
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pynput import mouse
import recorder as recorder_mod
from recorder import Recorder


def _fake_screenshot():
    return Image.new("RGB", (20, 15), color=(0, 0, 0))


class RecorderTestBase(unittest.TestCase):
    """Simule _grab_screenshot pour tous les tests de ce module : rapide,
    deterministe, et ne depend jamais de l'etat reel de l'ecran."""

    def setUp(self):
        self._grab_patcher = mock.patch.object(recorder_mod, "_grab_screenshot", side_effect=_fake_screenshot)
        self._grab_patcher.start()
        self.addCleanup(self._grab_patcher.stop)


class RecorderTestCase(RecorderTestBase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.recorder = Recorder(self.tmp / "session")
        self.addCleanup(self.recorder.shutdown)
        self.recorder._active = True  # simule start() sans le vrai hook systeme

    def _left_click(self, x, y):
        self.recorder._on_click(x, y, mouse.Button.left, True)
        self.recorder._on_click(x, y, mouse.Button.left, False)  # relachement, ignore

    def test_release_does_not_create_a_step(self):
        self.recorder._on_click(10, 10, mouse.Button.left, False)
        self.recorder._on_click(10, 10, mouse.Button.right, False)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 0)

    def test_middle_button_is_ignored(self):
        self.recorder._on_click(10, 10, mouse.Button.middle, True)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 0)

    def test_left_button_press_creates_a_step_tagged_left(self):
        self._left_click(5, 5)
        self.recorder.wait_for_pending_saves()
        event = self.recorder.events.get()
        self.assertEqual(event["button"], "left")

    def test_right_button_press_creates_a_step_tagged_right(self):
        self.recorder._on_click(10, 10, mouse.Button.right, True)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 1)
        event = self.recorder.events.get()
        self.assertEqual(event["button"], "right")

    def test_rapid_clicks_are_all_saved_without_loss(self):
        for i in range(15):
            self._left_click(i * 10, i * 5)
        self.recorder.wait_for_pending_saves()

        collected = []
        while not self.recorder.events.empty():
            collected.append(self.recorder.events.get())
        self.assertEqual(len(collected), 15)

    def test_steps_are_saved_and_delivered_in_click_order(self):
        for i in range(8):
            self._left_click(i, i)
        self.recorder.wait_for_pending_saves()

        collected = []
        while not self.recorder.events.empty():
            collected.append(self.recorder.events.get())
        self.assertEqual([e["index"] for e in collected], list(range(1, 9)))

    def test_raw_screenshot_file_exists_after_wait(self):
        self._left_click(50, 50)
        self.recorder.wait_for_pending_saves()
        event = self.recorder.events.get()
        self.assertTrue(event["raw_image_path"].exists())

    def test_wait_for_pending_saves_returns_true_once_drained(self):
        self._left_click(1, 1)
        self._left_click(2, 2)
        start = time.time()
        result = self.recorder.wait_for_pending_saves(timeout=5.0)
        elapsed = time.time() - start
        self.assertTrue(result)
        self.assertTrue(self.recorder._save_queue.empty())
        self.assertLess(elapsed, 5.0)  # ne doit pas attendre le timeout complet

    def test_wait_for_pending_saves_returns_false_on_timeout(self):
        # Bloque le thread d'ecriture pour simuler une sauvegarde anormalement
        # lente (gros ecran multi-moniteurs, disque sature, antivirus...).
        # L'appelant doit pouvoir distinguer "tout est sauvegarde" de
        # "le delai est depasse" plutot que de supposer silencieusement le
        # premier cas.
        block_event = __import__("threading").Event()

        def blocking_save(img_self, path, *args, **kwargs):
            block_event.wait(timeout=2.0)

        with mock.patch.object(Image.Image, "save", blocking_save):
            self._left_click(1, 1)
            result = self.recorder.wait_for_pending_saves(timeout=0.2)
            self.assertFalse(result)
            block_event.set()

    def test_shutdown_stops_writer_thread_cleanly(self):
        self._left_click(5, 5)
        self.recorder.shutdown()
        self.assertFalse(self.recorder._writer_thread.is_alive())

    def test_start_after_shutdown_raises(self):
        self.recorder.shutdown()
        with self.assertRaises(RuntimeError):
            self.recorder.start()

    def test_pause_ignores_clicks_without_losing_counter_progress(self):
        self._left_click(1, 1)
        self.recorder.wait_for_pending_saves()
        self.recorder.pause()
        self.assertTrue(self.recorder.is_paused)
        self._left_click(2, 2)
        self._left_click(3, 3)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 1)  # les clics en pause sont ignores

    def test_resume_lets_clicks_resume_from_the_same_counter(self):
        self._left_click(1, 1)
        self.recorder.wait_for_pending_saves()
        self.recorder.pause()
        self._left_click(2, 2)  # ignore pendant la pause
        self.recorder.resume()
        self.assertFalse(self.recorder.is_paused)
        self._left_click(3, 3)
        self.recorder.wait_for_pending_saves()
        collected = []
        while not self.recorder.events.empty():
            collected.append(self.recorder.events.get())
        # Le compteur n'est jamais decremente par un clic ignore en pause :
        # la deuxieme etape reelle porte l'index 2, pas 3.
        self.assertEqual([e["index"] for e in collected], [1, 2])

    def test_pause_and_resume_are_no_ops_when_not_active(self):
        self.recorder._active = False
        self.recorder.pause()
        self.assertFalse(self.recorder.is_paused)
        self.recorder.resume()
        self.assertFalse(self.recorder.is_paused)

    def test_stop_clears_paused_state(self):
        self.recorder.pause()
        self.recorder.stop()
        self.assertFalse(self.recorder.is_paused)


class ErrorHandlingTestCase(RecorderTestBase):
    """Une erreur de capture ou d'ecriture ne doit jamais faire disparaitre
    silencieusement une etape ni casser le thread d'ecriture pour les etapes
    suivantes - c'est exactement la categorie des deux bugs deja corriges
    dans ce projet (ecriture bloquante dans le hook, condition de course)."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.recorder = Recorder(self.tmp / "session")
        self.addCleanup(self.recorder.shutdown)
        self.recorder._active = True

    def test_unexpected_exception_in_grab_is_reported_not_silent(self):
        with mock.patch.object(recorder_mod, "_grab_screenshot", side_effect=RuntimeError("boom")):
            self.recorder._on_click(1, 1, mouse.Button.left, True)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 0)
        self.assertEqual(self.recorder._counter, 0)  # le compteur n'avance pas sur un echec
        self.assertFalse(self.recorder.capture_errors.empty())

    def test_writer_survives_one_save_failure_and_processes_next_item(self):
        call_count = {"n": 0}
        real_save = Image.Image.save

        def flaky_save(self_img, path, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("disque plein (simule)")
            return real_save(self_img, path, *a, **kw)

        with mock.patch.object(Image.Image, "save", flaky_save):
            self.recorder._on_click(1, 1, mouse.Button.left, True)  # echouera
            self.recorder._on_click(2, 2, mouse.Button.left, True)  # doit reussir
            self.recorder.wait_for_pending_saves()

        self.assertEqual(self.recorder.events.qsize(), 1)  # seule la 2e etape arrive
        self.assertFalse(self.recorder.capture_errors.empty())
        self.assertTrue(self.recorder._writer_thread.is_alive())  # le thread n'est pas mort


class ExcludedWindowsTestCase(RecorderTestBase):
    """Un clic sur nos propres fenetres (ex: le bouton Arreter du HUD flottant)
    ne doit jamais devenir une etape parasite du guide, quel que soit l'etat
    du focus au moment du clic (voir get_window_at_point : verifie la fenetre
    physiquement sous le curseur, pas la fenetre qui a le focus)."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.recorder = Recorder(self.tmp / "session", excluded_hwnds=frozenset({999}))
        self.addCleanup(self.recorder.shutdown)
        self.recorder._active = True

    def test_click_on_excluded_window_creates_no_step(self):
        with mock.patch.object(recorder_mod, "get_window_at_point", return_value=999):
            self.recorder._on_click(10, 10, mouse.Button.left, True)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 0)
        self.assertEqual(self.recorder._counter, 0)

    def test_click_elsewhere_still_creates_a_step(self):
        with mock.patch.object(recorder_mod, "get_window_at_point", return_value=12345):
            self.recorder._on_click(10, 10, mouse.Button.left, True)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 1)

    def test_no_exclusion_when_excluded_hwnds_is_empty(self):
        recorder2 = Recorder(self.tmp / "session2")
        self.addCleanup(recorder2.shutdown)
        recorder2._active = True
        with mock.patch.object(recorder_mod, "get_window_at_point", return_value=0):
            recorder2._on_click(10, 10, mouse.Button.left, True)
        recorder2.wait_for_pending_saves()
        self.assertEqual(recorder2.events.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
