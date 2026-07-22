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
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

CLICK_MARKER_COLOR = (230, 30, 30)
RIGHT_CLICK_MARKER_COLOR = (30, 90, 230)
CLICK_MARKER_RADIUS = 22
CLICK_MARKER_WIDTH = 4
REDACTION_COLOR = (20, 20, 20)

# Signatures explicites (argtypes/restype) pour les appels Win32 utilises plus
# bas : sans elles, ctypes traite par defaut les HWND comme des c_int 32 bits
# signes, ce qui pourrait mal se comporter pour une valeur de HWND >= 0x80000000
# (improbable en pratique, mais peu couteux a fiabiliser). `_user32` vaut None
# hors Windows ou si l'initialisation echoue ; chaque fonction ci-dessous gere
# deja ce cas via son propre try/except.
_MONITORINFO = None

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
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = _wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [_wintypes.HWND, ctypes.POINTER(_wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = _wintypes.DWORD
    # Signatures pour le positionnement du HUD sur le moniteur sous le
    # curseur (trouvaille d'audit, dimension 15) - voir get_cursor_pos et
    # get_monitor_work_area_at_point ci-dessous.
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_wintypes.POINT)]
    _user32.GetCursorPos.restype = _wintypes.BOOL
    _user32.MonitorFromPoint.argtypes = [_wintypes.POINT, ctypes.c_uint]
    _user32.MonitorFromPoint.restype = _wintypes.HANDLE

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", _wintypes.RECT),
            ("rcWork", _wintypes.RECT),
            ("dwFlags", ctypes.c_ulong),
        ]

    _user32.GetMonitorInfoW.argtypes = [_wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    _user32.GetMonitorInfoW.restype = _wintypes.BOOL
except (AttributeError, OSError):
    _wintypes = None
    _user32 = None
    _MONITORINFO = None

# Signatures Win32 pour la detection UIPI/elevation (voir
# foreground_window_is_elevated ci-dessous) : distinctes du bloc _user32
# au-dessus, kernel32/advapi32 restent None independamment si l'un des deux
# modules est indisponible.
try:
    _kernel32 = ctypes.windll.kernel32
    _advapi32 = ctypes.windll.advapi32
    _kernel32.OpenProcess.argtypes = [_wintypes.DWORD, _wintypes.BOOL, _wintypes.DWORD]
    _kernel32.OpenProcess.restype = _wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
    _kernel32.CloseHandle.restype = _wintypes.BOOL
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = _wintypes.HANDLE
    _advapi32.OpenProcessToken.argtypes = [_wintypes.HANDLE, _wintypes.DWORD, ctypes.POINTER(_wintypes.HANDLE)]
    _advapi32.OpenProcessToken.restype = _wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        _wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, _wintypes.DWORD, ctypes.POINTER(_wintypes.DWORD),
    ]
    _advapi32.GetTokenInformation.restype = _wintypes.BOOL
    _advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    _advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    _advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, _wintypes.DWORD]
    _advapi32.GetSidSubAuthority.restype = ctypes.POINTER(_wintypes.DWORD)
except (AttributeError, OSError):
    _kernel32 = None
    _advapi32 = None


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
    # Identifiant stable et unique par ETAPE (pas par fichier image) - utilise
    # par gui.py pour isoler le dossier de reprise de chaque etape. Distinct
    # de raw_image_path : deux etapes (original + copie de duplicate_step)
    # peuvent partager le meme fichier image brut sans jamais partager le
    # meme uid, ce qui evite que la reprise de l'une n'ecrase le fichier
    # utilise par l'autre (bug trouve a l'audit).
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    # "left" ou "right" - beaucoup de procedures reelles passent par un menu
    # contextuel (clic droit > Renommer, > Coller...), invisible jusqu'ici
    # puisque seul le clic gauche etait ecoute.
    button: str = "left"

    def default_description(self) -> str:
        app = self.window_title.strip() or "une fenetre non identifiee"
        if self.button == "right":
            return f"Cliquez droit dans {app}."
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


