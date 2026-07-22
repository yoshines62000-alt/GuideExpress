"""Tests de fumee pour gui.py (Tk reel, jamais le vrai dossier
~/.guide_express de l'utilisateur - SESSIONS_DIR et LOG_PATH sont toujours
repointes vers un dossier temporaire avant toute construction de l'app ou
creation de session, meme motif que celui utilise pendant l'audit expert qui
a trouve les regressions couvertes ici).

Dimensions de l'audit du 2026-07-22 verrouillees ici :
- dimension 1 (Critique) : une SEULE image brute corrompue/illisible parmi
  les etapes d'une session ne doit plus interrompre la construction de tout
  l'ecran de relecture (UnidentifiedImageError non geree auparavant,
  app._export_buttons restait vide et l'utilisateur se retrouvait face a un
  ecran a moitie construit, sans aucun message).
- dimension 3 (Majeure) : session.json doit desormais etre ecrit de facon
  INCREMENTALE pendant l'enregistrement actif (pas seulement a l'arret), pour
  qu'un crash en cours de session reste au moins partiellement recuperable.
- dimension 4 (Moderee, traitee dans le meme correctif que la dimension 3) :
  l'ecriture de session.json doit etre atomique (fichier temporaire +
  os.replace), sans fichier .tmp residuel apres une sauvegarde normale.
- dimension 6 (Majeure) : la fenetre au premier plan executee a un niveau
  d'integrite superieur (UIPI/administrateur) doit declencher un
  avertissement explicite dans le HUD, plutot qu'un silence total sur les
  clics qui n'y seront jamais captures.
- dimension 7 (Majeure) : le processus doit etre rendu explicitement
  Per-Monitor V2 DPI Aware avant toute fenetre Tk.
- dimension 8 (Majeure) : a la taille minimale de fenetre EXACTEMENT
  declaree par l'application (self.minsize), les boutons d'action de chaque
  carte d'etape (notamment "Rediger" et "Supprimer") doivent rester
  entierement visibles - pas coupes par le bord droit de la fenetre, cachdes
  sous la barre de defilement verticale (regression partielle d'un bug deja
  "corrige" au commit 387c5b4).
- dimension 9 (Majeure) : la construction de l'ecran de relecture doit
  rendre la main a la boucle d'evenements Tk periodiquement sur une session
  volumineuse (curseur sablier + update_idletasks() toutes les N cartes),
  au lieu de geler totalement l'interface du debut a la fin.
- dimension 10 (Majeure, couverture de tests) : ce fichier lui-meme est la
  reponse a cette dimension - inclut notamment le test d'aller-retour complet
  _save_session_meta()/_reopen_session() suggere par le correctif propose.
"""

import json
import queue
import sys
import tempfile
import time
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap
import gui as gui_mod
from capture import Step


