"""Helper de cache atomique JSON pour les providers de metadonnees.

Sprint D.2 v0.5.0 — factorise le pattern atomic-write deja utilise par tmdb.py
pour eviter la duplication entre BnF / Google Books / OpenLibrary / IGDB / etc.

Pattern :
- Cache JSON unique par provider (`data/.bnf_cache.json`, `.google_books_cache.json`...)
- Cle = ISBN normalise (13 chiffres) ou autre identifiant stable
- Atomic write via tmp + os.replace pour eviter les fichiers tronques
- Lecture tolerante : JSON corrompu -> on repart de zero
- Sentinelle pour les misses : on cache aussi les "pas trouve" (None marker)
  pour eviter de re-fetch un livre absent du catalogue toutes les 5 minutes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# Marker special qui distingue "pas encore cache" de "cache = pas trouve".
# Permet de cacher les "404 / not found" pour eviter de re-frapper les APIs.
_MISS_MARKER: str = "__NOT_FOUND__"


def load_cache(cache_file: Path) -> dict[str, Any]:
    """Charge un cache JSON, retourne dict vide si absent ou corrompu.

    Ne plante jamais : un cache invalide est silencieusement reinitialise
    (le provider va juste re-fetch tout ce qu'il a besoin).
    """
    if not cache_file.is_file():
        return {}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"[WARN] Cache {cache_file.name} illisible ({type(e).__name__}: {e}), reset.")
        return {}


def save_cache(cache_file: Path, cache: dict[str, Any]) -> None:
    """Sauve un cache JSON en atomic write (tmp + os.replace).

    Ne plante jamais : un echec d'ecriture est loggue mais le pipeline
    continue (le cache sera juste vide au prochain run).
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, cache_file)
    except (OSError, TypeError, ValueError) as e:
        print(f"[WARN] Cache {cache_file.name} write failed ({type(e).__name__}): {e}")


def normalize_isbn(isbn: str) -> str:
    """Normalise un ISBN : enleve tirets, espaces, prefixes. Garde 10 ou 13 chiffres.

    Retourne "" si pas un ISBN valide (longueur != 10 ou 13).
    """
    if not isbn:
        return ""
    clean = isbn.strip().upper()
    # Retirer prefixe ISBN: ou urn:isbn:
    for prefix in ("URN:ISBN:", "ISBN:", "ISBN-13:", "ISBN-10:", "ISBN "):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break
    # Retirer tirets / espaces
    clean = clean.replace("-", "").replace(" ", "")
    # ISBN-10 peut finir par 'X' (chiffre de controle), sinon tout doit etre des chiffres
    if len(clean) == 10:
        body, check = clean[:-1], clean[-1]
        if body.isdigit() and (check.isdigit() or check == "X"):
            return clean
    elif len(clean) == 13 and clean.isdigit():
        return clean
    return ""


def cache_key_isbn(isbn: str) -> str:
    """Construit une cle de cache depuis un ISBN. ISBN-13 prioritaire."""
    return normalize_isbn(isbn) or ""


def is_miss(cached_value: Any) -> bool:
    """Vrai si la valeur cachee est le marker 'pas trouve'."""
    return cached_value == _MISS_MARKER


def make_miss() -> str:
    """Retourne le marker 'pas trouve' a stocker dans le cache."""
    return _MISS_MARKER