def get_window_text(hwnd) -> str:
    """Titre d'une fenetre a partir d'un HWND deja connu (obtenu au moment
    du clic via get_window_at_point, rapide et non bloquant). Wrapper public
    de _get_window_text : utilise pour resoudre le TEXTE du titre plus tard
    (voir recorder.Recorder._writer_loop), jamais dans le callback du hook
    bas niveau lui-meme. GetWindowTextW envoie en interne un message
    WM_GETTEXT a la fenetre ciblee et ATTEND sa reponse - si cette fenetre
    appartient a une application non reactive (gelee, en attente reseau...),
    l'appel peut bloquer plusieurs secondes. Windows impose un delai de
    reponse maximal aux hooks bas niveau (LowLevelHooksTimeout, 300 ms par
    defaut) : au-dela, l'OS desinstalle le hook SILENCIEUSEMENT, sans lever
    d'exception cote Python (bug trouve a l'audit, dimension 2). Appeler
    cette fonction depuis un thread separe (jamais depuis le callback du
    hook) elimine ce risque : un GetWindowTextW lent y est sans consequence
    pour la capture des clics suivants."""
    return _get_window_text(hwnd)


# ---------------------------------------------------------------------------
# Positionnement du HUD sur le bon moniteur (trouvaille d'audit, dimension 15)
# ---------------------------------------------------------------------------
# Tk.winfo_screenwidth() ne renvoie jamais que la largeur de l'ecran PRINCIPAL
# Windows, independamment de l'endroit ou l'utilisateur travaille reellement
# en configuration multi-ecrans : le HUD (statut d'enregistrement, compteur
# d'etapes, bouton Arreter) apparaissait alors systematiquement sur l'ecran
# principal, potentiellement loin de la zone de travail reelle sur un ecran
# secondaire. Les deux fonctions ci-dessous permettent a gui.py de calculer la
# position du HUD relativement au moniteur qui contient le curseur au moment
# de l'ouverture, plutot que systematiquement au moniteur principal.

def get_cursor_pos() -> Optional[tuple]:
    """Position actuelle du curseur en coordonnees ecran. Renvoie None si
    indisponible (hors Windows, echec d'un appel Win32...) - jamais
    d'exception."""
    if _user32 is None:
        return None
    try:
        pt = _wintypes.POINT()
        if not _user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return (pt.x, pt.y)
    except (AttributeError, OSError):
        return None


