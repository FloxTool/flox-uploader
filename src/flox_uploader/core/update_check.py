"""Sprint 6 PLAN-V1 — Auto-update v1.

Verifie si une nouvelle version de Flox Uploader est disponible sur GitHub
Releases. Tout est local et non-bloquant : le fetch tourne dans un thread
background, le resultat est cache 6h sur disque, et le banner UI s'auto-masque
si l'user a dismiss la version courante (localStorage cote front).

Decisions de cadrage figees (cf. PLAN-V1.md §1.6) :

- **Comparateur semver strict** : on parse uniquement `vX.Y.Z` (3 nombres
  positifs). Tout suffixe (`-rc1`, `-beta`, `+meta`) est rejete → pas de
  banner pour les pre-releases. On hit `/releases/latest` qui exclut
  automatiquement les prereleases cote GitHub (double garde).
- **Silent fail + cache persistant disque** : si le fetch echoue (offline,
  rate-limit 403, 5xx), on ne touche pas au cache. Si jamais cache → pas
  de banner. Si cache OK → on l'utilise meme si stale. Robuste pour users
  offline / firewall corporate.
- **Cache** : `data_dir() / .update_cache.json`, TTL 6h en succes, conserve
  sinon.

Ce module n'expose **aucune** donnee user a GitHub : pas d'envoi de version,
pas de telemetry, pas d'identifiant. Le seul appel est un GET HTTP standard
sur l'API publique GitHub.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .. import __version__

# ============================================================================
# Constantes
# ============================================================================

GITHUB_RELEASES_LATEST_URL = (
    "https://api.github.com/repos/FloxTool/flox-uploader/releases/latest"
)
"""Endpoint GitHub officiel. `/releases/latest` exclut automatiquement les
prereleases — c'est notre premiere ligne de defense contre les notifs intempestives."""

CACHE_FILENAME = ".update_cache.json"
"""Fichier de cache dans `data_dir()`. Prefixe `.` pour ne pas polluer les
listings utilisateur."""

CACHE_TTL_SECONDS = 6 * 3600
"""6 heures. Compromis entre fraicheur (l'user voit une nouvelle release
sous une demi-journee max) et politesse envers l'API GitHub (rate limit
60 req/h en non-authentifie, largement OK avec 4 requetes/jour/user)."""

FETCH_TIMEOUT_SECONDS = 5
"""Timeout court : si GitHub met plus de 5s a repondre, c'est qu'on a un
souci reseau, on abandonne pour ne pas bloquer le startup du serveur."""


# ============================================================================
# Modele
# ============================================================================

@dataclass(frozen=True)
class UpdateInfo:
    """Snapshot du statut update, retourne par `read_cached_update_info()`.

    - `available` : True ssi `latest` parse en semver valide ET > `current`.
    - `latest` / `release_url` / `release_notes` : vides si pas de fetch
      reussi (premier lancement offline, par exemple).
    - `fetched_at` : ISO UTC du dernier fetch reussi ("" si jamais).
    """

    available: bool
    current: str
    latest: str
    release_url: str
    release_notes: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Parsing semver
# ============================================================================

def _parse_version(raw: str) -> tuple[int, int, int] | None:
    """Parse `v0.3.5` ou `0.3.5` -> `(0, 3, 5)`.

    Retourne None pour tout suffixe (-rc1, -beta, +build, etc.) — on ignore
    volontairement les pre-releases en v1 (cf. PLAN-V1.md §1.6, decision
    "strict + ignore pre-releases").
    """
    if not raw:
        return None
    s = raw.strip().lstrip("vV")
    if not s:
        return None
    # Tout suffixe de pre-release / build metadata → rejet.
    for sep in ("-", "+", "_"):
        if sep in s:
            return None
    parts = s.split(".")
    if len(parts) != 3:
        return None
    try:
        a, b, c = (int(p) for p in parts)
    except ValueError:
        return None
    if a < 0 or b < 0 or c < 0:
        return None
    return (a, b, c)


def is_newer(latest: str, current: str) -> bool:
    """True ssi `latest` est un semver strictement superieur a `current`.

    Retourne False si l'un des deux ne parse pas — comportement defensif :
    on n'affiche pas de banner en cas de doute."""
    a = _parse_version(latest)
    b = _parse_version(current)
    if a is None or b is None:
        return False
    return a > b


# ============================================================================
# Cache disque
# ============================================================================

def _cache_path() -> Path:
    # Import differe pour eviter les cycles config <-> update_check au load.
    from ..config import data_dir
    return data_dir() / CACHE_FILENAME


def _load_cache() -> dict | None:
    """Lit le cache disque. Retourne None si absent / illisible."""
    p = _cache_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # JSON corrompu (rare, mais possible si crash en plein write).
        # On considere le cache comme absent — il sera ecrase au prochain
        # fetch reussi.
        return None


def _save_cache(payload: dict) -> None:
    """Write atomique du cache. Best-effort : on swallow les erreurs IO
    (disk full, permissions, etc.) — l'auto-update n'est pas critique."""
    p = _cache_path()
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        # Cleanup du tmp si l'os.replace a foire.
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


# ============================================================================
# Fetch reseau
# ============================================================================

