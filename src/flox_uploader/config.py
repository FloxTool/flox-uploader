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


# ============================================================
# Sprint 4 PLAN-V1.md — detection et migration douce du data legacy
# ============================================================
# Cas d'usage : l'user a essaye l'app en mode dev (`<repo>/data/`) puis
# installe le `.exe` packagé. Le nouveau data_dir pointe maintenant vers
# `%APPDATA%\fremontlouis\flox-uploader\` (vide). On detecte les packages
# legacy + on propose une migration NON-BLOQUANTE via banniere UI.
# Decision user : "détection + bannière proposant l'import, non-bloquante".

def legacy_data_dir() -> "Path | None":
    """Retourne le path d'un data legacy a migrer, ou None.

    Critere : on est en mode packagé (pas dev), il existe `<repo>/data/`
    avec des packages dedans, et ce path est DIFFERENT du data_dir actuel.

    NE PAS appeler depuis le pipeline (les calls reguliers couteraient cher
    en stat() inutiles). C'est destine au boot UI + endpoint d'import.
    """
    if _is_dev_install():
        # En dev, `<repo>/data/` EST le data_dir actuel, pas un legacy
        return None

    legacy = PROJECT_ROOT / "data"
    if not legacy.is_dir():
        return None

    # Faut que ce soit different de l'emplacement actuel
    try:
        if legacy.resolve() == data_dir().resolve():
            return None
    except OSError:
        return None

    # Faut qu'il y ait du contenu interessant (au moins des packages)
    upload_packages = legacy / "upload_packages"
    if not upload_packages.is_dir():
        return None
    try:
        has_packages = any(p.is_dir() for p in upload_packages.iterdir())
    except OSError:
        return None
    if not has_packages:
        return None

    return legacy


def legacy_data_stats(legacy_path: "Path") -> dict:
    """Stats descriptives sur ce qu'on va migrer. Utilise pour l'aperçu UI.

    Retourne :
      {
        "package_count": int,
        "total_size_bytes": int,
        "has_env": bool,
        "has_jobs_db": bool,
        "has_tmdb_cache": bool,
      }
    """
    stats = {
        "package_count": 0,
        "total_size_bytes": 0,
        "has_env": (legacy_path.parent / ".env").is_file()
                   or (legacy_path / ".env").is_file(),
        "has_jobs_db": (legacy_path / "jobs.db").is_file(),
        "has_tmdb_cache": (legacy_path / ".tmdb_cache.json").is_file(),
    }
    upload_packages = legacy_path / "upload_packages"
    if upload_packages.is_dir():
        for pkg in upload_packages.iterdir():
            if not pkg.is_dir():
                continue
            stats["package_count"] += 1
            try:
                for f in pkg.rglob("*"):
                    if f.is_file():
                        try:
                            stats["total_size_bytes"] += f.stat().st_size
                        except OSError:
                            pass
            except OSError:
                pass
    return stats


def migrate_legacy_data(legacy_path: "Path", dry_run: bool = False) -> dict:
    """Effectue la migration du data legacy vers le data_dir courant.

    Strategie : non-destructive. On COPIE (pas move) pour ne pas casser un
    user qui veut continuer a tester en dev en parallele. Si un fichier
    cible existe deja, on le SKIP (ne pas ecraser une config user).

    Si dry_run=True, on ne fait rien, juste retourner ce qu'on aurait fait.

    Retourne :
      {
        "copied_packages": int,
        "skipped_packages": int,    # deja presents dans le data_dir cible
        "copied_files": list[str],  # .env, jobs.db, .tmdb_cache.json
        "errors": list[str],
      }
    """
    result = {
        "copied_packages": 0,
        "skipped_packages": 0,
        "copied_files": [],
        "errors": [],
    }
    target = data_dir()
    if legacy_path.resolve() == target.resolve():
        result["errors"].append("Legacy path == target path, rien a migrer.")
        return result

    # 1. Packages (upload_packages/)
    src_packages = legacy_path / "upload_packages"
    dst_packages = target / "upload_packages"
    if src_packages.is_dir():
        if not dry_run:
            dst_packages.mkdir(parents=True, exist_ok=True)
        try:
            for pkg_src in src_packages.iterdir():
                if not pkg_src.is_dir():
                    continue
                pkg_dst = dst_packages / pkg_src.name
                if pkg_dst.exists():
                    result["skipped_packages"] += 1
                    continue
                if not dry_run:
                    try:
                        shutil.copytree(pkg_src, pkg_dst)
                    except OSError as e:
                        result["errors"].append(f"Copie {pkg_src.name} : {e}")
                        continue
                result["copied_packages"] += 1
        except OSError as e:
            result["errors"].append(f"Lecture upload_packages : {e}")

    # 2. Fichiers a la racine du legacy : .env, jobs.db, .tmdb_cache.json
    for filename in (".env", "jobs.db", ".tmdb_cache.json"):
        src_file = legacy_path / filename
        if not src_file.is_file():
            continue
        dst_file = target / filename
        if dst_file.exists():
            # Skip silencieux : on ne touche pas une config user existante
            continue
        if not dry_run:
            try:
                shutil.copy2(src_file, dst_file)
            except OSError as e:
                result["errors"].append(f"Copie {filename} : {e}")
                continue
        result["copied_files"].append(filename)

    # 3. Cas particulier : le `.env` peut etre a la racine du repo (pas dans
    # data/), c'est l'historique tracker_uploader. On le verifie aussi.
    legacy_env_at_root = PROJECT_ROOT / ".env"
    target_env = target / ".env"
    if (
        legacy_env_at_root.is_file()
        and not target_env.exists()
        and ".env" not in result["copied_files"]
    ):
        if not dry_run:
            try:
                shutil.copy2(legacy_env_at_root, target_env)
                result["copied_files"].append(".env (depuis racine repo)")
            except OSError as e:
                result["errors"].append(f"Copie .env racine : {e}")
        else:
            result["copied_files"].append(".env (depuis racine repo)")

    return result


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
