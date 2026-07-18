"""Enregistreur de session GuideExpress.

Isole tout ce qui touche au systeme (ecoute globale des clics, capture d'ecran,
thread en arriere-plan) du reste du code. La logique de rendu/export pure vit
dans capture.py et export.py, sans dependance a ce module.

Confidentialite : seule la position des clics de souris et une capture d'ecran
sont enregistrees. Aucune frappe clavier n'est jamais interceptee.
"""

from __future__ import annotations

import queue
import time
from pathlib import Path

from PIL import ImageGrab
from pynput import mouse

from capture import get_active_window_title


class Recorder:
    """Ecoute les clics gauche globaux et sauvegarde une capture d'ecran brute
    pour chacun. Les evenements sont deposes dans une file thread-safe (`events`)
    a consommer depuis le thread principal (ex: via Tk `after()`), jamais lus
    directement depuis le thread d'ecoute."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue = queue.Queue()
        self._listener = None
        self._active = False
        self._counter = 0

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.start()

    def stop(self) -> None:
        self._active = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x, y, button, pressed):
        # Ne reagit qu'au clic gauche, uniquement a l'enfoncement (pas au
        # relachement, pour eviter un doublon par clic).
        if not self._active or button != mouse.Button.left or not pressed:
            return
        self._counter += 1
        idx = self._counter
        try:
            screenshot = ImageGrab.grab()
        except OSError:
            self._counter -= 1
            return
        raw_path = self.session_dir / f"step_{idx:04d}_raw.png"
        screenshot.save(raw_path)
        self.events.put({
            "index": idx,
            "raw_image_path": raw_path,
            "click_x": x,
            "click_y": y,
            "window_title": get_active_window_title(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
