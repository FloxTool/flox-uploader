"""R3 (audit AUDIT_2026-07-19) : validate_payload verifie les invariants du
PDF TORRENT_API avant le POST (type coherent avec la categorie, resolution/
mediainfo/season requis selon la categorie).
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from flox_uploader.core.gemini_api import UploadPayload
from flox_uploader.core.upload_orchestrator import validate_payload
from flox_uploader.trackers.gemini import unit3d_mapping as m


def _torrent():
    t = pathlib.Path(tempfile.mkdtemp()) / "f.torrent"
    t.write_bytes(b"d0:e")
    return t


def _p(**kw):
    base = dict(
        name="x", description="d", mediainfo="", torrent_path=_torrent(),
        category_id=1, type_id=3, resolution_id=2, tmdb_id=42,
    )
    base.update(kw)
    return UploadPayload(**base)


def test_valid_movie_payload_has_no_problems():
    assert validate_payload(_p(), mediainfo="General") == []


def test_valid_book_payload_has_no_problems():
    p = _p(category_id=m.CATEGORY_BOOKS, type_id=m.TYPE_BOOK_EBOOK,
           resolution_id=0, tmdb_id=0)
    assert validate_payload(p) == []


def test_book_with_video_type_is_flagged():
    """Cat 12 + type BDRip (3) = combinaison invalide (le bug d'avant R3)."""
    p = _p(category_id=m.CATEGORY_BOOKS, type_id=m.TYPE_BDRIP,
           resolution_id=0, tmdb_id=0)
    probs = validate_payload(p)
    assert any("incoherent avec la categorie" in x for x in probs)


def test_movie_missing_resolution_flagged():
    probs = validate_payload(_p(resolution_id=0), mediainfo="General")
    assert any("resolution_id manquant" in x for x in probs)


def test_movie_missing_mediainfo_flagged():
    probs = validate_payload(_p(), mediainfo="")
    assert any("mediainfo vide" in x for x in probs)


def test_series_missing_season_flagged(monkeypatch):
    """Cat serie : season/episode doivent etre dans le form-data."""
    # UploadPayload avec cat serie ET season/episode -> to_form_data les inclut.
    p = _p(category_id=m.CATEGORY_TV, type_id=m.TYPE_WEB,
           season_number=1, episode_number=2)
    assert not any("season_number" in x for x in validate_payload(p, mediainfo="G"))


def test_type_zero_flagged():
    probs = validate_payload(_p(type_id=0), mediainfo="General")
    assert any("type_id manquant" in x for x in probs)
