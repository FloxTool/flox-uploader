"""Tests des helpers reutilisables dans core/upload_orchestrator.

Couvre les helpers extraits dans le Lot 4 architecture (§7.3) ET la lecture
de bundle (§6.2 _extract_size_bytes fallback).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flox_uploader.core.gemini_api import (
    DupConfidence,
    DuplicateCandidate,
    DuplicateCheckResult,
    GeminiAPIError,
)
from flox_uploader.core.package_state import (
    PackageState,
    PackageStateData,
    init_state,
    read_state,
    state_path,
    write_state,
)
from flox_uploader.core.upload_orchestrator import (
    _extract_size_bytes,
    _imdb_id_to_int,
    _media_type_from_debug,
    mark_aborted_duplicate,
    try_check_duplicate,
)


# ============================================================
# try_check_duplicate
# ============================================================

def test_try_check_duplicate_returns_none_when_no_inputs():
    client = MagicMock()
    result = try_check_duplicate(client, tmdb_id=0, size_bytes=0, release_name="")
    assert result is None
    client.check_duplicate.assert_not_called()


def test_try_check_duplicate_swallows_api_error_with_log(capsys):
    client = MagicMock()
    client.check_duplicate.side_effect = GeminiAPIError("boom")
    result = try_check_duplicate(
        client, tmdb_id=42, size_bytes=1000, release_name="Foo.2024",
    )
    assert result is None
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert "check_duplicate echoue" in captured.out


def test_try_check_duplicate_returns_result_on_success():
    client = MagicMock()
    expected = DuplicateCheckResult(
        confidence=DupConfidence.NONE, candidates=[],
    )
    client.check_duplicate.return_value = expected
    result = try_check_duplicate(
        client, tmdb_id=42, size_bytes=1000, release_name="Foo.2024",
    )
    assert result is expected


# ============================================================
# mark_aborted_duplicate
# ============================================================

@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    p = tmp_path / "Foo.2024.1080p.BluRay.x265-TEAM"
    p.mkdir()
    init_state(p, "Foo.2024.1080p.BluRay.x265-TEAM", "gemini")
    return p


def test_mark_aborted_duplicate_persists_fields(package_dir: Path):
    candidate = DuplicateCandidate(
        torrent_id=1234,
        name="Foo.2024.1080p.BluRay.x265-OTHER",
        url="https://gemini-tracker.org/torrents/1234",
        size_bytes=1_000_000,
        delta_pct=0.05,
        confidence=DupConfidence.CERTAIN,
    )
    dup = DuplicateCheckResult(
        confidence=DupConfidence.CERTAIN, candidates=[candidate],
        matched_via="tmdb",
    )
    mark_aborted_duplicate(package_dir, dup, note="test note", infohash="deadbeef")
    state = read_state(package_dir)
    assert state is not None
    assert state.state == PackageState.ABORTED_DUPLICATE
    assert state.existing_torrent_id == 1234
    assert state.existing_torrent_url == "https://gemini-tracker.org/torrents/1234"
    assert state.dedup_confidence == "certain"
    assert state.dedup_checked_at  # non-vide
    assert state.infohash == "deadbeef"


def test_mark_aborted_duplicate_handles_none_primary(package_dir: Path):
    """Si la liste candidats est vide (cas degenere), on doit accepter sans
    crasher (existing_torrent_id devient None / url vide)."""
    dup = DuplicateCheckResult(confidence=DupConfidence.NONE, candidates=[])
    mark_aborted_duplicate(package_dir, dup, note="test")
    state = read_state(package_dir)
    assert state is not None
    assert state.state == PackageState.ABORTED_DUPLICATE
    assert state.existing_torrent_id is None
    assert state.existing_torrent_url == ""


# ============================================================
# _extract_size_bytes : §6.2 fallback Torrent.size
# ============================================================

def test_extract_size_bytes_uses_mediainfo_first(tmp_path: Path):
    """Priorite : si debug a mediainfo_data.size_bytes, on l'utilise."""
    debug = {"mediainfo_data": {"size_bytes": 12345678}}
    fake_torrent = tmp_path / "fake.torrent"
    # On ne cree pas le fichier : la priorite mediainfo court-circuite la lecture.
    assert _extract_size_bytes(debug, fake_torrent) == 12345678


def test_extract_size_bytes_falls_back_to_torrent_when_missing(tmp_path: Path):
    """Sans mediainfo_data.size_bytes (cas legacy), on lit le .torrent.

    On utilise torf pour generer un .torrent valide a partir d'un fichier
    de taille connue. Test du chemin de fallback critique (§6.2 audit).
    """
    from torf import Torrent
    content = b"x" * 4096  # 4KB
    src = tmp_path / "video.mkv"
    src.write_bytes(content)
    t = Torrent(path=str(src))
    t.private = True
    t.trackers = [["http://localhost/announce"]]
    t.generate()
    torrent_path = tmp_path / "video.torrent"
    t.write(str(torrent_path))

    # debug vide -> doit retourner la taille via Torrent.size
    assert _extract_size_bytes({}, torrent_path) == 4096