def _tk_available() -> bool:
    """Certains environnements d'execution (CI headless, session distante
    deconnectee) n'ont aucun serveur d'affichage disponible : Tk() y echoue a
    l'instanciation. Les tests de ce module exigent un Tk REEL (voir la
    methodologie de l'audit qui a trouve ces deux bugs - un mock de Tk
    n'aurait jamais reproduit ni le plantage de construction, ni le
    debordement geometrique des boutons), donc ils se desactivent proprement
    plutot que d'echouer bruyamment la ou aucun affichage n'existe."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


_TK_AVAILABLE = _tk_available()


def _valid_png_bytes(size=(1600, 900)) -> bytes:
    import io
    buf = io.BytesIO()
    Image.new("RGB", size, color=(200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


class _RealAppTestCase(unittest.TestCase):
    """Base commune : construit une vraie GuideExpressApp sans jamais
    toucher au vrai dossier de donnees utilisateur, ni faire de vrai appel
    reseau (verification de mise a jour), ni laisser une boite de dialogue
    bloquer le test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

        self._sessions_dir_patcher = mock.patch.object(gui_mod, "SESSIONS_DIR", self.tmp / "sessions")
        self._sessions_dir_patcher.start()
        self.addCleanup(self._sessions_dir_patcher.stop)

        # Le fichier de log (dimension 5) doit lui aussi rester dans le
        # dossier temporaire du test, jamais dans le vrai ~/.guide_express.
        self._log_path_patcher = mock.patch.object(gui_mod, "LOG_PATH", self.tmp / "logs" / "guideexpress.log")
        self._log_path_patcher.start()
        self.addCleanup(self._log_path_patcher.stop)

        # Pas de vrai appel reseau (GitHub) pendant les tests.
        self._update_check_patcher = mock.patch.object(gui_mod.update_checker, "start_update_check")
        self._update_check_patcher.start()
        self.addCleanup(self._update_check_patcher.stop)

        self.mocks = {}
        for name in ("showinfo", "showwarning", "showerror", "askyesno"):
            patcher = mock.patch.object(gui_mod.messagebox, name)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

        self.app = gui_mod.GuideExpressApp()
        self.addCleanup(self.app.destroy)

    def _make_step(self, index, session_dir, image_bytes=None):
        raw_path = session_dir / f"step_{index:04d}_raw.png"
        raw_path.write_bytes(image_bytes if image_bytes is not None else _valid_png_bytes())
        return Step(
            index=index, raw_image_path=raw_path, click_x=100, click_y=100,
            window_title="Explorateur de fichiers", timestamp="2026-01-01 10:00:00",
        )


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class ReviewViewCorruptedImageTestCase(_RealAppTestCase):
    """Dimension 1 de l'audit : une image brute presente mais corrompue (0
    octet - ecriture interrompue par un crash, verrou antivirus, disque
    plein) ne doit plus faire planter toute la construction de l'ecran de
    relecture."""

    def test_build_review_view_survives_a_corrupted_step_image(self):
        session_dir = self.tmp / "sessions" / "20260101-100000"
        session_dir.mkdir(parents=True)

        steps = [
            self._make_step(1, session_dir),
            self._make_step(2, session_dir, image_bytes=b""),  # 0 octet : corrompu
            self._make_step(3, session_dir),
        ]
        self.app.session_dir = session_dir
        self.app.steps = steps

        # Avant le correctif, UnidentifiedImageError (heritee d'OSError)
        # remontait ici non geree et interrompait la boucle de construction
        # en plein milieu : ce simple appel suffisait a faire planter tout
        # l'ecran de relecture pour une SEULE etape en cause.
        self.app._build_review_view()

        # La construction ne s'est PAS arretee en plein milieu : la barre du
        # bas (boutons d'export) et les 3 cartes ont bien ete atteintes.
        self.assertEqual(len(self.app._export_buttons), 3)
        self.assertEqual(len(self.app._rows), 3)
        for btn in self.app._export_buttons:
            self.assertEqual(str(btn.cget("state")), "normal")

        # L'etape corrompue est bien signalee comme telle...
        self.assertIn(steps[1].uid, self.app._thumbnail_error_uids)
        # ...mais pas les deux autres, dont l'image est valide.
        self.assertNotIn(steps[0].uid, self.app._thumbnail_error_uids)
        self.assertNotIn(steps[2].uid, self.app._thumbnail_error_uids)

        # Indicateur d'erreur visible sur la carte concernee (pas de simple
        # plantage total : un signal clair, exploitable par l'utilisateur).
        error_label = self.app._rows[steps[1].uid]["error_label"]
        self.assertEqual(error_label.winfo_manager(), "pack")
        self.assertIn("introuvable", error_label.cget("text").lower())
        # ... et absent des deux cartes dont l'image est valide.
        self.assertEqual(self.app._rows[steps[0].uid]["error_label"].winfo_manager(), "")
        self.assertEqual(self.app._rows[steps[2].uid]["error_label"].winfo_manager(), "")

        # Un avertissement AGREGE (un seul messagebox, pas un par etape) a
        # bien ete affiche a la fin de la construction.
        self.mocks["showwarning"].assert_called_once()

    def test_reopen_session_with_a_corrupted_step_survives_end_to_end(self):
        # Reproduction fidele du scenario exact de l'audit : passe par
        # _reopen_session (session.json + fichiers sur disque), pas
        # directement par _build_review_view.
        session_dir = self.tmp / "sessions" / "20260101-110000"
        session_dir.mkdir(parents=True)
        steps = [
            self._make_step(1, session_dir),
            self._make_step(2, session_dir, image_bytes=b""),  # tronque/corrompu
            self._make_step(3, session_dir),
        ]
        meta = {
            "title": "Guide de test",
            "steps": [cap.step_to_dict(step, session_dir) for step in steps],
        }
        import json
        (session_dir / gui_mod.SESSION_META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
        )

        class _FakeTree:
            def selection(self_):
                return [str(session_dir)]

        self.app._reopen_session(_FakeTree())

        self.assertEqual(len(self.app.steps), 3)  # aucune etape ecartee : le fichier EXISTE (0 octet, pas absent)
        self.assertEqual(len(self.app._export_buttons), 3)
        self.assertTrue(self.mocks["showwarning"].called)


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class MinsizeButtonsVisibleTestCase(_RealAppTestCase):
    """Dimension 8 de l'audit : a la taille minimale de fenetre EXACTEMENT
    declaree par l'application elle-meme (self.minsize()), les boutons
    d'action de chaque carte d'etape doivent rester entierement visibles.
    Verifie a la fois par les coordonnees Tk et par une VRAIE capture
    d'ecran de la fenetre (PIL.ImageGrab), comme fait pendant l'audit qui a
    trouve cette regression (motif topmost+lift+focus_force+delai)."""

    @staticmethod
    def _find_button(widget, text):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button) and child.cget("text") == text:
                return child
            found = MinsizeButtonsVisibleTestCase._find_button(child, text)
            if found is not None:
                return found
        return None

    def test_action_buttons_stay_within_the_window_at_declared_minsize(self):
        session_dir = self.tmp / "sessions" / "20260101-120000"
        session_dir.mkdir(parents=True)
        steps = [self._make_step(1, session_dir), self._make_step(2, session_dir)]
        self.app.session_dir = session_dir
        self.app.steps = steps
        self.app._build_review_view()

        # Taille minimale EXACTE declaree par l'application elle-meme (pas
        # une valeur recopiee en dur ici) : au moment de l'audit, 760x420
        # (gui.py, self.minsize(760, 420)).
        min_w, min_h = self.app.minsize()
        self.app.deiconify()
        self.app.geometry(f"{min_w}x{min_h}+50+50")
        self.app.attributes("-topmost", True)
        self.app.update_idletasks()
        self.app.lift()
        try:
            self.app.focus_force()
        except Exception:
            pass
        self.app.update()
        time.sleep(0.3)  # laisse le gestionnaire de fenetres dessiner reellement le cadre redimensionne
        self.app.update()

        win_x0 = self.app.winfo_rootx()
        win_y0 = self.app.winfo_rooty()
        win_x1 = win_x0 + self.app.winfo_width()
        win_y1 = win_y0 + self.app.winfo_height()
        self.assertEqual(self.app.winfo_width(), min_w)
        self.assertEqual(self.app.winfo_height(), min_h)

        # VRAIE capture d'ecran de la fenetre reelle, a la taille minimale
        # exacte declaree par l'application - pas une simulation.
        screenshot = ImageGrab.grab(bbox=(win_x0, win_y0, win_x1, win_y1))

        first_row = self.app._rows[steps[0].uid]["frame"]
        redact_btn = self._find_button(first_row, "Rediger")
        delete_btn = self._find_button(first_row, "Supprimer")
        self.assertIsNotNone(redact_btn, "bouton 'Rediger' introuvable dans la carte")
        self.assertIsNotNone(delete_btn, "bouton 'Supprimer' introuvable dans la carte")

        for label, btn in [("Rediger", redact_btn), ("Supprimer", delete_btn)]:
            bx0 = btn.winfo_rootx()
            by0 = btn.winfo_rooty()
            bx1 = bx0 + btn.winfo_width()
            by1 = by0 + btn.winfo_height()

            # 1) Verification geometrique directe (coordonnees Tk) : le
            # bouton doit etre entierement contenu dans la fenetre - c'est
            # exactement le calcul qui aurait detecte la regression
            # ("Rediger"/"Supprimer" coupes par le bord droit de la fenetre
            # a 760x420, trouvaille de l'audit).
            self.assertGreaterEqual(bx0, win_x0, f"{label} deborde a gauche de la fenetre")
            self.assertLessEqual(bx1, win_x1, f"{label} deborde a droite de la fenetre (coupe hors champ)")
            self.assertLessEqual(by0, win_y1, f"{label} deborde en haut/bas de la fenetre")
            self.assertLessEqual(by1, win_y1, f"{label} deborde en bas de la fenetre")

            # 2) Verification independante par la VRAIE image capturee : le
            # rectangle du bouton, traduit dans le repere de cette image,
            # doit rester entierement a l'interieur - preuve que ce n'est
            # pas seulement Tk qui *pense* que le bouton est bien place,
            # mais que le pixel correspondant est reellement dans la zone
            # visible et capturable a l'ecran.
            local_x1 = bx1 - win_x0
            local_y1 = by1 - win_y0
            self.assertLessEqual(
                local_x1, screenshot.width,
                f"{label} deborde de l'image capturee de la fenetre (largeur {screenshot.width}px)",
            )
            self.assertLessEqual(local_y1, screenshot.height, f"{label} deborde en bas de l'image capturee")


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class IncrementalSessionSaveTestCase(_RealAppTestCase):
    """Dimension 3 de l'audit : avant ce correctif, session.json n'etait
    ecrit qu'a l'ARRET de l'enregistrement (_stop_recording ->
    _build_review_view) - un crash/coupure de courant PENDANT
    l'enregistrement actif (avant le premier arret) laissait alors les
    captures brutes (step_XXXX_raw.png) sur le disque sans AUCUN fichier
    pour les referencer : ordre, positions de clic et titres de fenetre
    etaient perdus, seules des images anonymes survivaient. Verifie que
    _poll_events (deja appele toutes les 150 ms pendant l'enregistrement)
    persiste desormais l'etat courant a chaque lot d'evenements draine, de
    facon atomique (dimension 4, traitee dans le meme correctif)."""

    class _FakeRecorder:
        """Remplace un vrai Recorder (pas de hook souris reel installe ici) :
        seuls `events`/`capture_errors`/`is_active` sont lus par
        _poll_events, exactement l'interface que ce test doit imiter."""

        def __init__(self):
            self.events = queue.Queue()
            self.capture_errors = queue.Queue()
            self.is_active = False

    def test_session_json_exists_before_any_stop_after_first_batch_of_clicks(self):
        session_dir = self.tmp / "sessions" / "20260101-130000"
        session_dir.mkdir(parents=True)
        self.app.session_dir = session_dir
        self.app.steps = []
        self.app.recorder = self._FakeRecorder()
        meta_path = session_dir / gui_mod.SESSION_META_FILENAME

        # Avant tout evenement draine : rien n'a encore ete ecrit (comportement
        # inchange par rapport a avant ce correctif).
        self.app._poll_events()
        self.assertFalse(meta_path.exists())

        # 3 "clics" simules, avec exactement la forme des dicts que
        # recorder._writer_loop depose reellement dans events.
        for i in range(1, 4):
            raw_path = session_dir / f"step_{i:04d}_raw.png"
            raw_path.write_bytes(_valid_png_bytes())
            self.app.recorder.events.put({
                "index": i, "raw_image_path": raw_path, "click_x": 10 * i, "click_y": 20 * i,
                "button": "left", "window_title": "Fenetre de test", "timestamp": "2026-01-01 10:00:00",
            })

        # Simule un crash IMMEDIATEMENT apres ce lot de clics, avant tout
        # arret propre de l'enregistrement : seul ce second appel a
        # _poll_events() (deja planifie toutes les 150 ms par
        # _start_recording en usage reel) a eu l'occasion de tourner.
        self.app._poll_events()

        self.assertEqual(len(self.app.steps), 3)
        self.assertTrue(
            meta_path.exists(),
            "session.json aurait du etre ecrit AVANT tout arret de l'enregistrement",
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(len(meta["steps"]), 3)
        self.assertEqual(meta["steps"][2]["click_x"], 30)

        # Pas de fichier temporaire residuel apres une ecriture normale
        # (ecriture atomique, dimension 4).
        self.assertFalse((session_dir / f"{gui_mod.SESSION_META_FILENAME}.tmp").exists())

        # La session est bien reouvrable a partir de ce seul instantane,
        # exactement comme apres un crash reel survenu a cet instant precis.
        class _FakeTree:
            def selection(self_):
                return [str(session_dir)]

        self.app.steps = []
        self.app.session_dir = None
        self.app._reopen_session(_FakeTree())
        self.assertEqual(len(self.app.steps), 3)


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class SessionRoundTripTestCase(_RealAppTestCase):
    """Dimension 10 de l'audit (couverture de tests de gui.py) : troisieme
    test suggere par le correctif propose - un aller-retour complet
    _save_session_meta() -> _reopen_session() doit preserver fidelement le
    titre et les champs par etape (description, redactions, zoom), avec un
    vrai tempfile.mkdtemp() (jamais le vrai ~/.guide_express)."""

    def test_save_then_reopen_preserves_title_and_step_fields(self):
        session_dir = self.tmp / "sessions" / "20260101-150000"
        session_dir.mkdir(parents=True)
        step = self._make_step(1, session_dir)
        step.description = "Cliquez sur le bouton Enregistrer"
        step.redactions = [(10, 10, 50, 50)]
        step.zoom = True

        self.app.session_dir = session_dir
        self.app.steps = [step]
        self.app.title_var.set("Guide de demonstration")
        self.app._save_session_meta()

        class _FakeTree:
            def selection(self_):
                return [str(session_dir)]

        # Repart d'un etat vide : rien de residuel en memoire ne doit
        # influencer la verification qui suit, seul session.json compte.
        self.app.steps = []
        self.app.session_dir = None
        self.app.title_var.set("")
        self.app._reopen_session(_FakeTree())

        self.assertEqual(self.app.title_var.get(), "Guide de demonstration")
        self.assertEqual(len(self.app.steps), 1)
        reopened = self.app.steps[0]
        self.assertEqual(reopened.description, "Cliquez sur le bouton Enregistrer")
        self.assertEqual(reopened.redactions, [(10, 10, 50, 50)])
        self.assertTrue(reopened.zoom)


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class ElevatedWindowWarningTestCase(_RealAppTestCase):
    """Dimension 6 de l'audit (UIPI/elevation) : Windows empeche le hook
    bas niveau de pynput de recevoir les clics destines a une fenetre d'un
    niveau d'integrite superieur (ex: lancee "en tant qu'administrateur") -
    silencieusement, sans exception ni evenement cote Python. Comme il
    n'existe structurellement aucun moyen de detecter APRES coup un clic
    jamais recu, la seule detection possible est PROACTIVE (verifier
    periodiquement la fenetre au premier plan) : ce test verifie que le
    bandeau d'avertissement du HUD reagit correctement aux 3 cas possibles
    (elevee / non elevee / indetermine)."""

    def test_warning_label_toggles_with_elevation_detection(self):
        self.app._open_hud()
        self.addCleanup(lambda: self.app.hud.destroy() if self.app.hud is not None else None)
        label = self.app.hud_elevated_warning_label

        # Cache par defaut, avant le premier sondage.
        self.assertEqual(label.winfo_manager(), "")

        with mock.patch.object(gui_mod, "foreground_window_is_elevated", return_value=True):
            self.app._update_elevated_window_warning()
        self.assertEqual(label.winfo_manager(), "pack", "le bandeau doit apparaitre face a une fenetre elevee")
        self.assertIn("administrateur", label.cget("text").lower())

        with mock.patch.object(gui_mod, "foreground_window_is_elevated", return_value=False):
            self.app._update_elevated_window_warning()
        self.assertEqual(label.winfo_manager(), "", "le bandeau doit disparaitre des que la fenetre n'est plus elevee")

        # Reaffiche puis verifie qu'un resultat INDETERMINE (None : hors
        # Windows, echec d'un appel Win32...) masque le bandeau plutot que de
        # l'afficher a tort sur une donnee inconnue.
        with mock.patch.object(gui_mod, "foreground_window_is_elevated", return_value=True):
            self.app._update_elevated_window_warning()
        with mock.patch.object(gui_mod, "foreground_window_is_elevated", return_value=None):
            self.app._update_elevated_window_warning()
        self.assertEqual(label.winfo_manager(), "")

    def test_no_warning_wiring_without_an_open_hud(self):
        # _poll_events() peut etre appele apres que le HUD ait ete detruit
        # (ex: entre l'arret et la mise a jour de self.hud = None) - ne doit
        # jamais lever d'exception.
        self.app.hud = None
        self.app._update_elevated_window_warning()  # ne doit pas lever


@unittest.skipUnless(_TK_AVAILABLE, "Aucun affichage Tk disponible dans cet environnement.")
class ReviewBuildResponsivenessTestCase(_RealAppTestCase):
    """Dimension 9 de l'audit : sur une session volumineuse, _build_review_view
    doit rendre la main a la boucle d'evenements Tk periodiquement pendant la
    construction (curseur sablier + update_idletasks() toutes les
    _REVIEW_BUILD_PROGRESS_EVERY cartes), au lieu de geler totalement
    l'interface du debut a la fin (mesure de l'audit : 10.1s de gel total sur
    300 etapes - au-dela du seuil "Ne repond pas" typique de Windows, ~5s)."""

    def test_build_review_view_yields_to_the_event_loop_periodically(self):
        session_dir = self.tmp / "sessions" / "20260101-140000"
        session_dir.mkdir(parents=True)
        raw_path = session_dir / "shared_raw.png"
        raw_path.write_bytes(_valid_png_bytes())

        # Au moins 2 points de controle attendus pendant la construction.
        step_count = 2 * gui_mod._REVIEW_BUILD_PROGRESS_EVERY + 5
        steps = [
            Step(
                index=i, raw_image_path=raw_path, click_x=10, click_y=10,
                window_title="Fenetre", timestamp="2026-01-01 10:00:00",
            )
            for i in range(1, step_count + 1)
        ]
        self.app.session_dir = session_dir
        self.app.steps = steps

        calls = []
        original_update_idletasks = self.app.update_idletasks

        def _spy(*args, **kwargs):
            calls.append(1)
            return original_update_idletasks(*args, **kwargs)

        self.app.update_idletasks = _spy
        try:
            self.app._build_review_view()
        finally:
            del self.app.update_idletasks  # restaure la resolution normale via la classe

        self.assertEqual(len(self.app._rows), step_count)
        # 1 appel avant la boucle + au moins 2 points de controle pendant :
        # au moins 3 rendus-la-main a la boucle d'evenements Tk pendant la
        # construction, plutot qu'un seul gel total du debut a la fin.
        self.assertGreaterEqual(calls.count(1), 3)
        # Le curseur sablier doit avoir ete restaure a la fin (jamais laisse
        # actif, meme si une erreur avait interrompu la boucle - voir le
        # try/finally du correctif).
        self.assertEqual(str(self.app.cget("cursor")), "")


class DpiAwarenessTestCase(unittest.TestCase):
    """Dimension 7 de l'audit : le processus doit etre rendu explicitement
    Per-Monitor V2 DPI Aware AVANT toute fenetre Tk - sans quoi le hook bas
    niveau de pynput (coordonnees physiques) et GetSystemMetrics/ImageGrab
    (valeurs virtualisees pour un processus non DPI-aware) peuvent se
    desynchroniser sur un ecran mis a l'echelle (125%/150%/200%), en plus
    d'un flou de capture."""

    def test_configure_dpi_awareness_is_idempotent_and_does_not_raise(self):
        # Deja appele une fois a l'import de gui.py (niveau module) : un
        # second appel explicite ne doit rien refaire ni lever.
        gui_mod._configure_dpi_awareness()
        gui_mod._configure_dpi_awareness()
        self.assertTrue(gui_mod._dpi_awareness_configured)

    @unittest.skipUnless(sys.platform == "win32", "verification specifique a l'API Win32")
    def test_process_is_actually_per_monitor_v2_dpi_aware_on_windows(self):
        import ctypes
        gui_mod._configure_dpi_awareness()
        user32 = ctypes.windll.user32
        if not hasattr(user32, "GetThreadDpiAwarenessContext"):
            self.skipTest("GetThreadDpiAwarenessContext indisponible sur ce Windows (trop ancien)")
        current_context = user32.GetThreadDpiAwarenessContext()
        per_monitor_v2 = ctypes.c_void_p(-4)
        is_pm_v2 = bool(user32.AreDpiAwarenessContextsEqual(current_context, per_monitor_v2))
        self.assertTrue(is_pm_v2, "le processus devrait etre Per-Monitor V2 DPI Aware apres _configure_dpi_awareness()")


if __name__ == "__main__":
    unittest.main()
