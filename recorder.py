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

from capture import get_window_at_point, get_window_title_at_point


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
    `after()`), jamais lus directement depuis le thread d'ecoute. Les erreurs
    (capture ou ecriture echouee) sont deposees dans `capture_errors`, a
    afficher a l'utilisateur plutot qu'a laisser disparaitre silencieusement.

    Important : le callback appele par pynput (_on_click) s'execute dans le
    hook systeme bas-niveau de la souris. Windows impose un delai maximum de
    reponse a ce genre de callback ; y faire de l'encodage PNG et de
    l'ecriture disque directement risquerait de perdre des clics (voire de
    faire desactiver le hook par l'OS sur une machine lente). Seuls ces deux
    travaux lents (encodage PNG, ecriture disque) sont donc deportes vers le
    thread d'ecriture separe (_writer_loop), via _save_queue.

    La capture d'ecran elle-meme (ImageGrab.grab, voir _grab_screenshot)
    reste en revanche appelee de facon SYNCHRONE, directement dans le
    callback, avant toute delegation : c'est volontaire, pas un oubli - le
    moment exact de la capture doit rester solidaire de celui du clic. La
    deporter vers le thread d'ecriture changerait ce qui est effectivement
    capture (l'ecran au moment ou le thread traite la file, potentiellement
    plus tard si elle a du retard, plutot qu'au moment reel du clic)."""

    def __init__(self, session_dir: Path, excluded_hwnds: frozenset = frozenset()):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue = queue.Queue()
        self.capture_errors: queue.Queue = queue.Queue()
        self._save_queue: queue.Queue = queue.Queue()
        self._listener = None
        self._active = False
        self._paused = False
        self._counter = 0
        self._shut_down = False
        # Fenetres (HWND) a ignorer : nos propres fenetres (ex: le bouton
        # "Arreter l'enregistrement"), pour ne pas polluer le guide d'une
        # etape parasite montrant l'utilisateur en train d'arreter l'outil.
        self.excluded_hwnds = frozenset(excluded_hwnds)
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if self._shut_down:
            raise RuntimeError("Ce Recorder a deja ete arrete definitivement (shutdown) ; creez-en un nouveau.")
        if self._active:
            return
        self._active = True
        self._paused = False
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.start()

    def pause(self) -> None:
        """Suspend temporairement la capture des clics sans arreter
        l'ecoute globale ni le thread d'ecriture : contrairement a stop(),
        l'enregistrement peut reprendre ensuite avec resume() en gardant le
        meme session_dir et le meme compteur d'etapes (aucune renumerotation,
        aucune perte de la progression deja capturee)."""
        if self._active:
            self._paused = True

    def resume(self) -> None:
        if self._active:
            self._paused = False

    def stop(self) -> None:
        self._active = False
        self._paused = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def wait_for_pending_saves(self, timeout: float = 8.0) -> bool:
        """Attend que toutes les captures encore en attente d'ecriture disque
        soient traitees, pour ne perdre aucune etape prise juste avant l'arret.
        A appeler apres stop(), avant de considerer la session terminee.
        Renvoie False si le delai est depasse (l'appelant doit alors prevenir
        l'utilisateur qu'une etape pourrait manquer, plutot que de continuer
        silencieusement comme si tout avait ete sauvegarde).

        Utilise `unfinished_tasks` plutot que `empty()` : `empty()` redevient
        vrai des qu'un element est retire de la file par `get()`, mais AVANT
        que le thread d'ecriture ait fini de l'ecrire sur le disque et de le
        deposer dans `events` - une simple verification de `empty()` peut
        donc renvoyer trop tot et faire perdre la derniere etape capturee."""
        deadline = time.time() + timeout
        while self._save_queue.unfinished_tasks > 0 and time.time() < deadline:
            time.sleep(0.02)
        return self._save_queue.unfinished_tasks == 0

    def shutdown(self) -> None:
        """Arrete definitivement le thread d'ecriture (fin de vie du Recorder).
        Bloque jusqu'a ce que le thread ait reellement termine, pour un arret
        deterministe (utile notamment dans les tests). Ce Recorder ne peut
        plus etre redemarre ensuite (voir start())."""
        self.stop()
        self._shut_down = True
        self.wait_for_pending_saves()
        if self._writer_thread.is_alive():
            self._save_queue.put(None)
            self._writer_thread.join(timeout=2.0)

    def _on_click(self, x, y, button, pressed):
        # Ne reagit qu'au clic gauche, uniquement a l'enfoncement (pas au
        # relachement, pour eviter un doublon par clic). Reste volontairement
        # tres court : la capture elle-meme (rapide) est faite ici, mais tout
        # le travail lent (encodage, ecriture disque) est delegue.
        if not self._active or self._paused or button not in (mouse.Button.left, mouse.Button.right) or not pressed:
            return
        try:
            if self.excluded_hwnds and get_window_at_point(x, y) in self.excluded_hwnds:
                return  # clic sur notre propre fenetre (ex: bouton Arreter) : ignore
            self._counter += 1
            idx = self._counter
            screenshot = _grab_screenshot()
        except Exception as exc:  # noqa: BLE001 - callback de hook systeme :
            # une exception non geree ici tuerait le thread d'ecoute pynput
            # sans que rien ne le signale a l'utilisateur (meme categorie de
            # bug que les deux deja corriges dans ce projet). On avale
            # l'exception, on la remonte via capture_errors, et le clic
            # suivant continue d'etre traite normalement.
            self._counter = max(0, self._counter - 1)
            self.capture_errors.put(f"Capture d'un clic echouee : {exc}")
            return
        self._save_queue.put({
            "index": idx,
            "image": screenshot,
            "click_x": x,
            "click_y": y,
            "button": "left" if button == mouse.Button.left else "right",
            "window_title": get_window_title_at_point(x, y),
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
                self.events.put({
                    "index": idx,
                    "raw_image_path": raw_path,
                    "click_x": item["click_x"],
                    "click_y": item["click_y"],
                    "button": item["button"],
                    "window_title": item["window_title"],
                    "timestamp": item["timestamp"],
                })
            except Exception as exc:  # noqa: BLE001 - une etape en echec ne doit
                # jamais arreter le thread d'ecriture : les etapes suivantes
                # doivent continuer a etre traitees normalement.
                self.capture_errors.put(f"Etape {idx} non enregistree : {exc}")
            finally:
                self._save_queue.task_done()
