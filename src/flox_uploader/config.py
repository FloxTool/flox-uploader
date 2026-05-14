"""Resolution des chemins de runtime et chargement de la config (.env).

Strategie data_dir :

- **Override explicite** via `FLOX_UPLOADER_DATA_DIR` : toujours respecte.
- **Mode dev** (install editable, `pyproject.toml` detecte a cote du package
  ET pas frozen) : `<repo>/data/`. Compat tests + workflow dev historique.
- **Mode packagé** (PyInstaller `frozen=True`, ou `pyproject.toml` absent
  car installé depuis un wheel) : `platformdirs.user_data_dir(...)`. Sur
  Windows : `%LOCALAPPDATA%\\fremontlouis\\flox-uploader\\`. Sur Linux :
  `~/.local/share/flox-uploader/`. Sur macOS : `~/Library/Application
  Support/flox-uploader/`. Survit aux updates de l'app.

Le `.env` suit le data_dir : co-localise. Au premier boot apres upgrade,
si l'ancien `<repo>/.env` existe et que le nouveau emplacement est vide, on
fait une copie one-shot.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import platformdirs


# Le package est installe a src/flox_uploader/, la racine projet est 2 crans
# au-dessus quand on est en mode editable / dev. En mode packagé, ce path
# pointe dans le bundle PyInstaller (sys._MEIPASS) ou dans site-packages,
# ce qui n'est PAS un endroit valide pour stocker des donnees user.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Identifiants de l'app pour platformdirs (definissent les sous-dossiers OS).
_APPNAME = "flox-uploader"
_APPAUTHOR = "fremontlouis"


def _is_frozen() -> bool:
    """Vrai si on tourne dans un bundle PyInstaller / cx_Freeze / similaire."""
    return getattr(sys, "frozen", False)


def _is_dev_install() -> bool:
    """Vrai si on est en install editable a cote du repo (pyproject.toml visible).

    Critere conservateur : on a la fois `pyproject.toml` ET `src/flox_uploader/`
    sous PROJECT_ROOT, ET on n'est pas frozen. Si le user a installe le wheel
    dans un venv qui se trouve par hasard a cote d'un pyproject.toml d'un autre
    projet, on ne se laisse pas avoir.
    """
    if _is_frozen():
        return False
    return (
        (PROJECT_ROOT / "pyproject.toml").is_file()
        and (PROJECT_ROOT / "src" / "flox_uploader" / "__init__.py").is_file()
    )


def _default_data_dir() -> Path:
    """Resout le data dir par defaut selon le mode (dev vs packaged)."""
    if _is_dev_install():
        return PROJECT_ROOT / "data"
    return Path(platformdirs.user_data_dir(_APPNAME, _APPAUTHOR))


def data_dir() -> Path:
    """Retourne le data dir effectif. Relit l'env a chaque appel pour que
    `monkeypatch.setenv` en tests fonctionne meme apres l'import du module.

    Important : on traite explicitement la chaine vide comme "non defini"
    (sinon Path("") = Path(".") = current dir, ce qui fait pointer le
    serveur dans le mauvais dossier).

    Backward compat (Sprint 1 v0.3.1) : on lit aussi l'ancien nom de var
    `TRACKER_UPLOADER_DATA_DIR` si la nouvelle est absente. Permet aux
    installs existantes (pre-refactor) de continuer a fonctionner sans
    modifier le .env. A retirer dans une release future (v0.5+).
    """
    raw = os.getenv("FLOX_UPLOADER_DATA_DIR", "").strip()
    if not raw:
        # Fallback : ancien nom de var (deprecie mais accepte pendant la transition)
        raw = os.getenv("TRACKER_UPLOADER_DATA_DIR", "").strip()
    if raw:
        p = Path(raw)
    else:
        p = _default_data_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def packages_dir() -> Path:
    p = data_dir() / "upload_packages"
    p.mkdir(parents=True, exist_ok=True)
    return p


def temp_dir() -> Path:
    p = data_dir() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def torrent_download_dir() -> Path:
    """Dossier ou les .torrent finaux (avec passkey, recus du tracker) sont
    deposes apres un upload reussi. Centralise -> facile a pointer comme
    watch-folder pour qBittorrent / rTorrent / Transmission.

    Override via TORRENT_DOWNLOAD_DIR dans le .env. Defaut : data/torrents_to_seed/.
    """
    override = os.getenv("TORRENT_DOWNLOAD_DIR", "").strip()
    if override:
        p = Path(override)
    else:
        p = data_dir() / "torrents_to_seed"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tmdb_cache_path() -> Path:
    return data_dir() / ".tmdb_cache.json"


def env_file() -> Path:
    """Path du `.env` effectif : co-localise avec le data_dir.

    En mode dev (cf. `_is_dev_install`), si `<repo>/.env` existe deja a la
    racine, on continue de le lire la (compat workflow historique). Sinon
    (mode packagé ou premier setup), on utilise `<data_dir>/.env`.
    """
    legacy = PROJECT_ROOT / ".env"
    if _is_dev_install() and legacy.is_file():
        return legacy
    return data_dir() / ".env"


def _migrate_legacy_env_if_needed() -> None:
    """Si on est en mode packagé et que l'ancien `<repo>/.env` existe ET que le
    nouveau `<data_dir>/.env` n'existe pas → copie one-shot.

    Ne fait rien en mode dev (pour ne pas casser le workflow historique).
    """
    if _is_dev_install():
        return
    legacy = PROJECT_ROOT / ".env"
    target = data_dir() / ".env"
    if legacy.is_file() and not target.exists():
        try:
            shutil.copy2(legacy, target)
            print(f"[INFO] Migration .env : {legacy} -> {target}")
        except OSError as e:
            print(f"[WARN] Migration .env echouee : {e}")


def load_env() -> None:
    """Charge `.env` (au bon emplacement) via python-dotenv si dispo, sinon
    via un mini-parser interne (pour respecter le principe "minimal deps").

    Effectue la migration legacy `<repo>/.env` -> `<data_dir>/.env` au passage
    si on est en mode packagé (transparent pour le user).
    """
    _migrate_legacy_env_if_needed()
    env_path = env_file()
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(env_path)
        return
    except ImportError:
        pass

    # Mini-parseur de fallback : KEY=VALUE par ligne, ignore commentaires.
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_required_env(name: str) -> str:
    """Retourne la valeur de la variable d'env ou leve SystemExit."""
    value = os.getenv(name, "").strip()
    if not value:
        from .core.errors import die
        die(f"{name} absent dans le fichier .env")
    return value


