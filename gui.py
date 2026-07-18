"""Interface graphique (Tkinter) de GuideExpress."""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

from PIL import ImageTk

DONATE_URL = "https://ko-fi.com/yoshines62000"

from capture import Step, render_step_image, move_step, delete_step, sanitize_filename, get_window_at_point
from recorder import Recorder
from export import export_html, export_markdown

APP_DIR = Path.home() / ".guide_express"
SESSIONS_DIR = APP_DIR / "sessions"

THUMBNAIL_MAX_SIZE = (220, 150)
EDITOR_MAX_SIZE = (980, 680)


def _resource_path(name: str) -> Path:
    """Chemin d'une ressource embarquee (ex: icon.ico), fonctionne aussi bien
    lance depuis le code source qu'empaquete par PyInstaller (les fichiers de
    donnees sont alors extraits dans un dossier temporaire sys._MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


class GuideExpressApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GuideExpress - Guides pas-a-pas")
        self.geometry("760x560")
        self.minsize(620, 420)
        try:
            self.iconbitmap(str(_resource_path("icon.ico")))
        except tk.TclError:
            pass  # icone absente ou format non supporte : pas bloquant

        self.steps: list = []
        self.recorder: Recorder | None = None
        self.hud: tk.Toplevel | None = None
        self.title_var = tk.StringVar(value="Mon guide")
        self._thumbnail_refs: list = []
        self._container = ttk.Frame(self)
        self._container.pack(fill="both", expand=True)

        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill="x", side="bottom")
        donate_label = ttk.Label(bottom_bar, text="☕ Soutenir le projet", foreground="#0645AD", cursor="hand2")
        donate_label.pack(side="right", padx=8, pady=4)
        donate_label.bind("<Button-1>", lambda event: webbrowser.open(DONATE_URL))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_start_view()

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
    # Enregistrement
    # ------------------------------------------------------------------

    def _start_recording(self):
        session_dir = SESSIONS_DIR / time.strftime("%Y%m%d-%H%M%S")
        self.steps = []

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
        self.recorder = Recorder(session_dir, excluded_hwnds=excluded)
        self.recorder.start()
        self.after(150, self._poll_events)

    def _open_hud(self):
        self.hud = tk.Toplevel(self)
        self.hud.title("GuideExpress")
        self.hud.attributes("-topmost", True)
        self.hud.resizable(False, False)
        self.hud.protocol("WM_DELETE_WINDOW", self._stop_recording)

        frame = ttk.Frame(self.hud, padding=12)
        frame.pack()
        ttk.Label(frame, text="Enregistrement en cours", foreground="#c0392b", font=("Segoe UI", 10, "bold")).pack()
        self.hud_count_var = tk.StringVar(value="0 etape(s) capturee(s)")
        ttk.Label(frame, textvariable=self.hud_count_var).pack(pady=(4, 8))
        ttk.Button(frame, text="Arreter l'enregistrement", command=self._stop_recording).pack()

        self.hud.update_idletasks()
        screen_w = self.hud.winfo_screenwidth()
        self.hud.geometry(f"+{screen_w - 260}+20")

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
        self._clear_container()
        self._thumbnail_refs = []

        top = ttk.Frame(self._container, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Titre :").pack(side="left")
        ttk.Entry(top, textvariable=self.title_var, width=40).pack(side="left", padx=6)
        ttk.Label(top, text=f"{len(self.steps)} etape(s)").pack(side="left", padx=12)

        list_frame = ttk.Frame(self._container)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        if not self.steps:
            ttk.Label(inner, text="Aucune etape capturee (aucun clic detecte pendant l'enregistrement).").pack(pady=20)

        for i, step in enumerate(self.steps):
            self._build_step_row(inner, i)

        bottom = ttk.Frame(self._container, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Nouvel enregistrement", command=self._build_start_view).pack(side="left")
        state = "normal" if self.steps else "disabled"
        ttk.Button(bottom, text="Exporter en HTML", command=self._export_html, state=state).pack(side="left", padx=6)
        ttk.Button(bottom, text="Exporter en Markdown", command=self._export_markdown, state=state).pack(side="left")

    def _build_step_row(self, parent, index):
        step = self.steps[index]
        row = ttk.Frame(parent, padding=8, relief="groove")
        row.pack(fill="x", pady=4, padx=2)

        img = render_step_image(step, zoom=False)
        img.thumbnail(THUMBNAIL_MAX_SIZE)
        photo = ImageTk.PhotoImage(img)
        self._thumbnail_refs.append(photo)
        ttk.Label(row, image=photo).pack(side="left", padx=(0, 10))

        mid = ttk.Frame(row)
        mid.pack(side="left", fill="both", expand=True)
        ttk.Label(mid, text=f"Etape {step.index}", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        desc_var = tk.StringVar(value=step.description)
        entry = ttk.Entry(mid, textvariable=desc_var, width=50)
        entry.pack(anchor="w", fill="x", pady=(2, 0))
        entry.bind("<FocusOut>", lambda e, s=step, v=desc_var: setattr(s, "description", v.get()))
        entry.bind("<Return>", lambda e, s=step, v=desc_var: setattr(s, "description", v.get()))

        btns = ttk.Frame(row)
        btns.pack(side="right")
        ttk.Button(btns, text="Haut", width=6, command=lambda i=index: self._move(i, -1)).pack(side="left", padx=2)
        ttk.Button(btns, text="Bas", width=6, command=lambda i=index: self._move(i, +1)).pack(side="left", padx=2)
        ttk.Button(btns, text="Rediger", width=8, command=lambda i=index: self._open_redaction_editor(i)).pack(side="left", padx=2)
        ttk.Button(btns, text="Supprimer", width=9, command=lambda i=index: self._delete(i)).pack(side="left", padx=2)

    def _move(self, index, direction):
        move_step(self.steps, index, direction)
        self._build_review_view()

    def _delete(self, index):
        if not messagebox.askyesno("Supprimer l'etape", "Supprimer cette etape du guide ?"):
            return
        delete_step(self.steps, index)
        self._build_review_view()

    # ------------------------------------------------------------------
    # Editeur de redaction (masquage de zones sensibles)
    # ------------------------------------------------------------------

    def _open_redaction_editor(self, index):
        step = self.steps[index]
        try:
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
        editor.protocol("WM_DELETE_WINDOW", lambda: self._close_editor(editor, index))
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
        ttk.Button(btns, text="Terminer", command=lambda: self._close_editor(editor, index)).pack(side="left", padx=4)

    def _close_editor(self, editor, index):
        editor.destroy()
        self._build_review_view()

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

    # ------------------------------------------------------------------

    def _on_close(self):
        if self.recorder is not None:
            self.recorder.shutdown()
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
