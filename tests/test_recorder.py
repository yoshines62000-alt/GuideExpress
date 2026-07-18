"""Tests pour recorder.py : l'ecriture disque est deleguee a un thread separe
(pour ne jamais bloquer le callback du hook souris bas-niveau), ces tests
verifient que ce decouplage ne perd ni ne desordonne aucune etape.

Le vrai crochet global pynput n'est jamais declenche ici : on appelle
directement `_on_click`, ce qui exerce toute la logique du Recorder sans
accrocher la souris reelle de la machine qui fait tourner les tests.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pynput import mouse
import recorder as recorder_mod
from recorder import Recorder


class RecorderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.recorder = Recorder(self.tmp / "session")
        self.addCleanup(self.recorder.shutdown)
        self.recorder._active = True  # simule start() sans le vrai hook systeme

    def _left_click(self, x, y):
        self.recorder._on_click(x, y, mouse.Button.left, True)
        self.recorder._on_click(x, y, mouse.Button.left, False)  # relachement, ignore

    def test_only_left_button_press_creates_a_step(self):
        self.recorder._on_click(10, 10, mouse.Button.right, True)
        self.recorder._on_click(10, 10, mouse.Button.left, False)
        self.recorder.wait_for_pending_saves()
        self.assertEqual(self.recorder.events.qsize(), 0)

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

    def test_wait_for_pending_saves_returns_once_queue_is_drained(self):
        self._left_click(1, 1)
        self._left_click(2, 2)
        start = time.time()
        self.recorder.wait_for_pending_saves(timeout=5.0)
        elapsed = time.time() - start
        self.assertTrue(self.recorder._save_queue.empty())
        self.assertLess(elapsed, 5.0)  # ne doit pas attendre le timeout complet

    def test_shutdown_stops_writer_thread_cleanly(self):
        self._left_click(5, 5)
        self.recorder.shutdown()
        self.assertFalse(self.recorder._writer_thread.is_alive())


class ExcludedWindowsTestCase(unittest.TestCase):
    """Un clic sur nos propres fenetres (ex: le bouton Arreter du HUD flottant)
    ne doit jamais devenir une etape parasite du guide, quel que soit l'etat
    du focus au moment du clic (voir get_window_at_point : verifie la fenetre
    physiquement sous le curseur, pas la fenetre qui a le focus)."""

    def setUp(self):
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
