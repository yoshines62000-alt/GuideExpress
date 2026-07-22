"""Interface graphique (Tkinter) de GuideExpress."""

from __future__ import annotations

import datetime
import json
import logging
import os
import queue
import shutil
import sys
import time
import tkinter as tk
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, simpledialog

from PIL import Image, ImageDraw, ImageTk

DONATE_URL = "https://ko-fi.com/yoshines62000"
APP_VERSION = "1.1.11"
UPDATE_REPO = "yoshines62000-alt/GuideExpress"
RELEASES_URL = f"https://github.com/{UPDATE_REPO}/releases/latest"

import update_checker
from capture import (
    Step, render_step_image, move_step, move_step_to, delete_step, duplicate_step,
    sanitize_filename, get_window_at_point, step_to_dict, step_from_dict, renumber,
)
from recorder import Recorder
from export import export_html, export_markdown, export_pdf

APP_DIR = Path.home() / ".guide_express"
SESSIONS_DIR = APP_DIR / "sessions"
SESSION_META_FILENAME = "session.json"
LOG_PATH = APP_DIR / "guideexpress.log"

THUMBNAIL_MAX_SIZE = (220, 150)
EDITOR_MAX_SIZE = (980, 680)

_logging_configured = False


def _configure_logging() -> None:
    """Journalisation minimale et locale (cohérente avec l'engagement "100%
    local, zéro télémétrie" du projet) : sans elle, aucune des pannes
    silencieuses possibles (image brute corrompue, exception inattendue
    absorbée par Tkinter...) n'était diagnosticable, ni par l'utilisateur ni
    par le développeur solo qui doit supporter cette application sans
    télémétrie - l'exécutable est empaqueté sans console
    (GuideExpress.spec, console=False), donc stderr n'existe nulle part pour
    un utilisateur final (trouvaille d'audit : recherche exhaustive de
    `logging`/`traceback`/`print` sur tout le dépôt, aucune occurrence).
    RotatingFileHandler limité à 1 Mo : un utilisateur qui laisse
    GuideExpress installé des mois ne doit jamais voir son dossier de
    données grossir indéfiniment à cause du seul fichier de log.
    Idempotent (protégé par `_logging_configured`) : plusieurs instances de
    GuideExpressApp (ex: tests) ne doivent pas empiler des handlers en
    double sur le logger racine."""
    global _logging_configured
    if _logging_configured:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        root_logger.addHandler(handler)
    except OSError:
        pass  # dossier de donnees inaccessible en ecriture (permissions,
        # disque plein...) : l'absence de journalisation ne doit jamais
        # rendre l'application elle-meme inutilisable.
    _logging_configured = True


