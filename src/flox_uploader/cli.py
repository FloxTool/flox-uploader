"""Entree CLI (power-user / scripting).

Le flux user-final passe par la web UI (`flox-uploader serve`). Les
sous-commandes ci-dessous sont conservees pour le debug, l'integration
dans des scripts (Sonarr/Radarr post-import, CI), et les tests.

    flox-uploader serve  [--host 127.0.0.1] [--port 8765]
    flox-uploader prepare <fichier> [--tracker gemini] [--force-fr VFF]
                              [--upload [--dry-run] [--anonymous]
                               [--force-upload --i-know-this-is-a-duplicate=ID]]
    flox-uploader upload  <package_dir> [--tracker gemini]
                              [--dry-run] [--anonymous]
                              [--force-upload --i-know-this-is-a-duplicate=ID]
    flox-uploader inspect <torrent_id> [--tmdb-id-hint=ID]

Le mode --upload ferme la boucle vers le tracker :
  1. verifie l'absence de doublon via /api/torrents/filter
  2. upload le .torrent + metadata via /api/torrents/upload
  3. telecharge le .torrent final (avec passkey) qui remplace le local

Mode --dry-run : prepare le payload, l'affiche, mais ne POST rien.
Mode --force-upload : autorise l'upload meme si un doublon est detecte. Friction
intentionnelle : il faut combiner avec --i-know-this-is-a-duplicate=ID exact.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .core.errors import die
from .core.release_name import ALLOWED_FORCE_FR
from .trackers import list_trackers


def _add_tracker_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tracker",
        choices=list_trackers(),
        default="gemini",
        help="Tracker cible (défaut : gemini)",
    )


def _add_force_fr_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force-fr",
        choices=sorted(ALLOWED_FORCE_FR),
        default=None,
        help="Force la variante FR quand le nom est ambigu",
    )


def _add_upload_options(parser: argparse.ArgumentParser, default_dry_run: bool) -> None:
    """Ajoute les flags lies a l'upload (partages entre prepare et upload)."""
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Apres la generation du package, lance la boucle upload vers le tracker.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=default_dry_run,
        help=(
            "Mode dry-run : prepare le payload, affiche ce qui serait POST, "
            "mais ne fait AUCUN appel reseau d'upload. Defaut "
            f"{'active' if default_dry_run else 'desactive'}."
        ),
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Desactive le dry-run (upload REEL vers le tracker).",
    )
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help="Marque l'upload comme anonyme cote tracker.",
    )
    parser.add_argument(
        "--force-upload",
        action="store_true",
        help=(
            "Force l'upload meme si un doublon est detecte. Doit etre combine "
            "avec --i-know-this-is-a-duplicate=<id>."
        ),
    )
    parser.add_argument(
        "--i-know-this-is-a-duplicate",
        type=int,
        default=None,
        metavar="EXISTING_ID",
        help=(
            "ID exact du torrent existant detecte comme doublon. Sans correspondance "
            "exacte, --force-upload est ignore (friction intentionnelle)."
        ),
    )


def cmd_prepare(args: argparse.Namespace) -> int:
    from .pipeline import process_one
    companion_nfo = Path(args.companion_nfo) if args.companion_nfo else None
    if companion_nfo is not None and not companion_nfo.is_file():
        die(f"--companion-nfo : fichier introuvable : {companion_nfo}")
    package_dir = process_one(
        Path(args.target),
        tracker_key=args.tracker,
        force_fr=args.force_fr,
        explicit_companion_nfo=companion_nfo,
        tmdb_id_override=getattr(args, "tmdb_id_override", None) or None,
        manual_release_name=(
            getattr(args, "manual_release_name", None) or None
        ),
        category_hint=(
            int(getattr(args, "category_hint", 0) or 0) or None
        ),
        manual_isbn=(getattr(args, "manual_isbn", None) or None),
        manual_author=(getattr(args, "manual_author", None) or None),
        manual_book_title=(
            getattr(args, "manual_book_title", None) or None
        ),
        manual_book_year=(
            int(getattr(args, "manual_book_year", 0) or 0) or None
        ),
        manual_google_books_url=(
            getattr(args, "manual_google_books_url", None) or None
        ),
    )

    # Si --upload demande, on enchaine la boucle upload
    if getattr(args, "upload", False):
        return _run_upload_loop(package_dir, args)

    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    """Re-execute la boucle upload sur un package deja prepare."""
    package_dir = Path(args.package_dir)
    if not package_dir.is_dir():
        die(f"Dossier package introuvable : {package_dir}")
    return _run_upload_loop(package_dir, args)


