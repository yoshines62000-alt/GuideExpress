"""
Moteur de capture et de rendu pour GuideExpress.

Contient toute la logique metier (independante de l'interface graphique) :
- modele d'une etape (Step)
- rendu d'une image annotee (marqueur de clic, redaction) a partir de l'image brute
- recuperation du titre de la fenetre active (Windows, via ctypes, sans dependance externe)

Choix de confidentialite deliberes :
- aucune capture de frappe clavier n'est jamais effectuee, seulement la position des
  clics de souris et une capture d'ecran a cet instant. Un outil qui se veut sur et
  respectueux de la vie privee ne doit jamais s'approcher d'un keylogger.
- la redaction (masquage de zones sensibles) utilise des rectangles opaques, pas un
  flou : un flou trop leger peut laisser deviner le contenu masque, un rectangle
  plein ne laisse aucune ambiguite.
"""

from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

CLICK_MARKER_COLOR = (230, 30, 30)
CLICK_MARKER_RADIUS = 22
CLICK_MARKER_WIDTH = 4
REDACTION_COLOR = (20, 20, 20)

# Signatures explicites (argtypes/restype) pour les appels Win32 utilises plus
# bas : sans elles, ctypes traite par defaut les HWND comme des c_int 32 bits
# signes, ce qui pourrait mal se comporter pour une valeur de HWND >= 0x80000000
# (improbable en pratique, mais peu couteux a fiabiliser). `_user32` vaut None
# hors Windows ou si l'initialisation echoue ; chaque fonction ci-dessous gere
# deja ce cas via son propre try/except.
try:
    import ctypes.wintypes as _wintypes
    _user32 = ctypes.windll.user32
    _user32.WindowFromPoint.argtypes = [_wintypes.POINT]
    _user32.WindowFromPoint.restype = _wintypes.HWND
    _user32.GetAncestor.argtypes = [_wintypes.HWND, ctypes.c_uint]
    _user32.GetAncestor.restype = _wintypes.HWND
    _user32.GetWindowTextLengthW.argtypes = [_wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [_wintypes.HWND, _wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
except (AttributeError, OSError):
    _wintypes = None
    _user32 = None


@dataclass
class Step:
    """Une etape capturee : un clic, la capture d'ecran associee, et ses annotations."""

    index: int
    raw_image_path: Path
    click_x: int
    click_y: int
    window_title: str
    timestamp: str
    description: str = ""
    # Rectangles a masquer, en coordonnees absolues de l'image brute : (x1, y1, x2, y2).
    redactions: list = field(default_factory=list)
    # Zoome sur la zone du clic a l'export (voir render_step_image) - utile
    # pour un clic sur un petit element (icone, case a cocher) difficile a
    # repérer sur une capture plein ecran.
    zoom: bool = False

    def default_description(self) -> str:
        app = self.window_title.strip() or "une fenetre non identifiee"
        return f"Cliquez dans {app}."

    def display_description(self) -> str:
        return self.description.strip() or self.default_description()


def _get_window_text(hwnd) -> str:
    if _user32 is None or not hwnd:
        return ""
    try:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except (AttributeError, OSError):
        return ""


def get_window_at_point(x: int, y: int) -> int:
    """Handle (HWND) de la fenetre de plus haut niveau physiquement situee a
    la position ecran donnee - independamment de savoir si cette fenetre a le
    focus. Utilise pour exclure les clics sur nos propres fenetres (ex: le
    bouton Arreter de l'enregistrement) sans dependre de la semantique du
    focus, qui n'est pas fiable pour ce genre de verification.
    Renvoie 0 si indisponible."""
    if _user32 is None:
        return 0
    try:
        pt = _wintypes.POINT(x, y)
        hwnd = _user32.WindowFromPoint(pt)
        if not hwnd:
            return 0
        GA_ROOT = 2
        root = _user32.GetAncestor(hwnd, GA_ROOT)
        return root or hwnd
    except (AttributeError, OSError):
        return 0


def get_window_title_at_point(x: int, y: int) -> str:
    """Titre de la fenetre physiquement situee a la position ecran donnee."""
    hwnd = get_window_at_point(x, y)
    return _get_window_text(hwnd) if hwnd else ""


def render_step_image(step: Step, zoom: bool = False) -> Image.Image:
    """Construit l'image finale d'une etape (marqueur de clic + redactions applique)
    a partir de l'image brute, SANS jamais modifier le fichier source sur le disque.
    Permet de re-editer une etape (ex: ajouter une redaction) sans perte d'information."""
    with Image.open(step.raw_image_path) as src:
        img = src.convert("RGB").copy()

    draw = ImageDraw.Draw(img)
    for (x1, y1, x2, y2) in step.redactions:
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        draw.rectangle([left, top, right, bottom], fill=REDACTION_COLOR)

    r = CLICK_MARKER_RADIUS
    cx, cy = step.click_x, step.click_y
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=CLICK_MARKER_COLOR,
        width=CLICK_MARKER_WIDTH,
    )

    if zoom:
        img = _crop_zoomed_region(img, cx, cy)

    return img


def _crop_zoomed_region(img: Image.Image, cx: int, cy: int, half_size: int = 260) -> Image.Image:
    """Recadre une zone centree sur le clic, pour un aperçu rapproche (miniature)."""
    width, height = img.size
    left = max(0, min(cx - half_size, width - 2 * half_size)) if width > 2 * half_size else 0
    top = max(0, min(cy - half_size, height - 2 * half_size)) if height > 2 * half_size else 0
    right = min(width, left + 2 * half_size)
    bottom = min(height, top + 2 * half_size)
    return img.crop((left, top, right, bottom))


# ---------------------------------------------------------------------------
# Renumerotation / reordonnancement (logique pure, sans effet de bord disque)
# ---------------------------------------------------------------------------

def renumber(steps: list) -> None:
    """Reattribue les index 1..N dans l'ordre de la liste, en place."""
    for i, step in enumerate(steps, start=1):
        step.index = i


def move_step(steps: list, from_index: int, direction: int) -> list:
    """Deplace l'etape a la position `from_index` (0-based) de +1/-1 position.
    Renvoie la nouvelle liste (deja renumerotee) ; ne fait rien si le mouvement
    sortirait de la liste."""
    target = from_index + direction
    if target < 0 or target >= len(steps) or from_index < 0 or from_index >= len(steps):
        return steps
    steps[from_index], steps[target] = steps[target], steps[from_index]
    renumber(steps)
    return steps


def move_step_to(steps: list, from_index: int, to_index: int) -> list:
    """Deplace l'etape a la position `from_index` (0-based) directement a la
    position `to_index`, en decalant les etapes intermediaires - contrairement
    a move_step (echange avec le voisin immediat), l'etape peut ainsi sauter
    plusieurs positions en un seul geste (utilise par le glisser-deposer)."""
    if from_index == to_index:
        return steps
    if not (0 <= from_index < len(steps)) or not (0 <= to_index < len(steps)):
        return steps
    step = steps.pop(from_index)
    steps.insert(to_index, step)
    renumber(steps)
    return steps


def delete_step(steps: list, index: int) -> list:
    """Supprime l'etape a la position `index` (0-based) et renumerote."""
    if 0 <= index < len(steps):
        del steps[index]
        renumber(steps)
    return steps


# ---------------------------------------------------------------------------
# Nettoyage de texte pour l'export (protection contre l'injection/la casse Markdown)
# ---------------------------------------------------------------------------

_MARKDOWN_SPECIAL_CHARS = re.compile(r'([\\`*_{}\[\]()#+\-.!])')


def escape_markdown(text: str) -> str:
    """Echappe les caracteres Markdown speciaux dans un texte libre saisi par
    l'utilisateur, pour qu'il ne casse jamais la mise en forme du guide exporte."""
    return _MARKDOWN_SPECIAL_CHARS.sub(r'\\\1', text)


def html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Noms reserves par Windows pour des peripheriques : invalides comme nom de
# fichier/dossier meme sans aucun caractere interdit (ex: "CON.txt" echoue).
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def sanitize_filename(name: str, fallback: str = "guide") -> str:
    """Nettoie un titre de guide pour qu'il soit utilisable tel quel comme nom
    de fichier ou de dossier Windows (le titre est saisi librement par
    l'utilisateur et peut contenir des caracteres interdits comme '/' ou ':',
    ou coincider avec un nom de peripherique reserve comme "CON")."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    if not cleaned:
        return fallback
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        return f"{cleaned}_"
    return cleaned
