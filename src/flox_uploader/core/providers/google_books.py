"""Client API Google Books (Volumes API).

Sprint D.2 v0.5.0 (PLAN-MULTICAT §7.4). Bonne couverture mondiale, **resume
FR de qualite** quand dispo, **couverture** image accessible directement.
Gratuit jusqu'a 1000 req/jour sans cle, 100k avec cle Google Cloud.

Endpoint : https://www.googleapis.com/books/v1/volumes

Strategie :
- Recherche par ISBN-13 d'abord (le plus precis)
- Fallback par titre + auteur
- Filtrage langfilter=fr quand on cherche par titre (privilegie l'edition FR)
- Cache atomique par ISBN dans data/.google_books_cache.json
- Aucune cle requise pour les usages legers (~5-10 lookups par session)

JSON response shape :
{
  "items": [
    {
      "id": "...",
      "volumeInfo": {
        "title": "...",
        "subtitle": "...",
        "authors": ["..."],
        "publisher": "...",
        "publishedDate": "2024-03-15" ou "2024",
        "description": "...",
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "..."}, ...],
        "pageCount": 384,
        "language": "fr",
        "categories": ["Fiction / ..."],
        "imageLinks": {"thumbnail": "...", "smallThumbnail": "..."}
      }
    }
  ]
}
"""
from __future__ import annotations

import re
from pathlib import Path

from ..http import http_get_with_retry as _default_http_get
from .book_metadata import BookMetadata, book_from_dict, book_to_dict
from ._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, save_cache,
)


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


def lookup_google_books(
    isbn: str = "",
    title: str = "",
    author: str = "",
    cache_file: Path | None = None,
    api_key: str = "",
    http_get=None,
    extra_titles: list[str] | None = None,
) -> BookMetadata | None:
    """Cherche un livre dans Google Books.

    Args:
        isbn : ISBN-13 ou ISBN-10. Si fourni, query = "isbn:..." (precis).
        title : utilise en fallback si pas d'ISBN.
        author : optionnel, affine la recherche par titre.
        cache_file : path du cache JSON. Si None, pas de cache.
        api_key : cle Google Cloud optionnelle (augmente le quota).
        http_get : fonction HTTP injectable (pour les tests).
        extra_titles : Sprint D.29 v0.5.0. Titres candidats alternatifs
            essayes si la query avec `title` echoue. Cas typique : la
            metadata EPUB embarquee a un titre tronque ('POITIERS 2026
            (avec photos)') mais le filename scene parse contient le
            vrai titre canonique ('Guide Poitiers Petit Fute').

    Returns:
        BookMetadata avec source='google_books' si trouve, None sinon.
        Ne plante jamais sur erreur reseau.
    """
    http = http_get or _default_http_get
    cache = load_cache(cache_file) if cache_file else {}
    extras = list(extra_titles or [])

    key = cache_key_isbn(isbn)
    if key:
        if key in cache:
            cached = cache[key]
            if is_miss(cached):
                # Sprint D.17 v0.5.0 (note Louis N-Rel-3) : si l'ISBN
                # est MISS dans le cache mais qu'on a un titre, on
                # tente le fallback title+author au lieu de retourner
                # None silencieusement. Cas reel : reedition annuelle
                # (Petit Fute) ou ISBN ebook vs print divergent.
                if title:
                    return _query_by_title_author(
                        title, author, api_key=api_key, http=http,
                        extra_titles=extras,
                    )
                return None
            return book_from_dict(cached)

        meta = _query_by_isbn(key, api_key=api_key, http=http)
        if cache_file is not None:
            cache[key] = book_to_dict(meta) if meta else make_miss()
            save_cache(cache_file, cache)
        if meta is not None:
            return meta
        # Sprint D.17 : ISBN ne match pas en ligne -> fallback titre.
        if title:
            return _query_by_title_author(
                title, author, api_key=api_key, http=http,
                extra_titles=extras,
            )
        return None

    # Pas d'ISBN : fallback direct sur titre + auteur (pas de cache pour
    # ce type de query, trop variable).
    if title:
        return _query_by_title_author(
            title, author, api_key=api_key, http=http,
            extra_titles=extras,
        )

    return None


def _query_by_isbn(isbn: str, api_key: str, http) -> BookMetadata | None:
    """Recherche Google Books par ISBN."""
    params = {"q": f"isbn:{isbn}", "maxResults": "1"}
    if api_key:
        params["key"] = api_key
    try:
        resp = http(GOOGLE_BOOKS_URL, params=params)
    except Exception as e:
        print(f"[WARN] Google Books lookup ISBN {isbn} : {type(e).__name__} {e}")
        return None
    return _parse_first_item(resp.json())


