"""Tests Lot O.6 : bonus origine FR dans le ranking TMDB.

Cas reel rapporte par Louis : "La.Maison.2022.FRENCH.1080p.BluRay-ZiT".
Avant : on choisissait id 926899 (animation UK Netflix "The House",
original_language=en) parce qu'il avait plus de votes que id 960139
(drame franco-belge d'Anissa Bonnefont, IMDb tt17505492, original_language=fr).
Apres : si le release est tagge FR-only (FRENCH, VFF, etc. sans MULTi),
les candidats avec original_language=fr recoivent un bonus +2000 qui
suffit a departager les homonymes en cas d'egalite year+title, peu
importe leur pays d'origine (France, Belgique, Canada, Suisse, etc.).
"""
from __future__ import annotations

import pytest

from flox_uploader.core.tmdb import _detect_french_only_hint


# ============================================================
# _detect_french_only_hint
# ============================================================

def test_french_tag_without_multi_returns_fr():
    """FRENCH seul (pas de MULTi) -> hint='fr'"""
    assert _detect_french_only_hint(["FRENCH"]) == "fr"
    assert _detect_french_only_hint(["VFF"]) == "fr"
    assert _detect_french_only_hint(["VFQ"]) == "fr"
    assert _detect_french_only_hint(["VFB"]) == "fr"
    assert _detect_french_only_hint(["VF2"]) == "fr"
    assert _detect_french_only_hint(["VOF"]) == "fr"
    assert _detect_french_only_hint(["VOQ"]) == "fr"


def test_multi_present_returns_none():
    """MULTi.VFF -> pas de hint (release multi-langue)."""
    assert _detect_french_only_hint(["MULTi.VFF"]) is None
    assert _detect_french_only_hint(["MULTi"]) is None
    assert _detect_french_only_hint(["MULTI"]) is None


def test_no_lang_tags_returns_none():
    """Aucune lang -> None."""
    assert _detect_french_only_hint([]) is None
    assert _detect_french_only_hint(["VOSTFR"]) is None  # VOSTFR = sub fr, audio non-fr


def test_compound_tag_dotted():
    """Tags compounds : 'MULTi.VFF' = MULTi present donc None."""
    assert _detect_french_only_hint(["MULTi.VFF"]) is None
    # Mais 'VFF.x265' (theorique) reste FR si pas de MULTi
    assert _detect_french_only_hint(["VFF.x265"]) == "fr"


# ============================================================
# Test integration : ranking film avec bonus FR
# ============================================================

class _FakeResp:
    """Simule un resp TMDB minimal."""
    def __init__(self, results):
        self._results = results

    def json(self):
        return {"results": self._results}


@pytest.fixture
def fake_search(monkeypatch):
    """Patch http_get_with_retry pour retourner des resultats fakes selon
    la query/lang de la recherche TMDB."""
    from flox_uploader.core import tmdb as _tmdb

    # Resultats simules pour "La Maison" 2022 :
    # - id 926899 : The House (animation UK Netflix), original_language=en, votes=1128
    # - id 960139 : La Maison (drame franco-belge d'Anissa Bonnefont,
    #              IMDb tt17505492), original_language=fr, votes=50
    # En realite, la search TMDB renvoie BOTH dans les resultats.
    fake_results = [
        {
            "id": 926899, "title": "La Maison", "original_title": "The House",
            "release_date": "2022-01-14", "popularity": 2.6675,
            "vote_count": 1128, "original_language": "en",
        },
        {
            "id": 960139, "title": "La Maison", "original_title": "La Maison",
            "release_date": "2022-09-01", "popularity": 1.5,
            "vote_count": 50, "original_language": "fr",
        },
    ]
    fake_details = {
        926899: {
            "id": 926899, "title": "La Maison", "original_title": "The House",
            "original_language": "en", "release_date": "2022-01-14",
            "overview": "", "runtime": 97, "vote_average": 7.0,
            "vote_count": 1128, "genres": [{"name": "Animation"}],
            "production_countries": [{"name": "United Kingdom"}],
        },
        960139: {
            "id": 960139, "title": "La Maison", "original_title": "La Maison",
            "original_language": "fr", "release_date": "2022-09-01",
            "overview": "", "runtime": 90, "vote_average": 6.5,
            "vote_count": 50, "genres": [{"name": "Drame"}],
            # Cas reel : franco-belge (Anissa Bonnefont). Le fix se base
            # sur original_language=fr, pas sur le pays — donc France,
            # Belgique, Canada, etc. tous matchent identiquement.
            "production_countries": [
                {"name": "France"}, {"name": "Belgium"},
            ],
        },
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        if "/movie/" in url:
            mid = int(url.rstrip("/").rsplit("/", 1)[-1])
            return _FakeResp([])  # not used
        return _FakeResp([])

    # Hack : remplacer http_get_with_retry par fake_http qui retourne
    # un objet avec .json()
    def fake_http_with_resp(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        # details : retourne un .json() qui matche le mid
        for mid, d in fake_details.items():
            if f"/movie/{mid}" in url:
                return _FakeResp(d)
        return _FakeResp({})

    # Le helper _FakeResp.json renvoie une liste pour search, un dict pour
    # details, donc on doit differentier. On ajuste :
    class _DetailsResp:
        def __init__(self, data):
            self._data = data
        def json(self):
            return self._data

    def fake_http2(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        for mid, d in fake_details.items():
            if f"/movie/{mid}" in url:
                return _DetailsResp(d)
        return _DetailsResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http2)
    return fake_results


def test_french_release_picks_french_origin_film(fake_search, tmp_path):
    """Cas reel La Maison 2022 : avec hint='fr', on DOIT choisir le film
    franco-belge d'Anissa Bonnefont (id 960139, IMDb tt17505492,
    original_language=fr) malgre ses 50 votes contre 1128 pour le film
    UK animation Netflix (id 926899, "The House", original_language=en)."""
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["La", "Maison"], "2022", debug,
        release_lang_hint="fr",
    )
    assert ctx is not None
    assert ctx["movie_id"] == 960139, (
        f"Expected 960139 (QC, FR origin), got {ctx['movie_id']} "
        "(le bonus origine FR n'a pas departage)"
    )


def test_multi_release_picks_popular_film(fake_search, tmp_path):
    """Inverse : si pas de hint (release MULTi), on prend le plus populaire
    = id 926899 (1128 votes) malgre original_language=en."""
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["La", "Maison"], "2022", debug,
        release_lang_hint=None,  # pas FR-only
    )
    assert ctx is not None
    # Sans bonus, le film UK avec 1128 votes l'emporte
    assert ctx["movie_id"] == 926899


def test_cache_key_includes_lang_hint(tmp_path):
    """Verification : 2 appels avec hint different ne partagent PAS le cache."""
    from flox_uploader.core.tmdb import _cache_key

    k1 = _cache_key("La Maison", "2022", lang_hint=None)
    k2 = _cache_key("La Maison", "2022", lang_hint="fr")
    assert k1 != k2
    assert k1 == "la maison|2022"
    assert k2 == "la maison|2022|fr"