def get_monitor_work_area_at_point(x: int, y: int) -> Optional[tuple]:
    """Zone de travail (left, top, right, bottom - exclut la barre des
    taches) du moniteur physique contenant le point (x, y) donne. Renvoie
    None si indisponible. MONITOR_DEFAULTTONEAREST (2) : si le point ne
    tombe exactement sur aucun moniteur (rare, mais possible en bordure),
    retombe sur le moniteur le plus proche plutot que d'echouer."""
    if _user32 is None or _MONITORINFO is None:
        return None
    try:
        MONITOR_DEFAULTTONEAREST = 2
        pt = _wintypes.POINT(x, y)
        hmonitor = _user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        if not hmonitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return None
        r = info.rcWork
        return (r.left, r.top, r.right, r.bottom)
    except (AttributeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Detection UIPI / fenetre elevee (trouvaille d'audit, dimension 6)
# ---------------------------------------------------------------------------
# Windows applique l'UIPI (User Interface Privilege Isolation) depuis Vista :
# un processus de niveau d'integrite standard ne peut jamais recevoir, via un
# hook bas niveau WH_MOUSE_LL comme celui utilise par pynput, les clics
# destines a une fenetre appartenant a un processus de niveau d'integrite
# SUPERIEUR (ex: une fenetre lancee "en tant qu'administrateur"). C'est une
# barriere de securite du noyau, pas un bug de ce projet - mais sa
# consequence est un clic totalement PERDU, sans la moindre exception ni
# evenement cote Python : il n'existe donc structurellement AUCUN moyen de
# detecter APRES COUP "un clic qui n'a pas ete capture", puisqu'aucun signal
# n'atteint jamais l'application dans ce cas. La seule detection possible est
# PROACTIVE : interroger periodiquement le niveau d'integrite de la fenetre
# au premier plan et le comparer au notre, pour avertir l'utilisateur AVANT
# qu'il ne clique dedans en pensant que ses actions sont enregistrees
# (utilise par gui.GuideExpressApp pendant un enregistrement actif).

_TOKEN_QUERY = 0x0008
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS.TokenIntegrityLevel

_own_integrity_level_cache = "not_computed_yet"  # sentinelle : distincte de None (echec) et de tout entier valide


def _integrity_level_from_token_handle(h_token) -> Optional[int]:
    """RID (dernier sub-authority du SID) porte par un jeton d'acces deja
    ouvert. Renvoie None si indisponible - jamais d'exception."""
    if _advapi32 is None:
        return None
    try:
        size = _wintypes.DWORD(0)
        _advapi32.GetTokenInformation(h_token, _TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size))
        if size.value == 0:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        ok = _advapi32.GetTokenInformation(h_token, _TOKEN_INTEGRITY_LEVEL, buffer, size.value, ctypes.byref(size))
        if not ok:
            return None
        # TOKEN_MANDATORY_LABEL == { SID_AND_ATTRIBUTES Label } == { PSID Sid; DWORD Attributes; }
        # Le premier pointeur du buffer est donc directement le PSID.
        sid_ptr = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not sid_ptr:
            return None
        count_ptr = _advapi32.GetSidSubAuthorityCount(sid_ptr)
        if not count_ptr:
            return None
        rid_ptr = _advapi32.GetSidSubAuthority(sid_ptr, count_ptr[0] - 1)
        if not rid_ptr:
            return None
        return rid_ptr[0]
    except (AttributeError, OSError, ValueError):
        return None


def _own_integrity_level() -> Optional[int]:
    """Niveau d'integrite du processus GuideExpress lui-meme - constant
    pendant toute la duree de vie du processus, donc calcule une seule fois
    et mis en cache."""
    global _own_integrity_level_cache
    if _own_integrity_level_cache == "not_computed_yet":
        _own_integrity_level_cache = None
        if _kernel32 is not None and _advapi32 is not None:
            try:
                h_process = _kernel32.GetCurrentProcess()  # pseudo-handle, jamais a fermer
                h_token = _wintypes.HANDLE()
                if _advapi32.OpenProcessToken(h_process, _TOKEN_QUERY, ctypes.byref(h_token)):
                    try:
                        _own_integrity_level_cache = _integrity_level_from_token_handle(h_token)
                    finally:
                        _kernel32.CloseHandle(h_token)
            except (AttributeError, OSError):
                _own_integrity_level_cache = None
    return _own_integrity_level_cache


def _process_integrity_level(pid: int) -> Optional[int]:
    """Niveau d'integrite du processus `pid`. Renvoie None si indisponible
    (processus protege par le systeme, permissions insuffisantes, deja
    termine...) - un echec ici desactive simplement la detection, il ne doit
    jamais remonter d'exception a l'appelant."""
    if _kernel32 is None or _advapi32 is None or not pid:
        return None
    h_process = None
    h_token = None
    try:
        h_process = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_process:
            return None
        h_token = _wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(h_process, _TOKEN_QUERY, ctypes.byref(h_token)):
            return None
        return _integrity_level_from_token_handle(h_token)
    except (AttributeError, OSError):
        return None
    finally:
        if h_token:
            try:
                _kernel32.CloseHandle(h_token)
            except OSError:
                pass
        if h_process:
            try:
                _kernel32.CloseHandle(h_process)
            except OSError:
                pass


def foreground_window_is_elevated() -> Optional[bool]:
    """True si la fenetre actuellement au premier plan appartient a un
    processus de niveau d'integrite STRICTEMENT superieur a celui de
    GuideExpress - dans ce cas, les clics qui y seront faits ne declencheront
    jamais le hook (UIPI, voir commentaire de section ci-dessus). Renvoie
    None si la comparaison est indisponible (hors Windows, echec d'un appel
    Win32, processus protege...) : l'appelant doit alors traiter ce cas comme
    "rien a signaler" plutot que comme une elevation averee, pour ne jamais
    afficher un faux avertissement base sur une donnee inconnue."""
    if _user32 is None:
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = _wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
    except (AttributeError, OSError):
        return None
    own_level = _own_integrity_level()
    target_level = _process_integrity_level(pid.value)
    if own_level is None or target_level is None:
        return None
    return target_level > own_level


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
    marker_color = RIGHT_CLICK_MARKER_COLOR if step.button == "right" else CLICK_MARKER_COLOR
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=marker_color,
        width=CLICK_MARKER_WIDTH,
    )

    if zoom:
        img = _crop_zoomed_region(img, cx, cy)

    return img


