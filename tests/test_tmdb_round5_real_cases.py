"""Tests : 3 cas reels post-round4 (NOTES.md) sur les mismatches TMDB.

Cas 1 — Moon (2009) -> Twilight New Moon
  Le cache contient un mauvais match historique. Year matche (2009=2009)
  mais le titre "Moon" est noye dans "The Twilight Saga: New Moon". Doit
  etre rejete par le nouveau gate de relevance.

Cas 2 — Les Septs Samourai (1954) -> Red Shoes (2019)
  CACHE HIT pollue avec un mauvais match d'avant le seuil de pertinence.
  Le cache doit etre invalide silencieusement et la recherche relancee.

Cas 3 — L'Incroyable Histoire du Facteur Cheval -> Canal du Midi
  Le titre commence par "L " et notre splitter le rend confondant pour
  TMDB. Une variante "sans article de tete" doit etre tentee.
"""
from __future__ import annotations

import json

import pytest

from flox_uploader.core import tmdb as _tmdb
from flox_uploader.core.tmdb import (
    _cache_entry_passes_relevance,
    _significant_tokens,
    _title_relevance,
    make_tmdb_resolver,
)
from flox_uploader.core.debug import Debug


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"results": self._data} if isinstance(self._data, list) else self._data


# ============================================================
# Helpers : tests unitaires sur les fonctions de pertinence
# ============================================================

def test_significant_tokens_normalizes_accents_and_plural():
    """Sept Samouraïs / Septs Samourai -> meme tokens apres normalisation."""
    a = _significant_tokens("Les Sept Samouraïs")
    b = _significant_tokens("Les Septs Samourai")
    assert a == b == {"sept", "samourai"}


def test_significant_tokens_filters_stopwords_and_digits():
    tok = _significant_tokens("The 7 Samurai of the Galaxy")
    # "the", "of", chiffre "7" filtres ; "samurai" → "samurai" (pas de 's' finale a strip)
    assert tok == {"samurai", "galaxy"}


def test_title_relevance_moon_vs_new_moon_is_low():
    """Cas Moon -> Twilight : query "Moon" entierement dans "New Moon"
    mais le chosen a 4 tokens, donc chosen_coverage = 1/4 = 0.25."""
    candidate = {
        "title": "Twilight, chapitre 2 : Tentation",
        "original_title": "The Twilight Saga: New Moon",
    }
    rel = _title_relevance("Moon", candidate)
    # Best des deux : EN = 1/1 query, 1/4 chosen -> min 0.25. FR = 0.
    assert rel < 0.5
    assert abs(rel - 0.25) < 0.01


def test_title_relevance_moon_vs_moon_is_max():
    candidate = {"title": "Moon", "original_title": "Moon"}
    rel = _title_relevance("Moon", candidate)
    assert rel == 1.0


def test_title_relevance_sept_samourais_with_typo_still_passes():
    """Septs Samourai (typo) vs Sept Samouraïs (correct) -> 1.0."""
    candidate = {
        "title": "Les Sept Samouraïs",
        "original_title": "七人の侍",  # non-latin, ignore par tokenizer
    }
    rel = _title_relevance("Les Septs Samourai", candidate)
    assert rel >= 0.8


def test_title_relevance_facteur_cheval_vs_canal_du_midi_is_zero():
    """Rien en commun -> 0."""
    candidate = {
        "title": "Canal du Midi : un patrimoine révélé",
        "original_title": "Canal du Midi : un patrimoine révélé",
    }
    rel = _title_relevance("L Incroyable Histoire Du Facteur Cheval", candidate)
    assert rel == 0.0


def test_cache_entry_passes_relevance_rejects_moon_to_twilight():
    cached = {
        "title": "Twilight, chapitre 2 : Tentation",
        "original_title": "The Twilight Saga: New Moon",
        "release_date": "2009-11-18",
    }
    assert not _cache_entry_passes_relevance("Moon", "2009", cached, "2009")