def cmd_inspect(args: argparse.Namespace) -> int:
    """Recupere les attributes d'un torrent existant sur le tracker.

    Strategie en cascade :
    1. GET /api/torrents/{id} via gemini_api.get_torrent
    2. Si echec / vide : GET /api/torrents/filter?id={id} via la meme client
    3. Si --tmdb-id-hint fourni : filter?tmdbId=... + matching local sur l'id

    Utile pour decouvrir les valeurs reelles de category_id / type_id /
    resolution_id que le tracker utilise.
    """
    from .core.gemini_api import GeminiAPIError, GeminiClient
    from .core.upload_orchestrator import load_upload_config

    cfg = load_upload_config(
        dry_run=True, force_upload=False, force_existing_id=None, anonymous=False,
    )
    client = GeminiClient(api_url=cfg.api_url, api_key=cfg.api_key)

    flat: dict = {}

    # Tentative 1 : /api/torrents/{id}
    try:
        flat = client.get_torrent(args.torrent_id)
        # _raw est ajoute par get_torrent ; on le drop pour l'affichage
        if "_raw" in flat and len(flat) == 1:
            flat = {}
    except GeminiAPIError as e:
        print(f"[INFO] /api/torrents/{args.torrent_id} : {e}")
        flat = {}

    # Tentative 2 : filter?id=
    if not flat or "name" not in flat:
        print("[INFO] Fallback via /api/torrents/filter?id=...")
        try:
            result = client.check_duplicate(release_name=str(args.torrent_id))
        except GeminiAPIError as e:
            print(f"[INFO] filter?id : {e}")
            result = None
        # check_duplicate ne match pas par id directement mais sa logique
        # _extract_all_matches sait sortir tout ce que le tracker retourne.
        # On contourne en appelant directement le helper bas-niveau :
        if not flat:
            import requests as _requests
            try:
                resp = _requests.get(
                    f"{client.api_url}/torrents/filter",
                    headers={"Authorization": f"Bearer {client.api_key}",
                             "Accept": "application/json"},
                    params={"id": args.torrent_id},
                    timeout=client.timeout,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    matches = client._extract_all_matches(body)
                    if matches:
                        first = matches[0]
                        attrs = first.get("attributes") or {}
                        flat = {**(attrs if isinstance(attrs, dict) else {}),
                                **{k: v for k, v in first.items() if k != "attributes"}}
            except (_requests.RequestException, ValueError) as e:
                print(f"[ERREUR] filter?id : {e}")

    # Tentative 3 : tmdbId hint
    if not flat and args.tmdb_id_hint:
        print(f"[INFO] Fallback via filter?tmdbId={args.tmdb_id_hint}")
        import requests as _requests
        try:
            resp = _requests.get(
                f"{client.api_url}/torrents/filter",
                headers={"Authorization": f"Bearer {client.api_key}",
                         "Accept": "application/json"},
                params={"tmdbId": args.tmdb_id_hint},
                timeout=client.timeout,
            )
            if resp.status_code == 200:
                body = resp.json()
                for entry in client._extract_all_matches(body):
                    eid = entry.get("id") or (entry.get("attributes") or {}).get("id")
                    try:
                        if int(eid) == args.torrent_id:
                            attrs = entry.get("attributes") or {}
                            flat = {**(attrs if isinstance(attrs, dict) else {}),
                                    **{k: v for k, v in entry.items() if k != "attributes"}}
                            break
                    except (TypeError, ValueError):
                        continue
        except (_requests.RequestException, ValueError) as e:
            print(f"[ERREUR] filter?tmdbId : {e}")

    if not flat:
        die(
            f"Impossible de recuperer le torrent {args.torrent_id}. "
            "Si tu connais son tmdb_id, relance avec --tmdb-id-hint=<TMDB_ID>."
        )
        return 1  # unreachable

    print(f"\n[OK] Torrent {flat.get('id', args.torrent_id)}")
    print(f"  name           : {flat.get('name', '?')}")
    interesting_keys = (
        "category_id", "category",
        "type_id", "type",
        "resolution_id", "resolution",
        "tmdb_id", "imdb_id", "tvdb_id", "mal_id", "igdb_id",
        "info_hash", "size", "personal_release", "anonymous", "stream", "sd",
        "internal", "free", "doubleup", "featured", "sticky",
        "season_number", "episode_number", "release_year",
        "uploader", "freeleech", "double_upload", "refundable",
    )
    for k in interesting_keys:
        if k in flat:
            print(f"  {k:<15}: {flat[k]}")
    if flat.get("details_link"):
        print(f"  details_link   : {flat['details_link']}")
    print("\n[DEBUG] Tous les champs disponibles :")
    print("  " + ", ".join(sorted(k for k in flat.keys() if not k.startswith("_"))))
    return 0


def _run_upload_loop(package_dir: Path, args: argparse.Namespace) -> int:
    """Logique commune appelee par cmd_prepare(--upload) et cmd_upload."""
    from .core.upload_orchestrator import (
        UploadConfig,
        load_upload_config,
        upload_package,
    )
    cfg: UploadConfig = load_upload_config(
        dry_run=getattr(args, "dry_run", True),
        force_upload=getattr(args, "force_upload", False),
        force_existing_id=getattr(args, "i_know_this_is_a_duplicate", None),
        anonymous=getattr(args, "anonymous", False),
    )
    upload_package(package_dir, cfg, tracker_key=args.tracker)
    return 0


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _find_free_port(host: str, start: int, max_tries: int = 10) -> int:
    """Cherche un port libre a partir de `start`. Retourne `start` si dispo,
    sinon increment de 1 jusqu'a `max_tries` tentatives. Si tout est occupe,
    retourne `start` (uvicorn affichera une erreur claire).
    """
    import socket
    for offset in range(max_tries):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
                return port
        except OSError:
            continue
    return start


def cmd_serve(args: argparse.Namespace) -> int:
    """Lance l'interface web locale (FastAPI + uvicorn).

    Garde-fou securite : refuse de demarrer sur un host non-local sans le
    flag `--insecure-host` (ou la var d'env FLOX_UPLOADER_INSECURE_HOST=1).
    Sans ce garde-fou, un user qui passe `--host 0.0.0.0` exposerait son
    filesystem entier a tout le reseau (cf. AUDIT.md section 5.1).
    """
    try:
        import uvicorn
    except ImportError:
        die(
            "uvicorn n'est pas installe. Lance : "
            "pip install fastapi 'uvicorn[standard]' jinja2 python-multipart"
        )
        return 1

    host = args.host
    is_local = host in _LOCAL_HOSTS
    insecure_ok = (
        getattr(args, "insecure_host", False)
        or os.getenv("FLOX_UPLOADER_INSECURE_HOST", "").strip() in ("1", "true", "yes")
    )
    if not is_local and not insecure_ok:
        die(
            f"Host non-local ({host}) refuse par defaut : la web UI exposerait "
            "le filesystem du serveur a tout le reseau (cf. browser inbox, "
            "POST /api/queue/add). Si tu sais ce que tu fais, relance avec "
            "--insecure-host (ou FLOX_UPLOADER_INSECURE_HOST=1)."
        )
        return 1
    if not is_local and insecure_ok:
        print("=" * 60)
        print("[ATTENTION] La web UI est expose sur un host NON-LOCAL.")
        print(f"           Adresse : http://{host}:{args.port}/")
        print("           N'importe qui sur le reseau peut browse ton")
        print("           filesystem et lancer des prepares. Mets un")
        print("           reverse proxy + auth devant si tu veux que ce")
        print("           soit accessible a distance.")
        print("=" * 60)

    # Fallback de port si 8765 est occupe (cas frequent : uvicorn tourne deja
    # ailleurs, vieille session non terminee, etc.). On essaie jusqu'a +10.
    port = _find_free_port(host, args.port, max_tries=10)
    if port != args.port:
        print(f"[INFO] Port {args.port} occupe, bascule sur {port}.")

    from .web.app import create_app
    app = create_app()
    print(f"[INFO] Flox Uploader Web demarre sur http://{host}:{port}/")
    print("[INFO] Ctrl+C pour arreter.")
    # Auto-launch navigateur :
    # - En mode packagé (frozen) : oui par defaut (user lambda ne tape rien)
    # - En mode dev : non par defaut (le dev a deja son onglet ouvert)
    # - Override : --no-browser (skip dans tous les cas) si l'arg existe
    skip_browser = getattr(args, "no_browser", False)
    is_packaged = getattr(sys, "frozen", False)
    if not skip_browser and is_local and is_packaged:
        try:
            import webbrowser
            # Petit delai pour laisser uvicorn binder le port (sinon le browser
            # tente de se connecter avant que le serveur ecoute -> page d'erreur).
            # Sprint 5 PLAN-V1.md : besoin d'un timer cote thread pour pas
            # bloquer uvicorn.run() qui est bloquant.
            import threading
            def _open_later():
                webbrowser.open(f"http://{host}:{port}/")
            t = threading.Timer(1.5, _open_later)
            t.daemon = True
            t.start()
        except Exception:
            pass
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flox-uploader",
        description="Crée des packages d'upload pour trackers de torrents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser(
        "prepare", help="Génère un package pour un fichier vidéo."
    )
    p_prepare.add_argument("target", help="Fichier vidéo ou dossier le contenant")
    _add_tracker_option(p_prepare)
    _add_force_fr_option(p_prepare)
    p_prepare.add_argument(
        "--companion-nfo",
        default=None,
        help=(
            "Chemin d'un .nfo a inclure avec un .mkv standalone "
            "(torrent multi-fichiers + copie dans le package). "
            "Doit etre dans le meme dossier que le .mkv."
        ),
    )
    # Lot post-NOTES round 5 : flags utilises par le worker subprocess
    # (jobs_runner._run_prepare_job). Permet de passer les overrides
    # tmdb_id et release_name au subprocess CLI.
    p_prepare.add_argument(
        "--tmdb-id", dest="tmdb_id_override", type=int, default=0,
        help="Force un TMDB ID specifique (court-circuite la recherche).",
    )
    p_prepare.add_argument(
        "--release-name", dest="manual_release_name", default="",
        help="Force le release_name au lieu de celui derive par le pipeline.",
    )
    # Sprint C.1 v0.5.0 : hint categorie passe par le subprocess depuis la modal
    # Inbox (cf. web/jobs_runner.py). Court-circuite early_category_guess.
    p_prepare.add_argument(
        "--category-hint", dest="category_hint", type=int, default=0,
        help=(
            "Force la categorie Gemini (1=Films, 2=Series, 3=Jeux, 12=Livres, "
            "17=Logiciels, etc. — voir trackers/gemini/unit3d_mapping.py). "
            "0 = auto-detect via extension."
        ),
    )
    # Sprint D.9 v0.5.0 : overrides livre.
    p_prepare.add_argument(
        "--manual-isbn", dest="manual_isbn", default="",
        help="(Cat Livres) ISBN-13 ou ISBN-10 force pour le lookup BnF/Google Books.",
    )
    p_prepare.add_argument(
        "--manual-author", dest="manual_author", default="",
        help="(Cat Livres) Auteur principal force (override extraction EPUB/PDF/CBZ).",
    )
    p_prepare.add_argument(
        "--manual-book-title", dest="manual_book_title", default="",
        help="(Cat Livres) Titre du livre force (override extraction).",
    )
    # Sprint D.11 v0.5.0 : annee livre forcee.
    p_prepare.add_argument(
        "--manual-book-year", dest="manual_book_year", type=int, default=0,
        help="(Cat Livres) Annee de publication forcee (1900-2099).",
    )
    # Sprint D.40 v0.5.0 : URL Google Books forcee.
    p_prepare.add_argument(
        "--manual-google-books-url", dest="manual_google_books_url", default="",
        help=(
            "(Cat Livres) URL Google Books de la fiche canonique a forcer. "
            "Ex: https://books.google.com/books/edition/.../<volumeId>. On en "
            "extrait le volumeId et on bypasse la recherche par titre/auteur."
        ),
    )
    _add_upload_options(p_prepare, default_dry_run=True)
    p_prepare.set_defaults(func=cmd_prepare)

    p_upload = sub.add_parser(
        "upload",
        help="Lance la boucle upload sur un package deja prepare.",
    )
    p_upload.add_argument(
        "package_dir",
        help="Dossier package (sous data/upload_packages/) deja genere par prepare.",
    )
    _add_tracker_option(p_upload)
    _add_upload_options(p_upload, default_dry_run=True)
    p_upload.set_defaults(func=cmd_upload)

    p_inspect = sub.add_parser(
        "inspect",
        help=(
            "Recupere les attributes d'un torrent existant sur le tracker "
            "(GET /api/torrents/{id}). Utile pour decouvrir les "
            "category_id/type_id/resolution_id reels de Gemini."
        ),
    )
    p_inspect.add_argument(
        "torrent_id", type=int,
        help="ID du torrent sur le tracker (ex: 15447)",
    )
    p_inspect.add_argument(
        "--tmdb-id-hint", type=int, default=0,
        help=(
            "TMDB ID associe au torrent (optionnel). Permet le fallback via "
            "?tmdbId= si l'endpoint /api/torrents/{id} ne fonctionne pas."
        ),
    )
    _add_tracker_option(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect)

    p_serve = sub.add_parser(
        "serve",
        help="Lance l'interface web locale (par defaut http://127.0.0.1:8765/).",
    )
    p_serve.add_argument(
        "--host", default="127.0.0.1",
        help="Adresse d'ecoute (defaut : 127.0.0.1, local uniquement)",
    )
    p_serve.add_argument(
        "--port", type=int, default=8765,
        help="Port d'ecoute (defaut : 8765, fallback +1 jusqu'a +10 si occupe)",
    )
    p_serve.add_argument(
        "--insecure-host",
        action="store_true",
        help=(
            "Autorise le bind sur un host non-local (autre que 127.0.0.1 / "
            "localhost). Sans ce flag (ou FLOX_UPLOADER_INSECURE_HOST=1), "
            "tout host non-local est refuse pour eviter d'exposer le "
            "filesystem a tout le reseau."
        ),
    )
    p_serve.set_defaults(func=cmd_serve)

    return parser


def _show_fatal_dialog(title: str, message: str) -> None:
    """Affiche un dialog GUI d'erreur fatale.

    En mode PyInstaller windowed, stdout/stderr ne vont nulle part : un
    `print` ou un sys.exit avec message disparait. On utilise tkinter
    (toujours dispo dans un Python standard) pour garantir un retour visible.
    Echec silencieux si tkinter indisponible (Linux headless par ex) :
    on retombe sur stderr.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # Fallback : stderr (visible en mode console)
        try:
            print(f"[FATAL] {title} : {message}", file=sys.stderr)
        except Exception:
            pass


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
    except SystemExit:
        # argparse propage SystemExit pour --help / arg manquant ; on relaie tel quel
        raise
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        msg = f"Erreur inattendue : {e}"
        # En mode packagé (PyInstaller/cx_Freeze), stderr est invisible -> dialog GUI
        if getattr(sys, "frozen", False):
            _show_fatal_dialog("Flox Uploader - Erreur", msg)
        die(msg)
        return 1  # unreachable


if __name__ == "__main__":
    sys.exit(main())