def _zoomed_region_bounds(width: int, height: int, cx: int, cy: int, half_size: int = 260) -> tuple:
    """Bornes (left, top, right, bottom) de la zone de recadrage centree sur
    le clic, SANS effectuer le recadrage lui-meme - factorise depuis
    _crop_zoomed_region pour permettre a render_step_thumbnail de suivre le
    deplacement du point de clic apres un recadrage zoome (voir plus bas)."""
    left = max(0, min(cx - half_size, width - 2 * half_size)) if width > 2 * half_size else 0
    top = max(0, min(cy - half_size, height - 2 * half_size)) if height > 2 * half_size else 0
    right = min(width, left + 2 * half_size)
    bottom = min(height, top + 2 * half_size)
    return (left, top, right, bottom)


def _crop_zoomed_region(img: Image.Image, cx: int, cy: int, half_size: int = 260) -> Image.Image:
    """Recadre une zone centree sur le clic, pour un aperçu rapproche (miniature)."""
    left, top, right, bottom = _zoomed_region_bounds(img.width, img.height, cx, cy, half_size)
    return img.crop((left, top, right, bottom))


# Marqueur de clic a taille GARANTIE pour la miniature de l'ecran de relecture
# (trouvaille d'audit, dimension 16) : CLICK_MARKER_RADIUS/WIDTH sont
# dimensionnes pour une image en PLEINE resolution (export, editeur de
# redaction) - render_step_image dessine le marqueur AVANT toute reduction,
# donc pour une capture 1600x900 reduite a THUMBNAIL_MAX_SIZE (gui.py, facteur
# ~7.3x), l'anneau tombe a environ 6 px de diametre, difficile a reperer au
# premier coup d'oeil dans une longue liste de cartes. Ces valeurs restent
# nettement visibles a la taille de la miniature (220x150) sans jamais la
# depasser.
THUMBNAIL_MARKER_RADIUS = 8
THUMBNAIL_MARKER_WIDTH = 3


def render_step_thumbnail(step: Step, max_size: tuple, zoom: bool = False) -> Image.Image:
    """Construit la miniature d'une etape pour l'ecran de relecture, avec un
    marqueur de clic a taille garantie (voir THUMBNAIL_MARKER_RADIUS/WIDTH
    ci-dessus) plutot que de reduire un marqueur deja dessine en pleine
    resolution comme le fait render_step_image (utilise lui pour l'export et
    l'editeur de redaction, ou la taille du marqueur doit rester fidele a la
    resolution reelle de la capture). Le marqueur est dessine EN DERNIER, sur
    l'image DEJA reduite, pour que sa taille affichee ne depende jamais du
    facteur de reduction de l'image source (trouvaille d'audit, dimension 16).
    Leve les memes exceptions que render_step_image (OSError, ValueError) si
    l'image brute est illisible - a l'appelant de les gerer."""
    with Image.open(step.raw_image_path) as src:
        img = src.convert("RGB").copy()

    draw = ImageDraw.Draw(img)
    for (x1, y1, x2, y2) in step.redactions:
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        draw.rectangle([left, top, right, bottom], fill=REDACTION_COLOR)

    cx, cy = step.click_x, step.click_y
    if zoom:
        left, top, right, bottom = _zoomed_region_bounds(img.width, img.height, cx, cy)
        img = img.crop((left, top, right, bottom))
        cx, cy = cx - left, cy - top

    orig_width = img.width
    img.thumbnail(max_size)
    scale = img.width / orig_width if orig_width else 1.0
    cx, cy = cx * scale, cy * scale

    draw = ImageDraw.Draw(img)
    r = THUMBNAIL_MARKER_RADIUS
    marker_color = RIGHT_CLICK_MARKER_COLOR if step.button == "right" else CLICK_MARKER_COLOR
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=marker_color,
        width=THUMBNAIL_MARKER_WIDTH,
    )
    return img


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


def duplicate_step(steps: list, index: int) -> list:
    """Duplique l'etape a la position `index` (0-based) juste apres elle-meme,
    et renumerote. Utile pour scinder une etape en deux instructions distinctes
    sans reprendre une capture d'ecran (ex: "cliquez ici" puis, sur la meme
    image, "verifiez que ceci apparait"). La copie partage volontairement le
    meme fichier image brut que l'original (jamais modifie sur disque, voir
    render_step_image) : aucune copie de fichier n'est necessaire. Un nouvel
    `uid` est genere pour la copie (jamais copie depuis l'original) : c'est
    ce qui permet a `_retake_step` (gui.py) d'isoler le dossier de reprise de
    chaque etape - sans uid distinct, reprendre l'une des deux etapes avant
    l'autre ecraserait le fichier de reprise de l'autre (bug trouve a
    l'audit : les deux calculaient le meme dossier de reprise a partir du nom
    de fichier partage). Les redactions sont copiees (liste independante)
    pour qu'editer l'une des deux etapes ne modifie jamais l'autre."""
    if not (0 <= index < len(steps)):
        return steps
    original = steps[index]
    duplicate = replace(original, redactions=list(original.redactions), uid=uuid.uuid4().hex)
    steps.insert(index + 1, duplicate)
    renumber(steps)
    return steps


