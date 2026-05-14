"""TMDB lookup avec cache disque atomique.

Le cache est stocké dans `data_dir/.tmdb_cache.json` et résiste aux écritures
concurrentes (workers du batch) grâce à un write+rename atomique.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .debug import Debug
from .http import http_get_with_retry
from .release_name import ascii_fold

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_DETAILS_URL = "https://api.themoviedb.org/3/movie/{movie_id}"
TMDB_TV_SEARCH_URL = "https://api.themoviedb.org/3/search/tv"
TMDB_TV_DETAILS_URL = "https://api.themoviedb.org/3/tv/{tv_id}"
TMDB_TV_SEASON_URL = "https://api.themoviedb.org/3/tv/{tv_id}/season/{season_num}"


def _cache_load(cache_file: Path) -> dict:
    if not cache_file.exists():
        return {}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"[WARN] Cache TMDB illisible ({type(e).__name__}: {e}), on repart de zero.")
        return {}


def _cache_save(cache_file: Path, cache: dict) -> None:
    tmp = cache_file.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, cache_file)
    except (OSError, TypeError, ValueError) as e:
        # OSError (FS plein, droits...), TypeError/ValueError (donnees non
        # serialisables). On log mais on bloque pas le pipeline pour autant.
        print(f"[WARN] Cache TMDB write failed ({type(e).__name__}): {e}")


# Lot post-NOTES round 4 : version du cache TMDB. Bumper quand le ranking
# algo change pour invalider les vieilles entries (Lot O.2 ranking, Lot O.6
# bonus FR origin, Lot O.8 titre international). Une entry sans `_cache_version`
# est consideree comme antique -> re-fetch automatique.
_TMDB_CACHE_VERSION = 2


def _cache_key(title: str, year: str | None, lang_hint: str | None = None) -> str:
    """Cache key. Si `lang_hint` fourni, on l'inclut pour eviter qu'un release
    FR-only et un release MULTi du meme titre/annee partagent le meme cache
    (avec le bonus origine FR Lot O.6, le resultat peut differer)."""
    base = f"{title.strip().lower()}|{year or ''}"
    if lang_hint:
        return f"{base}|{lang_hint}"
    return base


def _is_cache_entry_fresh(cached: dict) -> bool:
    """Verifie si une entry du cache est compatible avec le ranking actuel.
    Une entry sans `_cache_version` ou avec une version < courante est
    consideree obsolete -> on refetch pour beneficier du nouveau ranking."""
    if not isinstance(cached, dict):
        return False
    cached_version = cached.get("_cache_version")
    if cached_version is None or not isinstance(cached_version, int):
        return False
    return cached_version >= _TMDB_CACHE_VERSION


# Lot O.6 : tags du release_name qui indiquent une release exclusivement
# francaise (= pas un MULTi). Quand un de ces tags est present sans MULTi,
# on bonifie les candidats TMDB de production francophone.
_FRENCH_ONLY_TAGS: set[str] = {
    "VFF", "VFQ", "VFB", "VF2",
    "VOF", "VOQ", "VOB",
    "FRENCH", "TRUEFRENCH", "FR",
}

# Codes ISO 639-1 + noms de pays consideres comme "francophones natifs"
_FRENCH_LANG_CODES: set[str] = {"fr"}
_FRENCH_COUNTRIES: set[str] = {
    "France", "Canada", "Belgium", "Belgique", "Switzerland", "Suisse",
    "Luxembourg", "Monaco",
}


# Lot post-NOTES round 5 : stopwords filtres pour le calcul de pertinence
# titre. On garde les noms communs / propres / verbes ; on retire les
# articles, prepositions courantes EN/FR qui ne discriminent rien.
_TITLE_STOPWORDS: set[str] = {
    # FR
    "le", "la", "les", "l",
    "un", "une", "des", "d",
    "de", "du", "au", "aux",
    "et", "ou", "ni",
    "a", "en",
    # EN
    "the", "an", "of", "and", "or",
    "in", "on", "at", "to", "for",
}

# Lot post-NOTES round 5 : articles de tete qu'on peut retirer pour une
# variante de query (cas "L'Incroyable..." passe en "L Incroyable..." par
# notre splitter, et TMDB ne digere pas le "L" isole en debut de query).
_LEADING_ARTICLE_TOKENS: set[str] = {
    "l", "le", "la", "les", "un", "une", "des", "d",
    "the", "a", "an",
}


def _significant_tokens(title: str) -> set[str]:
    """Tokenise un titre pour calcul de pertinence : split alphanumerique,
    fold accents, retire stopwords + chiffres seuls + chaines vides, et
    *strip le 's' final* pour tolerer pluriel/typo FR ("Septs"="Sept",
    "Samouraïs"="Samourai").

    Retourne un set car on veut juste savoir QUI matche, pas l'ordre.
    """
    if not title:
        return set()
    folded = ascii_fold(title).lower()
    raw = re.split(r"[^a-z0-9]+", folded)
    out: set[str] = set()
    for tok in raw:
        if not tok or tok.isdigit():
            continue
        if tok in _TITLE_STOPWORDS:
            continue
        # Strip trailing 's' (FR plural / typo) si le mot fait au moins
        # 4 chars (preserve "us", "is", "as" et autres mots courts).
        if len(tok) >= 4 and tok.endswith("s"):
            tok = tok[:-1]
        out.add(tok)
    return out


def _title_relevance(query: str, candidate: dict, *, is_tv: bool = False) -> float:
    """Calcule un score de pertinence titre entre la query et le candidat
    TMDB. Retourne min(query_coverage, chosen_coverage) sur le BEST entre
    `title` et `original_title` (resp. `name` / `original_name` pour TV).

    - query_coverage = matched_tokens / |query_tokens|  (a quel point la
      query est dans le candidat)
    - chosen_coverage = matched_tokens / |chosen_tokens|  (a quel point
      le candidat est centre sur la query — empeche "Moon" de matcher
      "The Twilight Saga: New Moon")

    On prend `min` pour exiger les DEUX (un titre 5x plus long que la
    query rate chosen_coverage meme si la query est entierement contenue).

    Retourne 0..1. 1.0 = tokens identiques apres normalisation.
    Si query_tokens est vide, retourne 1.0 (pas de signal pour juger).
    """
    q = _significant_tokens(query)
    if not q:
        return 1.0
    fld_pair = ("name", "original_name") if is_tv else ("title", "original_title")
    best = 0.0
    for fld in fld_pair:
        c = _significant_tokens(candidate.get(fld) or "")
        if not c:
            continue
        inter = q & c
        if not inter:
            continue
        query_cov = len(inter) / len(q)
        chosen_cov = len(inter) / len(c)
        score = min(query_cov, chosen_cov)
        if score > best:
            best = score
    return best


# Seuil de pertinence titre quand title_score=0 (titre TMDB ne contient
# pas la query en exact/prefix). Au-dessous, on rejette meme si year matche.
_TITLE_RELEVANCE_MIN_WHEN_NO_TITLE_SCORE: float = 0.5


def _year_match_score(year_query: str | None, release_date: str | None) -> int:
    """Variante module-level du _year_score utilisable hors closure.
    Memes tolerances (+/- 0, 1, 2 ans) pour invalider un cache hit."""
    if not year_query or not year_query.isdigit():
        return 0
    ry_str = str(release_date or "")[:4]
    if not ry_str.isdigit():
        return 0
    diff = abs(int(ry_str) - int(year_query))
    if diff == 0:
        return 5000
    if diff == 1:
        return 2500
    if diff == 2:
        return 500
    return 0


def _title_exact_score(query: str, candidate: dict, *, is_tv: bool = False) -> int:
    """Variante module-level du _title_score. NOTES round 6 : 0/500/3000."""
    title_norm = (query or "").strip().lower()
    if not title_norm:
        return 0
    if is_tv:
        t = (candidate.get("name") or "").strip().lower()
        ot = (candidate.get("original_name") or "").strip().lower()
    else:
        t = (candidate.get("title") or "").strip().lower()
        ot = (candidate.get("original_title") or "").strip().lower()
    if t == title_norm or ot == title_norm:
        return 3000
    if (t and t.startswith(title_norm)) or (ot and ot.startswith(title_norm)):
        return 500
    return 0


def _cache_entry_passes_relevance(
    query_title: str,
    query_year: str | None,
    candidate: dict,
    release_year: str,
    *,
    is_tv: bool = False,
) -> bool:
    """Verifie qu'un hit cache n'est pas un faux positif. Retourne False
    si on doit l'invalider et refetcher.

    Memes regles que pour un fresh match (cf. _passes_relevance_gate) :
    - rejet si year_score=0 ET title_score=0 (ancienne regle)
    - rejet si title_score=0 ET relevance < 0.5 (renforce Lot post-round 5)
    """
    ys = _year_match_score(query_year, release_year or candidate.get("release_date"))
    ts = _title_exact_score(query_title, candidate, is_tv=is_tv)
    if ys == 0 and ts == 0:
        return False
    if ts == 0:
        rel = _title_relevance(query_title, candidate, is_tv=is_tv)
        if rel < _TITLE_RELEVANCE_MIN_WHEN_NO_TITLE_SCORE:
            return False
    return True


def _detect_french_only_hint(lang_tokens: list[str]) -> str | None:
    """Retourne 'fr' si la liste lang du release contient un tag FR exclusif
    sans MULTi. Sinon None.

    Cas reel (Lot O.6) : "La.Maison.2022.FRENCH.1080p.BluRay-ZiT" -> 'fr',
    car FRENCH/VFF est present sans MULTi. Le release est probablement un
    film francophone natif (ou dub-only) et on devrait bonifier les
    candidats TMDB FR.

    "Furiosa.2024.MULTi.VFF...x265-Elcrackito" -> None : MULTi present,
    le release est multi-langue, le bonus FR n'a pas de sens (le film
    est probablement un blockbuster international).
    """
    if not lang_tokens:
        return None
    upper_tokens = []
    for t in lang_tokens:
        upper_tokens.extend(s.strip().upper() for s in str(t).split("."))
    has_multi = "MULTI" in upper_tokens or "MULTi".upper() in upper_tokens
    if has_multi:
        return None
    if any(t in _FRENCH_ONLY_TAGS for t in upper_tokens):
        return "fr"
    return None


def _extract_trailer_key(details: dict) -> str:
    """Retourne la cle YouTube du meilleur trailer dispo, ou chaine vide.

    Priorite : Trailer official YouTube > Trailer YouTube > 1er video YouTube.
    """
    videos = ((details.get("videos") or {}).get("results")) or []
    youtube = [v for v in videos if v.get("site") == "YouTube"]
    if not youtube:
        return ""
    trailers = [v for v in youtube if (v.get("type") or "").lower() == "trailer"]
    pool = trailers if trailers else youtube
    official = next((v for v in pool if v.get("official")), None)
    if official:
        return official.get("key", "") or ""
    return pool[0].get("key", "") if pool else ""


def _build_minimal_tmdb_context_from_search(
    chosen: dict, media_id: int, is_tv: bool = False,
) -> dict:
    """Lot O.7 : construit un tmdb_context minimal a partir d'un resultat
    de search TMDB quand le fetch /movie/{id} a echoue (502/503 transient).

    On a au moins :
    - id, title, original_title, release_date / first_air_date
    - original_language, popularity, vote_count, vote_average
    - poster_path, overview (parfois present dans search)

    On n'a PAS : cast, director, writers, runtime, genres, imdb_id, tvdb_id,
    keywords, trailer. La fiche BBCode sera incomplete (pas de poster avec
    casting) mais le release_name peut quand meme etre construit avec le
    bon titre, et le tracker recevra le bon TMDB ID.
    """
    if is_tv:
        return {
            "tv_id": media_id,
            "title": str(chosen.get("name", "") or "").strip(),
            "original_title": str(chosen.get("original_name", "") or "").strip(),
            "original_language": str(chosen.get("original_language", "") or "").strip().lower(),
            "release_date": str(chosen.get("first_air_date", "") or "").strip(),
            "overview": str(chosen.get("overview", "") or "").strip(),
            "runtime": None,
            "tmdb_rating": chosen.get("vote_average"),
            "tmdb_vote_count": chosen.get("vote_count"),
            "genres": [],
            "production_countries": [],
            "director": "",
            "writers": [],
            "cast": [],
            "imdb_id": "",
            "imdb_rating": "",
            "tmdb_poster_path": (chosen.get("poster_path") or "").strip(),
            "trailer_yt_key": "",
            "title_en": "",
            "tvdb_id": 0,
            "keywords": [],
            "_minimal_context": True,  # marqueur : details indisponibles
        }
    return {
        "movie_id": media_id,
        "title": str(chosen.get("title", "") or "").strip(),
        "original_title": str(chosen.get("original_title", "") or "").strip(),
        "original_language": str(chosen.get("original_language", "") or "").strip().lower(),
        "release_date": str(chosen.get("release_date", "") or "").strip(),
        "overview": str(chosen.get("overview", "") or "").strip(),
        "runtime": None,
        "tmdb_rating": chosen.get("vote_average"),
        "tmdb_vote_count": chosen.get("vote_count"),
        "genres": [],
        "production_countries": [],
        "director": "",
        "writers": [],
        "cast": [],
        "imdb_id": "",
        "imdb_rating": "",
        "tmdb_poster_path": (chosen.get("poster_path") or "").strip(),
        "trailer_yt_key": "",
        "title_en": "",
        "tvdb_id": 0,
        "keywords": [],
        "_minimal_context": True,
    }


def _build_tmdb_context(details: dict, movie_id: int) -> dict:
    credits = details.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []

    directors = [
        x.get("name", "").strip()
        for x in crew
        if x.get("job") == "Director" and x.get("name")
    ]
    writers = [
        x.get("name", "").strip()
        for x in crew
        if x.get("job") in {"Writer", "Screenplay"} and x.get("name")
    ]

    top_cast = [
        {
            "name": (a.get("name") or "").strip(),
            "character": (a.get("character") or "").strip(),
            "profile_path": (a.get("profile_path") or "").strip(),
        }
        for a in cast[:5]
        if (a.get("name") or "").strip()
    ]

    genres = [
        g.get("name", "").strip()
        for g in (details.get("genres") or [])
        if g.get("name")
    ]
    countries = [
        c.get("name", "").strip()
        for c in (details.get("production_countries") or [])
        if c.get("name")
    ]
    external_ids = details.get("external_ids") or {}

    # Lot Q : keywords TMDB pour le champ "Mots-cles" Gemini.
    # TMDB retourne `keywords.keywords[]` pour les films, `keywords.results[]`
    # pour les series. On garde max 8 keywords.
    keywords_block = details.get("keywords") or {}
    raw_kws = keywords_block.get("keywords") or keywords_block.get("results") or []
    keywords = [
        (kw.get("name") or "").strip()
        for kw in raw_kws[:8]
        if (kw.get("name") or "").strip()
    ]

    return {
        "movie_id": movie_id,
        "title": str(details.get("title", "") or "").strip(),
        "original_title": str(details.get("original_title", "") or "").strip(),
        "original_language": str(details.get("original_language", "") or "").strip().lower(),
        "release_date": str(details.get("release_date", "") or "").strip(),
        "overview": str(details.get("overview", "") or "").strip(),
        "runtime": details.get("runtime"),
        "tmdb_rating": details.get("vote_average"),
        "tmdb_vote_count": details.get("vote_count"),
        "genres": genres,
        "production_countries": countries,
        "director": directors[0] if directors else "",
        "writers": writers[:3],
        "cast": top_cast,
        "imdb_id": (external_ids.get("imdb_id") or "").strip(),
        "imdb_rating": "",
        "tmdb_poster_path": (details.get("poster_path") or "").strip(),
        "trailer_yt_key": _extract_trailer_key(details),
        "title_en": "",
        # Lot Q : IDs externes supplementaires (TVDB pour series, mais on
        # tente aussi pour les films au cas ou). MAL non fetchable depuis
        # TMDB de maniere fiable (l'user override manuellement pour anime).
        "tvdb_id": int(external_ids.get("tvdb_id") or 0) or 0,
        "keywords": keywords,
    }


# Langues d'origine non-latines : pour ces films, on prefere le titre
# international (title_en) car l'original_title est en CJK/cyrillique/arabe
# et perd toute son information apres ascii_fold. Convention scene FR/Gemini :
# "Godzilla.Minus.One" au lieu de "ゴジラ-1.0", "Parasite" au lieu de "기생충".
NON_LATIN_LANGUAGES = {
    "ja", "ko", "zh", "ru", "ar", "hi", "th", "vi", "he", "fa",
    "uk", "bg", "el", "sr", "mk", "yi", "ka", "hy", "am",
}


def _title_parts_from_tmdb(
    tmdb_context: dict, fallback_parts: list[str], debug: Debug | None = None,
) -> list[str]:
    """Reconstruit les parts du titre a partir des titres TMDB.

    Cela permet d'avoir une casse propre quel que soit la casse du fichier
    source : 'delicieux.2021...' -> 'Delicieux.2021...', 'the.matrix' ->
    'The.Matrix'. On retombe sur fallback_parts uniquement si TMDB n'a
    pas de titre.

    On ascii_fold systematiquement (meme pour les films FR) pour respecter
    la convention scene : pas d'accents, juste de l'ASCII.
    'Delicieux' au lieu de 'Délicieux'.

    Lot O.8 : pour les films d'origine non-latine (ja/ko/zh/ru/ar/...), on
    INVERSE l'ordre : title_en (international) prime sur original_title.
    Avant ce fix, "Godzilla Minus One" (ja, original "ゴジラ-1.0") devenait
    "1.0" parce que ascii_fold sur "ゴジラ-1.0" laissait "-1.0" qui survivait
    a notre validation. Maintenant on prend directement title_en="Godzilla
    Minus One" pour ces films.

    Si `debug` est fourni, emet les signaux de fallback :
    - SIG_TMDB_TITLE_EN_FALLBACK : original_title non utilisable (CJK/
      cyrillique/etc.), on utilise title_en. Comportement attendu pour ces
      films, signal soft.
    - SIG_TMDB_TITLE_FR_FALLBACK : ni original ni title_en utilisable, on
      retombe sur le titre FR (cas degrade : pas d'info anglaise dispo).
    """
    from . import naming_signals as ns

    original_title = tmdb_context.get("original_title") or ""
    title_en = tmdb_context.get("title_en") or ""
    title_fr = tmdb_context.get("title") or ""
    original_lang = (
        (tmdb_context.get("original_language") or "").strip().lower()
    )
    is_non_latin = original_lang in NON_LATIN_LANGUAGES

    # Lot O.8 : pour les films non-latins, title_en (international) prime
    # sur original_title (CJK/cyrillique inutilisable apres ascii_fold).
    if is_non_latin and title_en:
        candidates = [
            ("title_en", title_en),
            ("title_fr", title_fr),
            ("original", original_title),
        ]
    else:
        candidates = [
            ("original", original_title),
            ("title_en", title_en),
            ("title_fr", title_fr),
        ]
    for source, candidate in candidates:
        if not candidate:
            continue
        folded = ascii_fold(candidate)
        for ch in "'’‘`":
            folded = folded.replace(ch, "")
        cleaned = re.sub(r"[^A-Za-z0-9\s-]+", " ", folded)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            new_parts = [p for p in re.split(r"[\s\-]+", cleaned) if p]
            if new_parts:
                # Signaler le fallback si on n'est pas reste sur l'original
                if debug is not None:
                    if source == "title_en":
                        ns.emit_signal(debug, ns.SIG_TMDB_TITLE_EN_FALLBACK, True)
                    elif source == "title_fr" and not title_en:
                        # Vraie fallback FR (pas par choix mais par defaut
                        # : ni original ni title_en exploitable)
                        ns.emit_signal(debug, ns.SIG_TMDB_TITLE_FR_FALLBACK, True)
                return new_parts
    return fallback_parts


def _maybe_fetch_title_en(tmdb_context: dict, api_key: str, is_tv: bool) -> None:
    """Si le film/serie est d'origine non-latine (ja/ko/zh/ru/ar/hi/...),
    fetch le titre EN et le stocke dans tmdb_context["title_en"]. Permet
    aux resolvers d'utiliser le titre international au lieu du original_title
    en non-latin (qui devient vide apres ascii_fold).

    Echec non-bloquant si l'API ne repond pas (le pipeline tombera sur le
    fallback `_title_parts_from_tmdb` qui essaie original > title_en > title_fr).
    On log dans tmdb_context["_title_en_error"] pour traçabilite (visible
    dans debug.json).
    """
    if not api_key:
        return
    lang = (tmdb_context.get("original_language", "") or "").lower()
    # Lot O.8 : utilise NON_LATIN_LANGUAGES module-level (meme set utilise
    # par _title_parts_from_tmdb pour le re-ordonnement des candidats).
    if lang not in NON_LATIN_LANGUAGES:
        return
    media_id = tmdb_context.get("movie_id") or tmdb_context.get("tv_id") or 0
    if not media_id:
        return
    url = (TMDB_TV_DETAILS_URL if is_tv else TMDB_DETAILS_URL).format(
        **({"tv_id": media_id} if is_tv else {"movie_id": media_id})
    )
    try:
        resp = http_get_with_retry(
            url, params={"api_key": api_key, "language": "en-US"},
        )
        data = resp.json()
        tmdb_context["title_en"] = (data.get("title") or data.get("name") or "").strip()
    except Exception as e:
        tmdb_context["_title_en_error"] = f"{type(e).__name__}: {e}"


def make_tmdb_resolver(api_key: str, cache_file: Path):
    """Retourne une fonction `resolver(title_parts, year, debug)` capturant
    la clé API et le path du cache. Fait pour être passé à `build_release_name`.
    """

    def resolve(
        title_parts: list[str], year: str | None, debug: Debug,
        release_lang_hint: str | None = None,
    ) -> tuple[list[str], dict | None]:
        """Resolver TMDB film.

        Args:
            release_lang_hint : Lot O.6 — si "fr" (release tagge FR-only sans
                MULTi), on bonifie les candidats avec original_language=fr ou
                production_countries francophones. Permet de departager
                "La Maison" UK animation (en) vs "La Maison" QC (fr) quand
                le year+title sont identiques.
        """
        if not title_parts:
            return title_parts, None

        if not api_key:
            debug.set("tmdb_skipped_reason", "TMDB_API_KEY absent")
            return title_parts, None

        source_title = " ".join(title_parts).strip()
        if not source_title:
            return title_parts, None

        from . import naming_signals as ns

        # Cache lookup
        cache = _cache_load(cache_file)
        key = _cache_key(source_title, year, release_lang_hint)
        cached = cache.get(key)
        if cached and _is_cache_entry_fresh(cached):
            # Lot post-NOTES round 5 : verifie aussi la pertinence du cache
            # hit. Si une vieille recherche a stocke un mauvais match avant
            # la mise en place du seuil de pertinence (cas reel : Sept
            # Samouraïs -> Red Shoes, Moon 2009 -> Twilight New Moon), on
            # invalide silencieusement et on relance la recherche.
            cache_year = str(cached.get("release_date") or "")[:4]
            cache_release = {
                "title": cached.get("title"),
                "original_title": cached.get("original_title"),
                "release_date": cached.get("release_date"),
            }
            if _cache_entry_passes_relevance(
                source_title, year, cache_release, cache_year,
            ):
                debug.set("tmdb_cache_hit", key)
                # Re-emettre les signaux stockes dans le cache (le score de
                # confiance est recalcule a chaque ouverture du package)
                cached_signals = cached.get("naming_signals_at_resolve") or {}
                for sig_key, sig_value in cached_signals.items():
                    ns.emit_signal(debug, sig_key, sig_value)
                return _title_parts_from_tmdb(cached, title_parts, debug), cached
            # Cache pollue par un mauvais match : on continue vers le refetch
            debug.set("tmdb_cache_invalidated_low_relevance", {
                "key": key,
                "cached_id": cached.get("movie_id"),
                "cached_title": cached.get("title"),
            })
            print(
                f"[INFO] TMDB cache hit '{key}' rejete (mauvais match cache : "
                f"id={cached.get('movie_id')} '{cached.get('title')}'). Refetch."
            )
        elif cached:
            # Cache obsolete (Lot post-NOTES round 4) : on l'ignore et on
            # refetch pour beneficier du nouveau ranking. Log pour traçabilite.
            debug.set("tmdb_cache_invalidated", key)
            print(f"[INFO] TMDB cache obsolete pour {key} : refetch (ranking a evolue).")

        # === Lot O.2 + O.3 + O.4 : strategie de recherche refondue ===
        #
        # Anciennement : on stoppait au 1er resultat trouve (en-US prioritaire),
        # ce qui faisait gagner des homonymes peu populaires (court-metrage
        # "Dragonslayer Doppelganger" gagnait "Dragons" alors que le vrai
        # film "How to Train Your Dragon" - titre FR "Dragons" - n'avait
        # jamais ete teste en fr-FR).
        #
        # Maintenant :
        #  1. On cumule les resultats de en-US ET fr-FR (sans year-filter).
        #  2. On retente le titre raccourci si rien (1-2 mots droppes max).
        #  3. Si toujours rien : on retente avec les `.` remplaces par espaces
        #     (cas Furiosa : "Furiosa une Saga Mad Max" perd "Max" via les
        #     drop_tokens, query "Mad" trop generique. Si on garde le base
        #     bouillonnant et on remplace . par space, ca a meme effet sans
        #     perdre les mots ambigus).
        #  4. Le ranking final integre une tolerance d'annee +- 1 (Louis
        #     observe que I.Am.Love sort 2009 ou 2010 selon pays).
        all_results: list[dict] = []
        seen_ids: set[int] = set()
        attempted_title = source_title
        winning_words_dropped = 0
        words = source_title.split()

        def _do_search(query: str, language: str) -> list[dict]:
            """Une seule requete TMDB, sans year-filter (on rank en post)."""
            params = {
                "api_key": api_key,
                "query": query,
                "include_adult": "false",
                "language": language,
            }
            try:
                resp = http_get_with_retry(TMDB_SEARCH_URL, params=params)
                return resp.json().get("results", []) or []
            except Exception as e:
                debug.set("tmdb_search_error", f"{e}")
                return []

        def _accumulate(new: list[dict], language: str, n_drop: int) -> int:
            """Ajoute new dans all_results en dedupliquant par id.

            Tag chaque resultat avec sa langue source + n_drop pour permettre
            au signal SIG_TMDB_LANG_FALLBACK d'etre emis SEULEMENT si le
            resultat finalement choisi vient d'une recherche fr-FR (pas
            disponible en-US). Voir post-ranking ci-dessous.
            """
            added = 0
            for r in new:
                rid = r.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    r["_lang_source"] = language
                    r["_n_drop_source"] = n_drop
                    all_results.append(r)
                    added += 1
            return added

        # Phase 1a : titre complet en en-US + fr-FR (cumul des deux)
        attempts: list[tuple[str, str, int]] = [
            (source_title, "en-US", 0),
            (source_title, "fr-FR", 0),
        ]
        # Phase 1b (Lot post-NOTES round 5) : titre SANS article de tete.
        # Quand notre splitter remplace "L'" / "D'" par espaces, on se
        # retrouve avec "L Incroyable Histoire Du Facteur Cheval" qui rate
        # TMDB (le "L" isole est confondant). Tenter la version sans le
        # premier mot s'il fait partie des articles courants. n_drop=0 pour
        # beneficier de l'early-break si elle ramene >= 5 resultats.
        if (
            len(words) >= 4
            and words[0].lower() in _LEADING_ARTICLE_TOKENS
        ):
            without_lead = " ".join(words[1:])
            attempts.append((without_lead, "en-US", 0))
            attempts.append((without_lead, "fr-FR", 0))
        # Phase 1c (NOTES round 6) : titre SANS aucun stopword (et/la/du/
        # de/des/a/le/the/of/on/in/at/...). Cas reels :
        # - "Harry Potter Et La Chambre Des Secrets" -> "Harry Potter
        #   Chambre Secrets" : TMDB matche Chamber of Secrets cleanly au
        #   lieu de matcher Philosopher's Stone par year tolerance.
        # - "The Last Man On Earth" -> "Last Man Earth" : meme effet.
        # On ne le fait QUE si ca change le query (>=1 stopword) ET si
        # >=2 mots significatifs restent (sinon trop generique).
        sig_words = [w for w in words if w.lower() not in _TITLE_STOPWORDS]
        if 2 <= len(sig_words) < len(words):
            sig_query = " ".join(sig_words)
            # Ne pas dupliquer si identique a une variante deja en attempts
            existing_queries = {q for q, _, _ in attempts}
            if sig_query not in existing_queries:
                attempts.append((sig_query, "en-US", 0))
                attempts.append((sig_query, "fr-FR", 0))
        # Phase 2 : raccourcir la fin si toujours pas assez de candidats
        for n_drop in range(1, len(words)):
            shortened_words = words[: len(words) - n_drop]
            sig = [w for w in shortened_words if len(w) >= 3]
            if len(sig) < 2:
                break
            shortened = " ".join(shortened_words)
            attempts.append((shortened, "fr-FR", n_drop))
            attempts.append((shortened, "en-US", n_drop))

        for query, language, n_drop in attempts:
            new = _do_search(query, language)
            added = _accumulate(new, language, n_drop)
            if added and attempted_title == source_title:
                attempted_title = query

            # Optimisation : si la requete complete a deja ramene au moins
            # 5 candidats, inutile de raccourcir. Si elle est vide, on continue.
            if n_drop == 0 and len(all_results) >= 5:
                # On a tente en-US et fr-FR full title — on s'arrete sauf si
                # 0 candidat (continue avec shortened).
                if language == "fr-FR":
                    break

        # Phase 2 : si toujours rien, retry "espaces seulement" (cas Furiosa
        # ou un mot du titre a ete drop par les rules.drop_tokens).
        if not all_results:
            # On reconstruit une query a partir du base brut (sans nettoyage).
            # Faute du base original ici, on tente le source_title avec . -> ' '
            # (deja le cas en theorie, mais defensif). Plus simplement : on
            # inverse l'ordre des mots significatifs au cas ou le titre TMDB
            # contient des mots qu'on a raccourcis. Pas de magic — on logge
            # juste l'echec definitif.
            debug.set("tmdb_search_no_results",
                      {"title": source_title, "year": year})
            return title_parts, None

        results = all_results
        debug.set("tmdb_search_attempted", attempted_title)
        debug.set("tmdb_search_pool_size", len(results))
        # Note : SIG_TMDB_LANG_FALLBACK et SIG_TMDB_QUERY_SHORTENED sont
        # maintenant emis APRES le ranking, en se basant sur la source du
        # resultat CHOISI (pas sur le simple fait que la recherche fr-FR ait
        # ajoute des doublons au pool). Cf. apres `chosen = max(...)`.

        # === Ranking : year tolerance + popularity + match exact ===
        title_norm = source_title.strip().lower()
        year_int = int(year) if year and year.isdigit() else None

        def _year_score(r) -> int:
            """Bonus selon proximite annee. Tolerance Lot O.4 : +/- 1 an
            score legerement plus bas, +/- 2 ans encore moins. Au-dela : 0."""
            if year_int is None:
                return 0
            ry_str = str(r.get("release_date", ""))[:4]
            if not ry_str.isdigit():
                return 0
            ry = int(ry_str)
            diff = abs(ry - year_int)
            if diff == 0:
                return 5000
            if diff == 1:
                return 2500
            if diff == 2:
                return 500
            return 0

        def _title_score(r) -> int:
            # NOTES round 6 : boost title_score exact 1000 -> 3000 pour qu'il
            # domine la popularite (max ~2200 = 200 pop + 2000 vote_bonus).
            # Cas reel : "The Last Man on Earth" (vote_count=800, exact title
            # match) doit gagner contre "The Last of Us" (vote_count=12000+,
            # title_score=0). Avant : 1000 (Last Man) vs 2200 (Last of Us) -> Us
            # gagnait. Maintenant : 3000 vs 2200 -> Last Man gagne.
            t = (r.get("title") or "").strip().lower()
            ot = (r.get("original_title") or "").strip().lower()
            if t == title_norm or ot == title_norm:
                return 3000
            if t.startswith(title_norm) or ot.startswith(title_norm):
                return 500
            return 0

        def _origin_score(r) -> int:
            """Lot O.6 : bonus si release tagué FR-only et candidat de
            production francophone. Permet de privilegier "La Maison" QC
            (original_language=fr) face a "La Maison" UK animation
            (original_language=en) quand year+title sont egaux."""
            if release_lang_hint != "fr":
                return 0
            orig_lang = (r.get("original_language") or "").lower()
            # Bonus 2000 : superieur au vote_count * 0.5 d'un blockbuster
            # (~5000 votes = 2500 pts) dans la majorite des cas. Suffit
            # pour departager 2 homonymes year+title exacts sans ecraser
            # la priorite year (5000) ni title exact (1000).
            if orig_lang in _FRENCH_LANG_CODES:
                return 2000
            return 0

        def _final_score(r) -> float:
            pop = float(r.get("popularity") or 0)
            votes = float(r.get("vote_count") or 0)
            # Le vote_count est un meilleur signal de "vrai film populaire"
            # que la popularity (qui peut etre boostee par des releases
            # recentes ou trending). On le PLAFONNE a 2000 pour qu'un
            # blockbuster (>= 4000 votes) ne ecrase pas title_score=1000.
            # Cas reel : "Moon" (5000 votes) doit gagner contre "The Twilight
            # Saga: New Moon" (10000 votes) parce que title_score(Moon)=1000
            # et title_score(Twilight)=0. Sans cap, votes*0.5=5000 vs 2500
            # ferait gagner Twilight malgre l'absence de match titre.
            vote_bonus = min(votes * 0.5, 2000.0)
            return (
                _year_score(r) + _title_score(r) + _origin_score(r)
                + pop + vote_bonus
            )

        chosen = max(results, key=_final_score)
        movie_id = chosen.get("id")
        if not movie_id:
            return title_parts, None

        # Lot post-NOTES round 4 + round 5 : SEUIL MINIMUM DE PERTINENCE.
        # Si le candidat choisi a year_score=0 ET title_score=0, c'est qu'on
        # n'a aucun signal solide qui lie ce film au release source — juste
        # de la popularity brute. Le pool peut avoir UN SEUL resultat
        # accidentel (cas reel : "Les Septs Samourai" -> "Red Shoes 2019"
        # parce que la query mal orthographiee a ramene 1 resultat sans
        # rapport). Dans ce cas on retourne None plutot que d'imposer un
        # mauvais match.
        #
        # Round 5 : on renforce. Year_score>0 SEUL ne suffit plus si le
        # titre choisi n'a pas non plus de chevauchement minimal de tokens
        # avec la query. Cas reel : "Moon" (2009) -> "The Twilight Saga:
        # New Moon" (2009). year=5000 mais le mot "Moon" est noye dans un
        # titre 4x plus long, le film n'a rien a voir.
        chosen_ys = _year_score(chosen)
        chosen_ts = _title_score(chosen)
        chosen_tr = _title_relevance(source_title, chosen)
        if chosen_ys == 0 and chosen_ts == 0:
            debug.set(
                "tmdb_match_rejected_low_relevance",
                {
                    "id": movie_id,
                    "title": chosen.get("title"),
                    "release_date": chosen.get("release_date"),
                    "reason": "year_score=0 et title_score=0, match trop faible",
                },
            )
            print(
                f"[INFO] TMDB candidat {movie_id} '{chosen.get('title')}' "
                "rejete : aucun signal de pertinence (ni annee ni titre). "
                "Pas de match retourne."
            )
            return title_parts, None
        if chosen_ts == 0 and chosen_tr < _TITLE_RELEVANCE_MIN_WHEN_NO_TITLE_SCORE:
            debug.set(
                "tmdb_match_rejected_low_title_relevance",
                {
                    "id": movie_id,
                    "title": chosen.get("title"),
                    "release_date": chosen.get("release_date"),
                    "year_score": chosen_ys,
                    "title_relevance": round(chosen_tr, 3),
                    "reason": (
                        "title_score=0 et relevance < "
                        f"{_TITLE_RELEVANCE_MIN_WHEN_NO_TITLE_SCORE} : "
                        "year match seul, mais titre TMDB sans rapport "
                        "avec la query"
                    ),
                },
            )
            print(
                f"[INFO] TMDB candidat {movie_id} '{chosen.get('title')}' "
                f"rejete : year matche mais titre trop different de "
                f"'{source_title}' (relevance={chosen_tr:.2f}). Pas de match."
            )
            return title_parts, None

        # Lot O.2 fix : on emet les signaux SIG_TMDB_LANG_FALLBACK et
        # SIG_TMDB_QUERY_SHORTENED en se basant sur la SOURCE du resultat
        # choisi (pas sur le simple fait qu'une recherche secondaire ait
        # ajoute des doublons au pool). On regarde si l'ID choisi est
        # disponible aussi via une recherche en-US n_drop=0 ; sinon on
        # signale le fallback approprie.
        chosen_lang = chosen.get("_lang_source", "en-US")
        chosen_n_drop = int(chosen.get("_n_drop_source", 0))
        # Verifie si une recherche en-US n_drop=0 aurait ramene ce meme ID :
        # on regarde dans tous les resultats si un autre dict avec le meme
        # ID a ete ajoute via en-US. (En pratique, le seen_ids dedup empeche
        # cela — donc on regarde juste le tag du chosen lui-meme.)
        # Le signal est emis si le resultat choisi vient :
        # - d'une recherche fr-FR (donc en-US n'a pas trouve cet ID)
        if chosen_lang != "en-US":
            ns.emit_signal(debug, ns.SIG_TMDB_LANG_FALLBACK, True)
        if chosen_n_drop > 0:
            ns.emit_signal(
                debug, ns.SIG_TMDB_QUERY_SHORTENED, chosen_n_drop,
            )

        debug.set("tmdb_search_chosen", {
            "id": movie_id,
            "title": chosen.get("title"),
            "release_date": chosen.get("release_date"),
            "popularity": chosen.get("popularity"),
            "vote_count": chosen.get("vote_count"),
            "lang_source": chosen_lang,
            "n_drop_source": chosen_n_drop,
            "score_components": {
                "year_score": _year_score(chosen),
                "title_score": _title_score(chosen),
                "origin_score": _origin_score(chosen),
                "popularity": chosen.get("popularity"),
                "vote_count": chosen.get("vote_count"),
            },
            "release_lang_hint": release_lang_hint,
        })

        # Details
        details_params = {
            "api_key": api_key,
            "language": "fr-FR",
            "append_to_response": "credits,external_ids,release_dates,videos,keywords",
        }
        try:
            details_resp = http_get_with_retry(
                TMDB_DETAILS_URL.format(movie_id=movie_id),
                params=details_params,
            )
            details = details_resp.json()
        except Exception as e:
            # Lot O.7 : fallback sur le resultat de search quand /movie/{id}
            # echoue (502/503 transient TMDB). On a deja l'ID + title +
            # original_title + release_date + popularity dans `chosen`. On
            # construit une fiche minimale au lieu de tout perdre.
            debug.set("tmdb_details_error", f"{e}")
            ns.emit_signal(debug, ns.SIG_TMDB_DETAILS_FAILED, True)
            tmdb_context = _build_minimal_tmdb_context_from_search(
                chosen, movie_id, is_tv=False,
            )
            tmdb_context["naming_signals_at_resolve"] = dict(
                debug.data.get("naming_signals") or {}
            )
            # On ne cache PAS le contexte minimal : si TMDB se retablit, on
            # veut que la prochaine tentative refetch les details complets.
            debug.set("tmdb_context", tmdb_context)
            print(
                f"[WARN] TMDB /movie/{movie_id} indisponible — fiche "
                "minimale construite a partir des resultats de search "
                "(pas de cast/synopsis/imdb)."
            )
            return _title_parts_from_tmdb(tmdb_context, title_parts, debug), tmdb_context

        tmdb_context = _build_tmdb_context(details, movie_id)
        _maybe_fetch_title_en(tmdb_context, api_key, is_tv=False)
        # Snapshot des signaux deja emis pendant la recherche pour les
        # rejouer lors d'un futur cache hit (sinon le score perdrait l'info).
        tmdb_context["naming_signals_at_resolve"] = dict(
            debug.data.get("naming_signals") or {}
        )
        # Lot post-round 4 : versionne le cache pour invalidation automatique
        # quand le ranking algo change. _TMDB_CACHE_VERSION est bumpe a chaque
        # evolution du ranking.
        tmdb_context["_cache_version"] = _TMDB_CACHE_VERSION
        cache[key] = tmdb_context
        _cache_save(cache_file, cache)
        debug.set("tmdb_cache_write", key)
        debug.set("tmdb_context", tmdb_context)
        return _title_parts_from_tmdb(tmdb_context, title_parts, debug), tmdb_context

    return resolve


# ============================================================
# TMDB TV (series, saisons, integrales)
# ============================================================

def make_tmdb_forced_id_resolver(api_key: str, cache_file: Path, forced_id: int):
    """Resolver TMDB qui ignore le titre passe et fait un lookup DIRECT
    sur l'ID fourni. Utile pour overrider une recherche par titre qui se trompe.

    Retourne la meme signature que make_tmdb_resolver : (title_parts, ctx).
    """
    def resolve(
        title_parts: list[str], year: str | None, debug: Debug
    ) -> tuple[list[str], dict | None]:
        if not api_key:
            debug.set("tmdb_skipped_reason", "TMDB_API_KEY absent (forced_id)")
            return title_parts, None
        if forced_id <= 0:
            return title_parts, None
        debug.set("tmdb_forced_id", forced_id)
        details_params = {
            "api_key": api_key,
            "language": "fr-FR",
            "append_to_response": "credits,external_ids,release_dates,videos,keywords",
        }
        try:
            details_resp = http_get_with_retry(
                TMDB_DETAILS_URL.format(movie_id=forced_id),
                params=details_params,
            )
            details = details_resp.json()
        except Exception as e:
            debug.set("tmdb_forced_id_error", f"{e}")
            return title_parts, None
        if details.get("status_code"):
            # TMDB error response (ex: 34 = not found)
            debug.set("tmdb_forced_id_not_found", details.get("status_message", ""))
            return title_parts, None
        tmdb_context = _build_tmdb_context(details, forced_id)
        _maybe_fetch_title_en(tmdb_context, api_key, is_tv=False)
        debug.set("tmdb_context", tmdb_context)
        return _title_parts_from_tmdb(tmdb_context, title_parts, debug), tmdb_context

    return resolve


def make_tv_forced_id_resolver(api_key: str, cache_file: Path, forced_id: int, season_num: int | None = None):
    """Variante TV de make_tmdb_forced_id_resolver."""
    def resolve(
        title_parts: list[str], year: str | None, debug: Debug
    ) -> tuple[list[str], dict | None]:
        if not api_key or forced_id <= 0:
            return title_parts, None
        debug.set("tmdb_forced_id", forced_id)
        details_params = {
            "api_key": api_key,
            "language": "fr-FR",
            "append_to_response": "credits,external_ids,aggregate_credits,videos,keywords",
        }
        try:
            details_resp = http_get_with_retry(
                TMDB_TV_DETAILS_URL.format(tv_id=forced_id),
                params=details_params,
            )
            details = details_resp.json()
        except Exception as e:
            debug.set("tmdb_forced_id_error", f"{e}")
            return title_parts, None
        if details.get("status_code"):
            debug.set("tmdb_forced_id_not_found", details.get("status_message", ""))
            return title_parts, None
        season_details = None
        if season_num is not None and season_num > 0:
            try:
                season_resp = http_get_with_retry(
                    TMDB_TV_SEASON_URL.format(tv_id=forced_id, season_num=season_num),
                    params={"api_key": api_key, "language": "fr-FR"},
                )
                season_details = season_resp.json()
            except Exception:
                season_details = None
        tmdb_context = _build_tv_context(details, forced_id, season_details)
        debug.set("tmdb_context", tmdb_context)
        return _title_parts_from_tmdb(tmdb_context, title_parts, debug), tmdb_context

    return resolve


def _build_tv_context(details: dict, tv_id: int, season_details: dict | None = None) -> dict:
    """Construit le contexte TV (similaire a _build_tmdb_context mais pour series)."""
    credits = details.get("credits") or {}
    crew = credits.get("crew") or []
    cast = list(credits.get("cast") or [])

    # Si on a moins de 5 acteurs dans le cast 'standard', on complete avec
    # aggregate_credits qui agrege les acteurs sur toutes les saisons. Tres
    # utile pour :
    # - Series anthologiques (Black Mirror) : credits.cast vide
    # - Series ou seul le perso principal est dans credits (ex: Andor avec
    #   juste Diego Luna) : on ajoute les acteurs recurrents
    if len(cast) < 5:
        agg = details.get("aggregate_credits") or {}
        agg_cast = sorted(
            agg.get("cast") or [],
            key=lambda a: a.get("total_episode_count", 0),
            reverse=True,
        )
        seen_ids = {a.get("id") for a in cast}
        for a in agg_cast:
            if a.get("id") in seen_ids:
                continue
            # Adapte la structure aggregate -> credits standard :
            # 'character' vient du premier role
            if not a.get("character"):
                roles = a.get("roles") or []
                if roles:
                    a["character"] = roles[0].get("character", "")
            cast.append(a)
            seen_ids.add(a.get("id"))
            if len(cast) >= 5:
                break

    creators = [c.get("name", "").strip() for c in (details.get("created_by") or []) if c.get("name")]

    top_cast = [
        {"name": (a.get("name") or "").strip(),
         "character": (a.get("character") or "").strip(),
         "profile_path": (a.get("profile_path") or "").strip()}
        for a in cast[:5] if (a.get("name") or "").strip()
    ]
    genres = [g.get("name", "").strip() for g in (details.get("genres") or []) if g.get("name")]
    countries = [
        c.get("name", "").strip() if isinstance(c, dict) else c
        for c in (details.get("production_countries") or details.get("origin_country") or [])
    ]
    countries = [c for c in countries if c]
    external_ids = details.get("external_ids") or {}

    # Resume des saisons (utile pour les integrales) : on filtre les "Specials"
    # (saison 0) et on garde le numero + le nombre d'episodes.
    seasons_summary = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0:
            continue
        seasons_summary.append({
            "season_number": sn,
            "episode_count": s.get("episode_count") or 0,
            "name": (s.get("name") or "").strip(),
        })

    # Lot Q : keywords + tvdb_id pour le formulaire Gemini.
    keywords_block = details.get("keywords") or {}
    raw_kws = keywords_block.get("results") or keywords_block.get("keywords") or []
    keywords = [
        (kw.get("name") or "").strip()
        for kw in raw_kws[:8]
        if (kw.get("name") or "").strip()
    ]

    ctx = {
        "tv_id": tv_id,
        "title": str(details.get("name", "") or "").strip(),
        "original_title": str(details.get("original_name", "") or "").strip(),
        "original_language": str(details.get("original_language", "") or "").strip().lower(),
        "release_date": str(details.get("first_air_date", "") or "").strip(),
        "overview": str(details.get("overview", "") or "").strip(),
        "runtime": (details.get("episode_run_time") or [None])[0],
        "tmdb_rating": details.get("vote_average"),
        "tmdb_vote_count": details.get("vote_count"),
        "genres": genres,
        "production_countries": countries,
        "director": creators[0] if creators else "",
        "writers": creators[:3],
        "cast": top_cast,
        "imdb_id": (external_ids.get("imdb_id") or "").strip(),
        "imdb_rating": "",
        "tmdb_poster_path": (details.get("poster_path") or "").strip(),
        "number_of_seasons": details.get("number_of_seasons"),
        "number_of_episodes": details.get("number_of_episodes"),
        "seasons_summary": seasons_summary,
        "trailer_yt_key": _extract_trailer_key(details),
        # Lot Q
        "tvdb_id": int(external_ids.get("tvdb_id") or 0) or 0,
        "keywords": keywords,
    }
    if season_details:
        ctx["season_number"] = season_details.get("season_number")
        ctx["season_overview"] = (season_details.get("overview") or "").strip()
        ctx["season_episode_count"] = len(season_details.get("episodes") or [])
        ctx["season_episodes"] = [
            {
                "ep": e.get("episode_number"),
                "name": (e.get("name") or "").strip(),
                "runtime": e.get("runtime"),
            }
            for e in (season_details.get("episodes") or [])
        ]
    return ctx


def make_tv_resolver(api_key: str, cache_file: Path):
    """Resolver TMDB pour series. Signature compatible avec movies."""

    def resolve(
        title_parts: list[str], year: str | None, debug: Debug,
        season_num: int | None = None,
        release_lang_hint: str | None = None,
    ) -> tuple[list[str], dict | None]:
        """Lot O.6 : `release_lang_hint='fr'` bonifie les candidats TMDB
        de production francophone (idem variante film)."""
        if not title_parts or not api_key:
            if not api_key:
                debug.set("tmdb_skipped_reason", "TMDB_API_KEY absent")
            return title_parts, None
        source_title = " ".join(title_parts).strip()
        if not source_title:
            return title_parts, None

        from . import naming_signals as ns

        cache = _cache_load(cache_file)
        cache_key = f"tv|{source_title.lower()}|{year or ''}|{season_num or ''}|{release_lang_hint or ''}"
        cached_tv = cache.get(cache_key)
        if cached_tv and _is_cache_entry_fresh(cached_tv):
            # Lot post-NOTES round 5 : valide aussi la pertinence du hit TV.
            cache_year_tv = str(cached_tv.get("first_air_date") or "")[:4]
            cache_release_tv = {
                "name": cached_tv.get("name") or cached_tv.get("title"),
                "original_name": cached_tv.get("original_name")
                or cached_tv.get("original_title"),
                "first_air_date": cached_tv.get("first_air_date"),
            }
            if _cache_entry_passes_relevance(
                source_title, year, cache_release_tv, cache_year_tv, is_tv=True,
            ):
                debug.set("tmdb_cache_hit", cache_key)
                cached_signals = cached_tv.get("naming_signals_at_resolve") or {}
                for sig_key, sig_value in cached_signals.items():
                    ns.emit_signal(debug, sig_key, sig_value)
                return _title_parts_from_tmdb(cached_tv, title_parts, debug), cached_tv
            debug.set("tmdb_cache_invalidated_low_relevance", {
                "key": cache_key,
                "cached_id": cached_tv.get("tv_id"),
                "cached_name": cached_tv.get("name"),
            })
            print(
                f"[INFO] TMDB cache TV hit '{cache_key}' rejete (mauvais "
                f"match cache : id={cached_tv.get('tv_id')} "
                f"'{cached_tv.get('name')}'). Refetch."
            )
        elif cached_tv:
            debug.set("tmdb_cache_invalidated", cache_key)
            print(f"[INFO] TMDB cache TV obsolete pour {cache_key} : refetch.")

        # === Lot O.2 + O.4 (variante TV) : meme refonte que pour les films ===
        # On cumule les resultats EN/FR sans year-filter, puis on rank en
        # post-traitement avec tolerance d'annee +-1.
        all_results: list[dict] = []
        seen_ids: set[int] = set()
        attempted_title = source_title
        words = source_title.split()

        def _do_search_tv(query: str, language: str) -> list[dict]:
            params = {
                "api_key": api_key, "query": query,
                "include_adult": "false", "language": language,
            }
            try:
                resp = http_get_with_retry(TMDB_TV_SEARCH_URL, params=params)
                return resp.json().get("results", []) or []
            except Exception as e:
                debug.set("tmdb_search_error", f"{e}")
                return []

        def _accumulate_tv(new: list[dict], language: str, n_drop: int) -> int:
            """Tag chaque resultat avec sa source pour signal post-ranking."""
            added = 0
            for r in new:
                rid = r.get("id")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    r["_lang_source"] = language
                    r["_n_drop_source"] = n_drop
                    all_results.append(r)
                    added += 1
            return added

        attempts: list[tuple[str, str, int]] = [
            (source_title, "en-US", 0),
            (source_title, "fr-FR", 0),
        ]
        # Lot post-NOTES round 5 : variante "sans article de tete" (idem
        # variante movie). Important pour les series FR avec "L'X" qui
        # passent en "L X" apres notre splitter.
        if (
            len(words) >= 4
            and words[0].lower() in _LEADING_ARTICLE_TOKENS
        ):
            without_lead_tv = " ".join(words[1:])
            attempts.append((without_lead_tv, "en-US", 0))
            attempts.append((without_lead_tv, "fr-FR", 0))
        # NOTES round 6 : variante "sans stopwords" (idem movie). Cas reel :
        # "The Last Man On Earth" -> "Last Man Earth", "Your Friends and
        # Neighbors" -> "Friends Neighbors". TMDB matche mieux sans les
        # stopwords parasites qui font passer le query dans des resultats
        # generiques.
        sig_words_tv = [w for w in words if w.lower() not in _TITLE_STOPWORDS]
        if 2 <= len(sig_words_tv) < len(words):
            sig_query_tv = " ".join(sig_words_tv)
            existing_tv = {q for q, _, _ in attempts}
            if sig_query_tv not in existing_tv:
                attempts.append((sig_query_tv, "en-US", 0))
                attempts.append((sig_query_tv, "fr-FR", 0))
        for n_drop in range(1, len(words)):
            shortened_words = words[: len(words) - n_drop]
            sig = [w for w in shortened_words if len(w) >= 3]
            if len(sig) < 2:
                break
            shortened = " ".join(shortened_words)
            attempts.append((shortened, "fr-FR", n_drop))
            attempts.append((shortened, "en-US", n_drop))

        for query, language, n_drop in attempts:
            new = _do_search_tv(query, language)
            added = _accumulate_tv(new, language, n_drop)
            if added and attempted_title == source_title:
                attempted_title = query
            if n_drop == 0 and language == "fr-FR" and len(all_results) >= 5:
                break

        if not all_results:
            debug.set("tmdb_search_no_results",
                      {"title": source_title, "year": year})
            return title_parts, None

        results = all_results
        debug.set("tmdb_search_attempted", attempted_title)
        debug.set("tmdb_search_pool_size", len(results))
        # Note : signaux SIG_TMDB_LANG_FALLBACK / SIG_TMDB_QUERY_SHORTENED
        # emis APRES le ranking (cf. apres `chosen = max(...)`).

        title_norm = source_title.strip().lower()
        year_int = int(year) if year and year.isdigit() else None

        def _year_score_tv(r) -> int:
            if year_int is None:
                return 0
            ry_str = str(r.get("first_air_date", ""))[:4]
            if not ry_str.isdigit():
                return 0
            ry = int(ry_str)
            diff = abs(ry - year_int)
            if diff == 0:
                return 5000
            if diff == 1:
                return 2500
            if diff == 2:
                return 500
            return 0

        def _title_score_tv(r) -> int:
            # NOTES round 6 : boost exact 1000 -> 3000 (cf. movie variant).
            t = (r.get("name") or "").strip().lower()
            ot = (r.get("original_name") or "").strip().lower()
            if t == title_norm or ot == title_norm:
                return 3000
            if t.startswith(title_norm) or ot.startswith(title_norm):
                return 500
            return 0

        def _origin_score_tv(r) -> int:
            """Lot O.6 : bonus si release tagué FR-only et serie de
            production francophone."""
            if release_lang_hint != "fr":
                return 0
            orig_lang = (r.get("original_language") or "").lower()
            # Bonus 2000 : superieur au vote_count * 0.5 d'un blockbuster
            # (~5000 votes = 2500 pts) dans la majorite des cas. Suffit
            # pour departager 2 homonymes year+title exacts sans ecraser
            # la priorite year (5000) ni title exact (1000).
            if orig_lang in _FRENCH_LANG_CODES:
                return 2000
            return 0

        def _final_score_tv(r) -> float:
            pop = float(r.get("popularity") or 0)
            votes = float(r.get("vote_count") or 0)
            # Cap votes (idem movie, cf. commentaire la-bas).
            vote_bonus = min(votes * 0.5, 2000.0)
            return (
                _year_score_tv(r) + _title_score_tv(r) + _origin_score_tv(r)
                + pop + vote_bonus
            )

        chosen = max(results, key=_final_score_tv)
        tv_id = chosen.get("id")
        if not tv_id:
            return title_parts, None

        # Lot post-NOTES round 4 + round 5 : seuil minimum de pertinence
        # (idem movie). year_score=0 ET title_score=0 -> pas de match.
        # Round 5 : title_score=0 ET relevance<0.5 -> reject meme si year ok.
        chosen_ys = _year_score_tv(chosen)
        chosen_ts = _title_score_tv(chosen)
        chosen_tr = _title_relevance(source_title, chosen, is_tv=True)
        if chosen_ys == 0 and chosen_ts == 0:
            debug.set(
                "tmdb_match_rejected_low_relevance",
                {
                    "id": tv_id, "name": chosen.get("name"),
                    "first_air_date": chosen.get("first_air_date"),
                    "reason": "year_score=0 et title_score=0",
                },
            )
            print(
                f"[INFO] TMDB TV candidat {tv_id} '{chosen.get('name')}' "
                "rejete : aucun signal de pertinence."
            )
            return title_parts, None
        if chosen_ts == 0 and chosen_tr < _TITLE_RELEVANCE_MIN_WHEN_NO_TITLE_SCORE:
            debug.set(
                "tmdb_match_rejected_low_title_relevance",
                {
                    "id": tv_id, "name": chosen.get("name"),
                    "first_air_date": chosen.get("first_air_date"),
                    "year_score": chosen_ys,
                    "title_relevance": round(chosen_tr, 3),
                    "reason": "title_score=0, relevance trop faible",
                },
            )
            print(
                f"[INFO] TMDB TV candidat {tv_id} '{chosen.get('name')}' "
                f"rejete : year ok mais titre sans rapport (relevance="
                f"{chosen_tr:.2f})."
            )
            return title_parts, None

        # Lot O.2 fix : signaux bases sur la SOURCE du resultat choisi.
        chosen_lang = chosen.get("_lang_source", "en-US")
        chosen_n_drop = int(chosen.get("_n_drop_source", 0))
        if chosen_lang != "en-US":
            ns.emit_signal(debug, ns.SIG_TMDB_LANG_FALLBACK, True)
        if chosen_n_drop > 0:
            ns.emit_signal(
                debug, ns.SIG_TMDB_QUERY_SHORTENED, chosen_n_drop,
            )

        debug.set(
            "tmdb_search_chosen",
            {
                "id": tv_id,
                "name": chosen.get("name"),
                "first_air_date": chosen.get("first_air_date"),
                "popularity": chosen.get("popularity"),
                "total_results": len(results),
                "lang_source": chosen_lang,
                "n_drop_source": chosen_n_drop,
            },
        )

        # Details + credits + external_ids + aggregate_credits (fallback pour
        # series anthologiques type Black Mirror)
        params = {
            "api_key": api_key, "language": "fr-FR",
            "append_to_response": "credits,external_ids,aggregate_credits,videos,keywords",
        }
        try:
            details = http_get_with_retry(
                TMDB_TV_DETAILS_URL.format(tv_id=tv_id), params=params,
            ).json()
        except Exception as e:
            # Lot O.7 : fallback minimal (idem variante film)
            debug.set("tmdb_details_error", f"{e}")
            ns.emit_signal(debug, ns.SIG_TMDB_DETAILS_FAILED, True)
            tv_context = _build_minimal_tmdb_context_from_search(
                chosen, tv_id, is_tv=True,
            )
            tv_context["naming_signals_at_resolve"] = dict(
                debug.data.get("naming_signals") or {}
            )
            debug.set("tmdb_context", tv_context)
            print(
                f"[WARN] TMDB /tv/{tv_id} indisponible — fiche minimale "
                "construite a partir du search."
            )
            return _title_parts_from_tmdb(tv_context, title_parts, debug), tv_context

        season_details = None
        if season_num is not None:
            try:
                season_details = http_get_with_retry(
                    TMDB_TV_SEASON_URL.format(tv_id=tv_id, season_num=season_num),
                    params={"api_key": api_key, "language": "fr-FR"},
                ).json()
            except Exception as e:
                debug.set("tmdb_season_error", f"{e}")

        tv_context = _build_tv_context(details, tv_id, season_details)
        # Snapshot des signaux pour replay sur cache hit ulterieur
        tv_context["naming_signals_at_resolve"] = dict(
            debug.data.get("naming_signals") or {}
        )
        tv_context["_cache_version"] = _TMDB_CACHE_VERSION
        cache[cache_key] = tv_context
        _cache_save(cache_file, cache)
        debug.set("tmdb_context", tv_context)
        return _title_parts_from_tmdb(tv_context, title_parts, debug), tv_context

    return resolve