def get_optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def banned_teams_list() -> list[str]:
    """Retourne la liste des teams interdites configuree par l'utilisateur.

    Source : variable d'env `BANNED_TEAMS` (separateur virgule, point-virgule
    ou retour ligne). Editable depuis la page /config — la doc Gemini change
    souvent (nouvelles teams blacklistees) donc on veut que l'utilisateur
    puisse mettre a jour sans toucher au code.

    Cette liste s'AJOUTE aux teams interdites par defaut codees dans
    `compliance.DEFAULT_BANNED_TEAMS` (k0RE, Slay3R) — ne les remplace pas.

    Tolere les separateurs `,`, `;`, espaces ou retours ligne. Strip les vides.
    """
    raw = os.getenv("BANNED_TEAMS", "").strip()
    if not raw:
        return []
    # On split sur tous les separateurs courants pour etre permissif :
    # l'utilisateur peut taper "k0RE, Slay3R" ou "k0RE\nSlay3R" etc.
    parts = re.split(r"[,;\n\r]+", raw)
    return [p.strip() for p in parts if p.strip()]


# ============================================================
# SETUP / FIRST-RUN
# ============================================================

# Liste des variables d'env REQUISES pour que l'app soit operationnelle.
# Si l'une manque -> middleware redirige vers le wizard /setup.
REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "TRACKER_API_URL",
    "TRACKER_API_KEY",
    "TRACKER_ANNOUNCE",
    "TMDB_API_KEY",
)


def is_setup_complete() -> bool:
    """Vrai si toutes les variables critiques sont definies (non vides)."""
    return all(os.getenv(k, "").strip() for k in REQUIRED_ENV_KEYS)


def missing_required_keys() -> list[str]:
    """Liste les cles requises qui sont vides/absentes."""
    return [k for k in REQUIRED_ENV_KEYS if not os.getenv(k, "").strip()]
