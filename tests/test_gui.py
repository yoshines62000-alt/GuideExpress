"""Tests de fumee pour gui.py (Tk reel, jamais le vrai dossier
~/.guide_express de l'utilisateur - SESSIONS_DIR et LOG_PATH sont toujours
repointes vers un dossier temporaire avant toute construction de l'app ou
creation de session, meme motif que celui utilise pendant l'audit expert qui
a trouve les deux regressions couvertes ici).

Deux dimensions de l'audit du 2026-07-22 sont verrouillees ici :
- dimension 1 (Critique) : une SEULE image brute corrompue/illisible parmi
  les etapes d'une session ne doit plus interrompre la construction de tout
  l'ecran de relecture (UnidentifiedImageError non geree auparavant,
  app._export_buttons restait vide et l'utilisateur se retrouvait face a un
  ecran a moitie construit, sans aucun message).
- dimension 8 (Majeure) : a la taille minimale de fenetre EXACTEMENT
  declaree par l'application (self.minsize), les boutons d'action de chaque
  carte d'etape (notamment "Rediger" et "Supprimer") doivent rester
  entierement visibles - pas coupes par le bord droit de la fenetre, cachdes
  sous la barre de defilement verticale (regression partielle d'un bug deja
  "corrige" au commit 387c5b4).
"""

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


if __name__ == "__main__":
    unittest.main()