def _fetch_latest_release() -> dict | None:
    """GET `/releases/latest` sur GitHub. Retourne le JSON ou None en cas
    d'erreur (network, timeout, status != 200, JSON invalide).

    On ne retry pas : si GitHub est down, on reessaiera au prochain cycle 6h.
    Le silent fail est intentionnel (cf. doc module).
    """
    try:
        resp = requests.get(
            GITHUB_RELEASES_LATEST_URL,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"flox-uploader/{__version__}",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


# ============================================================================
# API publique
# ============================================================================

def read_cached_update_info() -> UpdateInfo:
    """Lit le cache disque et calcule `available`. Ne fait JAMAIS de fetch.

    Cette fonction est appelee a chaque page render via le Jinja global
    `update_info()`. Elle doit etre rapide (lecture d'un petit JSON) et
    silencieuse (jamais d'exception)."""
    current = __version__
    cache = _load_cache()
    if cache is None:
        return UpdateInfo(
            available=False,
            current=current,
            latest="",
            release_url="",
            release_notes="",
            fetched_at="",
        )
    latest = (cache.get("latest") or "").strip()
    return UpdateInfo(
        available=is_newer(latest, current),
        current=current,
        latest=latest,
        release_url=cache.get("release_url") or "",
        release_notes=cache.get("release_notes") or "",
        fetched_at=cache.get("checked_at_iso") or "",
    )


# Lock + flag pour eviter qu'un burst de requetes /api/update-info ne lance
# N threads de refresh en parallele.
_refresh_lock = threading.Lock()
_refresh_in_progress = False


def _is_cache_stale() -> bool:
    cache = _load_cache()
    if cache is None:
        return True
    ts = cache.get("checked_at_epoch")
    if not isinstance(ts, (int, float)):
        return True
    return (time.time() - ts) >= CACHE_TTL_SECONDS


def _refresh_now() -> bool:
    """Fetch + write cache. Retourne True si fetch reussi.

    Public pour les tests (mock requests + call direct). En prod on passe
    par `refresh_cache_if_stale_async()` qui spawn un thread."""
    data = _fetch_latest_release()
    if data is None:
        return False
    payload = {
        "checked_at_epoch": time.time(),
        "checked_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest": (data.get("tag_name") or "").strip(),
        "release_url": data.get("html_url") or "",
        "release_notes": data.get("body") or "",
    }
    _save_cache(payload)
    return True


def refresh_cache_if_stale_async() -> None:
    """Spawn un thread daemon qui refresh le cache si stale (>6h ou absent).

    Idempotent + thread-safe : si un refresh est deja en cours, on no-op.
    Si le cache est frais, on no-op aussi. Le caller (app startup,
    endpoint /api/update-info) peut appeler ca a chaque hit sans craindre
    de surcharge."""
    global _refresh_in_progress

    if not _is_cache_stale():
        return

    with _refresh_lock:
        if _refresh_in_progress:
            return
        _refresh_in_progress = True

    def _runner() -> None:
        global _refresh_in_progress
        try:
            _refresh_now()
        finally:
            with _refresh_lock:
                _refresh_in_progress = False

    t = threading.Thread(target=_runner, daemon=True, name="flox-update-check")
    t.start()


def ensure_cache_exists_sync(timeout_seconds: float = 5.0) -> bool:
    """Sprint 8 hotfix v8 : garantit que le cache existe au boot.

    Si le cache `.update_cache.json` n'a JAMAIS ete cree, on fait un refresh
    SYNC (bloquant max `timeout_seconds`) pour le creer. Important au 1er
    boot de l'app pour que le banner update soit visible des le 1er hit
    utilisateur (au lieu de devoir attendre que le thread daemon termine).

    Cas observe : sur la v0.3.7 installee de Louis, `.update_cache.json`
    n'existait toujours pas apres plusieurs jours. Le thread daemon
    `refresh_cache_if_stale_async()` lance au boot a manifestement
    silent-failed (raison inconnue : timing, GIL, threading specifique
    au bundle PyInstaller `--windowed` ou autre).

    Le refresh sync de 5s au 1er boot est acceptable. Apres, le cache
    existe et on tombe dans le code path async classique (TTL 6h).

    Skip si env var `FLOX_DISABLE_UPDATE_CHECK=1` est set (utilise par
    les tests pour eviter d'appeler GitHub a chaque create_app()).

    Retourne True si un refresh sync a eu lieu, False si le cache existait
    deja OU si l'update check est desactive."""
    if os.environ.get("FLOX_DISABLE_UPDATE_CHECK") == "1":
        return False
    if _load_cache() is not None:
        return False
    # Cache absent : refresh sync avec timeout court
    result = {"done": False}

    def _runner() -> None:
        try:
            _refresh_now()
        finally:
            result["done"] = True

    t = threading.Thread(target=_runner, daemon=True, name="flox-update-check-sync")
    t.start()
    t.join(timeout=timeout_seconds)
    return result["done"]


def force_refresh_sync() -> UpdateInfo:
    """Sprint 8 hotfix v8 : force un refresh sync, retourne le resultat.

    Utilise par l'endpoint POST /api/update-info/refresh quand l'user clique
    le bouton "Verifier maintenant" dans la page Guide. Bloque jusqu'a 5s
    max (timeout HTTP du fetch GitHub) puis retourne l'UpdateInfo a jour.

    Si le fetch echoue (offline, rate limit, etc.), retourne le cache
    existant (ou un UpdateInfo vide si jamais cache)."""
    _refresh_now()  # synchrone, ignore le lock pour priorite user
    return read_cached_update_info()
