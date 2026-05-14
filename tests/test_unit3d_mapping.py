"""Tests du mapping Unit3D pour Gemini.

On valide que les 3 cas reels rencontres pendant les dry-runs produisent
bien les IDs attendus, et qu'on couvre les variantes courantes du naming.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.media_type import MediaType
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_MOVIE,
    CATEGORY_TV,
    RESOLUTION_1080P,
    RESOLUTION_2160P,
    RESOLUTION_720P,
    RESOLUTION_OTHER,
    TYPE_BDRIP,
    TYPE_BLURAY,
    TYPE_DVDRIP,
    TYPE_ENCODE,
    TYPE_HDTV,
    TYPE_REMUX,
    TYPE_WEB_DL,
    TYPE_WEBRIP,
    category_id_for,
    resolution_id_for,
    type_id_for,
)


# ============================================================
# Categorie
# ============================================================

def test_category_movie():
    assert category_id_for(MediaType.MOVIE) == CATEGORY_MOVIE


def test_category_tv_episode():
    assert category_id_for(MediaType.TV_EPISODE) == CATEGORY_TV


def test_category_tv_season():
    assert category_id_for(MediaType.TV_SEASON) == CATEGORY_TV


def test_category_tv_integrale():
    assert category_id_for(MediaType.TV_INTEGRALE) == CATEGORY_TV


# ============================================================
# Type (la plus discriminante)
# ============================================================

@pytest.mark.parametrize("name,expected", [
    # WEBRip — cas reel GOAT (2160p WEBRip x265)
    ("GOAT.2026.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen", TYPE_WEBRIP),
    ("GOAT.2026.MULTi.VF2.2160p.DV.HDR10P.WEBRip.x265-Amen", TYPE_WEBRIP),
    # WEBRip cas Downton.Abbey
    ("Downton.Abbey.The.Grand.Finale.2025.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen", TYPE_WEBRIP),
    # WEB-DL detecte via .WEB. (cas delicieux)
    ("delicieux.2021.VOB.1080p.WEB.H.264-lost", TYPE_WEB_DL),
    # WEB-DL explicite
    ("Foo.2024.MULTi.VFF.1080p.WEB-DL.DDP5.1.H.264-TEAM", TYPE_WEB_DL),
    ("Foo.2024.WEBDL.1080p", TYPE_WEB_DL),
    # REMUX prioritaire sur BluRay
    ("Foo.2024.MULTi.VFF.2160p.UHD.BluRay.REMUX.HEVC.HDR.TrueHD.7.1-TEAM", TYPE_REMUX),
    # BluRay encode
    ("Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM", TYPE_ENCODE),
    # BDRip / DVDRip / HDTV
    ("Foo.2024.BDRip.1080p.x264-TEAM", TYPE_BDRIP),
    ("Foo.2024.DVDRip.x264-TEAM", TYPE_DVDRIP),
    ("Foo.S01E01.1080p.HDTV.x264-TEAM", TYPE_HDTV),
])
def test_type_id_for(name: str, expected: int):
    assert type_id_for(name) == expected, f"name={name}"


# ============================================================
# Resolution
# ============================================================

@pytest.mark.parametrize("name,expected", [
    ("Foo.2024.2160p.WEBRip-X", RESOLUTION_2160P),
    ("Foo.2024.UHD.BluRay-X", RESOLUTION_2160P),
    ("Foo.2024.4K.BluRay-X", RESOLUTION_2160P),
    ("Foo.2024.1080p.WEB-X", RESOLUTION_1080P),
    ("Foo.2024.720p.HDTV-X", RESOLUTION_720P),
    ("Foo.2024.unknown.x264-X", RESOLUTION_OTHER),
])
def test_resolution_id_for(name: str, expected: int):
    assert resolution_id_for(name) == expected, f"name={name}"


# ============================================================
# Cas reels de bout-en-bout (les 3 dry-runs qu'on a faits)
# ============================================================

def test_real_case_goat():
    """GOAT.2026.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen"""
    name = "GOAT.2026.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen"
    assert category_id_for(MediaType.MOVIE) == 1
    assert type_id_for(name) == 5         # webrip
    assert resolution_id_for(name) == 2   # 2160p


def test_real_case_downton():
    """Downton.Abbey.The.Grand.Finale.2025.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen"""
    name = "Downton.Abbey.The.Grand.Finale.2025.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen"
    assert category_id_for(MediaType.MOVIE) == 1
    assert type_id_for(name) == 5
    assert resolution_id_for(name) == 2


def test_real_case_delicieux():
    """delicieux.2021.VOB.1080p.WEB.H.264-lost"""
    name = "delicieux.2021.VOB.1080p.WEB.H.264-lost"
    assert category_id_for(MediaType.MOVIE) == 1
    assert type_id_for(name) == 4         # web-dl (via .WEB.)
    assert resolution_id_for(name) == 3   # 1080p


# ============================================================
# Doc PDF officielle (NOTES.md round 2) : IDs corrects + categories etendues
# ============================================================

def test_official_ids_match_pdf_doc():
    """Verifie que les IDs cles correspondent a la doc PDF officielle G3MINI.
    Plusieurs IDs Unit3Dup-G3MINI etaient FAUX (BDRip=25, DVDRip=24, WEBMux=26
    qui n'existe pas) — la doc officielle dit BDRip=3, DVDRip=13, etc."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        TYPE_FULL_DISC, TYPE_REMUX, TYPE_BDRIP, TYPE_WEB, TYPE_WEBRIP,
        TYPE_HDTV, TYPE_ISO, TYPE_DVD, TYPE_TVRIP, TYPE_DVDRIP, TYPE_VHSRIP,
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_GAME, CATEGORY_TV_ANIME,
        CATEGORY_MOVIE_ANIME, CATEGORY_SPORTS, CATEGORY_BOOKS,
        CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
        CATEGORY_SOFTWARE, CATEGORY_TRAINING,
    )
    # Categories
    assert CATEGORY_MOVIE == 1
    assert CATEGORY_TV == 2
    assert CATEGORY_GAME == 3
    assert CATEGORY_TV_ANIME == 6
    assert CATEGORY_MOVIE_ANIME == 7
    assert CATEGORY_SPORTS == 10
    assert CATEGORY_BOOKS == 12
    assert CATEGORY_MOVIE_DOC == 13
    assert CATEGORY_TV_DOC == 14
    assert CATEGORY_TV_SHOW == 15
    assert CATEGORY_SOFTWARE == 17
    assert CATEGORY_TRAINING == 18
    # Types (les IDs corrigés vs Unit3Dup-G3MINI)
    assert TYPE_FULL_DISC == 1
    assert TYPE_REMUX == 2
    assert TYPE_BDRIP == 3       # FIX : etait 25 dans Unit3Dup-G3MINI (faux)
    assert TYPE_WEB == 4
    assert TYPE_WEBRIP == 5
    assert TYPE_HDTV == 6
    assert TYPE_ISO == 7
    assert TYPE_DVD == 11
    assert TYPE_TVRIP == 12
    assert TYPE_DVDRIP == 13     # FIX : etait 24 dans Unit3Dup-G3MINI (faux)
    assert TYPE_VHSRIP == 38


