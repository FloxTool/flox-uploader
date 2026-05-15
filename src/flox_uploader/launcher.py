"""Entry point pour le bundle PyInstaller.

Quand l'user double-clique sur `Flox Uploader.exe`, ce script s'execute.
Il lance directement le serveur web local en mode "user-friendly" :

  - Port dynamique (8765 -> +10 fallback)
  - Host 127.0.0.1 (loopback only, sans flag --insecure-host)
  - Auto-launch navigateur sur l'URL une fois uvicorn pret
  - Hide console window (cf. PyInstaller --windowed)

L'user lambda n'a jamais a taper de commande. Pour les power-users qui
veulent les sous-commandes (prepare, upload, inspect), il y a toujours
`flox-uploader.exe prepare ...` accessible via la CLI complete (le
console_scripts entry point de pyproject.toml installe quand meme).

Sprint 5 PLAN-V1.md.
"""
from __future__ import annotations

# ============================================================
# IMPORTANT : reparation sys.stdout/stderr AVANT tout autre import.
# ============================================================
# En mode PyInstaller --windowed (pas de console), Python definit
# sys.stdout, sys.stderr et sys.stdin a None. Beaucoup de libs (uvicorn,
# logging, click, etc.) crashent quand elles font `sys.stdout.isatty()`
# ou `sys.stdout.write(...)`.
#
# Erreur typique :
#   AttributeError: 'NoneType' object has no attribute 'isatty'
#   ValueError: Unable to configure formatter 'default'
#
# Fix : on remplace None par des wrappers vers os.devnull qui acceptent
# .write() et .isatty() (renvoie False). Comme ca tout le code en aval
# (uvicorn logging, jinja2, fastapi) fonctionne sans modifier leur code.
#
# Apres ce patch les print() partent dans le neant — c'est OK en mode
# windowed parce que l'user ne voit rien de toute facon. Pour debug, on
# rajoutera une option --console plus tard ou un log file dans data_dir.
import sys as _sys

if _sys.stdout is None or _sys.stderr is None or _sys.stdin is None:
    import os as _os
    _devnull = open(_os.devnull, "w", encoding="utf-8")
    if _sys.stdout is None:
        _sys.stdout = _devnull
    if _sys.stderr is None:
        _sys.stderr = _devnull
    if _sys.stdin is None:
        _sys.stdin = open(_os.devnull, "r", encoding="utf-8")


import argparse
import sys
from pathlib import Path


def main() -> int:
    """Point d'entree du bundle PyInstaller. Equivalent a `flox-uploader serve`.

    Accepte les memes options que `cmd_serve` pour permettre aux users
    avances de lancer avec --host / --port custom. Default safe : 127.0.0.1
    + port 8765.
    """
    parser = argparse.ArgumentParser(
        prog="Flox Uploader",
        description=(
            "Préparation et upload soignés de releases vidéo pour trackers "
            "privés. Local-first."
        ),
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Adresse d'ecoute (defaut : 127.0.0.1, loopback only).",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port d'ecoute (defaut : 8765, +10 fallback si occupe).",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Ne pas ouvrir le navigateur automatiquement.",
    )
    parser.add_argument(
        "--insecure-host", action="store_true",
        help="Autorise --host autre que loopback (ATTENTION : expose au reseau).",
    )
    args = parser.parse_args()

    # On delegue a cmd_serve qui contient deja toute la logique (find_free_port,
    # safety check du host, etc.). On simule un argparse.Namespace compatible.
    #
    # Sprint 5 fix : ABSOLUTE import obligatoire. PyInstaller execute launcher.py
    # comme script top-level (pas comme module flox_uploader.launcher), donc
    # `from .cli import cmd_serve` echoue avec
    # "ImportError: attempted relative import with no known parent package".
    from flox_uploader.cli import cmd_serve

    class _Args:
        pass
    forward = _Args()
    forward.host = args.host
    forward.port = args.port
    forward.insecure_host = args.insecure_host
    forward.no_browser = args.no_browser
    return cmd_serve(forward)


if __name__ == "__main__":
    sys.exit(main())