def test_cache_entry_passes_relevance_accepts_real_moon():
    cached = {
        "title": "Moon",
        "original_title": "Moon",
        "release_date": "2009-07-17",
    }
    assert _cache_entry_passes_relevance("Moon", "2009", cached, "2009")


# ============================================================
# Cas 1 — Moon 2009 : fresh search doit rejeter Twilight et trouver Moon
# ============================================================

def test_moon_2009_rejects_twilight_picks_real_moon(monkeypatch, tmp_path):
    """Cas reel NOTES round 5 : Moon (2009) ne doit plus matcher Twilight
    New Moon meme s'ils ont la meme annee. Si le pool contient les deux,
    le vrai Moon (title exact) doit gagner. Si seul Twilight est present,
    on doit retourner None plutot qu'un faux positif."""
    # Pool TMDB realiste : les deux films sortent en 2009 et matchent
    # "Moon" comme query (popularity-sortis par TMDB)
    fake_results = [
        {
            "id": 17431, "title": "Moon", "original_title": "Moon",
            "release_date": "2009-07-17",
            "popularity": 15.0, "vote_count": 5000,
            "original_language": "en",
        },
        {
            "id": 18239, "title": "Twilight, chapitre 2 : Tentation",
            "original_title": "The Twilight Saga: New Moon",
            "release_date": "2009-11-18",
            "popularity": 30.0, "vote_count": 10000,
            "original_language": "en",
        },
    ]
    fake_details = {
        "id": 17431, "title": "Moon", "original_title": "Moon",
        "release_date": "2009-07-17", "original_language": "en",
        "runtime": 97, "vote_average": 7.8, "vote_count": 5000,
        "genres": [], "external_ids": {"imdb_id": "tt1182345"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [{"name": "UK"}],
        "overview": "", "poster_path": "/m.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        if "/movie/17431" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["Moon"], "2009", debug)
    # Le vrai Moon a title_score=1000 -> gagne meme contre Twilight popular
    assert ctx is not None
    assert ctx["movie_id"] == 17431


def test_moon_2009_alone_with_twilight_only_returns_none(monkeypatch, tmp_path):
    """Pool ne contient QUE Twilight. Year matche mais titre n'a rien a
    voir -> doit retourner None (mieux que faux positif)."""
    fake_results = [
        {
            "id": 18239, "title": "Twilight, chapitre 2 : Tentation",
            "original_title": "The Twilight Saga: New Moon",
            "release_date": "2009-11-18",
            "popularity": 30.0, "vote_count": 10000,
            "original_language": "en",
        },
    ]

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["Moon"], "2009", debug)
    assert ctx is None
    # Le debug doit avoir la cause du rejet
    rejected = debug.data.get("tmdb_match_rejected_low_title_relevance")
    assert rejected is not None
    assert rejected["id"] == 18239


# ============================================================
# Cas 2 — Cache pollue par mauvais match precedent
# ============================================================

def test_polluted_cache_is_invalidated_and_refetched(monkeypatch, tmp_path):
    """Si le cache contient le mauvais match Sept Samourai -> Red Shoes
    (provenant d'une recherche d'avant le seuil), il doit etre invalide
    et la recherche relancee."""
    # Pre-pollute le cache avec le mauvais match (comme c'etait sur disque
    # de Louis avant cette fix)
    cache_path = tmp_path / "cache.json"
    bad_cache = {
        "les septs samourai|1954": {
            "movie_id": 486589,
            "title": "Blanche Neige, les souliers rouges et les sept nains",
            "original_title": "레드슈즈",
            "release_date": "2019-07-25",
            "_cache_version": 2,
            "imdb_id": "tt4429160",
        }
    }
    cache_path.write_text(json.dumps(bad_cache), encoding="utf-8")

    # Le refetch doit retourner le bon film (TMDB 346)
    fake_results = [
        {
            "id": 346, "title": "Les Sept Samouraïs",
            "original_title": "七人の侍",
            "release_date": "1954-04-26",
            "popularity": 20.0, "vote_count": 4000,
            "original_language": "ja",
        },
    ]
    fake_details = {
        "id": 346, "title": "Les Sept Samouraïs",
        "original_title": "七人の侍", "release_date": "1954-04-26",
        "original_language": "ja", "runtime": 207,
        "vote_average": 8.5, "vote_count": 4000,
        "genres": [], "external_ids": {"imdb_id": "tt0047478"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [{"name": "Japan"}],
        "overview": "", "poster_path": "/x.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        if "/movie/346" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", cache_path)
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["Les", "Septs", "Samourai"], "1954", debug)
    # Le bon film doit etre choisi malgre le cache pollue
    assert ctx is not None
    assert ctx["movie_id"] == 346
    # Le debug doit logger l'invalidation
    assert debug.data.get("tmdb_cache_invalidated_low_relevance") is not None


def test_valid_cache_hit_still_works(monkeypatch, tmp_path):
    """Garde-fou : un cache hit LEGITIME doit toujours fonctionner sans
    refaire de search."""
    cache_path = tmp_path / "cache.json"
    good_cache = {
        "inception|2010": {
            "movie_id": 100,
            "title": "Inception",
            "original_title": "Inception",
            "release_date": "2010-07-15",
            "_cache_version": 2,
        }
    }
    cache_path.write_text(json.dumps(good_cache), encoding="utf-8")

    # Si TMDB est appele c'est qu'on a fait un refetch a tort
    call_count = {"n": 0}

    def fake_http(url, params=None, **kw):
        call_count["n"] += 1
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", cache_path)
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["Inception"], "2010", debug)
    assert ctx is not None
    assert ctx["movie_id"] == 100
    assert call_count["n"] == 0, "Cache hit valide ne doit pas refetch"


