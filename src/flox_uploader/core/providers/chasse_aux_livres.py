"""Provider chasse-aux-livres.fr (scraping HTML par ISBN).

Sprint D.26 v0.5.0 (note Louis N-LS2). Agregateur francais de prix livres
qui indexe les principaux marchands. Utile en fallback quand BnF +
Google Books + OpenLibrary ratent.

URL : https://www.chasse-aux-livres.fr/prix/{ISBN}
Pas d'API publique, on scrape les meta tags + le HTML.

Le site retourne typiquement une page avec :
- <h1>{Titre}</h1>
- <p>par <a href="/auteur/...">Auteur</a></p>
- <meta property="og:image" content="..."/>  (cover URL)
- <meta name="description" content="..."/>

On extrait juste : title, authors, cover_url. Pas de description (variable).
"""
from __future__ import annotations

from pathlib import Path

from .book_metadata import BookMetadata, book_from_dict, book_to_dict
from ._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, save_cache,
)
from ._html_scraper import fetch_html, extract_first


CHASSE_URL = "https://www.chasse-aux-livres.fr/prix/{isbn}"


def lookup_chasse_aux_livres(
    isbn: str = "",
    cache_file: Path | None = None,
    http_get=None,
) -> BookMetadata | None:
    """Cherche un livre sur chasse-aux-livres.fr par ISBN.

    Args:
        isbn : ISBN-13 ou ISBN-10. Si absent, retourne None (pas de search texte).
        cache_file : path du cache JSON. Si None, pas de cache.
        http_get : fonction HTTP injectable pour les tests.

    Returns:
        BookMetadata avec source='chasse_aux_livres' si trouve, None sinon.
        Ne plante jamais sur erreur reseau / scraping.
    """
    key = cache_key_isbn(isbn)
    if not key:
        return None  # Pas d'ISBN -> on ne fait rien

    cache = load_cache(cache_file) if cache_file else {}
    if key in cache:
        cached = cache[key]
        if is_miss(cached):
            return None
        return book_from_dict(cached)

    url = CHASSE_URL.format(isbn=key)
    html = fetch_html(url, http_get=http_get)
    if not html:
        # Reseau OK mais reponse vide ou erreur HTTP : on cache pas MISS
        # car ca peut etre transitoire. On retourne None silencieusement.
        return None

    meta = _parse_chasse_html(html, key)
    if meta is None:
        # Vraiment pas trouve : on cache MISS pour eviter de re-tenter.
        if cache_file is not None:
            cache[key] = make_miss()
            save_cache(cache_file, cache)
        return None

    if cache_file is not None:
        cache[key] = book_to_dict(meta)
        save_cache(cache_file, cache)
    return meta


def _parse_chasse_html(html: str, isbn: str) -> BookMetadata | None:
    """Parse le HTML de la page chasse-aux-livres pour un ISBN."""
    meta = BookMetadata()
    meta.sources.append("chasse_aux_livres")
    # On set au moins l'ISBN qu'on a cherche
    if len(isbn) == 13:
        meta.isbn_13 = isbn
    elif len(isbn) == 10:
        meta.isbn_10 = isbn.upper()

    # Titre : <h1>...</h1> typiquement
    # Ou meta property=og:title
    title = extract_first(html, r'<meta\s+property="og:title"\s+content="([^"]+)"')
    if not title:
        title = extract_first(html, r"<h1[^>]*>(.*?)</h1>")
    if title:
        # Retirer "9782... | " ou " - chasse-aux-livres" du titre
        if " | " in title:
            title = title.rsplit(" | ", 1)[0]
        if " - chasse" in title.lower():
            title = title.split(" - chasse", 1)[0]
        meta.title = title.strip()

    # Auteurs : pattern <a href="/auteur/...">Nom</a> ou via meta
    # On essaye d'extraire tous les auteurs listed
    authors_match = extract_first(
        html,
        r'<meta\s+name="author"\s+content="([^"]+)"',
    )
    if authors_match:
        # Plusieurs auteurs separes par ", " ou " et "
        for sep in [", ", " et ", " & "]:
            if sep in authors_match:
                meta.authors = [a.strip() for a in authors_match.split(sep) if a.strip()]
                break
        if not meta.authors:
            meta.authors = [authors_match.strip()]

    # Cover : meta og:image
    cover_url = extract_first(
        html,
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
    )
    if cover_url and cover_url.startswith(("http://", "https://")):
        # Sprint D.30 v0.5.0 (cas Louis Tomoji) : si l'URL pointe vers le
        # LOGO du site lui-meme au lieu d'une vraie couverture, on rejete.
        # Cas reel : chasse-aux-livres renvoie 'logo-chasse-aux-livres-
        # square.png' comme og:image quand la couverture n'est pas
        # disponible -> on prenait le logo comme cover. Pattern : "logo"
        # ou "placeholder" dans l'URL = rejet.
        cover_lower = cover_url.lower()
        is_logo = (
            "/logo-" in cover_lower
            or "logo." in cover_lower.rsplit("/", 1)[-1]
            or "placeholder" in cover_lower
            or "no-image" in cover_lower
            or "default" in cover_lower.rsplit("/", 1)[-1]
        )
        if not is_logo:
            meta.cover_url = cover_url

    # Si on n'a rien recupere (page "non trouve"), on retourne None
    if not meta.title and not meta.authors:
        return None
    return meta