def _resource_path(name: str) -> Path:
    """Chemin d'une ressource embarquee (ex: icon.ico), fonctionne aussi bien
    lance depuis le code source qu'empaquete par PyInstaller (les fichiers de
    donnees sont alors extraits dans un dossier temporaire sys._MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


class GuideExpressApp(tk.Tk):
    def __init__(self):
        _configure_logging()
        super().__init__()
        self.title("GuideExpress - Guides pas-a-pas")
        # 900x560 (au lieu de 760x560) : a 760px, meme repartis sur deux
        # rangees, les boutons "Rediger" et "Supprimer" de chaque carte
        # d'etape depassaient encore la largeur de la fenetre - invisibles
        # et inaccessibles sans agrandissement manuel, sans aucune barre de
        # defilement horizontale pour les atteindre (trouvaille d'audit,
        # verifiee empiriquement). 900px laisse une marge confortable sur un
        # ecran 1920x1080 standard.
        self.geometry("900x560")
        self.minsize(760, 420)
        try:
            self.iconbitmap(str(_resource_path("icon.ico")))
        except tk.TclError:
            pass  # icone absente ou format non supporte : pas bloquant

        self.steps: list = []
        self.recorder: Recorder | None = None
        self.session_dir: Path | None = None
        self.hud: tk.Toplevel | None = None
        self._retake_recorder: Recorder | None = None
        self._retake_step_obj = None
        self.title_var = tk.StringVar(value="Mon guide")
        # Cache des miniatures deja rendues, indexe par step.uid (identifiant
        # stable d'une etape, independant de sa position dans self.steps -
        # voir capture.Step.uid). Sans ce cache, _build_review_view devait
        # rouvrir et redecoder l'image brute de CHAQUE etape a CHAQUE
        # mutation (deplacement, suppression, coche de zoom...), meme quand
        # aucune image n'avait change : 14.8s mesures pour reconstruire la
        # relecture d'un guide de 150 etapes en 4K apres une seule action
        # (trouvaille d'audit Phase 3, chiffree empiriquement). Invalide au
        # cas par cas (pop de l'entree correspondante) uniquement quand le
        # RENDU d'une etape change reellement (redaction, reprise, zoom) -
        # jamais pour un simple reordonnancement, qui ne touche aucune image.
        self._thumbnail_cache: dict = {}
        # uid des etapes dont l'image brute est illisible/corrompue (fichier
        # 0 octet, tronque, supprime a la main...) : render_step_image a leve
        # (OSError, ValueError) pour ces etapes-la. Sans ce suivi, la SEULE
        # information disponible pour l'utilisateur aurait ete une vignette
        # de remplacement generique, sans lien avec les autres indicateurs
        # (label "Image introuvable" sur la carte, avertissement agrege en
        # fin de construction de l'ecran de relecture) - voir _get_thumbnail
        # et _build_review_view (bug trouve a l'audit : UnidentifiedImageError
        # non geree interrompait toute la construction de la liste).
        self._thumbnail_error_uids: set = set()
        # Vignette de remplacement (grise, croix rouge) partagee par toutes
        # les cartes en erreur - generee une seule fois a la demande (voir
        # _get_error_thumbnail), son contenu ne depend jamais de l'etape.
        self._error_thumbnail_photo = None
        # Widgets de chaque carte d'etape, indexes par step.uid : permet de
        # reordonner/mettre a jour une carte existante sans la detruire et la
        # reconstruire (donc sans jamais rappeler render_step_image) pour les
        # operations qui ne changent pas son contenu.
        self._rows: dict = {}
        self._container = ttk.Frame(self)
        self._container.pack(fill="both", expand=True)

        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill="x", side="bottom")
        ttk.Label(bottom_bar, text=f"v{APP_VERSION}", foreground="#666").pack(side="left", padx=(8, 0), pady=4)
        self.update_status_var = tk.StringVar(value="")
        self.update_status_label = ttk.Label(bottom_bar, textvariable=self.update_status_var, foreground="#666")
        self.update_status_label.pack(side="left", padx=(6, 0), pady=4)
        donate_label = ttk.Label(bottom_bar, text="☕ Soutenir le projet", foreground="#0645AD", cursor="hand2")
        donate_label.pack(side="right", padx=8, pady=4)
        donate_label.bind("<Button-1>", lambda event: webbrowser.open(DONATE_URL))

        self._update_check_queue = queue.Queue()
        update_checker.start_update_check(APP_VERSION, UPDATE_REPO, self._update_check_queue)
        self.after(500, self._poll_update_check)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_start_view()

    def report_callback_exception(self, exc, val, tb):
        """Tkinter appelle cette methode (jamais sys.excepthook) pour toute
        exception qui s'echappe d'un callback lie a la boucle d'evenements
        (clic sur un bouton, evenement <FocusOut>, rappel programme via
        after()...). Le comportement par defaut se contente d'ecrire la
        traceback sur stderr - invisible pour l'executable empaquete en mode
        fenetre (console=False, GuideExpress.spec:32), donc totalement
        silencieux pour l'utilisateur final (trouvaille d'audit, dimension 5).
        On journalise la traceback complete dans le fichier de log local ET
        on affiche un message clair, plutot que de laisser l'exception
        disparaitre sans aucune trace exploitable ni le moindre indice pour
        l'utilisateur qu'un probleme vient de se produire."""
        logging.getLogger(__name__).error(
            "Exception non geree dans un callback Tk", exc_info=(exc, val, tb),
        )
        try:
            messagebox.showerror(
                "Erreur inattendue",
                "Une erreur inattendue est survenue.\n\n"
                f"Details enregistres dans le journal :\n{LOG_PATH}",
            )
        except tk.TclError:
            pass  # Tk lui-meme dans un etat instable : ne pas aggraver la situation

    def _poll_update_check(self):
        try:
            status, tag = self._update_check_queue.get_nowait()
        except queue.Empty:
            self.after(500, self._poll_update_check)
            return
        if status == "update_available":
            self.update_status_var.set(f"Mise a jour disponible : {tag} - Telecharger")
            self.update_status_label.configure(foreground="#0645AD", cursor="hand2")
            self.update_status_label.bind("<Button-1>", lambda event: webbrowser.open(RELEASES_URL))
        elif status == "up_to_date":
            self.update_status_var.set("A jour")
            self.update_status_label.configure(foreground="#1B7A1B", cursor="")
        # "check_failed" (hors ligne, GitHub inaccessible...) : on ne
        # revendique rien plutot que d'afficher a tort "a jour".

    # ------------------------------------------------------------------
    # Ecran de demarrage
    # ------------------------------------------------------------------

    def _clear_container(self):
        for child in self._container.winfo_children():
            child.destroy()

    def _build_start_view(self):
        self._clear_container()
        frame = ttk.Frame(self._container, padding=30)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="GuideExpress", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Cree des guides pas-a-pas illustres a partir de tes clics reels.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(0, 20))

        ttk.Label(frame, text="Titre du guide :").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.title_var, width=50).pack(anchor="w", pady=(2, 20))

        ttk.Button(frame, text="Demarrer l'enregistrement", command=self._start_recording).pack(anchor="w")
        ttk.Button(frame, text="Gerer les sessions enregistrees", command=self._build_sessions_view).pack(anchor="w", pady=(8, 0))

        privacy = ttk.LabelFrame(frame, text="Confidentialite", padding=12)
        privacy.pack(fill="x", pady=(30, 0))
        ttk.Label(
            privacy,
            text=(
                "- Aucune frappe clavier n'est jamais enregistree, seulement la position des clics.\n"
                "- Tout reste sur ta machine : aucune capture n'est envoyee nulle part.\n"
                "- Rien n'est exporte sans que tu aies pu relire et modifier chaque etape.\n"
                "- L'outil de redaction masque les zones sensibles avec un rectangle plein, pas un flou."
            ),
            justify="left",
        ).pack(anchor="w")

    # ------------------------------------------------------------------
    # Gestion des sessions enregistrees (captures brutes sur le disque)
    # ------------------------------------------------------------------

    @staticmethod
    def _list_sessions():
        if not SESSIONS_DIR.exists():
            return []
        sessions = []
        for entry in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            files = [f for f in entry.rglob("*") if f.is_file()]
            size = sum(f.stat().st_size for f in files)
            sessions.append((entry, len(files), size))
        return sessions

    def _build_sessions_view(self):
        self._clear_container()
        frame = ttk.Frame(self._container, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Gerer les sessions enregistrees", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                f"Captures brutes stockees dans {SESSIONS_DIR} - GuideExpress ne les supprime\n"
                "jamais automatiquement. Supprimez ici celles qui ne sont plus necessaires (Ctrl/Shift-clic\n"
                "pour en selectionner plusieurs a la fois, ou purgez les sessions les plus anciennes d'un coup)."
            ),
            foreground="#666", justify="left",
        ).pack(anchor="w", pady=(4, 12))

        columns = ("session", "files", "size")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        for col, label, width in [("session", "Session", 220), ("files", "Fichiers", 100), ("size", "Taille", 100)]:
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        sessions = self._list_sessions()
        for path, file_count, size_bytes in sessions:
            tree.insert("", "end", iid=str(path), values=(path.name, file_count, f"{size_bytes / 1024:.0f} Ko"))

        if not sessions:
            ttk.Label(frame, text="Aucune session enregistree pour le moment.", foreground="#666").pack(anchor="w", pady=10)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(
            actions, text="Rouvrir la session selectionnee",
            command=lambda: self._reopen_session(tree),
        ).pack(side="left")
        ttk.Button(
            actions, text="Supprimer la selection",
            command=lambda: self._delete_session(tree),
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            actions, text="Supprimer les sessions de plus de N jours...",
            command=self._delete_old_sessions,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Retour", command=self._build_start_view).pack(side="right")

    def _save_session_meta(self) -> None:
        """Ecrit session_dir/session.json (titre + etapes), pour pouvoir
        rouvrir la session plus tard - sans ca, fermer l'application apres
        un enregistrement perdait tout le travail de relecture (descriptions,
        redactions, ordre, zoom), seules les captures brutes survivant sur
        le disque, inutilisables telles quelles."""
        if self.session_dir is None:
            return
        meta = {
            "title": self.title_var.get(),
            "steps": [step_to_dict(step, self.session_dir) for step in self.steps],
        }
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            (self.session_dir / SESSION_META_FILENAME).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError:
            pass  # une sauvegarde de metadonnees ratee ne doit jamais interrompre l'edition en cours

    def _reopen_session(self, tree):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Rouvrir une session", "Selectionnez une session d'abord.")
            return
        session_path = Path(selection[0])
        meta_path = session_path / SESSION_META_FILENAME
        if not meta_path.exists():
            messagebox.showinfo(
                "Rouvrir une session",
                "Cette session n'a pas de fichier de metadonnees (enregistree avant "
                "cette fonctionnalite, ou clic droit sur 'Retour' sans jamais avoir "
                "atteint la relecture) : seules les captures brutes existent, elle "
                "ne peut pas etre rouverte automatiquement.",
            )
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Rouvrir une session", f"Fichier de session illisible ou corrompu :\n{exc}")
            return

        steps = []
        missing = 0
        for data in meta.get("steps", []):
            step = step_from_dict(data, session_path)
            # is_file(), pas exists() : une entree sans raw_image_path (ou
            # vide) fait retomber step_from_dict sur session_path / "" ==
            # session_path lui-meme, qui EXISTE toujours (c'est un dossier)
            # - exists() ne detectait donc jamais ce cas et laissait passer
            # une etape pointant vers un dossier, plantant plus tard dans
            # render_step_image (Image.open() sur un dossier) au lieu
            # d'etre proprement comptee dans l'avertissement "etapes
            # ignorees" ci-dessous (bug trouve a l'audit).
            if not step.raw_image_path.is_file():
                missing += 1
                continue
            steps.append(step)

        if missing:
            renumber(steps)  # des etapes manquantes ont ete ecartees : combler les trous de numerotation
        self.session_dir = session_path
        self.title_var.set(meta.get("title", "Mon guide"))
        self.steps = steps
        self._thumbnail_cache = {}  # session rouverte : rien a reutiliser d'une session precedente
        self._thumbnail_error_uids = set()
        self._build_review_view()
        if missing:
            messagebox.showwarning(
                "Rouvrir une session",
                f"{missing} etape(s) ignoree(s) : leur image brute est introuvable sur le disque.",
            )

    @staticmethod
    def _session_date(path: Path) -> datetime.datetime:
        """Date de creation d'une session. Les dossiers de session sont
        toujours nommes par _start_recording() via time.strftime("%Y%m%d-%H%M%S") :
        on privilegie ce nom, fiable et independant du systeme de fichiers,
        et on ne retombe sur la date de derniere modification du dossier que
        pour un dossier au nom non standard (renomme manuellement, etc.)."""
        try:
            return datetime.datetime.strptime(path.name, "%Y%m%d-%H%M%S")
        except ValueError:
            return datetime.datetime.fromtimestamp(path.stat().st_mtime)

    @staticmethod
    def _delete_session_paths(session_paths: list) -> list:
        """Supprime chaque dossier de session de la liste. Une erreur sur
        l'un d'eux (fichier verrouille, permissions, etc.) est capturee et
        n'empeche pas la suppression des suivants - meme esprit que le reste
        du projet : ne jamais laisser un echec individuel bloquer le
        traitement des autres elements. Renvoie la liste des echecs sous
        forme de tuples (nom_session, message_erreur)."""
        failures = []
        for session_path in session_paths:
            try:
                shutil.rmtree(session_path)
            except OSError as exc:
                failures.append((session_path.name, str(exc)))
        return failures

    @staticmethod
    def _report_delete_failures(failures: list, total: int) -> None:
        if not failures:
            return
        details = "\n".join(f"- {name} : {err}" for name, err in failures)
        messagebox.showwarning(
            "Suppression partielle",
            f"{len(failures)} session(s) sur {total} n'ont pas pu etre supprimee(s) :\n\n{details}",
        )

    def _delete_session(self, tree):
        # Le Treeview est en mode de selection "extended" (defaut de
        # ttk.Treeview, jamais restreint explicitement ici) : l'utilisateur
        # peut selectionner plusieurs sessions a la fois (Ctrl/Shift-clic).
        # Une version precedente ne traitait que selection[0], supprimant
        # silencieusement une seule session meme quand plusieurs etaient
        # cochees (bug trouve a l'audit).
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Gerer les sessions", "Selectionnez au moins une session d'abord.")
            return
        session_paths = [Path(iid) for iid in selection]
        count = len(session_paths)
        if count == 1:
            message = (
                f"Supprimer definitivement la session '{session_paths[0].name}' et toutes ses captures ?\n"
                "Cette action est irreversible."
            )
        else:
            names = "\n".join(f"- {p.name}" for p in session_paths)
            message = (
                f"Supprimer {count} session(s) ?\n\n{names}\n\n"
                "Cette action est irreversible."
            )
        if not messagebox.askyesno("Supprimer la session" if count == 1 else "Supprimer les sessions", message):
            return
        failures = self._delete_session_paths(session_paths)
        self._build_sessions_view()
        self._report_delete_failures(failures, count)

    def _delete_old_sessions(self):
        # Complement a la suppression multi-selection ci-dessus : purge en
        # un coup les sessions plus anciennes qu'un nombre de jours donne,
        # sans avoir a toutes les selectionner manuellement (voir README,
        # section Confidentialite, qui documentait jusqu'ici uniquement le
        # vidage manuel du dossier de sessions).
        days = simpledialog.askinteger(
            "Supprimer les anciennes sessions",
            "Supprimer les sessions vieilles de plus de combien de jours ?",
            parent=self, minvalue=0,
        )
        if days is None:
            return
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        old_paths = [path for path, _files, _size in self._list_sessions() if self._session_date(path) < cutoff]
        if not old_paths:
            messagebox.showinfo(
                "Supprimer les anciennes sessions",
                f"Aucune session de plus de {days} jour(s).",
            )
            return
        if not messagebox.askyesno(
            "Supprimer les anciennes sessions",
            f"Supprimer definitivement {len(old_paths)} session(s) de plus de {days} jour(s) "
            "et toutes leurs captures ?\nCette action est irreversible.",
        ):
            return
        failures = self._delete_session_paths(old_paths)
        self._build_sessions_view()
        self._report_delete_failures(failures, len(old_paths))

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------

    def _start_recording(self):
        session_dir = SESSIONS_DIR / time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = session_dir
        self.steps = []
        self._thumbnail_cache = {}  # nouvelle session : rien a reutiliser de la precedente
        self._thumbnail_error_uids = set()

        self.withdraw()
        self._open_hud()
        # Exclut notre propre fenetre HUD des clics enregistres : sans ca,
        # cliquer sur "Arreter l'enregistrement" ajouterait une derniere
        # etape parasite au guide. Note : `winfo_id()` de Tkinter ne
        # correspond PAS au HWND de haut niveau que Windows rapporte via
        # WindowFromPoint (Tk cree une fenetre-cadre interne distincte) - on
        # doit donc interroger l'OS sur un point reellement situe dans le
        # HUD pour obtenir le HWND a comparer avec la meme logique que celle
        # utilisee par le Recorder au moment du clic.
        self.hud.update_idletasks()
        hud_cx = self.hud.winfo_rootx() + self.hud.winfo_width() // 2
        hud_cy = self.hud.winfo_rooty() + self.hud.winfo_height() // 2
        hud_hwnd = get_window_at_point(hud_cx, hud_cy)
        excluded = {hud_hwnd} if hud_hwnd else set()
        # Cree ET demarre le Recorder dans le meme bloc protege : la creation
        # (mkdir du dossier de session) et le demarrage (installation du hook
        # souris bas-niveau pynput) peuvent tous deux echouer independamment
        # (dossier non accessible en ecriture ; permissions/antivirus/EDR
        # bloquant l'installation du hook). Sans cette protection, l'exception
        # remontait non geree APRES self.withdraw()/self._open_hud() : la
        # fenetre principale restait cachee et le HUD bloque a "0 etape(s)",
        # sans aucun moyen visible de s'en sortir ni le moindre message
        # d'erreur (bug trouve a l'audit).
        try:
            self.recorder = Recorder(session_dir, excluded_hwnds=excluded)
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001 - toute cause d'echec doit
            # ramener l'utilisateur a un etat utilisable (fenetre visible,
            # message clair) plutot que le laisser bloque sans recours.
            self.recorder = None
            if self.hud is not None:
                self.hud.destroy()
                self.hud = None
            self.deiconify()
            messagebox.showerror(
                "Enregistrement impossible",
                "L'enregistrement n'a pas pu demarrer.\n\n"
                "Causes possibles : permissions insuffisantes, antivirus/EDR "
                "bloquant l'ecoute de la souris, ou dossier de session "
                "inaccessible en ecriture.\n\n"
                f"Detail : {exc}",
            )
            return
        self.after(150, self._poll_events)

    def _open_hud(self):
        self.hud = tk.Toplevel(self)
        self.hud.title("GuideExpress")
        self.hud.attributes("-topmost", True)
        self.hud.resizable(False, False)
        self.hud.protocol("WM_DELETE_WINDOW", self._stop_recording)

        frame = ttk.Frame(self.hud, padding=12)
        frame.pack()
        self.hud_status_var = tk.StringVar(value="Enregistrement en cours")
        ttk.Label(frame, textvariable=self.hud_status_var, foreground="#c0392b", font=("Segoe UI", 10, "bold")).pack()
        self.hud_count_var = tk.StringVar(value="0 etape(s) capturee(s)")
        ttk.Label(frame, textvariable=self.hud_count_var).pack(pady=(4, 8))
        ttk.Label(
            frame, text="Clic gauche ou droit = une etape", foreground="#666", font=("Segoe UI", 8),
        ).pack(pady=(0, 6))
        self.hud_pause_button = ttk.Button(frame, text="Pause", command=self._toggle_pause_recording)
        self.hud_pause_button.pack(pady=(0, 6))
        ttk.Button(frame, text="Arreter l'enregistrement", command=self._stop_recording).pack()

        self.hud.update_idletasks()
        screen_w = self.hud.winfo_screenwidth()
        self.hud.geometry(f"+{screen_w - 260}+20")

    def _toggle_pause_recording(self):
        if self.recorder is None:
            return
        if self.recorder.is_paused:
            self.recorder.resume()
            self.hud_status_var.set("Enregistrement en cours")
            self.hud_pause_button.configure(text="Pause")
        else:
            self.recorder.pause()
            self.hud_status_var.set("En pause")
            self.hud_pause_button.configure(text="Reprendre")

    def _poll_events(self):
        if self.recorder is None:
            return
        drained = self._drain_events()
        self._drain_capture_errors()
        if drained and self.hud is not None:
            self.hud_count_var.set(f"{len(self.steps)} etape(s) capturee(s)")
        if self.recorder.is_active:
            self.after(150, self._poll_events)

    def _drain_events(self) -> bool:
        if self.recorder is None:
            return False
        drained = False
        while not self.recorder.events.empty():
            data = self.recorder.events.get()
            self.steps.append(Step(**data))
            drained = True
        return drained

    def _drain_capture_errors(self) -> list:
        """Recupere les erreurs de capture/ecriture survenues en arriere-plan
        (voir Recorder.capture_errors), pour pouvoir les signaler a
        l'utilisateur plutot que de les laisser disparaitre silencieusement."""
        if self.recorder is None:
            return []
        messages = []
        while not self.recorder.capture_errors.empty():
            messages.append(self.recorder.capture_errors.get())
        return messages

    def _stop_recording(self):
        if self.recorder is None:
            return
        self.recorder.stop()
        # Laisse le temps au thread d'ecriture de sauvegarder les captures
        # prises juste avant l'arret, pour ne perdre aucune etape.
        fully_saved = self.recorder.wait_for_pending_saves()
        self._drain_events()
        errors = self._drain_capture_errors()
        if self.hud is not None:
            self.hud.destroy()
            self.hud = None
        self.deiconify()
        # shutdown() (pas juste stop()) : sans lui, le thread d'ecriture
        # reste bloque indefiniment sur _save_queue.get() en attente du
        # sentinelle que seul shutdown() envoie - un Recorder + thread
        # seraient alors abandonnes, jamais liberes, a chaque enregistrement
        # (bug trouve a l'audit : fuite de thread a chaque arret normal).
        self.recorder.shutdown()
        self.recorder = None
        self._build_review_view()

        if not fully_saved:
            messagebox.showwarning(
                "Enregistrement",
                "Certaines captures n'ont pas pu etre finalisees a temps : "
                "il est possible qu'une etape manque a la fin du guide.",
            )
        if errors:
            messagebox.showwarning(
                "Erreurs de capture",
                "Certains clics n'ont pas pu etre enregistres correctement :\n\n"
                + "\n".join(errors),
            )

    # ------------------------------------------------------------------
    # Ecran de relecture / edition
    # ------------------------------------------------------------------

    def _build_review_view(self):
        # Construction COMPLETE de l'ecran de relecture : appelee uniquement
        # aux points d'entree qui remplacent entierement self.steps (fin
        # d'enregistrement, reouverture de session) ou quand la liste devient
        # vide (cas rare, pas de contrainte de performance). Les mutations
        # courantes (deplacer/supprimer/dupliquer/zoomer/rediger/reprendre)
        # passent desormais par des mises a jour incrementales (voir
        # _reorder_and_repack, _refresh_row_image, _remove_row,
        # _insert_row_after) qui evitent de detruire et reconstruire TOUTES
        # les cartes et de rappeler render_step_image() pour CHAQUE etape a
        # chaque action - 14.8s mesures sur 150 etapes en 4K pour une seule
        # action avant cette optimisation (trouvaille d'audit Phase 3).
        self._save_session_meta()
        self._clear_container()
        self._rows = {}

        top = ttk.Frame(self._container, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Titre :").pack(side="left")
        title_entry = ttk.Entry(top, textvariable=self.title_var, width=40)
        title_entry.pack(side="left", padx=6)
        # Sans ce binding, editer le titre puis fermer l'app sans aucune
        # AUTRE mutation (deplacer/supprimer/dupliquer/zoomer/reprendre une
        # etape) ne sauvegardait jamais le nouveau titre dans session.json -
        # _save_session_meta() n'etait alors appele qu'au debut de
        # _build_review_view(), jamais quand seul un champ de saisie change
        # (bug trouve a l'audit).
        title_entry.bind("<FocusOut>", lambda e: self._save_session_meta())
        title_entry.bind("<Return>", lambda e: self._save_session_meta())
        self._step_count_var = tk.StringVar(value=f"{len(self.steps)} etape(s)")
        ttk.Label(top, textvariable=self._step_count_var).pack(side="left", padx=12)

        list_frame = ttk.Frame(self._container)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        inner_window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        # Sans cette ligne, "inner" (et donc chaque carte d'etape qu'il
        # contient) auto-dimensionne sa PROPRE largeur a la somme des
        # demandes naturelles de tous ses widgets (poignee + miniature +
        # zone de texte + boutons), completement independamment de la
        # largeur reellement visible du canvas - seul un defilement VERTICAL
        # existe, rien ne compense jamais cet exces horizontal. Consequence
        # verifiee empiriquement (bug trouve a l'audit, dimension 8) : meme
        # apres avoir reordonne l'empaquetage des boutons dans
        # _build_step_row (les boutons empaquetes avant la zone de texte),
        # "inner" restait plus large que la fenetre, et "Rediger"/"Supprimer"
        # continuaient d'etre positionnes au-dela du bord droit reel de la
        # fenetre, invisibles et inaccessibles, a la taille minimale
        # declaree (self.minsize). En liant la largeur de l'item canvas a la
        # largeur REELLE du canvas a chaque redimensionnement, "inner" (et
        # donc chaque carte, via son propre fill="x") est desormais contraint
        # a ne jamais depasser la largeur visible : c'est alors la zone de
        # texte (seul widget avec fill+expand, empaquete en dernier dans
        # _build_step_row) qui absorbe le manque de place en retrecissant,
        # jamais les boutons d'action, qui reservent toujours leur taille
        # minimale requise en priorite.
        def _sync_inner_width(event, canvas=canvas, window_id=inner_window_id):
            canvas.itemconfig(window_id, width=event.width)

        canvas.bind("<Configure>", _sync_inner_width)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self._review_inner = inner  # reutilise par les insertions incrementales (duplication)

        if not self.steps:
            ttk.Label(inner, text="Aucune etape capturee (aucun clic detecte pendant l'enregistrement).").pack(pady=20)

        self._drag_uid = None
        for step in self.steps:
            self._build_step_row(inner, step)

        bottom = ttk.Frame(self._container, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Nouvel enregistrement", command=self._build_start_view).pack(side="left")
        state = "normal" if self.steps else "disabled"
        self._export_buttons = []
        html_btn = ttk.Button(bottom, text="Exporter en HTML", command=self._export_html, state=state)
        html_btn.pack(side="left", padx=6)
        md_btn = ttk.Button(bottom, text="Exporter en Markdown", command=self._export_markdown, state=state)
        md_btn.pack(side="left")
        pdf_btn = ttk.Button(bottom, text="Exporter en PDF", command=self._export_pdf, state=state)
        pdf_btn.pack(side="left", padx=6)
        self._export_buttons = [html_btn, md_btn, pdf_btn]

        # Agrege TOUTES les etapes en erreur (image brute illisible/corrompue,
        # voir _get_thumbnail) en un seul avertissement, affiche une fois la
        # vue entierement construite (barre du bas comprise) - jamais un
        # messagebox par etape, qui obligerait l'utilisateur a fermer une
        # rafale de boites de dialogue avant de pouvoir seulement voir son
        # ecran de relecture. Meme modele que l'avertissement deja existant
        # pour les fichiers manquants dans _reopen_session.
        error_count = sum(1 for step in self.steps if step.uid in self._thumbnail_error_uids)
        if error_count:
            messagebox.showwarning(
                "Images illisibles",
                f"{error_count} etape(s) ont une image brute illisible ou corrompue "
                "(fichier vide, endommage, ou verrouille par un antivirus) et "
                "s'affichent avec une vignette de remplacement, reperable a la "
                "mention \"Image introuvable ou corrompue\" sur leur carte.\n\n"
                "Utilisez le bouton \"Reprendre\" pour recapturer l'etape "
                "concernee, ou \"Supprimer\" pour la retirer du guide.",
            )

    def _get_error_thumbnail(self):
        """Vignette de remplacement (fond gris, croix rouge) affichee a la
        place de la miniature d'une etape dont l'image brute est illisible ou
        corrompue - generee une seule fois puis partagee entre toutes les
        cartes en erreur (son contenu ne depend jamais de l'etape)."""
        if self._error_thumbnail_photo is None:
            w, h = THUMBNAIL_MAX_SIZE
            img = Image.new("RGB", (w, h), color=(90, 90, 90))
            draw = ImageDraw.Draw(img)
            margin = min(w, h) // 5
            draw.line([(margin, margin), (w - margin, h - margin)], fill=(220, 60, 60), width=4)
            draw.line([(w - margin, margin), (margin, h - margin)], fill=(220, 60, 60), width=4)
            self._error_thumbnail_photo = ImageTk.PhotoImage(img)
        return self._error_thumbnail_photo

    def _get_thumbnail(self, step):
        """Renvoie la miniature (PhotoImage) deja rendue pour cette etape si
        elle est en cache, sinon la (re)genere depuis le disque et la met en
        cache. Le cache est indexe par step.uid, invalide explicitement par
        les gestionnaires d'evenements des qu'une mutation change reellement
        le RENDU de l'etape (redaction, reprise, zoom) - jamais pour un
        simple reordonnancement.

        Si l'image brute est illisible ou corrompue (fichier 0 octet,
        tronque, verrou antivirus, disque plein ayant interrompu l'ecriture),
        render_step_image leve (OSError, ValueError, y compris
        PIL.UnidentifiedImageError qui herite de OSError) - AVANT ce
        correctif, cette exception remontait non geree jusqu'a la boucle de
        construction de _build_review_view, l'interrompant en plein milieu
        et laissant un ecran a moitie construit, sans bouton d'export ni
        moyen de revenir en arriere (bug trouve a l'audit, dimension 1).
        Cette etape-la ne doit jamais empecher l'affichage des autres."""
        cached = self._thumbnail_cache.get(step.uid)
        if cached is not None:
            return cached
        try:
            img = render_step_image(step, zoom=step.zoom)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning(
                "Image brute illisible pour l'etape %s (%s)",
                step.index, step.raw_image_path, exc_info=True,
            )
            self._thumbnail_error_uids.add(step.uid)
            photo = self._get_error_thumbnail()
            self._thumbnail_cache[step.uid] = photo
            return photo
        self._thumbnail_error_uids.discard(step.uid)
        img.thumbnail(THUMBNAIL_MAX_SIZE)
        photo = ImageTk.PhotoImage(img)
        self._thumbnail_cache[step.uid] = photo
        return photo

    def _invalidate_thumbnail(self, step):
        """Invalide le cache de miniature ET le marqueur d'erreur associe
        d'UNE etape - a appeler des que le RENDU de cette etape change
        reellement (reprise, redaction, zoom, suppression). Regroupe les deux
        pour eviter qu'une etape corrigee par une reprise/redaction ne reste
        marquee en erreur indefiniment (ou inversement)."""
        self._thumbnail_cache.pop(step.uid, None)
        self._thumbnail_error_uids.discard(step.uid)

    def _refresh_row_image(self, step):
        """Recalcule uniquement la miniature d'UNE etape (dont le cache a
        deja ete invalide par l'appelant) et met a jour la carte existante
        en place, sans toucher aux autres cartes ni a l'ordre d'affichage."""
        row_info = self._rows.get(step.uid)
        if row_info is None:
            return
        photo = self._get_thumbnail(step)
        row_info["img_label"].configure(image=photo)
        row_info["img_label"].image = photo
        error_label = row_info.get("error_label")
        if error_label is not None:
            if step.uid in self._thumbnail_error_uids:
                error_label.pack(anchor="w")
            else:
                error_label.pack_forget()

    def _update_step_count_and_buttons(self):
        if hasattr(self, "_step_count_var"):
            self._step_count_var.set(f"{len(self.steps)} etape(s)")
        state = "normal" if self.steps else "disabled"
        for btn in getattr(self, "_export_buttons", []):
            btn.configure(state=state)

    def _reorder_and_repack(self):
        """Reapplique l'ordre courant de self.steps aux cartes DEJA
        construites, sans reconstruire ni re-rendre aucune image : utilise
        apres un deplacement (Haut/Bas/glisser-depose), qui ne change que la
        POSITION des etapes, jamais le contenu d'aucune image. Repack (pas de
        destruction/recreation de widgets) + mise a jour des libelles
        "Etape N", qui eux changent bien pour toutes les cartes suivant le
        point de deplacement."""
        for step in self.steps:
            row_info = self._rows.get(step.uid)
            if row_info is None:
                continue
            row_info["frame"].pack_forget()
            row_info["frame"].pack(fill="x", pady=4, padx=2)
            row_info["index_var"].set(f"Etape {step.index}")

    def _current_row_frames(self):
        """Cartes actuellement affichees, dans l'ordre de self.steps -
        recalcule a la volee (simple liste de references deja existantes,
        cout negligeable) plutot que maintenu incrementalement en parallele."""
        frames = []
        for step in self.steps:
            row_info = self._rows.get(step.uid)
            if row_info is not None:
                frames.append(row_info["frame"])
        return frames

    def _remove_row(self, step):
        row_info = self._rows.pop(step.uid, None)
        if row_info is not None:
            row_info["frame"].destroy()
        self._invalidate_thumbnail(step)

    def _insert_row_after(self, step, after_step):
        after_frame = self._rows[after_step.uid]["frame"] if after_step is not None else None
        self._build_step_row(self._review_inner, step, after=after_frame)

    def _build_step_row(self, parent, step, *, after=None):
        row = ttk.Frame(parent, padding=8, relief="groove")
        pack_kwargs = {"fill": "x", "pady": 4, "padx": 2}
        if after is not None:
            pack_kwargs["after"] = after
        row.pack(**pack_kwargs)

        grip = ttk.Label(row, text="⣿⣿", foreground="#888", cursor="fleur")
        grip.pack(side="left", padx=(0, 8))
        grip.bind("<ButtonPress-1>", lambda e, s=step: self._on_drag_start(s))
        grip.bind("<ButtonRelease-1>", self._on_drag_drop)

        photo = self._get_thumbnail(step)
        img_label = ttk.Label(row, image=photo)
        img_label.image = photo
        img_label.pack(side="left", padx=(0, 10))

        # Les boutons d'action sont empaquetes AVANT le bloc de texte "mid"
        # (contrairement a l'ordre precedent : texte d'abord, boutons
        # ensuite). Sous le gestionnaire pack de Tk, c'est l'ORDRE
        # D'EMPAQUETAGE - pas le side="left"/"right" - qui determine quel
        # widget reclame sa part de la cavite disponible en premier. Avec le
        # texte empaquete en premier (ancien ordre) et expand=True, "mid"
        # reclamait tout l'espace restant AVANT que les boutons n'aient pu
        # reserver le leur : en dessous d'un certain seuil de largeur de
        # fenetre (atteint bien avant self.minsize), "Rediger" et "Supprimer"
        # se retrouvaient coupes hors champ, caches sous la barre de
        # defilement verticale, sans aucune barre de defilement horizontale
        # pour les atteindre (bug trouve a l'audit : regression partielle du
        # fix du commit 387c5b4, qui avait bien reparti les boutons sur deux
        # rangees mais sans corriger cet ordre d'empaquetage). En empaquetant
        # les boutons D'ABORD, ils reservent toujours leur taille minimale
        # requise en priorite ; c'est desormais le champ de texte (qui peut
        # legitimement retrecir sans perdre de fonctionnalite) qui absorbe le
        # manque de place, jamais les boutons d'action.
        btns = ttk.Frame(row)
        btns.pack(side="right")
        btns_row1 = ttk.Frame(btns)
        btns_row1.pack(anchor="e")
        btns_row2 = ttk.Frame(btns)
        btns_row2.pack(anchor="e", pady=(4, 0))
        ttk.Button(btns_row1, text="Haut", width=6, command=lambda s=step: self._move(s, -1)).pack(side="left", padx=2)
        ttk.Button(btns_row1, text="Bas", width=6, command=lambda s=step: self._move(s, +1)).pack(side="left", padx=2)
        ttk.Button(btns_row1, text="Rediger", width=8, command=lambda s=step: self._open_redaction_editor(s)).pack(side="left", padx=2)
        ttk.Button(btns_row2, text="Reprendre", width=9, command=lambda s=step: self._retake_step(s)).pack(side="left", padx=2)
        ttk.Button(btns_row2, text="Dupliquer", width=9, command=lambda s=step: self._duplicate(s)).pack(side="left", padx=2)
        ttk.Button(btns_row2, text="Supprimer", width=9, command=lambda s=step: self._delete(s)).pack(side="left", padx=2)

        mid = ttk.Frame(row)
        mid.pack(side="left", fill="both", expand=True)
        index_var = tk.StringVar(value=f"Etape {step.index}")
        ttk.Label(mid, textvariable=index_var, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        # Indicateur visible uniquement si l'image brute de cette etape est
        # illisible/corrompue (voir _get_thumbnail) - jamais bloquant, juste
        # une alerte qui oriente l'utilisateur vers "Reprendre" ou
        # "Supprimer" plutot que de le laisser deviner pourquoi la vignette
        # est grise (bug trouve a l'audit, dimension 1).
        error_label = ttk.Label(
            mid, text="Image introuvable ou corrompue",
            foreground="#c0392b", font=("Segoe UI", 8, "bold"),
        )
        if step.uid in self._thumbnail_error_uids:
            error_label.pack(anchor="w")
        desc_var = tk.StringVar(value=step.description)
        entry = ttk.Entry(mid, textvariable=desc_var, width=50)
        entry.pack(anchor="w", fill="x", pady=(2, 0))
        # Meme bug que pour le titre (voir _build_review_view) : sans
        # l'appel a _save_session_meta() ici, une description editee puis
        # jamais suivie d'une AUTRE mutation de self.steps n'etait jamais
        # ecrite dans session.json. On appelle _save_session_meta()
        # directement (pas _build_review_view()) pour ne pas reconstruire
        # toute la vue - et donc perdre le focus/défilement - a chaque
        # simple edition de texte.
        def _on_description_committed(event, s=step, v=desc_var):
            s.description = v.get()
            self._save_session_meta()

        entry.bind("<FocusOut>", _on_description_committed)
        entry.bind("<Return>", _on_description_committed)
        zoom_var = tk.BooleanVar(value=step.zoom)
        zoom_check = ttk.Checkbutton(
            mid, text="Zoomer sur la zone du clic", variable=zoom_var,
            command=lambda s=step, v=zoom_var: self._toggle_zoom(s, v),
        )
        zoom_check.pack(anchor="w", pady=(4, 0))

        self._rows[step.uid] = {
            "frame": row, "index_var": index_var, "img_label": img_label, "error_label": error_label,
        }
        return row

    def _toggle_zoom(self, step, zoom_var):
        step.zoom = zoom_var.get()
        # Seule l'image de CETTE etape change (cadrage zoome ou non) : on
        # invalide uniquement son entree de cache et on ne re-rend que sa
        # carte, au lieu de reconstruire toute la vue de relecture.
        self._invalidate_thumbnail(step)
        self._save_session_meta()
        self._refresh_row_image(step)

    def _move(self, step, direction):
        # Haut/Bas ne change que la POSITION des etapes, jamais le contenu
        # d'aucune image : aucune miniature n'a besoin d'etre re-rendue,
        # seul l'ordre d'affichage et les libelles "Etape N" doivent l'etre.
        index = self.steps.index(step)
        move_step(self.steps, index, direction)
        self._reorder_and_repack()
        self._save_session_meta()

    def _delete(self, step):
        if not messagebox.askyesno("Supprimer l'etape", "Supprimer cette etape du guide ?"):
            return
        index = self.steps.index(step)
        delete_step(self.steps, index)
        self._remove_row(step)
        if not self.steps:
            # Cas rare (derniere etape supprimee) : reconstruction complete
            # pour reafficher le message "Aucune etape capturee" et
            # desactiver les boutons d'export, sans logique dediee pour un
            # etat qui ne se produit qu'une fois par guide au plus.
            self._build_review_view()
            return
        for s in self.steps:
            self._rows[s.uid]["index_var"].set(f"Etape {s.index}")
        self._save_session_meta()
        self._update_step_count_and_buttons()

    def _duplicate(self, step):
        # Utile pour scinder une etape en deux instructions distinctes sur la
        # meme capture d'ecran (ex: "cliquez ici" puis "verifiez que ceci
        # apparait"), sans avoir a reprendre une nouvelle capture.
        index = self.steps.index(step)
        duplicate_step(self.steps, index)
        new_step = self.steps[index + 1]
        self._insert_row_after(new_step, step)
        for s in self.steps:
            self._rows[s.uid]["index_var"].set(f"Etape {s.index}")
        self._save_session_meta()
        self._update_step_count_and_buttons()

    # ------------------------------------------------------------------
    # Reprise (re-capture) d'une seule etape, sans refaire tout l'enregistrement
    # ------------------------------------------------------------------

    def _retake_step(self, step):
        self._retake_step_obj = step
        self.withdraw()
        self._open_retake_hud(step)

        self.hud.update_idletasks()
        hud_cx = self.hud.winfo_rootx() + self.hud.winfo_width() // 2
        hud_cy = self.hud.winfo_rooty() + self.hud.winfo_height() // 2
        hud_hwnd = get_window_at_point(hud_cx, hud_cy)
        excluded = {hud_hwnd} if hud_hwnd else set()
        # Sous-dossier dedie aux reprises, propre a CETTE etape : un nouveau
        # Recorder recommence sa propre numerotation a 1 a chaque reprise, ce
        # qui ecraserait silencieusement la reprise d'une AUTRE etape si
        # toutes les reprises partageaient le meme dossier "retakes" (bug
        # trouve a l'audit). Toujours recalcule a partir de `step.uid` SEUL
        # (jamais a partir de raw_image_path.parent) : une precedente
        # version reutilisait le dossier parent de raw_image_path des que
        # "retakes" y apparaissait, mais duplicate_step donne une copie qui
        # partage le raw_image_path de l'original (potentiellement deja
        # sous retakes/<uid_original>/) tout en ayant son PROPRE uid neuf -
        # reprendre cette copie recalculait alors le dossier de l'ORIGINAL
        # au lieu du sien, ecrasant silencieusement la reprise de
        # l'original (second bug trouve a l'audit, reintroduit par la
        # duplication d'etape). Cette version, purement fonction de
        # step.uid, retombe naturellement sur le meme dossier qu'une
        # reprise precedente de la MEME etape (meme uid), et sur un dossier
        # distinct pour toute autre etape, dupliquee ou non.
        retake_dir = self.session_dir / "retakes" / step.uid
        # Meme protection que _start_recording (voir son commentaire) : la
        # reprise passe elle aussi par self.withdraw() avant de creer/demarrer
        # le Recorder, donc le meme risque de fenetre cachee + HUD bloque sans
        # message d'erreur s'applique ici a l'identique.
        try:
            self._retake_recorder = Recorder(retake_dir, excluded_hwnds=excluded)
            self._retake_recorder.start()
        except Exception as exc:  # noqa: BLE001
            self._retake_recorder = None
            if self.hud is not None:
                self.hud.destroy()
                self.hud = None
            self.deiconify()
            messagebox.showerror(
                "Reprise impossible",
                "La reprise de cette etape n'a pas pu demarrer.\n\n"
                "Causes possibles : permissions insuffisantes, antivirus/EDR "
                "bloquant l'ecoute de la souris, ou dossier de session "
                "inaccessible en ecriture.\n\n"
                f"Detail : {exc}",
            )
            return
        self.after(150, self._poll_retake)

    def _open_retake_hud(self, step):
        self.hud = tk.Toplevel(self)
        self.hud.title("GuideExpress")
        self.hud.attributes("-topmost", True)
        self.hud.resizable(False, False)
        self.hud.protocol("WM_DELETE_WINDOW", self._cancel_retake)

        frame = ttk.Frame(self.hud, padding=12)
        frame.pack()
        ttk.Label(
            frame, text=f"Reprise de l'etape {step.index}", foreground="#c0392b", font=("Segoe UI", 10, "bold"),
        ).pack()
        ttk.Label(frame, text="Cliquez sur l'element a capturer...").pack(pady=(4, 8))
        ttk.Button(frame, text="Annuler", command=self._cancel_retake).pack()

        self.hud.update_idletasks()
        screen_w = self.hud.winfo_screenwidth()
        self.hud.geometry(f"+{screen_w - 260}+20")

    def _poll_retake(self):
        if self._retake_recorder is None:
            return
        if not self._retake_recorder.events.empty():
            data = self._retake_recorder.events.get()
            self._finish_retake(data)
            return
        if self._retake_recorder.is_active:
            self.after(150, self._poll_retake)

    def _finish_retake(self, data):
        self._retake_recorder.stop()
        self._retake_recorder.wait_for_pending_saves()
        # Un clic supplementaire survenu pendant la fenetre de reprise (avant
        # que stop() ne prenne effet, ex: double-clic) peut deja avoir ete
        # capture et ecrit sur le disque - cette capture excedentaire n'est
        # jamais referencee par aucune etape (seule la premiere, ci-dessus,
        # est utilisee) : sans nettoyage, elle resterait orpheline sur le
        # disque indefiniment.
        while not self._retake_recorder.events.empty():
            extra = self._retake_recorder.events.get()
            try:
                extra["raw_image_path"].unlink(missing_ok=True)
            except OSError:
                pass
        self._retake_recorder.shutdown()
        self._retake_recorder = None

        step = self._retake_step_obj
        self._retake_step_obj = None
        step.raw_image_path = data["raw_image_path"]
        step.click_x = data["click_x"]
        step.click_y = data["click_y"]
        step.button = data["button"]
        step.window_title = data["window_title"]
        step.timestamp = data["timestamp"]
        # Les rectangles de redaction sont en coordonnees absolues de
        # l'ancienne capture : ils n'ont plus de sens sur la nouvelle image
        # (fenetre/resolution potentiellement differentes), donc on les
        # efface plutot que de risquer un masquage mal place ou manquant.
        step.redactions = []

        if self.hud is not None:
            self.hud.destroy()
            self.hud = None
        self.deiconify()
        # Seule l'image de CETTE etape a change (nouvelle capture) : sa
        # position dans la liste, son index affiche et toutes les autres
        # cartes restent inchanges, inutile de reconstruire toute la vue.
        self._invalidate_thumbnail(step)
        self._save_session_meta()
        self._refresh_row_image(step)

    def _cancel_retake(self):
        if self._retake_recorder is not None:
            self._retake_recorder.stop()
            self._retake_recorder.wait_for_pending_saves()
            # Un clic peut avoir eu lieu juste avant l'annulation (capture
            # deja ecrite sur le disque, mais pas encore consommee par
            # _poll_retake) : sans nettoyage, ce fichier ne serait jamais
            # rattache a aucune etape et resterait orphelin.
            while not self._retake_recorder.events.empty():
                extra = self._retake_recorder.events.get()
                try:
                    extra["raw_image_path"].unlink(missing_ok=True)
                except OSError:
                    pass
            self._retake_recorder.shutdown()
            self._retake_recorder = None
        self._retake_step_obj = None
        if self.hud is not None:
            self.hud.destroy()
            self.hud = None
        self.deiconify()

    def _on_drag_start(self, step):
        self._drag_uid = step.uid

    def _on_drag_drop(self, event):
        if self._drag_uid is None:
            return
        drag_uid = self._drag_uid
        self._drag_uid = None
        drag_index = next((i for i, s in enumerate(self.steps) if s.uid == drag_uid), None)
        if drag_index is None:
            return
        # event.x_root/y_root donnent la position ecran reelle du curseur au
        # relachement, independamment du widget qui a recu l'evenement (le
        # "grab" implicite de Tkinter livre toujours le ButtonRelease a la
        # poignee ou le glisse a commence, pas au widget survole a la fin).
        widget = self.winfo_containing(event.x_root, event.y_root)
        target_index = self._row_index_of(widget)
        if target_index is None or target_index == drag_index:
            return
        # Un glisser-depose ne change que la POSITION des etapes, jamais le
        # contenu d'aucune image : meme optimisation que _move (voir son
        # commentaire), aucune miniature n'a besoin d'etre re-rendue.
        move_step_to(self.steps, drag_index, target_index)
        self._reorder_and_repack()
        self._save_session_meta()

    def _row_index_of(self, widget):
        """Remonte la hierarchie de widgets depuis `widget` jusqu'a trouver
        une des lignes d'etape connues, et renvoie sa position (0-based)."""
        row_frames = self._current_row_frames()
        while widget is not None:
            if widget in row_frames:
                return row_frames.index(widget)
            widget = widget.master
        return None

    # ------------------------------------------------------------------
    # Editeur de redaction (masquage de zones sensibles)
    # ------------------------------------------------------------------

    def _open_redaction_editor(self, step):
        try:
            # Toujours zoom=False ici, meme si step.zoom est active : les
            # coordonnees de redaction sont stockees en absolu par rapport a
            # l'image brute complete (voir capture.py), le zoom n'est qu'un
            # cadrage applique a l'export/apercu final, jamais a l'espace de
            # coordonnees d'edition.
            full_img = render_step_image(step, zoom=False)
        except (OSError, ValueError) as exc:
            # La capture brute a pu etre supprimee/corrompue depuis
            # l'enregistrement (nettoyage manuel du dossier de session, etc.).
            # Charger l'image AVANT d'ouvrir la fenetre modale (grab_set)
            # evite de laisser l'application bloquee sur une boite vide si
            # cet appel echoue.
            messagebox.showerror(
                "Image introuvable",
                f"Impossible de charger la capture de l'etape {step.index} :\n{exc}",
            )
            return

        editor = tk.Toplevel(self)
        editor.title(f"Rediger - Etape {step.index}")
        editor.transient(self)
        editor.protocol("WM_DELETE_WINDOW", lambda: self._close_editor(editor, step))
        editor.grab_set()

        display_img = full_img.copy()
        display_img.thumbnail(EDITOR_MAX_SIZE)
        scale_x = full_img.width / display_img.width
        scale_y = full_img.height / display_img.height

        ttk.Label(
            editor,
            text="Cliquez-glissez pour masquer une zone sensible (rectangle plein, irreversible a l'export).",
            padding=8,
        ).pack()

        canvas = tk.Canvas(editor, width=display_img.width, height=display_img.height, cursor="crosshair")
        canvas.pack(padx=8, pady=8)
        photo = ImageTk.PhotoImage(display_img)
        canvas.image = photo  # garde une reference (sinon Tk purge l'image)
        canvas.create_image(0, 0, anchor="nw", image=photo)

        state = {"start": None, "rect_id": None}

        def on_press(event):
            state["start"] = (event.x, event.y)
            state["rect_id"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

        def on_drag(event):
            if state["rect_id"] is not None:
                x0, y0 = state["start"]
                canvas.coords(state["rect_id"], x0, y0, event.x, event.y)

        def on_release(event):
            if state["start"] is None:
                return
            x0, y0 = state["start"]
            x1, y1 = event.x, event.y
            state["start"] = None
            state["rect_id"] = None
            if abs(x1 - x0) < 3 or abs(y1 - y0) < 3:
                return  # clic sans glissement reel : ignore
            step.redactions.append((
                int(x0 * scale_x), int(y0 * scale_y),
                int(x1 * scale_x), int(y1 * scale_y),
            ))
            _redraw()

        def _redraw():
            img = render_step_image(step, zoom=False)
            img.thumbnail(EDITOR_MAX_SIZE)
            new_photo = ImageTk.PhotoImage(img)
            canvas.image = new_photo
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=new_photo)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        btns = ttk.Frame(editor, padding=8)
        btns.pack()

        def undo_last():
            if step.redactions:
                step.redactions.pop()
                _redraw()

        ttk.Button(btns, text="Annuler la derniere redaction", command=undo_last).pack(side="left", padx=4)
        ttk.Button(btns, text="Terminer", command=lambda: self._close_editor(editor, step)).pack(side="left", padx=4)

    def _close_editor(self, editor, step):
        editor.destroy()
        # Seule l'image de CETTE etape a change (redactions ajoutees ou
        # retirees dans l'editeur) : pas besoin de reconstruire toute la vue
        # de relecture, juste d'invalider son cache et de re-rendre sa carte.
        self._invalidate_thumbnail(step)
        self._save_session_meta()
        self._refresh_row_image(step)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_html(self):
        safe_name = sanitize_filename(self.title_var.get())
        path = filedialog.asksaveasfilename(
            title="Exporter le guide en HTML",
            defaultextension=".html",
            filetypes=[("Page HTML", "*.html")],
            initialfile=f"{safe_name}.html",
        )
        if not path:
            return
        try:
            export_html(self.steps, self.title_var.get() or "Guide", Path(path))
        except OSError as exc:
            messagebox.showerror("Echec de l'export", f"Impossible d'ecrire le fichier :\n{exc}")
            return
        if messagebox.askyesno("Export termine", f"Guide exporte :\n{path}\n\nL'ouvrir maintenant ?"):
            os.startfile(path)

    def _export_markdown(self):
        directory = filedialog.askdirectory(title="Choisir le dossier de destination pour le guide Markdown")
        if not directory:
            return
        safe_name = sanitize_filename(self.title_var.get())
        try:
            md_path = export_markdown(self.steps, self.title_var.get() or "Guide", Path(directory) / safe_name)
        except OSError as exc:
            messagebox.showerror("Echec de l'export", f"Impossible d'ecrire le guide :\n{exc}")
            return
        messagebox.showinfo("Export termine", f"Guide exporte :\n{md_path}")

    def _export_pdf(self):
        safe_name = sanitize_filename(self.title_var.get())
        path = filedialog.asksaveasfilename(
            title="Exporter le guide en PDF",
            defaultextension=".pdf",
            filetypes=[("Document PDF", "*.pdf")],
            initialfile=f"{safe_name}.pdf",
        )
        if not path:
            return
        try:
            export_pdf(self.steps, self.title_var.get() or "Guide", Path(path))
        except OSError as exc:
            messagebox.showerror("Echec de l'export", f"Impossible d'ecrire le fichier :\n{exc}")
            return
        if messagebox.askyesno("Export termine", f"Guide exporte :\n{path}\n\nL'ouvrir maintenant ?"):
            os.startfile(path)

    # ------------------------------------------------------------------

    def _on_close(self):
        if self.recorder is not None:
            self.recorder.shutdown()
        if self._retake_recorder is not None:
            self._retake_recorder.shutdown()
        if self.hud is not None:
            try:
                self.hud.destroy()
            except tk.TclError:
                pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def run_gui():
    app = GuideExpressApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
