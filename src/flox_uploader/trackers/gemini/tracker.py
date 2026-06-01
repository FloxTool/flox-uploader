"""Implementation Tracker pour Gemini (gemini-tracker.org)."""
from __future__ import annotations

from pathlib import Path

from ..base import Tracker, load_tracker_rules

GEMINI_DIR = Path(__file__).resolve().parent


def load_gemini_tracker(announce_url: str) -> Tracker:
    rules = load_tracker_rules(GEMINI_DIR)
    return Tracker(
        key="gemini",
        display_name="Gemini",
        announce_url=announce_url,
        rules=rules,
        # Sprint D.47 v0.5.0 (feedback Louis Le Grinch — bug qBittorrent
        # ne sync pas) : le tracker re-genere les .torrent avec
        # `Source: G3MINI` (cf. nom officiel des PDFs `G3MINI TR4CK3R - ...`).
        # On utilisait `Source: Gemini` localement -> infohash different
        # entre le .torrent original (cree par Flox) et le .torrent final
        # (telecharge du tracker apres upload). qBittorrent considere donc
        # 2 torrents distincts pour le meme fichier .mkv -> re-hash-check
        # + impossible de seeder le pre-uploaded local.
        # Verifie : 103 .torrent finalises dans torrents_to_seed/ ont tous
        # `Source: G3MINI`. Aucun avec `Gemini`. C'est le nom officiel.
        torrent_source="G3MINI",
        default_team="NoTAG",
        private=True,
    )
