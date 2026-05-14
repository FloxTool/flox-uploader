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
        torrent_source="Gemini",
        default_team="NoTAG",
        private=True,
    )
