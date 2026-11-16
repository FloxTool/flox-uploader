"""Tests : comparaison de titre TMDB insensible aux accents / ponctuation.

Cas reel Louis (2026-11-15) :
  Dans.Une.Galaxie.Pres.De.Chez.Vous.S02.VFQ.720p.WEBRiP.x265.AAC-EpicSnoopyQC

  Le resolver TV trouvait bien la serie TMDB 13706 ("Dans une galaxie près
  de chez vous") puis la REJETAIT :
      tmdb_match_rejected_low_relevance : "year_score=0 et title_score=0"

  - year_score=0 : une saison de serie n'a pas d'annee dans son nom ;
  - title_score=0 : l'egalite stricte "pres" != "près" echouait, alors que
    le nom de release est sans accent PAR CONSTRUCTION (convention scene).

  Resultat : "Pas de correspondance TMDB" sur toute serie au titre accentue
  (ou avec apostrophe) dont le nom de release n'a pas d'annee.

Le garde-fou anti-faux-positif (year_score=0 ET title_score=0 -> rejet) est
conserve tel quel : seul le calcul du title_score devient insensible aux
accents et a la ponctuation.
"""
from __future__ import annotations

from flox_uploader.core import tmdb as _tmdb
from flox_uploader.core.debug import Debug
from flox_uploader.core.tmdb import (
    _cache_entry_passes_relevance,
    _title_exact_score,
    make_tmdb_resolver,
    make_tv_resolver,
)


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"results": self._data} if isinstance(self._data, list) else self._data


# Donnees reelles TMDB (search/tv, releve du 2026-11-15)
_GALAXIE_SERIE = {
    "id": 13706, "name": "Dans une galaxie près de chez vous",
    "original_name": "Dans une galaxie près de chez vous",
    "first_air_date": "1999-01-25",
    "popularity": 5.4862, "vote_count": 11, "original_language": "fr",
}
_GALAXIE_25_ANS = {
    "id": 253266,
    "name": "Dans une galaxie près de chez vous : 25 ans de mission",
    "original_name": "Dans une galaxie près de chez vous : 25 ans de mission",
    "first_air_date": "2024-05-01",
    "popularity": 0.7526, "vote_count": 3, "original_language": "fr",
}
# Bruit reel ramene par la query raccourcie "Dans Une"
_BRUIT_DANS_UNE = [
    {
        "id": 38526, "name": "Il était une fois dans le trouble",
        "original_name": "Il était une fois dans le trouble",
        "first_air_date": "2004-09-27",
        "popularity": 6.557, "vote_count": 1, "original_language": "en",
    },
    {
        "id": 27244, "name": "Haruka ~ Dans une époque lointaine",
        "original_name": "遙かなる時空の中で ～八葉抄～",
        "first_air_date": "2004-10-05",
        "popularity": 7.1021, "vote_count": 5, "original_language": "ja",
    },
    {
        "id": 66888, "name": "Dans la peau d'une autre",
        "original_name": "En Otra Piel",
        "first_air_date": "2014-02-18",
        "popularity": 5.9967, "vote_count": 14, "original_language": "es",
    },
]

_GALAXIE_QUERY = "Dans Une Galaxie Pres De Chez Vous"
_GALAXIE_PARTS = ["Dans", "Une", "Galaxie", "Pres", "De", "Chez", "Vous"]


# ============================================================
# Unitaires : _title_exact_score
# ============================================================

def test_title_exact_score_ignores_accents_cas_galaxie():
    """Le cas reel : "Pres" (release) == "près" (TMDB) -> match exact."""
    assert _title_exact_score(_GALAXIE_QUERY, _GALAXIE_SERIE, is_tv=True) == 3000


def test_title_exact_score_ignores_apostrophe_and_accents_movie():
    """L'apostrophe devient un espace dans le nom de release."""
    candidate = {
        "title": "Le Fabuleux Destin d'Amélie Poulain",
        "original_title": "Le Fabuleux Destin d'Amélie Poulain",
    }
    assert _title_exact_score(
        "Le Fabuleux Destin D Amelie Poulain", candidate,
    ) == 3000


def test_title_exact_score_ignores_hyphen_and_colon():
    candidate = {
        "title": "Spider-Man : No Way Home",
        "original_title": "Spider-Man: No Way Home",
    }
    assert _title_exact_score("Spider Man No Way Home", candidate) == 3000


def test_title_exact_score_prefix_ignores_accents():
    """Prefixe (500) : la serie derivee commence par le titre cherche."""
    assert _title_exact_score(_GALAXIE_QUERY, _GALAXIE_25_ANS, is_tv=True) == 500


def test_title_exact_score_unrelated_title_stays_zero():
    """Garde-fou : la normalisation ne cree pas de faux match."""
    candidate = {
        "title": "Twilight, chapitre 2 : Tentation",
        "original_title": "The Twilight Saga: New Moon",
    }
    assert _title_exact_score("Moon", candidate) == 0
    for bruit in _BRUIT_DANS_UNE:
        assert _title_exact_score(_GALAXIE_QUERY, bruit, is_tv=True) == 0


def test_title_exact_score_non_latin_candidate_is_not_a_prefix_match():
    """Un titre non latin se vide a la normalisation : il ne doit ni matcher
    ni servir de prefixe universel."""
    candidate = {"title": "七人の侍", "original_title": "七人の侍"}
    assert _title_exact_score("Moon", candidate) == 0


def test_title_exact_score_non_latin_query_keeps_raw_exact_match():
    """Non-regression : une query non latine garde son match exact brut
    (la normalisation ASCII la viderait), sans matcher le reste."""
    assert _title_exact_score("七人の侍", {"title": "七人の侍"}) == 3000
    assert _title_exact_score("七人の侍", {"title": "Moon"}) == 0


