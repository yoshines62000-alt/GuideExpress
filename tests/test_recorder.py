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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pynput import mouse
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


if __name__ == "__main__":
    unittest.main()
