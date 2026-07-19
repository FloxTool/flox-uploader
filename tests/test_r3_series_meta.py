"""R3 (audit AUDIT_2026-07-19) : season_number/episode_number envoyes pour
TOUTES les categories serie (2, 6, 14, 15), pas seulement la cat 2.

Source : gemini/ TORRENT_API.txt p.4 — « Serie (TMDB) : oui » pour :
  2  Series
  6  Series Animations
  14 Series Documentaires
  15 Emission TV
Avant, seule la cat 2 les envoyait -> une serie d'animation/docu/emission
partait sans meta S/E (rejet API ou mauvaise indexation).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.gemini_api import UploadPayload
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_MOVIE,
    CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC,
    CATEGORY_SPORTS,
    CATEGORY_TV,
    CATEGORY_TV_ANIME,
    CATEGORY_TV_DOC,
    CATEGORY_TV_SHOW,
    SERIES_META_CATEGORIES,
)


def _payload(tmp_path: Path, category_id: int) -> UploadPayload:
    t = tmp_path / "f.torrent"
    t.write_bytes(b"d0:e")
    return UploadPayload(
        name="Foo.S01E02.1080p.WEB-DL.x265-TEAM",
        description="x",
        mediainfo="General",
        torrent_path=t,
        tmdb_id=42,
        category_id=category_id,
        type_id=4,
        resolution_id=2,
        season_number=1,
        episode_number=2,
    )


def test_series_meta_constant_matches_pdf():
    assert SERIES_META_CATEGORIES == {
        CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
    }


@pytest.mark.parametrize("cat", [
    CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
])
def test_series_categories_include_season_episode(tmp_path, cat):
    d = _payload(tmp_path, cat).to_form_data()
    assert d["season_number"] == 1
    assert d["episode_number"] == 2


@pytest.mark.parametrize("cat", [
    CATEGORY_MOVIE, CATEGORY_MOVIE_ANIME, CATEGORY_MOVIE_DOC, CATEGORY_SPORTS, 12,
])
def test_non_series_categories_omit_season_episode(tmp_path, cat):
    d = _payload(tmp_path, cat).to_form_data()
    assert "season_number" not in d
    assert "episode_number" not in d