def _query_by_title_author(
    title: str, author: str, api_key: str, http,
    extra_titles: list[str] | None = None,
) -> BookMetadata | None:
    """Recherche Google Books par titre + auteur.

    Sprint D.16 v0.5.0 : multi-stratégies. On normalise titre+auteur via
    _query_normalize, puis on essaye plusieurs variantes du plus strict au
    plus permissif jusqu'à trouver un match.

    Sprint D.29 v0.5.0 : si `extra_titles` est fourni (typiquement le
    scene_parsed.title quand il differe de la metadata EPUB), on construit
    des variantes additionnelles avec chaque titre alternatif. Cas Louis
    Petit Fute Poitiers : metadata EPUB = 'POITIERS 2026 (avec photos)'
    (titre tronque editeur), filename scene = 'Guide Poitiers Petit Fute'
    (titre canonique cherchable).

    Cf. notes Louis N-Rel-1 à N-Rel-6 : nos titres viennent souvent du
    nom de fichier scene avec dots, tokens techniques (FRENCH/EPUB/PDF/...)
    et marqueurs tome. La query strict avec quotes ratait tout.
    """
    from ._query_normalize import build_query_variants, normalize_title_for_query
    variants = build_query_variants(title, author)
    # Sprint D.29 : ajouter les variantes pour chaque extra_title different
    if extra_titles:
        seen_norm = {normalize_title_for_query(title).lower()}
        for extra in extra_titles:
            norm = normalize_title_for_query(extra).lower()
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            variants.extend(build_query_variants(extra, author))
    if not variants:
        return None

    # Dedupe global (titre+author+quotes)
    seen_keys: set[tuple[str, str, bool]] = set()
    unique_variants = []
    for v in variants:
        k = (v.title.lower(), v.author.lower(), v.use_quotes)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        unique_variants.append(v)
    variants = unique_variants

    for variant in variants:
        # Construire la query selon la variante
        if variant.use_quotes:
            query_parts = [f'intitle:"{variant.title}"']
            if variant.author:
                query_parts.append(f'inauthor:"{variant.author}"')
        else:
            # Sans quotes : intitle:mot1 intitle:mot2 (chaque mot du titre)
            # ou simplement intitle:tous-les-mots-concatenés. Google Books
            # accepte les 2 ; on prefere la 2e qui est moins stricte.
            query_parts = [f"intitle:{variant.title}"]
            if variant.author:
                query_parts.append(f"inauthor:{variant.author}")
        params = {
            "q": " ".join(query_parts),
            "maxResults": "1",
            "langRestrict": "fr",  # privilegier l'edition FR
        }
        if api_key:
            params["key"] = api_key
        try:
            resp = http(GOOGLE_BOOKS_URL, params=params)
        except Exception as e:
            print(f"[WARN] Google Books variant {variant.label!r} : {type(e).__name__} {e}")
            continue

        try:
            data = resp.json()
        except Exception:
            continue

        meta = _parse_first_item(data)
        if meta is not None:
            # Match trouvé : on s'arrête sur la 1re variante qui fonctionne
            return meta

    # Aucune variante n'a matché
    return None


def _parse_first_item(data) -> BookMetadata | None:
    """Parse une reponse Google Books JSON et extrait le premier item."""
    if not isinstance(data, dict):
        return None
    items = data.get("items") or []
    if not items:
        return None
    first_item = items[0]
    info = first_item.get("volumeInfo") or {}
    if not isinstance(info, dict):
        return None

    meta = BookMetadata()
    meta.sources.append("google_books")

    # Sprint D.15 v0.5.0 : capturer le volumeId pour generer un lien
    # direct vers la fiche Google Books (https://books.google.com/books?id={id})
    # au lieu d'un lien de recherche generique.
    volume_id = str(first_item.get("id") or "").strip()
    if volume_id:
        meta.google_books_id = volume_id

    # Titre + sous-titre
    if info.get("title"):
        meta.title = str(info["title"]).strip()
    if info.get("subtitle"):
        meta.subtitle = str(info["subtitle"]).strip()

    # Auteurs
    raw_authors = info.get("authors") or []
    if isinstance(raw_authors, list):
        for a in raw_authors:
            name = str(a).strip()
            if name and name not in meta.authors:
                meta.authors.append(name)

    # Editeur
    if info.get("publisher"):
        meta.publisher = str(info["publisher"]).strip()

    # Date -> annee
    date_str = str(info.get("publishedDate") or "")
    m = re.search(r"\b(1[89]|20)\d{2}\b", date_str)
    if m:
        try:
            meta.publication_year = int(m.group())
        except ValueError:
            pass

    # Description (strip HTML : certaines reponses Google contiennent <br>)
    if info.get("description"):
        from ._html import strip_html
        meta.description = strip_html(str(info["description"]))

    # Pages
    if info.get("pageCount"):
        try:
            meta.page_count = int(info["pageCount"])
        except (TypeError, ValueError):
            pass

    # Langue (deja en ISO 639-1 cote Google Books)
    if info.get("language"):
        meta.language = str(info["language"]).strip().lower()[:2]

    # ISBN
    for ident in info.get("industryIdentifiers") or []:
        if not isinstance(ident, dict):
            continue
        kind = str(ident.get("type") or "").upper()
        val = str(ident.get("identifier") or "").replace("-", "").replace(" ", "")
        if kind == "ISBN_13" and len(val) == 13 and val.isdigit() and not meta.isbn_13:
            meta.isbn_13 = val
        elif kind == "ISBN_10" and len(val) == 10 and not meta.isbn_10:
            meta.isbn_10 = val.upper()

    # Genres (categories)
    raw_cats = info.get("categories") or []
    if isinstance(raw_cats, list):
        for c in raw_cats:
            cat = str(c).strip()
            if cat and cat not in meta.genres:
                meta.genres.append(cat)

    # Couverture (thumbnail / smallThumbnail)
    image_links = info.get("imageLinks") or {}
    if isinstance(image_links, dict):
        # Preference : thumbnail > smallThumbnail
        url = image_links.get("thumbnail") or image_links.get("smallThumbnail") or ""
        if url:
            # Google sert HTTP par defaut, on force HTTPS pour eviter mixed-content
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            meta.cover_url = str(url)

    if not meta.title and not meta.authors and not meta.isbn_13:
        return None
    return meta