def test_title_exact_score_empty_query_is_zero():
    assert _title_exact_score("", _GALAXIE_SERIE, is_tv=True) == 0
    assert _title_exact_score("...", _GALAXIE_SERIE, is_tv=True) == 0


def test_cache_entry_passes_relevance_accented_tv_title_without_year():
    """Un hit cache sur la bonne serie (sans annee) ne doit pas etre invalide."""
    assert _cache_entry_passes_relevance(
        _GALAXIE_QUERY, None, _GALAXIE_SERIE, "1999", is_tv=True,
    )


# ============================================================
# Integration : resolver TV, saison sans annee, titre accentue
# ============================================================

def _galaxie_fake_http(extra_search: dict | None = None):
    """fake http_get_with_retry rejouant les reponses TMDB reelles."""
    full_title_results = [_GALAXIE_SERIE, _GALAXIE_25_ANS]
    search = {
        _GALAXIE_QUERY: full_title_results,
        "Dans Une": [_BRUIT_DANS_UNE[0], _GALAXIE_SERIE, *_BRUIT_DANS_UNE[1:]],
    }
    if extra_search is not None:
        search = extra_search
    details = {
        "id": 13706, "name": "Dans une galaxie près de chez vous",
        "original_name": "Dans une galaxie près de chez vous",
        "first_air_date": "1999-01-25", "original_language": "fr",
        "vote_average": 7.5, "vote_count": 11,
        "genres": [], "external_ids": {"imdb_id": "tt0190177"},
        "credits": {"crew": [], "cast": []},
        "aggregate_credits": {"cast": [], "crew": []},
        "videos": {"results": []}, "keywords": {"results": []},
        "production_countries": [{"name": "Canada"}],
        "overview": "", "poster_path": "/g.jpg",
        "number_of_seasons": 4, "number_of_episodes": 65,
        "seasons": [
            {"season_number": 1, "episode_count": 13, "name": "Saison 1"},
            {"season_number": 2, "episode_count": 26, "name": "Saison 2"},
        ],
    }
    season_2 = {
        "season_number": 2, "overview": "",
        "episodes": [{"episode_number": 1, "name": "Ep 1", "runtime": 22}],
    }

    def fake_http(url, params=None, **kw):
        if "search/tv" in url:
            return _FakeResp(search.get((params or {}).get("query", ""), []))
        if "/tv/13706/season/2" in url:
            return _FakeResp(season_2)
        if "/tv/13706" in url:
            return _FakeResp(details)
        return _FakeResp({})

    return fake_http


def test_cas_galaxie_s02_sans_annee_resout_la_serie(monkeypatch, tmp_path):
    """Cas reel Louis : saison S02 sans annee, titre TMDB accentue.
    Avant le fix : ctx None + tmdb_match_rejected_low_relevance(13706)."""
    monkeypatch.setattr(_tmdb, "http_get_with_retry", _galaxie_fake_http())
    resolver = make_tv_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        _GALAXIE_PARTS, None, debug, season_num=2, release_lang_hint="fr",
    )
    assert ctx is not None
    assert ctx["tv_id"] == 13706
    assert ctx["season_number"] == 2
    assert debug.data.get("tmdb_match_rejected_low_relevance") is None


def test_cas_galaxie_sans_hint_langue_resout_aussi(monkeypatch, tmp_path):
    """Sans le bonus francophone (release MULTi), le titre exact doit suffire
    a faire gagner la serie sur le bruit de la query raccourcie."""
    monkeypatch.setattr(_tmdb, "http_get_with_retry", _galaxie_fake_http())
    resolver = make_tv_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(_GALAXIE_PARTS, None, debug, season_num=2)
    assert ctx is not None
    assert ctx["tv_id"] == 13706


def test_tv_sans_annee_titre_sans_rapport_reste_rejete(monkeypatch, tmp_path):
    """Garde-fou conserve : sans annee ET sans titre concordant, on prefere
    "pas de match" a un faux positif."""
    fake_http = _galaxie_fake_http(extra_search={
        _GALAXIE_QUERY: [_BRUIT_DANS_UNE[2]],
    })
    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tv_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(_GALAXIE_PARTS, None, debug, season_num=2)
    assert ctx is None
    rejected = debug.data.get("tmdb_match_rejected_low_relevance")
    assert rejected is not None
    assert rejected["id"] == 66888


# ============================================================
# Integration : resolver film (meme defaut, masque par l'annee)
# ============================================================

def test_movie_sans_annee_titre_accentue_resout(monkeypatch, tmp_path):
    """Variante film : sans annee dans le nom, le titre accentue + apostrophe
    doit quand meme etre reconnu comme match exact."""
    fake_results = [
        {
            "id": 194, "title": "Le Fabuleux Destin d'Amélie Poulain",
            "original_title": "Le Fabuleux Destin d'Amélie Poulain",
            "release_date": "2001-04-25",
            "popularity": 20.0, "vote_count": 11000,
            "original_language": "fr",
        },
    ]
    fake_details = {
        "id": 194, "title": "Le Fabuleux Destin d'Amélie Poulain",
        "original_title": "Le Fabuleux Destin d'Amélie Poulain",
        "release_date": "2001-04-25", "original_language": "fr",
        "runtime": 122, "vote_average": 7.9, "vote_count": 11000,
        "genres": [], "external_ids": {"imdb_id": "tt0211915"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [{"name": "France"}],
        "overview": "", "poster_path": "/a.jpg",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        if "/movie/194" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)
    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["Le", "Fabuleux", "Destin", "D", "Amelie", "Poulain"], None, debug,
    )
    assert ctx is not None
    assert ctx["movie_id"] == 194
    assert debug.data.get("tmdb_match_rejected_low_relevance") is None