# ---------------------------------------------------------------------------
# Sauvegarde/reouverture d'une session (session.json)
# ---------------------------------------------------------------------------
# Fonctions pures, sans effet de bord disque (gui.py se charge de
# lire/ecrire le fichier session.json lui-meme) : facilite les tests et
# separe la logique de serialisation de son declenchement dans l'UI.

def step_to_dict(step: Step, session_dir: Path) -> dict:
    """Serialise une etape en dict JSON-compatible. raw_image_path est
    stocke RELATIF a session_dir (jamais en absolu) pour que le dossier de
    session reste deplacable/copiable sans casser session.json."""
    try:
        raw_relative = str(step.raw_image_path.relative_to(session_dir))
    except ValueError:
        # Ne devrait jamais arriver (toutes les images d'une session vivent
        # sous session_dir, y compris les reprises dans retakes/<uid>) - un
        # chemin absolu de secours vaut mieux qu'une exception qui ferait
        # echouer toute la sauvegarde de session pour une seule etape.
        raw_relative = str(step.raw_image_path)
    return {
        "index": step.index,
        "raw_image_path": raw_relative,
        "click_x": step.click_x,
        "click_y": step.click_y,
        "button": step.button,
        "window_title": step.window_title,
        "timestamp": step.timestamp,
        "description": step.description,
        "redactions": [list(r) for r in step.redactions],
        "zoom": step.zoom,
        "uid": step.uid,
    }


def step_from_dict(data: dict, session_dir: Path) -> Step:
    """Reconstruit une etape depuis un dict deja charge (session.json). Les
    cles inconnues sont ignorees et les cles absentes retombent sur une
    valeur par defaut raisonnable, pour tolerer un schema legerement
    different d'une version future/passee de GuideExpress plutot que de
    faire echouer toute la reouverture d'une session pour un champ manquant."""
    return Step(
        index=data.get("index", 0),
        raw_image_path=session_dir / data.get("raw_image_path", ""),
        click_x=data.get("click_x", 0),
        click_y=data.get("click_y", 0),
        button=data.get("button", "left"),
        window_title=data.get("window_title", ""),
        timestamp=data.get("timestamp", ""),
        description=data.get("description", ""),
        redactions=[tuple(r) for r in data.get("redactions", [])],
        zoom=bool(data.get("zoom", False)),
        uid=data.get("uid") or uuid.uuid4().hex,
    )


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


# Windows limite historiquement un chemin COMPLET (dossier + nom + extension)
# a 260 caracteres (MAX_PATH) - aucune limite de longueur n'existe ailleurs
# sur le titre du guide ou les descriptions d'etape saisis librement (trouvaille
# d'audit, dimension 31) : un titre demesurement long, combine a une
# destination d'export deja profonde, pourrait s'en approcher et produire une
# erreur d'ecriture peu claire plutot qu'un message explicite. 100 caracteres
# laisse une marge tres confortable pour le reste du chemin (dossier de
# destination, extension) tout en restant largement suffisant pour identifier
# un guide.
_MAX_FILENAME_LENGTH = 100


def sanitize_filename(name: str, fallback: str = "guide") -> str:
    """Nettoie un titre de guide pour qu'il soit utilisable tel quel comme nom
    de fichier ou de dossier Windows (le titre est saisi librement par
    l'utilisateur et peut contenir des caracteres interdits comme '/' ou ':',
    ou coincider avec un nom de peripherique reserve comme "CON"), et le
    tronque a une longueur raisonnable (voir _MAX_FILENAME_LENGTH)."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    if not cleaned:
        return fallback
    if len(cleaned) > _MAX_FILENAME_LENGTH:
        # Re-nettoyage apres troncature : couper au milieu du nom peut
        # laisser un espace ou un point en fin de chaine, egalement invalides
        # comme dernier caractere d'un nom de fichier/dossier Windows.
        cleaned = cleaned[:_MAX_FILENAME_LENGTH].strip(" .")
        if not cleaned:
            return fallback
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        return f"{cleaned}_"
    return cleaned
