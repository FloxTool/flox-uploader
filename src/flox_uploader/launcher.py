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
    from .cli import cmd_serve

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
