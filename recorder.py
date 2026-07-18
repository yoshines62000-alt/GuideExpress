"""Enregistreur de session GuideExpress.

Isole tout ce qui touche au systeme (ecoute globale des clics, capture d'ecran,
threads en arriere-plan) du reste du code. La logique de rendu/export pure vit
dans capture.py et export.py, sans dependance a ce module.

Confidentialite : seule la position des clics de souris et une capture d'ecran
sont enregistrees. Aucune frappe clavier n'est jamais interceptee.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from PIL import ImageGrab
from pynput import mouse

from capture import get_active_window_title


def _grab_screenshot():
    """Capture l'ecran (tous les moniteurs si possible). Le clic peut avoir
    lieu sur n'importe quel ecran d'une configuration multi-ecrans ; les
    coordonnees fournies par pynput sont deja dans le repere du bureau
    virtuel complet, donc la capture doit l'etre aussi."""
    try:
        return ImageGrab.grab(all_screens=True)
    except TypeError:
        # Anciennes versions de Pillow sans le parametre all_screens.
        return ImageGrab.grab()


class Recorder:
    """Ecoute les clics gauche globaux et sauvegarde une capture d'ecran brute
    pour chacun. Les evenements finalises sont deposes dans une file
    thread-safe (`events`) a consommer depuis le thread principal (ex: via Tk
    `after()`), jamais lus directement depuis le thread d'ecoute.

    Important : le callback appele par pynput s'execute dans le hook systeme
    bas-niveau de la souris. Windows impose un delai maximum de reponse a ce
    genre de callback ; y faire de l'encodage PNG et de l'ecriture disque
    directement risquerait de perdre des clics (voire de faire desactiver le
    hook par l'OS sur une machine lente). Le callback se contente donc de
    saisir la capture en memoire et de la deleguer immediatement a un thread
    d'ecriture separe."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue = queue.Queue()
        self._save_queue: queue.Queue = queue.Queue()
        self._listener = None
        self._active = False
        self._counter = 0
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

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

    def wait_for_pending_saves(self, timeout: float = 3.0) -> None:
        """Attend que toutes les captures encore en attente d'ecriture disque
        soient traitees, pour ne perdre aucune etape prise juste avant l'arret.
        A appeler apres stop(), avant de considerer la session terminee.

        Utilise `unfinished_tasks` plutot que `empty()` : `empty()` redevient
        vrai des qu'un element est retire de la file par `get()`, mais AVANT
        que le thread d'ecriture ait fini de l'ecrire sur le disque et de le
        deposer dans `events` - une simple verification de `empty()` peut
        donc renvoyer trop tot et faire perdre la derniere etape capturee."""
        deadline = time.time() + timeout
        while self._save_queue.unfinished_tasks > 0 and time.time() < deadline:
            time.sleep(0.02)

    def shutdown(self) -> None:
        """Arrete definitivement le thread d'ecriture (fin de vie du Recorder).
        Bloque jusqu'a ce que le thread ait reellement termine, pour un arret
        deterministe (utile notamment dans les tests)."""
        self.stop()
        self.wait_for_pending_saves()
        if self._writer_thread.is_alive():
            self._save_queue.put(None)
            self._writer_thread.join(timeout=2.0)

    def _on_click(self, x, y, button, pressed):
        # Ne reagit qu'au clic gauche, uniquement a l'enfoncement (pas au
        # relachement, pour eviter un doublon par clic). Reste volontairement
        # tres court : la capture elle-meme (rapide) est faite ici, mais tout
        # le travail lent (encodage, ecriture disque) est delegue.
        if not self._active or button != mouse.Button.left or not pressed:
            return
        self._counter += 1
        idx = self._counter
        try:
            screenshot = _grab_screenshot()
        except OSError:
            self._counter -= 1
            return
        self._save_queue.put({
            "index": idx,
            "image": screenshot,
            "click_x": x,
            "click_y": y,
            "window_title": get_active_window_title(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _writer_loop(self):
        while True:
            item = self._save_queue.get()
            if item is None:
                self._save_queue.task_done()
                break
            idx = item["index"]
            raw_path = self.session_dir / f"step_{idx:04d}_raw.png"
            try:
                item["image"].save(raw_path)
            except OSError:
                self._save_queue.task_done()
                continue
            self.events.put({
                "index": idx,
                "raw_image_path": raw_path,
                "click_x": item["click_x"],
                "click_y": item["click_y"],
                "window_title": item["window_title"],
                "timestamp": item["timestamp"],
            })
            self._save_queue.task_done()
