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
    trace: list | None = None,
    target_year: int = 0,
    target_volume: float = 0.0,
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

    # Sprint D.30 v0.5.0 : trace diagnostique. Chaque tentative est loggee
    # dans debug.json via BookNamingStrategy pour permettre de diagnostiquer
    # les 429 / no_match / etc. sans avoir a re-instrumenter.
    entry: dict | None = None
    if trace is not None:
        entry = {
            "provider": "google_books",
            "isbn": isbn,
            "title": title,
            "author": author,
            "extra_titles": list(extras),
            "queries": [],
            "outcome": "no_match",
            "has_api_key": bool(api_key),
        }
        trace.append(entry)

    def _set_outcome(name: str, **extra):
        if entry is not None:
            entry["outcome"] = name
            for k, v in extra.items():
                entry[k] = v

    key = cache_key_isbn(isbn)
    if key:
        if key in cache:
            cached = cache[key]
            if is_miss(cached):
                _set_outcome("cached_miss")
                # Sprint D.17 v0.5.0 (note Louis N-Rel-3) : si l'ISBN
                # est MISS dans le cache mais qu'on a un titre, on
                # tente le fallback title+author au lieu de retourner
                # None silencieusement. Cas reel : reedition annuelle
                # (Petit Fute) ou ISBN ebook vs print divergent.
                if title:
                    return _query_by_title_author(
                        title, author, api_key=api_key, http=http,
                        extra_titles=extras, trace_entry=entry,
                        target_year=target_year, target_volume=target_volume,
                    )
                return None
            _set_outcome("cached_hit", matched_id=cached.get("google_books_id", ""))
            return book_from_dict(cached)

        meta = _query_by_isbn(key, api_key=api_key, http=http, trace_entry=entry)
        if cache_file is not None:
            cache[key] = book_to_dict(meta) if meta else make_miss()
            save_cache(cache_file, cache)
        if meta is not None:
            _set_outcome("matched_isbn", matched_id=meta.google_books_id or "",
                         matched_title=meta.title)
            return meta
        # Sprint D.17 : ISBN ne match pas en ligne -> fallback titre.
        if title:
            return _query_by_title_author(
                title, author, api_key=api_key, http=http,
                extra_titles=extras, trace_entry=entry,
            )
        return None

    # Pas d'ISBN : fallback direct sur titre + auteur (pas de cache pour
    # ce type de query, trop variable).
    if title:
        return _query_by_title_author(
            title, author, api_key=api_key, http=http,
            extra_titles=extras, trace_entry=entry,
            target_year=target_year, target_volume=target_volume,
        )

    return None


def _query_by_isbn(
    isbn: str, api_key: str, http,
    trace_entry: dict | None = None,
) -> BookMetadata | None:
    """Recherche Google Books par ISBN.

    Sprint D.44 v0.5.0 (feedback Louis Space Brothers T33) : on demande
    maintenant maxResults=5 (au lieu de 1) pour avoir plusieurs candidates
    a ranker via _parse_best_item, qui penalise les title suspects (year-
    only, number-only). Cas Louis : ISBN Pika T33 a 2 fiches Google :
    'ZXe9ygEACAAJ' (title='2021', suspect) et 'elEXEAAAQBAJ' (title='Space
    Brothers T33', meaningful). On veut la 2eme.
    """
    import time
    params = {"q": f"isbn:{isbn}", "maxResults": "5"}
    if api_key:
        params["key"] = api_key
    t0 = time.monotonic()
    q_entry = {"q": f"isbn:{isbn}", "phase": "isbn"}
    try:
        resp = http(GOOGLE_BOOKS_URL, params=params)
    except Exception as e:
        q_entry.update({
            "error": f"{type(e).__name__}: {e}",
            "ms": int((time.monotonic() - t0) * 1000),
        })
        if trace_entry is not None:
            trace_entry["queries"].append(q_entry)
            if "429" in str(e):
                trace_entry["outcome"] = "rate_limited"
        print(f"[WARN] Google Books lookup ISBN {isbn} : {type(e).__name__} {e}")
        return None
    q_entry.update({
        "http_status": getattr(resp, "status_code", 200),
        "ms": int((time.monotonic() - t0) * 1000),
    })
    try:
        data = resp.json()
    except Exception:
        data = {}
    q_entry["items_returned"] = len(data.get("items", []) or [])
    if trace_entry is not None:
        trace_entry["queries"].append(q_entry)
    # Sprint D.44 : ranking via _parse_best_item (penalise titles suspects).
    return _parse_best_item(data)


