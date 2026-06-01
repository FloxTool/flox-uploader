"""Tests Sprint D.47 v0.5.0 — torrent_source = G3MINI (pas Gemini).

Cible feedback Louis : Le Grinch upload reussi mais qBittorrent ne sync
pas le seed. Cause racine : on creait les .torrent locaux avec `Source:
Gemini` alors que le tracker re-genere avec `Source: G3MINI` (nom
officiel). Infohash different -> qBT considere 2 torrents distincts.

Verification : 103 .torrent finalises dans torrents_to_seed/ ont tous
`Source: G3MINI`. Donc c'est bien le nom officiel.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_gemini_tracker_uses_g3mini_source():
    """torrent_source doit etre 'G3MINI' (et plus 'Gemini')."""
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://gemini-tracker.org/announce/test")
    assert tracker.torrent_source == "G3MINI"


def test_gemini_tracker_display_name_unchanged():
    """display_name reste 'Gemini' (cosmetique UI), seul Source change."""
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://gemini-tracker.org/announce/test")
    assert tracker.display_name == "Gemini"
    assert tracker.key == "gemini"


def test_create_torrent_writes_g3mini_source(tmp_path):
    """create_torrent doit embed Source=G3MINI dans le .torrent genere."""
    from torf import Torrent
    from flox_uploader.core.torrent import create_torrent
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://gemini-tracker.org/announce/test")

    source = tmp_path / "fake.mkv"
    source.write_bytes(b"x" * 1024 * 200)  # 200 KB

    torrent_path = tmp_path / "fake.torrent"
    create_torrent(
        source, torrent_path,
        announce_url=tracker.announce_url,
        source=tracker.torrent_source,
        private=tracker.private,
    )

    t = Torrent.read(str(torrent_path))
    assert t.source == "G3MINI", (
        f"Le champ Source devrait etre 'G3MINI', got '{t.source}'"
    )
    assert t.private is True
