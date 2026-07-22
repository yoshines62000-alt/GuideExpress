# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GuideExpress',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX desactive (trouvaille d'audit, dimension 11) : la compression UPX
    # est une technique aussi largement utilisee par des malwares pour
    # echapper a la detection par signature - sa presence est un facteur
    # aggravant bien identifie de faux positif antivirus pour les
    # executables PyInstaller, qui s'ajoute ici a un profil deja a risque
    # (hook souris global bas niveau + capture d'ecran automatisee, un
    # schema comportemental proche de celui des keyloggers/spywares aux yeux
    # des moteurs heuristiques). Desactiver UPX est le levier le plus simple
    # et le plus documente pour reduire ce risque, au prix d'un executable un
    # peu plus volumineux - compromis raisonnable ici.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    # Manifeste DPI-aware (trouvaille d'audit, dimension 7) : voir
    # GuideExpress.manifest pour le detail et la justification complete.
    # Sans lui, l'executable empaquete n'est pas declare sensible au DPI et
    # Windows virtualise ses coordonnees/captures a 96 DPI des qu'un facteur
    # d'echelle different de 100% est actif (tres courant sur portables et
    # ecrans modernes) - risque de flou et de desalignement du marqueur de
    # clic. Complementaire de l'appel ctypes equivalent fait au demarrage de
    # gui.py (_configure_dpi_awareness), qui reste un filet de securite pour
    # une execution depuis le code source (non empaquetee).
    manifest='GuideExpress.manifest',
)