def _query_by_title_author(
    title: str, author: str, api_key: str, http,
    extra_titles: list[str] | None = None,
    trace_entry: dict | None = None,
    target_year: int = 0,
    target_volume: float = 0.0,
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

    # Sprint D.34 v0.5.0 : variantes avec VOLUME signal pour series/manga.
    # Cas Louis Miraculous T2, Space Brothers T33, One Piece, Vanessa Vale T2.
    # Sans volume dans la query, Google retourne A volume de la serie (souvent
    # T1 ou le plus populaire) plutot que LE volume cible. On ajoute donc
    # 3 formats : "Tome N", "T0N", "Vol N".
    #
    # IMPORTANT : on construit les QueryVariant directement (PAS via
    # build_query_variants) car celui-ci re-applique normalize_title_for_query
    # qui STRIP les marqueurs Tome / T0N / Vol (paradoxalement utile pour les
    # queries series-only mais ici contre-productif).
    from ._query_normalize import normalize_author_for_query, QueryVariant
    if target_volume and target_volume > 0:
        vol_int = int(target_volume) if target_volume == int(target_volume) else target_volume
        vol_str = str(vol_int)
        # 3 formats de suffix volume
        volume_suffixes = [f"Tome {vol_str}", f"T{int(vol_int):02d}", f"Vol {vol_str}"]
        norm_author = normalize_author_for_query(author)
        added_titles: set[str] = set()
        # Liste des titres a essayer (primary + extras)
        title_candidates = [title]
        if extra_titles:
            title_candidates.extend(extra_titles)
        for cand_title in title_candidates:
            cand_norm = normalize_title_for_query(cand_title)
            if not cand_norm:
                continue
            for vsuf in volume_suffixes:
                title_with_vol = f"{cand_norm} {vsuf}"
                if title_with_vol.lower() in added_titles:
                    continue
                added_titles.add(title_with_vol.lower())
                # Souple (sans quotes) - plus permissif
                variants.append(QueryVariant(
                    title=title_with_vol,
                    author=norm_author,
                    use_quotes=False,
                    label=f"volume signal '{vsuf}' souple : {title_with_vol} + {norm_author}",
                ))

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

    import time
    rate_limited = False
    # Sprint D.31 : si target_year fourni, on collecte les MEILLEURS candidats
    # de chaque variante puis on rank globalement. Sans ca, on baille sur la
    # 1ere variante meme si son meilleur candidat est tres loin de target_year
    # (cas Petit Fute : variante "POITIERS avec photos" renvoie edition 2013,
    # mais variante "Guide Poitiers Petit Fute" aurait renvoye 2026).
    best_so_far: BookMetadata | None = None
    best_distance: int = 9999
    best_via_variant: str = ""
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
        q_str = " ".join(query_parts)
        # Sprint D.31 : maxResults=5 pour avoir un pool a ranker (cas Petit
        # Fute : 5 editions annuelles, on doit choisir celle qui matche
        # target_year). Si target_year=0, on prend juste le 1er.
        params = {
            "q": q_str,
            "maxResults": "5" if target_year else "1",
            "langRestrict": "fr",  # privilegier l'edition FR
        }
        if api_key:
            params["key"] = api_key
        t0 = time.monotonic()
        q_entry = {"q": q_str, "phase": "title_author", "label": variant.label}
        try:
            resp = http(GOOGLE_BOOKS_URL, params=params)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            q_entry.update({
                "error": err,
                "ms": int((time.monotonic() - t0) * 1000),
            })
            if trace_entry is not None:
                trace_entry["queries"].append(q_entry)
            if "429" in str(e):
                rate_limited = True
                # Si on est rate-limite, inutile de continuer a hammer
                print(f"[WARN] Google Books rate-limited (429), abandon des variants suivants.")
                break
            print(f"[WARN] Google Books variant {variant.label!r} : {type(e).__name__} {e}")
            continue

        q_entry.update({
            "http_status": getattr(resp, "status_code", 200),
            "ms": int((time.monotonic() - t0) * 1000),
        })
        try:
            data = resp.json()
        except Exception:
            q_entry["error"] = "invalid_json"
            if trace_entry is not None:
                trace_entry["queries"].append(q_entry)
            continue

        items_count = len(data.get("items", []) or [])
        q_entry["items_returned"] = items_count
        if trace_entry is not None:
            trace_entry["queries"].append(q_entry)

        # Sprint D.31 : ranking par annee si target_year fourni. Cas Petit
        # Fute : 5 editions (2014, 2020, 2023, 2025, 2026), on veut celle
        # la plus proche de target_year. Sans ranking, on prenait la 1ere
        # retournee par Google qui n'est pas forcement la bonne.
        # Sprint D.37 : ranking par volume aussi (mangas), volume_score
        # domine year_distance car le bon tome est plus important que
        # l'annee.
        meta = _parse_best_item(data, target_year=target_year,
                                target_volume=target_volume)
        if meta is None:
            continue

        # Sprint D.31 : si pas de target_year, on retourne immediatement
        # (comportement legacy). Sinon, on calcule la distance et on
        # garde le meilleur GLOBAL, continuant les variantes suivantes
        # SI le best courant est encore loin (>5 ans).
        if not target_year:
            if trace_entry is not None:
                trace_entry["outcome"] = "matched_title"
                trace_entry["matched_id"] = meta.google_books_id or ""
                trace_entry["matched_title"] = meta.title
                trace_entry["matched_via_variant"] = variant.label
                trace_entry["candidates_count"] = items_count
            return meta

        # On a un target_year : ranking global
        year = meta.publication_year or 0
        distance = abs(year - target_year) if year else 100
        if distance < best_distance:
            best_so_far = meta
            best_distance = distance
            best_via_variant = variant.label

        # Si match parfait (distance <= 1 an), on s'arrete
        if distance <= 1:
            break
        # Sinon on continue aux autres variantes pour voir si on trouve mieux

    # Fin de boucle : si on a un best_so_far, on le retourne
    if best_so_far is not None:
        if trace_entry is not None:
            trace_entry["outcome"] = "matched_title"
            trace_entry["matched_id"] = best_so_far.google_books_id or ""
            trace_entry["matched_title"] = best_so_far.title
            trace_entry["matched_via_variant"] = best_via_variant
            trace_entry["matched_year"] = best_so_far.publication_year
            trace_entry["target_year"] = target_year
            trace_entry["best_year_distance"] = best_distance
        return best_so_far

    # Aucune variante n'a matché
    if trace_entry is not None and rate_limited:
        trace_entry["outcome"] = "rate_limited"
    return None


def _title_volume_match_score(title: str, target_vol: float) -> int:
    """Sprint D.37 : score de match volume dans un titre Google Books.

    Retourne :
        0 = match exact du volume (ex target=30, title contient "T30" ou "Tome 30")
        50 = mauvais volume detecte (target=30 mais title="40")
        100 = pas d'info volume dans title (neutre)

    Utilise par ranker pour PREFERER les candidats avec le bon volume.
    """
    if not target_vol or target_vol <= 0 or not title:
        return 100
    vol_int = int(target_vol) if target_vol == int(target_vol) else None
    if vol_int is None:
        return 100
    title_lower = title.lower()
    # Patterns d'expression du volume : T<n>, Tome <n>, Vol <n>, vol.<n>,
    # #<n>, "Volume <n>"
    patterns_ok = [
        rf"\bt0*{vol_int}\b",
        rf"\btome\s*0*{vol_int}\b",
        rf"\bvol(?:ume)?\.?\s*0*{vol_int}\b",
        rf"#0*{vol_int}\b",
        rf"\bchapitre\s*0*{vol_int}\b",
    ]
    for pat in patterns_ok:
        if re.search(pat, title_lower):
            return 0  # match exact
    # Si on trouve un AUTRE numero de volume dans le titre -> wrong volume
    other_vol_patterns = [
        r"\bt0*(\d+)\b",
        r"\btome\s*0*(\d+)\b",
        r"\bvol(?:ume)?\.?\s*0*(\d+)\b",
        r"#0*(\d+)\b",
        r"\bchapitre\s*0*(\d+)\b",
    ]
    for pat in other_vol_patterns:
        m = re.search(pat, title_lower)
        if m:
            other_vol = int(m.group(1))
            if other_vol != vol_int:
                return 50  # wrong volume signal
    return 100  # no info


def _title_suspect_penalty(title: str) -> int:
    """Sprint D.44 v0.5.0 (feedback Louis Space Brothers T33) : retourne
    une penalite si le title de la fiche Google Books est suspect :
    juste une annee ('2021'), un chapitre ('C1180'), un nombre seul.

    Penalite forte (200) pour qu'elle domine year + volume scores
    (qui font max ~100 + max ~50 = 150).

    Cas Louis : pour ISBN 9782811644796 (Pika Space Brothers T33),
    Google a 2 fiches :
    - ZXe9ygEACAAJ : title="2021" (suspect, fiche tronquee)
    - elEXEAAAQBAJ : title="Space Brothers T33" (meaningful)
    On veut preferer celle qui est meaningful.
    """
    if not title:
        return 200
    t = title.strip()
    # Year-only ('2021', '2024')
    if re.match(r"^(?:19|20)\d{2}$", t):
        return 200
    # Chapter-only ('C1180')
    if re.match(r"^C\s*\d{2,4}$", t, re.IGNORECASE):
        return 200
    # Number-only
    if re.match(r"^\d{1,5}$", t):
        return 200
    # Very short (< 3 chars)
    if len(t) < 3:
        return 100
    return 0


def _parse_best_item(data, target_year: int = 0,
                     target_volume: float = 0.0) -> BookMetadata | None:
    """Parse une reponse Google Books et choisit le meilleur item.

    Sprint D.31 : si target_year > 0, ranking par proximite d'annee.
    Sprint D.37 : si target_volume > 0, BOOST les candidats dont le titre
    contient le bon volume (penalise ceux avec un autre volume).
    Sprint D.44 : penalise les candidates au title suspect (year/number-only).
    """
    if not isinstance(data, dict):
        return None
    items = data.get("items") or []
    if not items:
        return None

    # Sprint D.44 : meme avec target_year=0 et target_volume=0, on prefere
    # filtrer les candidates au title suspect (cas Space Brothers).
    # Donc on score TOUJOURS si on a >= 2 items.
    if len(items) == 1:
        return _parse_first_item({"items": items[:1]})

    # Ranking compose : title_suspect_penalty (D.44) + volume_score + year_distance
    # Sprint D.37 : volume_score domine (multiplie x10).
    # Sprint D.44 : title_suspect_penalty domine encore plus (un title "2021"
    # est inutile meme si volume + year sont parfaits).
    scored: list[tuple[int, int, dict]] = []
    for item in items:
        info = item.get("volumeInfo") or {}
        date_str = str(info.get("publishedDate") or "")
        m = re.search(r"\b(1[89]|20)\d{2}\b", date_str)
        item_year = int(m.group()) if m else 0
        year_distance = (
            abs(item_year - target_year) if item_year and target_year else
            100 if target_year else 0
        )
        title = str(info.get("title") or "")
        vol_score = _title_volume_match_score(title, target_volume)
        title_suspect = _title_suspect_penalty(title)
        # Total : title_suspect + volume * 10 + year_distance
        total = title_suspect + vol_score * 10 + year_distance
        scored.append((total, vol_score, item))

    scored.sort(key=lambda x: x[0])
    best = scored[0]
    # Sprint D.37 : si meme le meilleur a volume_score = 50 (wrong volume),
    # et target_volume > 0, on considere que rien ne matche correctement.
    # Mieux vaut retourner None que de claim un mauvais tome.
    if target_volume > 0 and best[1] >= 50:
        # Wrong volume → ne pas retourner ce mauvais match
        return None
    return _parse_first_item({"items": [best[2]]})


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


# ============================================================
# Sprint D.40 v0.5.0 : URL Google Books → volumeId + lookup direct
# ============================================================

# Patterns d'URL Google Books supportes :
# - https://www.google.com/books/edition/<slug>/<volumeId>?hl=fr
# - https://www.google.ca/books/edition/Sorceleur_T3/4eeGAQAAQBAJ
# - https://books.google.com/books?id=<volumeId>
# - https://books.google.fr/books?id=4eeGAQAAQBAJ&hl=fr
# - https://play.google.com/store/books/details?id=<volumeId>
_GOOGLE_BOOKS_URL_PATTERNS = [
    # Format moderne /books/edition/<slug>/<volumeId>
    re.compile(
        r"google\.[a-z.]+/books/edition/[^/]+/([A-Za-z0-9_-]{10,16})",
        re.IGNORECASE,
    ),
    # Format legacy ?id=<volumeId>
    re.compile(
        r"(?:books|play)\.google\.[a-z.]+/(?:books|store/books/details)"
        r"[^?]*\?[^#]*\bid=([A-Za-z0-9_-]{10,16})",
        re.IGNORECASE,
    ),
]


def extract_volume_id_from_url(url: str) -> str:
    """Extrait le volumeId Google Books depuis une URL collee par l'user.

    Sprint D.40 v0.5.0 (feedback Louis) : l'user copie l'URL Google Books
    de la bonne fiche depuis son navigateur et la colle dans le champ
    "URL Google Books forcee". On en extrait l'ID interne (10-16 chars
    alphanum + underscores/tirets) pour bypasser la recherche par titre.

    Args:
        url : URL Google Books (modern /books/edition/... ou legacy ?id=...).

    Returns:
        Le volumeId string si extrait, sinon "".

    Exemples :
        >>> extract_volume_id_from_url(
        ...     "https://www.google.ca/books/edition/Sorceleur/4eeGAQAAQBAJ?hl=fr"
        ... )
        '4eeGAQAAQBAJ'
        >>> extract_volume_id_from_url(
        ...     "https://books.google.com/books?id=YPvVEQAAQBAJ&hl=fr"
        ... )
        'YPvVEQAAQBAJ'
        >>> extract_volume_id_from_url("invalid")
        ''
    """
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    for pattern in _GOOGLE_BOOKS_URL_PATTERNS:
        m = pattern.search(s)
        if m:
            return m.group(1).strip()
    # Tolerance : si l'user colle juste l'ID brut (10-16 chars alphanum)
    # sans URL autour, on accepte.
    if re.fullmatch(r"[A-Za-z0-9_-]{10,16}", s):
        return s
    return ""


def fetch_volume_by_id(
    volume_id: str,
    cache_file: Path | None = None,
    api_key: str = "",
    http_get=None,
) -> BookMetadata | None:
    """Lookup Google Books direct par volumeId.

    Sprint D.40 v0.5.0 : utilise l'endpoint Volume detail
    (GET /books/v1/volumes/<volumeId>) qui retourne UN SEUL item sans
    recherche. Plus precis et plus rapide que /volumes?q=...

    Args:
        volume_id : ID Google Books (ex: '4eeGAQAAQBAJ').
        cache_file : path du cache JSON (reutilise le cache global).
        api_key : optionnelle.
        http_get : injectable pour tests.

    Returns:
        BookMetadata complet ou None si l'ID est invalide / inaccessible.
    """
    if not volume_id:
        return None
    http_get = http_get or _default_http_get

    # Cache key : 'gbid:<volume_id>'
    cache = load_cache(cache_file) if cache_file else {}
    cache_k = f"gbid:{volume_id}"
    if cache_k in cache:
        cached = cache[cache_k]
        if is_miss(cached):
            return None
        try:
            return book_from_dict(cached)
        except Exception:
            pass

    url = f"{GOOGLE_BOOKS_URL}/{volume_id}"
    params = {}
    if api_key:
        params["key"] = api_key

    try:
        resp = http_get(url, params=params, timeout=15)
        if resp.status_code != 200:
            if cache_file:
                cache[cache_k] = make_miss()
                save_cache(cache_file, cache)
            return None
        data = resp.json()
    except Exception:
        return None

    # Reconstruit la shape /volumes (items=[...]) pour reutiliser le parser
    item_shape = {"items": [data]}
    meta = _parse_first_item(item_shape)
    if not meta:
        if cache_file:
            cache[cache_k] = make_miss()
            save_cache(cache_file, cache)
        return None

    if cache_file:
        cache[cache_k] = book_to_dict(meta)
        save_cache(cache_file, cache)
    return meta
