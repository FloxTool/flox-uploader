"""Provider leslibraires.ca (scraping HTML par ISBN).

Sprint D.26 v0.5.0 (note Louis N-LS2). Reseau de librairies independantes
canadiennes (QC). Utile pour les livres FR-CA et editions speciales QC.

URL : https://www.leslibraires.ca/livres/?q={ISBN}
Le site redirige vers la fiche du livre si match unique sur ISBN.

On extrait : title, authors, publisher, cover_url depuis les meta tags
Schema.org (qui sont stables et standardises).
"""
from __future__ import annotations

from pathlib import Path

from .book_metadata import BookMetadata, book_from_dict, book_to_dict
from ._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, save_cache,
)
from ._html_scraper import fetch_html, extract_first


LESLIBRAIRES_URL = "https://www.leslibraires.ca/livres/?q={isbn}"


def lookup_leslibraires_ca(
    isbn: str = "",
    cache_file: Path | None = None,
    http_get=None,
) -> BookMetadata | None:
    """Cherche un livre sur leslibraires.ca par ISBN.

    Args:
        isbn : ISBN-13 ou ISBN-10. Si absent, retourne None.
        cache_file : path du cache JSON. Si None, pas de cache.
        http_get : fonction HTTP injectable pour les tests.

    Returns:
        BookMetadata avec source='leslibraires_ca' si trouve, None sinon.
    """
    key = cache_key_isbn(isbn)
    if not key:
        return None

    cache = load_cache(cache_file) if cache_file else {}
    if key in cache:
        cached = cache[key]
        if is_miss(cached):
            return None
        return book_from_dict(cached)

    url = LESLIBRAIRES_URL.format(isbn=key)
    html = fetch_html(url, http_get=http_get)
    if not html:
        return None

    meta = _parse_leslibraires_html(html, key)
    if meta is None:
        if cache_file is not None:
            cache[key] = make_miss()
            save_cache(cache_file, cache)
        return None

    if cache_file is not None:
        cache[key] = book_to_dict(meta)
        save_cache(cache_file, cache)
    return meta


def _parse_leslibraires_html(html: str, isbn: str) -> BookMetadata | None:
    """Parse le HTML pour extraire title/authors/publisher/cover.

    leslibraires.ca utilise du Schema.org/Book microdata :
      <span itemprop="name">Titre</span>
      <span itemprop="author">Auteur</span>
      <span itemprop="publisher">Editeur</span>
    Et meta og:image pour la cover.
    """
    meta = BookMetadata()
    meta.sources.append("leslibraires_ca")
    if len(isbn) == 13:
        meta.isbn_13 = isbn
    elif len(isbn) == 10:
        meta.isbn_10 = isbn.upper()

    # Title : og:title ou Schema.org name
    title = extract_first(html, r'<meta\s+property="og:title"\s+content="([^"]+)"')
    if not title:
        title = extract_first(
            html,
            r'<[^>]+itemprop="name"[^>]*>([^<]+)</[^>]+>',
        )
    if title:
        # Nettoyer les suffixes comme " | Les Libraires" ou " - Les Libraires"
        for sep in [" | Les Libraires", " - Les Libraires", " - leslibraires"]:
            if sep in title:
                title = title.split(sep, 1)[0]
                break
        meta.title = title.strip()

    # Authors : meta name=author OU Schema.org author
    authors_raw = extract_first(html, r'<meta\s+name="author"\s+content="([^"]+)"')
    if not authors_raw:
        # Schema.org : peut y avoir plusieurs <span itemprop="author">
        from ._html_scraper import extract_all
        authors_list = extract_all(
            html,
            r'<[^>]+itemprop="author"[^>]*>([^<]+)</[^>]+>',
        )
        if authors_list:
            meta.authors = [a.strip() for a in authors_list if a.strip()]
    if authors_raw and not meta.authors:
        for sep in [", ", " et ", " & "]:
            if sep in authors_raw:
                meta.authors = [a.strip() for a in authors_raw.split(sep) if a.strip()]
                break
        if not meta.authors:
            meta.authors = [authors_raw.strip()]

    # Publisher : Schema.org publisher
    publisher = extract_first(
        html,
        r'<[^>]+itemprop="publisher"[^>]*>([^<]+)</[^>]+>',
    )
    if publisher:
        meta.publisher = publisher.strip()

    # Cover : og:image
    cover_url = extract_first(
        html,
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
    )
    if cover_url and cover_url.startswith(("http://", "https://")):
        meta.cover_url = cover_url

    if not meta.title and not meta.authors:
        return None
    return meta
