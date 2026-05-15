# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Flox Uploader.

Build Windows :
    pyinstaller packaging/flox_uploader.spec --clean --noconfirm

Produit `dist/Flox Uploader/Flox Uploader.exe` + dossier `_internal/` avec
les DLLs Python et toutes les datas embarquees (templates Jinja, static,
trackers/gemini/*.bbcode + rules.json, et MediaInfo CLI Windows si present
dans `packaging/vendor/mediainfo/`).

Sprint 5 PLAN-V1.md.

Strategie :
- onedir (pas onefile) : startup plus rapide, easier debug, taille ok
- console=True pendant le dev (on voit les logs uvicorn / erreurs python)
  Switcher a False (--windowed) plus tard quand stable
- Datas declares EXPLICITEMENT (PyInstaller ne lit pas pyproject.toml
  [tool.setuptools.package-data], faut tout passer ici)
- Hidden imports : ceux que l'analyse statique de PyInstaller rate
  typiquement avec FastAPI / uvicorn / jinja2

Variables d'env utilisees par le build :
- FLOX_INCLUDE_MEDIAINFO=1 (default) : embarque le binaire MediaInfo CLI
  depuis packaging/vendor/mediainfo/. Si pas present, log un warning et
  build quand meme (l'app au runtime cherchera MediaInfo dans le PATH).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Racine du projet (le .spec est dans <root>/packaging/)
SPEC_ROOT = Path(SPEC).parent  # type: ignore[name-defined]  # injecte par PyInstaller
PROJECT_ROOT = SPEC_ROOT.parent
SRC_ROOT = PROJECT_ROOT / "src" / "flox_uploader"

# ============================================================
# DATA FILES — fichiers a embarquer dans le bundle
# ============================================================
# Format : (source_path, dest_inside_bundle)
# PyInstaller copiera ces fichiers et les rendra accessibles via
# sys._MEIPASS au runtime (en mode frozen).
datas = []

# Templates Jinja (HTML)
templates_src = SRC_ROOT / "web" / "templates"
for tpl in templates_src.glob("*.html"):
    datas.append((str(tpl), "flox_uploader/web/templates"))

# Static files (logo, manifest)
static_src = SRC_ROOT / "web" / "static"
for s in static_src.iterdir():
    if s.is_file():
        datas.append((str(s), "flox_uploader/web/static"))

# Trackers — rules.json + templates BBCode
gemini_src = SRC_ROOT / "trackers" / "gemini"
for f in gemini_src.iterdir():
    if f.is_file() and f.suffix in (".json", ".bbcode"):
        datas.append((str(f), "flox_uploader/trackers/gemini"))

# ============================================================
# BINARIES — MediaInfo CLI Windows (optionnel)
# ============================================================
binaries = []
include_mediainfo = os.getenv("FLOX_INCLUDE_MEDIAINFO", "1").strip() not in ("0", "false", "no")
mediainfo_vendor = SPEC_ROOT / "vendor" / "mediainfo"
if include_mediainfo and mediainfo_vendor.is_dir():
    # On embarque tout le dossier MediaInfo (MediaInfo.exe + DLLs)
    for f in mediainfo_vendor.iterdir():
        if f.is_file():
            binaries.append((str(f), "mediainfo"))
    print(f"[INFO] MediaInfo CLI bundlé depuis {mediainfo_vendor}")
elif include_mediainfo:
    print(
        "[WARN] MediaInfo CLI absent de packaging/vendor/mediainfo/. "
        "Le bundle ne l'aura pas — l'app cherchera MediaInfo dans le PATH."
    )

# ============================================================
# HIDDEN IMPORTS — modules que PyInstaller rate parfois
# ============================================================
hiddenimports = [
    # FastAPI utilise des sub-modules importes dynamiquement
    "email.mime.multipart",
    "email.mime.text",
    # uvicorn loops/parsers — selon plateforme
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.logging",
    # Notre package — assure que PyInstaller scanne TOUS les sous-modules
    # meme ceux importes dynamiquement (ex: tracker registry)
    "flox_uploader",
    "flox_uploader.cli",
    "flox_uploader.config",
    "flox_uploader.launcher",
    "flox_uploader.pipeline",
    "flox_uploader.core",
    "flox_uploader.core.gemini_api",
    "flox_uploader.core.tmdb",
    "flox_uploader.core.omdb",
    "flox_uploader.core.mediainfo_parser",
    "flox_uploader.core.upload_orchestrator",
    "flox_uploader.core.compliance",
    "flox_uploader.core.confidence",
    "flox_uploader.core.release_name",
    "flox_uploader.web",
    "flox_uploader.web.app",
    "flox_uploader.web.config_view",
    "flox_uploader.web.jobs_runner",
    "flox_uploader.trackers",
    "flox_uploader.trackers.base",
    "flox_uploader.trackers.gemini",
    "flox_uploader.trackers.gemini.tracker",
    "flox_uploader.trackers.gemini.unit3d_mapping",
]

# ============================================================
# EXCLUDES — modules a ne pas embarquer (reduction taille)
# ============================================================
excludes = [
    "tkinter",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "matplotlib", "numpy", "pandas", "scipy",  # au cas où pulled by transitive
    "IPython", "jupyter", "notebook",
    "test", "tests", "unittest",  # pas de test framework au runtime
]

# ============================================================
# ANALYSIS
# ============================================================
a = Analysis(
    [str(SRC_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ============================================================
# EXECUTABLE
# ============================================================
# `console=True` pendant le dev : on voit les print() / erreurs Python.
# `console=False` (windowed) : aucune fenetre console — UX user lambda.
# Override via env var FLOX_CONSOLE=1 si on veut forcer le mode debug.
console_mode = os.getenv("FLOX_CONSOLE", "0").strip() in ("1", "true", "yes")

_icon_path = SPEC_ROOT / "icon.ico"
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Flox Uploader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX peut casser certaines DLLs + lent au boot
    console=console_mode,         # default False (windowed)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon_path) if _icon_path.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Flox Uploader",
)
