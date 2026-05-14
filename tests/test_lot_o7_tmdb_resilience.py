"""Tests Lot O.7 : resilience TMDB sur erreurs 5xx du fetch /movie/{id}.

Cas reel rapporte par Louis : "The 6th Day 2000". La recherche TMDB a bien
trouve id 8452 (year_score=5000, title_score=1000 = match parfait), mais
le fetch /movie/8452 a renvoye 502 Bad Gateway. Avant : on perdait tout.
Apres : on construit une fiche minimale a partir du resultat de search
pour preserver l'ID + title + year + original_language.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.tmdb import (
    _build_minimal_tmdb_context_from_search,
)


# ============================================================
# _build_minimal_tmdb_context_from_search
# ============================================================

def test_minimal_context_movie_preserves_essential_fields():
    """A partir d'un resultat de search, on garde id, title, year, lang."""
    chosen = {
        "id": 8452,
        "title": "The 6th Day",
        "original_title": "The 6th Day",
        "release_date": "2000-11-17",
        "popularity": 3.69,
        "vote_count": 2249,
        "vote_average": 6.0,
        "original_language": "en",
        "poster_path": "/path/poster.jpg",
        "overview": "Court synopsis du search",
    }
    ctx = _build_minimal_tmdb_context_from_search(chosen, 8452, is_tv=False)
    assert ctx["movie_id"] == 8452
    assert ctx["title"] == "The 6th Day"
    assert ctx["original_title"] == "The 6th Day"
    assert ctx["release_date"] == "2000-11-17"
    assert ctx["original_language"] == "en"
    assert ctx["tmdb_vote_count"] == 2249
    assert ctx["tmdb_rating"] == 6.0
    assert ctx["tmdb_poster_path"] == "/path/poster.jpg"
    assert ctx["overview"] == "Court synopsis du search"
    # Marqueur signalant qu'on n'a PAS les details
    assert ctx["_minimal_context"] is True


def test_minimal_context_movie_empty_optional_fields():
    """Champs non-disponibles dans search sont vides (cast, director, imdb)."""
    chosen = {"id": 1, "title": "X", "release_date": "2020"}
    ctx = _build_minimal_tmdb_context_from_search(chosen, 1, is_tv=False)
    assert ctx["cast"] == []
    assert ctx["director"] == ""
    assert ctx["genres"] == []
    assert ctx["imdb_id"] == ""
    assert ctx["keywords"] == []


def test_minimal_context_tv_uses_correct_keys():
    """Pour TV, on prend `name` et `first_air_date`, pas `title`/`release_date`."""
    chosen = {
        "id": 100,
        "name": "Some Show",
        "original_name": "Original Show",
        "first_air_date": "2015-01-01",
        "vote_count": 500,
        "original_language": "fr",
    }
    ctx = _build_minimal_tmdb_context_from_search(chosen, 100, is_tv=True)
    assert ctx["tv_id"] == 100
    assert "movie_id" not in ctx
    assert ctx["title"] == "Some Show"
    assert ctx["original_title"] == "Original Show"
    assert ctx["release_date"] == "2015-01-01"
    assert ctx["original_language"] == "fr"


# ============================================================
# Signal SIG_TMDB_DETAILS_FAILED
# ============================================================

def test_sig_tmdb_details_failed_constant():
    from flox_uploader.core.naming_signals import (
        SIG_TMDB_DETAILS_FAILED, SIGNAL_METADATA,
    )
    assert SIG_TMDB_DETAILS_FAILED in SIGNAL_METADATA
    penalty, label = SIGNAL_METADATA[SIG_TMDB_DETAILS_FAILED]
    # Penalite moderee (5pts) — beaucoup moins que -25 si on avait abandonne
    assert penalty == 5
    assert "TMDB" in label
    assert "indisponible" in label.lower() or "minimale" in label.lower()


# ============================================================
# Integration : 502 -> fiche minimale au lieu de None
# ============================================================

class _FakeRespJson:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_resolver_502_on_details_returns_minimal_context(monkeypatch, tmp_path):
    """Le cas reel : search trouve, /movie/{id} renvoie 502.
    Doit retourner un context minimal (pas None)."""
    import requests
    from flox_uploader.core import tmdb as _tmdb
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    fake_search_results = [
        {
            "id": 8452,
            "title": "The 6th Day",
            "original_title": "The 6th Day",
            "release_date": "2000-11-17",
            "popularity": 3.69,
            "vote_count": 2249,
            "vote_average": 6.0,
            "original_language": "en",
            "poster_path": "/path/poster.jpg",
        }
    ]

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeRespJson({"results": fake_search_results})
        if "/movie/8452" in url:
            # Simule 502 Bad Gateway persistant (apres tous les retries)
            err = requests.HTTPError("502 Server Error: Bad Gateway")
            err.response = type("R", (), {"status_code": 502})()
            raise err
        return _FakeRespJson({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    title_parts, ctx = resolver(["The", "6th", "Day"], "2000", debug)

    # Avant Lot O.7 : ctx aurait ete None et title_parts inchanges (pas de fiche)
    assert ctx is not None, "Expected minimal context, got None"
    assert ctx["movie_id"] == 8452
    assert ctx["title"] == "The 6th Day"
    assert ctx["release_date"] == "2000-11-17"
    assert ctx.get("_minimal_context") is True
    # Le signal SIG_TMDB_DETAILS_FAILED doit etre emit
    sigs = debug.data.get("naming_signals") or {}
    assert sigs.get("tmdb_details_failed") is True


def test_resolver_success_path_unchanged(monkeypatch, tmp_path):
    """Cas normal (pas d'erreur 502) : le resolver fonctionne comme avant
    et NE marque PAS _minimal_context."""
    from flox_uploader.core import tmdb as _tmdb
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    fake_search_results = [
        {
            "id": 8452, "title": "The 6th Day",
            "original_title": "The 6th Day",
            "release_date": "2000-11-17",
            "popularity": 3.69, "vote_count": 2249,
            "original_language": "en",
        }
    ]
    fake_details = {
        "id": 8452, "title": "The 6th Day",
        "original_title": "The 6th Day",
        "release_date": "2000-11-17",
        "original_language": "en", "runtime": 124,
        "vote_average": 6.0, "vote_count": 2249,
        "genres": [{"name": "Action"}, {"name": "Science-Fiction"}],
        "production_countries": [{"name": "United States"}],
        "external_ids": {"imdb_id": "tt0216216"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []},
        "keywords": {"keywords": []},
        "overview": "Synopsis complet",
        "poster_path": "/path/poster.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeRespJson({"results": fake_search_results})
        if "/movie/8452" in url:
            return _FakeRespJson(fake_details)
        return _FakeRespJson({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(["The", "6th", "Day"], "2000", debug)

    assert ctx is not None
    assert ctx["movie_id"] == 8452
    assert ctx["imdb_id"] == "tt0216216"
    # Path normal : pas de _minimal_context
    assert ctx.get("_minimal_context") is None or ctx.get("_minimal_context") is False
    sigs = debug.data.get("naming_signals") or {}
    assert sigs.get("tmdb_details_failed") is None or sigs.get("tmdb_details_failed") is False
