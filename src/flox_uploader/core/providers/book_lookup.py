"""Orchestrateur de lookup metadonnees livre — combine BnF + Google Books + OpenLibrary.

Sprint D.2 v0.5.0 (PLAN-MULTICAT §7.4). Strategie de fallback :

1. Si on a un ISBN -> on tente BnF d'abord (pivot FR, donnees canoniques FR)
2. Puis Google Books (resume FR + couverture image)
3. Puis OpenLibrary (fallback gratuit, parfois la seule source qui a un livre)

Les 3 providers ENRICHISSENT le BookMetadata via merge_from(), sans s'ecraser.
L'extraction locale (EPUB) reste autoritaire pour ce qui est dans le fichier
(elle a deja remplit le meta avant qu'on appelle lookup_book_metadata).

Comportement gracieux :
- Si BnF + Google Books + OpenLibrary echouent tous -> on retourne le meta tel quel
- Si certains sont down ou rate-limited -> on continue avec les autres
- Aucun ne plante l'orchestrateur

Cache : chaque provider a son propre cache JSON par ISBN. Aucun nettoyage TTL
(les metadonnees livre sont quasi-immuables). Si une entry est buggee, l'user
peut supprimer le fichier cache pour forcer un re-fetch.
"""
from __future__ import annotations

from pathlib import Path

from .book_metadata import BookMetadata
from .bnf import lookup_bnf
from .google_books import lookup_google_books
from .openlibrary import lookup_openlibrary


def lookup_book_metadata(
    base: BookMetadata,
    cache_dir: Path | None = None,
    google_api_key: str = "",
    http_get=None,
    providers_order: tuple[str, ...] = ("bnf", "google_books", "openlibrary"),
) -> BookMetadata:
    """Enrichit `base` avec les metadonnees BnF, Google Books, OpenLibrary.

    `base` est typiquement le BookMetadata extrait localement (EPUB). On
    suppose qu'il a au moins un ISBN OU (title + author). Si ni l'un ni
    l'autre, on retourne `base` inchange.

    L'enrichissement se fait via merge_from() : les champs deja remplis dans
    `base` NE SONT PAS ecrases. Les providers viennent COMPLETER ce qui manque
    (typiquement : resume, couverture, editeur canonique, annee).

    Args:
        base : BookMetadata source (idealement deja peuple par extract_epub_metadata).
        cache_dir : dossier pour les caches JSON (un fichier par provider).
        google_api_key : cle Google Books optionnelle (augmente quota).
        http_get : fonction HTTP injectable (pour les tests). Par defaut
            http_get_with_retry.
        providers_order : ordre d'appel des providers. Defaut: bnf > google > openlib.

    Returns:
        Le meme objet `base` enrichi (mute in-place + retourne pour chainer).
    """
    # On a besoin d'au moins ISBN OU title (auteur optionnel) pour chercher.
    # Sprint D.7 v0.5.0 : on permet title-seul (sans author) car de
    # nombreux PDF/CBZ n'ont pas d'auteur dans /Info ou ComicInfo.xml.
    # Google Books / BnF acceptent une recherche par titre seul.
    has_isbn = bool(base.isbn)
    has_text_query = bool(base.title)
    if not has_isbn and not has_text_query:
        return base

    bnf_cache = cache_dir / ".bnf_cache.json" if cache_dir else None
    google_cache = cache_dir / ".google_books_cache.json" if cache_dir else None
    openlib_cache = cache_dir / ".openlibrary_cache.json" if cache_dir else None

    for provider in providers_order:
        try:
            if provider == "bnf":
                enriched = lookup_bnf(
                    isbn=base.isbn,
                    title=base.title,
                    author=base.primary_author,
                    cache_file=bnf_cache,
                    http_get=http_get,
                )
            elif provider == "google_books":
                enriched = lookup_google_books(
                    isbn=base.isbn,
                    title=base.title,
                    author=base.primary_author,
                    cache_file=google_cache,
                    api_key=google_api_key,
                    http_get=http_get,
                )
            elif provider == "openlibrary":
                # OpenLibrary ne supporte que la recherche par ISBN
                if not base.isbn:
                    continue
                enriched = lookup_openlibrary(
                    isbn=base.isbn,
                    cache_file=openlib_cache,
                    http_get=http_get,
                )
            else:
                continue
        except Exception as e:
            # Ceinture et bretelles : meme si un provider leve une exception
            # inattendue, on continue avec les suivants.
            print(f"[WARN] book_lookup provider {provider} : {type(e).__name__} {e}")
            continue

        if enriched is not None:
            base.merge_from(enriched, source_name=provider)

    return base
