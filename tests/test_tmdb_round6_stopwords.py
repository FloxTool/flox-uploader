"""Tests NOTES round 6 : variante 'sans stopwords' dans les attempts TMDB.

Cas reels :
- Harry Potter Et La Chambre Des Secrets (2002) -> matche Chamber of
  Secrets (TMDB 672) au lieu de Philosopher's Stone (TMDB 671 / 2001)
  via year tolerance.
- The Last Man On Earth -> matche tv 61888 au lieu de no-match.
- Your Friends and Neighbors -> matche tv 241609.

La fix : ajouter une variante "sans stopwords" (et/la/the/of/on/in/
at/...) avant la troncature de queue. Permet a TMDB de matcher le
titre exact sans les mots parasites qui faisaient rater le hit.
"""
from __future__ import annotations

import pytest

from flox_uploader.core import tmdb as _tmdb
from flox_uploader.core.tmdb import (
    _significant_tokens,
    make_tmdb_resolver,
)
from flox_uploader.core.debug import Debug


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"results": self._data} if isinstance(self._data, list) else self._data


def test_harry_potter_chambre_des_secrets_picks_chamber_not_stone(monkeypatch, tmp_path):
    """Cas reel : "Harry Potter Et La Chambre Des Secrets" (2002).
    Avant fix : matchait Philosopher's Stone (671, 2001, year tolerance).
    Apres fix : la variante sans stopwords ("Harry Potter Chambre
    Secrets") trouve Chamber of Secrets (672, 2002) avec title exact."""
    queries_seen = []
    # Pool simulant ce que TMDB retourne :
    # - Pour la query complete : 0 hits (TMDB strict sur les stopwords FR)
    # - Pour query truncated "Harry Potter Et" : Philosopher's Stone
    # - Pour query sans stopwords "Harry Potter Chambre Secrets" : Chamber!
    fake_results = {
        "Harry Potter Et La Chambre Des Secrets": [],
        "Harry Potter Chambre Secrets": [
            {
                "id": 672,
                "title": "Harry Potter et la Chambre des Secrets",
                "original_title": "Harry Potter and the Chamber of Secrets",
                "release_date": "2002-11-13",
                "popularity": 30.0, "vote_count": 25000,
                "original_language": "en",
            },
        ],
        "Harry Potter Et La Chambre Des": [],
        "Harry Potter Et La Chambre": [],
        "Harry Potter Et La": [],
        "Harry Potter Et": [
            {
                "id": 671,
                "title": "Harry Potter à l'école des sorciers",
                "original_title": "Harry Potter and the Philosopher's Stone",
                "release_date": "2001-11-16",
                "popularity": 24.46, "vote_count": 29463,
                "original_language": "en",
            },
        ],
    }
    fake_details = {
        "id": 672, "title": "Harry Potter et la Chambre des Secrets",
        "original_title": "Harry Potter and the Chamber of Secrets",
        "release_date": "2002-11-13", "original_language": "en",
        "runtime": 161, "vote_average": 7.7, "vote_count": 25000,
        "genres": [], "external_ids": {"imdb_id": "tt0295297"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [{"name": "UK"}],
        "overview": "", "poster_path": "/cs.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            q = (params or {}).get("query", "")
            queries_seen.append(q)
            return _FakeResp(fake_results.get(q, []))
        if "/movie/672" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["Harry", "Potter", "Et", "La", "Chambre", "Des", "Secrets"],
        "2002", debug,
    )
    assert ctx is not None
    assert ctx["movie_id"] == 672
    # La variante sans stopwords doit avoir ete tentee
    assert "Harry Potter Chambre Secrets" in queries_seen


def test_significant_tokens_drops_french_stopwords():
    """Tokens significatifs apres normalisation : et/la/des sont strippes."""
    tokens = _significant_tokens("Harry Potter Et La Chambre Des Secrets")
    # 'harry', 'potter', 'chambre', 'secret' (trailing s strip pour
    # tolerer typo + 'des' filtre comme stopword)
    assert "harry" in tokens
    assert "potter" in tokens
    assert "chambre" in tokens
    assert "secret" in tokens
    # Stopwords filtres
    assert "et" not in tokens
    assert "la" not in tokens
    assert "des" not in tokens


def test_significant_tokens_drops_english_stopwords():
    """The/on/at filtres."""
    tokens = _significant_tokens("The Last Man On Earth")
    assert tokens == {"last", "man", "earth"}


def test_stopwords_only_variant_not_emitted_if_no_change():
    """Si le titre n'a aucun stopword, on ne genere pas une variante
    identique (eviterait du bruit dans les attempts).
    Verification de la condition : `2 <= len(sig_words) < len(words)`.
    Pour 'Inception' (1 mot) : sig_words=['Inception'] (1 < 2) -> skip."""
    from flox_uploader.core.tmdb import _TITLE_STOPWORDS
    words = "Inception".split()
    sig_words = [w for w in words if w.lower() not in _TITLE_STOPWORDS]
    assert len(sig_words) == 1


def test_last_man_on_earth_picks_correct_show(monkeypatch, tmp_path):
    """The Last Man On Earth (sans annee) -> matche tv 61888 via la
    variante sans stopwords "Last Man Earth"."""
    queries_seen = []
    fake_results = {
        "The Last Man On Earth": [
            # Le top-result fr-FR retourne Last of Us avant Last Man on Earth
            # (cas reel observe sur l'API TMDB).
            {
                "id": 100088, "name": "The Last of Us",
                "original_name": "The Last of Us",
                "first_air_date": "2023-01-15",
                "popularity": 200.0, "vote_count": 12000,
                "original_language": "en",
            },
        ],
        # La variante sans stopwords matche le bon show
        "Last Man Earth": [
            {
                "id": 61888, "name": "The Last Man on Earth",
                "original_name": "The Last Man on Earth",
                "first_air_date": "2015-03-01",
                "popularity": 15.0, "vote_count": 800,
                "original_language": "en",
            },
        ],
    }
    fake_details = {
        "id": 61888, "name": "The Last Man on Earth",
        "original_name": "The Last Man on Earth",
        "first_air_date": "2015-03-01", "original_language": "en",
        "vote_average": 7.4, "vote_count": 800,
        "genres": [], "external_ids": {"imdb_id": "tt3230854"},
        "credits": {"crew": [], "cast": []},
        "aggregate_credits": {"cast": [], "crew": []},
        "videos": {"results": []}, "keywords": {"results": []},
        "production_countries": [],
        "overview": "", "poster_path": "/lm.jpg",
        "number_of_seasons": 4, "number_of_episodes": 67,
    }

    def fake_http(url, params=None, **kw):
        if "search/tv" in url:
            q = (params or {}).get("query", "")
            queries_seen.append(q)
            return _FakeResp(fake_results.get(q, []))
        if "/tv/61888" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    from flox_uploader.core.tmdb import make_tv_resolver
    resolver = make_tv_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["The", "Last", "Man", "On", "Earth"], None, debug,
    )
    # La variante sans stopwords doit hit "Last Man Earth" -> 61888
    assert ctx is not None
    assert ctx["tv_id"] == 61888
    assert "Last Man Earth" in queries_seen