# ============================================================
# Cas 3 — Variante "sans article de tete"
# ============================================================

def test_leading_article_variant_tried_when_full_query_empty(monkeypatch, tmp_path):
    """Cas reel Facteur Cheval : "L Incroyable Histoire Du Facteur Cheval"
    rate TMDB (L isole confondant). On doit aussi tenter "Incroyable
    Histoire Du Facteur Cheval" -> trouve le vrai film."""
    queries_seen = []
    fake_results_by_query = {
        # Query complete rate
        "L Incroyable Histoire Du Facteur Cheval": [],
        # Sans article de tete : trouve
        "Incroyable Histoire Du Facteur Cheval": [
            {
                "id": 510455,
                "title": "L'Incroyable Histoire du facteur Cheval",
                "original_title": "L'Incroyable Histoire du facteur Cheval",
                "release_date": "2018-12-26",
                "popularity": 5.0, "vote_count": 200,
                "original_language": "fr",
            },
        ],
    }
    fake_details = {
        "id": 510455, "title": "L'Incroyable Histoire du facteur Cheval",
        "original_title": "L'Incroyable Histoire du facteur Cheval",
        "release_date": "2018-12-26", "original_language": "fr",
        "runtime": 105, "vote_average": 7.2, "vote_count": 200,
        "genres": [], "external_ids": {"imdb_id": "tt6160360"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [{"name": "France"}],
        "overview": "", "poster_path": "/fc.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            q = (params or {}).get("query", "")
            queries_seen.append(q)
            return _FakeResp(fake_results_by_query.get(q, []))
        if "/movie/510455" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["L", "Incroyable", "Histoire", "Du", "Facteur", "Cheval"],
        "2018", debug,
    )
    assert ctx is not None
    assert ctx["movie_id"] == 510455
    # La variante "sans article" doit avoir ete tentee
    assert "Incroyable Histoire Du Facteur Cheval" in queries_seen


def test_short_title_no_leading_variant(monkeypatch, tmp_path):
    """Garde-fou : titres a 3 mots ou moins ne declenchent PAS la variante
    (sinon on cherche "Pacte" pour "Le Pacte" et on perd de l'info)."""
    queries_seen = []

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            queries_seen.append((params or {}).get("query", ""))
            return _FakeResp([])
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["Le", "Pacte"], "2006", debug)
    # On ne doit PAS avoir tente "Pacte" tout seul
    assert "Pacte" not in queries_seen