# ============================================================
# Heuristique category_id_for via genres TMDB
# ============================================================

def test_category_animation_movie_via_tmdb_genres():
    """Genres TMDB contient 'Animation' -> CATEGORY_MOVIE_ANIME (7)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_MOVIE_ANIME
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"genres": ["Animation", "Family"]},
    )
    assert cat == CATEGORY_MOVIE_ANIME


def test_category_animation_tv_via_tmdb_genres():
    """Genres TMDB 'Animation' + media TV -> CATEGORY_TV_ANIME (6)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_TV_ANIME
    cat = category_id_for(
        MediaType.TV_SEASON,
        tmdb_context={"genres": ["Animation", "Comedy"]},
    )
    assert cat == CATEGORY_TV_ANIME


def test_category_documentary_movie_via_tmdb_genres():
    """Genres 'Documentary' -> CATEGORY_MOVIE_DOC (13). Anglais ou francais."""
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_MOVIE_DOC
    cat_en = category_id_for(MediaType.MOVIE, tmdb_context={"genres": ["Documentary"]})
    cat_fr = category_id_for(MediaType.MOVIE, tmdb_context={"genres": ["Documentaire"]})
    assert cat_en == CATEGORY_MOVIE_DOC
    assert cat_fr == CATEGORY_MOVIE_DOC


def test_category_documentary_tv_via_tmdb_genres():
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_TV_DOC
    cat = category_id_for(
        MediaType.TV_INTEGRALE,
        tmdb_context={"genres": ["Documentaire", "History"]},
    )
    assert cat == CATEGORY_TV_DOC


def test_category_default_movie_no_tmdb():
    """Sans tmdb_context : MOVIE -> 1, TV -> 2 (defaut classique)."""
    assert category_id_for(MediaType.MOVIE) == 1
    assert category_id_for(MediaType.TV_SEASON) == 2
    assert category_id_for(MediaType.TV_SEASON, tmdb_context={"genres": []}) == 2


def test_category_animation_takes_precedence_over_documentary():
    """Cas tordu : Animation + Documentaire -> Animation prioritaire (un anime
    documentaire est rare ; on suit l'usage scene FR qui range plutot dans
    Animations)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_MOVIE_ANIME
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"genres": ["Animation", "Documentary"]},
    )
    assert cat == CATEGORY_MOVIE_ANIME
