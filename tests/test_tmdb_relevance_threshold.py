"""Tests : seuil minimum de pertinence TMDB + detection encode elargie pour PGS.

Cas reel rapporte par Louis : "Les Septs Samourai 1954" (orthographe mauvaise)
matchait "Red Shoes and the Seven Dwarfs" (2019) alors qu'aucun signal de
pertinence ne liait les deux. Score = popularity brute uniquement.

Pour le PGS dans encode : meme release n'etait pas flagge en compliance
parce que le release_name n'avait pas de tag "BluRay/BDRip/WEBRip" — juste
"1080p.x264". Maintenant on detecte aussi via la presence d'un codec encode.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.compliance import Severity, check_compliance


def _mi(audio=None, subs=None, video=None):
    return {
        "container": "MATROSKA",
        "video": video or {"resolution_label": "1080p", "codec": "AVC / x264"},
        "audio_tracks": audio or [],
        "subtitle_tracks": subs or [],
    }


# ============================================================
# C3 elargi : PGS dans encode meme sans tag source explicite
# ============================================================

def test_pgs_in_release_with_x264_no_source_tag_is_warned():
    """Cas reel Red Shoes : "Red.Shoes...1080p.x264-mHDgz" (pas de BluRay/BDRip
    dans le nom mais x264 = encode). PGS uniquement -> WARN."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Red.Shoes.And.The.Seven.Dwarfs.1954.VOSTFR.1080p.AAC1.0.x264-mHDgz",
        _mi(subs=subs),
    )
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert len(sub_issues) == 1
    assert sub_issues[0].severity == Severity.WARN
    assert "uniquement" in sub_issues[0].message.lower()


def test_pgs_in_x265_release_is_warned():
    """Idem avec x265."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Movie.2020.MULTi.VFF.2160p.HDR.x265-TEAM",
        _mi(subs=subs),
    )
    assert any(i.field == "subtitles" for i in issues)


def test_pgs_with_hevc_tag_warned():
    """`HEVC` dans le nom = encode."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Movie.2020.HEVC-TEAM",
        _mi(subs=subs),
    )
    assert any(i.field == "subtitles" for i in issues)


def test_pgs_in_remux_still_ok():
    """REMUX reste tolere pour PGS, meme avec codec dans le nom."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Movie.2020.REMUX.HEVC-TEAM",
        _mi(subs=subs),
    )
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert sub_issues == []


def test_pgs_in_release_without_codec_still_skipped():
    """Si VRAIMENT aucun tag (ni source ni codec), on skip pour rester
    safe (cas Full Disc pure / autres)."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    # Release sans codec ni source — peut etre raw / inconnu
    issues = check_compliance(
        "Movie.2020-TEAM",
        _mi(subs=subs),
    )
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert sub_issues == []


# ============================================================
# TMDB seuil de pertinence : year_score=0 + title_score=0 -> rejet
# ============================================================

class _FakeResp:
    def __init__(self, data):
        self._data = data
    def json(self):
        return {"results": self._data} if isinstance(self._data, list) else self._data


def test_tmdb_rejects_match_with_zero_relevance_signals(monkeypatch, tmp_path):
    """Cas reel : "Les Septs Samourai" (mal ortho) matche "Red Shoes 2019"
    par defaut. year_score=0 (1954 vs 2019), title_score=0. Doit retourner
    None au lieu d'imposer un mauvais match."""
    from flox_uploader.core import tmdb as _tmdb
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    # Le pool ne contient QU'UN seul resultat sans rapport (2019)
    fake_results = [{
        "id": 486589,
        "title": "Red Shoes and the Seven Dwarfs",
        "original_title": "레드슈즈",
        "release_date": "2019-07-25",
        "popularity": 4.4,
        "vote_count": 1134,
        "original_language": "ko",
    }]

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["Les", "Septs", "Samourai"], "1954", debug,
    )
    # Doit etre None (year_score=0 + title_score=0 => match rejete)
    assert ctx is None, (
        "Expected None for low-relevance match, got: "
        f"{ctx.get('title') if ctx else ctx}"
    )


def test_tmdb_accepts_match_with_year_signal(monkeypatch, tmp_path):
    """Si year match (year_score > 0), on accepte meme sans title_score."""
    from flox_uploader.core import tmdb as _tmdb
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    # Le pool a un resultat avec year=1954 (year_score=5000) — accepte meme
    # si le titre ne match pas exactement
    fake_results = [{
        "id": 346,
        "title": "Les Sept Samouraïs",
        "original_title": "七人の侍",
        "release_date": "1954-04-26",
        "popularity": 20.0,
        "vote_count": 4000,
        "original_language": "ja",
    }]
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

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    _parts, ctx = resolver(
        ["Les", "Septs", "Samourai"], "1954", debug,
    )
    # Year match = 5000 -> match accepte malgre title_score=0
    assert ctx is not None
    assert ctx["movie_id"] == 346


def test_tmdb_accepts_match_with_title_signal(monkeypatch, tmp_path):
    """Title exact (title_score > 0), pas de year -> accepte."""
    from flox_uploader.core import tmdb as _tmdb
    from flox_uploader.core.tmdb import make_tmdb_resolver
    from flox_uploader.core.debug import Debug

    fake_results = [{
        "id": 100,
        "title": "Inception",
        "original_title": "Inception",
        "release_date": "2010-07-15",
        "popularity": 50.0,
        "vote_count": 30000,
        "original_language": "en",
    }]
    fake_details = {
        "id": 100, "title": "Inception", "original_title": "Inception",
        "release_date": "2010-07-15", "original_language": "en",
        "runtime": 148, "vote_average": 8.4, "vote_count": 30000,
        "genres": [], "external_ids": {"imdb_id": "tt1375666"},
        "credits": {"crew": [], "cast": []},
        "videos": {"results": []}, "keywords": {"keywords": []},
        "production_countries": [],
        "overview": "", "poster_path": "",
    }

    def fake_http(url, params=None, **kw):
        if "search/movie" in url:
            return _FakeResp(fake_results)
        if "/movie/100" in url:
            return _FakeResp(fake_details)
        return _FakeResp({})

    monkeypatch.setattr(_tmdb, "http_get_with_retry", fake_http)

    resolver = make_tmdb_resolver("test-key", tmp_path / "cache.json")
    debug = Debug(tmp_path / "debug")
    # Search "Inception" sans year -> year_score=0 mais title_score=1000
    _parts, ctx = resolver(["Inception"], None, debug)
    assert ctx is not None
    assert ctx["movie_id"] == 100