def test_extract_size_bytes_returns_zero_on_unreadable_torrent(tmp_path: Path):
    """Si le .torrent est invalide / illisible, retourne 0 + log [WARN]."""
    bad = tmp_path / "broken.torrent"
    bad.write_text("not a torrent file at all")
    result = _extract_size_bytes({}, bad)
    assert result == 0


# ============================================================
# Helpers de bundle
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("tt0123456", 123456),
    ("tt9999999", 9999999),
    ("0123456", 123456),
    ("123456", 123456),
    ("", 0),
    (None, 0),
    ("not-a-number", 0),
    ("tt0", 0),
])
def test_imdb_id_to_int(raw, expected):
    assert _imdb_id_to_int(raw) == expected


# ============================================================
# F3 NOTES.md : overrides Unit3D dans build_upload_payload
# ============================================================

def test_build_upload_payload_uses_state_overrides(package_dir: Path, tmp_path: Path):
    """Si manual_category_id / manual_type_id / manual_resolution_id > 0
    dans le state, ils doivent override l'auto-detection (F3 NOTES.md)."""
    from flox_uploader.core.media_type import MediaType
    from flox_uploader.core.package_state import transition, PackageState
    from flox_uploader.core.upload_orchestrator import (
        PackageBundle, UploadConfig, build_upload_payload,
    )

    # On part d'un state PREPARED (deja init) et on pose les overrides
    transition(
        package_dir, PackageState.PREPARED,
        manual_category_id=2,    # = TV (au lieu d'auto)
        manual_type_id=2,        # = Remux
        manual_resolution_id=3,  # = 1080p
    )

    # Faux torrent + bundle minimal
    torrent_path = package_dir / "fake.torrent"
    torrent_path.write_bytes(b"d8:announce0:e")
    bundle = PackageBundle(
        package_dir=package_dir,
        release_name="Foo.2024.MULTi.VFF.2160p.WEB-DL.x265-TEAM",  # auto = movie/web-dl/2160p
        description="",
        mediainfo="",
        torrent_path=torrent_path,
        nfo_path=None,
        infohash="abc",
        size_bytes=1000,
        tmdb_id=42,
        imdb_id=999,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
    )
    cfg = UploadConfig(api_url="http://x", api_key="y")
    payload = build_upload_payload(bundle, cfg)

    # Les overrides ont pris effet (et pas l'auto-detection)
    assert payload.category_id == 2  # TV (overridden, sinon serait MOVIE=1)
    assert payload.type_id == 2      # Remux (overridden, sinon WEB-DL=4)
    assert payload.resolution_id == 3  # 1080p (overridden, sinon 2160p=2)


def test_build_upload_payload_falls_back_to_auto_when_no_override(package_dir: Path):
    """Sans override (= 0 dans le state), on utilise l'auto-detection
    via unit3d_mapping (release_name + media_type)."""
    from flox_uploader.core.media_type import MediaType
    from flox_uploader.core.upload_orchestrator import (
        PackageBundle, UploadConfig, build_upload_payload,
    )

    torrent_path = package_dir / "fake.torrent"
    torrent_path.write_bytes(b"d8:announce0:e")
    bundle = PackageBundle(
        package_dir=package_dir,
        release_name="Foo.2024.MULTi.VFF.2160p.WEB-DL.x265-TEAM",
        description="",
        mediainfo="",
        torrent_path=torrent_path,
        nfo_path=None,
        infohash="abc",
        size_bytes=1000,
        tmdb_id=42,
        imdb_id=999,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
    )
    cfg = UploadConfig(api_url="http://x", api_key="y")
    payload = build_upload_payload(bundle, cfg)
    # Auto-detection
    assert payload.category_id == 1  # MOVIE
    assert payload.type_id == 4      # WEB-DL
    assert payload.resolution_id == 2  # 2160p


def test_media_type_from_debug_default_movie():
    from flox_uploader.core.media_type import MediaType
    assert _media_type_from_debug({}) == MediaType.MOVIE


def test_media_type_from_debug_invalid_falls_back():
    from flox_uploader.core.media_type import MediaType
    assert _media_type_from_debug({"media_type": "garbage"}) == MediaType.MOVIE


def test_media_type_from_debug_tv_episode():
    from flox_uploader.core.media_type import MediaType
    assert _media_type_from_debug({"media_type": "tv_episode"}) == MediaType.TV_EPISODE
