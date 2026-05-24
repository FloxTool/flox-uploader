"""Client API OpenLibrary — fallback gratuit sans cle.

Sprint D.2 v0.5.0 (PLAN-MULTICAT §7.4). Backup quand BnF et Google Books
ratent. Couverture mondiale, donnees parfois moins propres que Google mais
existence d'entries pour beaucoup de livres absents ailleurs (auto-publies,
imprimes recents, etc.).

Endpoint Books API : https://openlibrary.org/api/books?bibkeys=ISBN:<isbn>&format=json&jscmd=data

JSON response shape (par bibkey):
{
  "ISBN:9782267027044": {
    "title": "...",
    "subtitle": "...",
    "authors": [{"name": "..."}, ...],
    "publishers": [{"name": "..."}, ...],
    "publish_date": "2002",
    "number_of_pages": 384,
    "subjects": [{"name": "...", "url": "..."}, ...],
    "cover": {"small": "...", "medium": "...", "large": "..."},
    "identifiers": {"isbn_13": ["..."], "isbn_10": ["..."]},
    "notes": "...",
    "languages": [{"key": "/languages/fre"}, ...]
  }
}

Limites : pas de description riche (le champ "notes" est bref ou vide
souvent). C'est un complement, pas un primary source.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..http import http_get_with_retry as _default_http_get
from .book_metadata import BookMetadata, book_from_dict, book_to_dict
from ._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, save_cache,
)


OPENLIBRARY_URL = "https://openlibrary.org/api/books"


def lookup_openlibrary(
    isbn: str = "",
    cache_file: Path | None = None,
    http_get=None,
) -> BookMetadata | None:
    """Cherche un livre dans OpenLibrary par ISBN.

    OpenLibrary expose un /search.json par titre+auteur mais la qualite des
    resultats est aleatoire (souvent multiple editions). On se limite a
    l'ISBN lookup (qui est fiable).

    Args:
        isbn : ISBN-13 ou ISBN-10. Requis (pas de lookup par titre ici).
        cache_file : path du cache JSON. Si None, pas de cache.
        http_get : fonction HTTP injectable (pour les tests).

    Returns:
        BookMetadata avec source='openlibrary' si trouve, None sinon.
    """
    http = http_get or _default_http_get

    key = cache_key_isbn(isbn)
    if not key:
        return None

    cache = load_cache(cache_file) if cache_file else {}
    if key in cache:
        cached = cache[key]
        if is_miss(cached):
            return None
        return book_from_dict(cached)

    meta = _query_openlibrary(key, http=http)
    if cache_file is not None:
        cache[key] = book_to_dict(meta) if meta else make_miss()
        save_cache(cache_file, cache)
    return meta


def _query_openlibrary(isbn: str, http) -> BookMetadata | None:
    """Requete OpenLibrary par ISBN."""
    bibkey = f"ISBN:{isbn}"
    params = {
        "bibkeys": bibkey,
        "format": "json",
        "jscmd": "data",
    }
    try:
        resp = http(OPENLIBRARY_URL, params=params)
    except Exception as e:
        print(f"[WARN] OpenLibrary lookup ISBN {isbn} : {type(e).__name__} {e}")
        return None
    try:
        data = resp.json()
    except (ValueError, AttributeError):
        return None
    if not isinstance(data, dict):
        return None
    info = data.get(bibkey)
    if not isinstance(info, dict):
        return None
    return _parse_openlibrary_record(info, isbn)


def _parse_openlibrary_record(info: dict, isbn_queried: str) -> BookMetadata | None:
    """Parse un record OpenLibrary en BookMetadata."""
    meta = BookMetadata()
    meta.sources.append("openlibrary")

    # Titre + sous-titre
    if info.get("title"):
        meta.title = str(info["title"]).strip()
    if info.get("subtitle"):
        meta.subtitle = str(info["subtitle"]).strip()

    # Auteurs (list of dicts {name: ...})
    raw_authors = info.get("authors") or []
    if isinstance(raw_authors, list):
        for a in raw_authors:
            if isinstance(a, dict) and a.get("name"):
                name = str(a["name"]).strip()
                if name and name not in meta.authors:
                    meta.authors.append(name)

    # Editeurs (list of dicts {name: ...}) — premier
    raw_pubs = info.get("publishers") or []
    if isinstance(raw_pubs, list) and raw_pubs:
        first = raw_pubs[0]
        if isinstance(first, dict) and first.get("name"):
            meta.publisher = str(first["name"]).strip()

    # Date -> annee
    date_str = str(info.get("publish_date") or "")
    m = re.search(r"\b(1[89]|20)\d{2}\b", date_str)
    if m:
        try:
            meta.publication_year = int(m.group())
        except ValueError:
            pass

    # Pages
    pc = info.get("number_of_pages")
    if pc is not None:
        try:
            meta.page_count = int(pc)
        except (TypeError, ValueError):
            pass

    # ISBN : preferer industry_identifiers > fallback isbn querie
    identifiers = info.get("identifiers") or {}
    if isinstance(identifiers, dict):
        isbn_13_list = identifiers.get("isbn_13") or []
        isbn_10_list = identifiers.get("isbn_10") or []
        if isbn_13_list and isinstance(isbn_13_list, list):
            val = str(isbn_13_list[0]).replace("-", "").replace(" ", "")
            if len(val) == 13 and val.isdigit():
                meta.isbn_13 = val
        if isbn_10_list and isinstance(isbn_10_list, list):
            val = str(isbn_10_list[0]).replace("-", "").replace(" ", "")
            if len(val) == 10 and not meta.isbn_10:
                meta.isbn_10 = val.upper()
    # Si rien dans identifiers, on garde l'ISBN demande (qu'on connait deja)
    if not meta.isbn_13 and len(isbn_queried) == 13:
        meta.isbn_13 = isbn_queried
    if not meta.isbn_10 and len(isbn_queried) == 10:
        meta.isbn_10 = isbn_queried

    # Genres (subjects)
    subjects = info.get("subjects") or []
    if isinstance(subjects, list):
        for s in subjects:
            name = ""
            if isinstance(s, dict) and s.get("name"):
                name = str(s["name"]).strip()
            elif isinstance(s, str):
                name = s.strip()
            if name and name not in meta.genres:
                meta.genres.append(name)

    # Langue : OpenLibrary expose une key "/languages/fre", on en extrait le code
    langs = info.get("languages") or []
    if isinstance(langs, list) and langs:
        first = langs[0]
        if isinstance(first, dict):
            key = str(first.get("key") or "")
            # "/languages/fre" -> "fre" -> "fr"
            code = key.rsplit("/", 1)[-1] if key else ""
            mapping = {"fre": "fr", "fra": "fr", "eng": "en", "spa": "es",
                       "ger": "de", "deu": "de", "ita": "it", "jpn": "ja",
                       "chi": "zh", "zho": "zh", "rus": "ru", "por": "pt"}
            if code in mapping:
                meta.language = mapping[code]
            elif code and len(code) >= 2:
                meta.language = code[:2].lower()

    # Couverture (large > medium > small)
    cover = info.get("cover") or {}
    if isinstance(cover, dict):
        url = cover.get("large") or cover.get("medium") or cover.get("small") or ""
        if url:
            url = str(url)
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            meta.cover_url = url

    # Notes (description partielle)
    notes = info.get("notes")
    if notes and not meta.description:
        if isinstance(notes, dict) and notes.get("value"):
            meta.description = str(notes["value"]).strip()
        elif isinstance(notes, str):
            meta.description = notes.strip()

    if not meta.title and not meta.authors and not meta.isbn_13:
        return None
    return meta
