"""Tests pour _resolution_label : classification de la resolution depuis
width + height MediaInfo.

Cas critiques :
- CinemaScope 2.39:1 (large + court) : se classe par WIDTH
- Academy 1.37:1 (carre, vieux films) : se classe par HEIGHT
- PAL vs NTSC (meme width 720) : se classe par HEIGHT
"""
from __future__ import annotations

import pytest

from flox_uploader.core.mediainfo_parser import _resolution_label


@pytest.mark.parametrize("label,w,h,expected", [
    # Standards
    ("UHD 3840x2160", 3840, 2160, "2160p"),
    ("Full HD 1920x1080", 1920, 1080, "1080p"),
    ("HD 1280x720", 1280, 720, "720p"),
    ("PAL 720x576", 720, 576, "576p"),
    ("NTSC 720x480", 720, 480, "480p"),

    # CinemaScope (2.39:1) : largeur pleine, hauteur reduite
    ("CinemaScope 2160p 3840x1606 (GOAT)", 3840, 1606, "2160p"),
    ("CinemaScope 1080p 1920x800", 1920, 800, "1080p"),
    ("CinemaScope 720p 1280x534", 1280, 534, "720p"),

    # Academy (1.37:1, vieux films) : hauteur pleine, largeur reduite
    ("Academy 1080p 1480x1080 (Laigle 1948)", 1480, 1080, "1080p"),
    ("Academy 4K 2880x2160", 2880, 2160, "2160p"),
    ("Academy 720p 988x720", 988, 720, "720p"),

    # Edge : pas de signal
    ("Empty", 0, 0, ""),
])
def test_resolution_label(label: str, w: int, h: int, expected: str):
    assert _resolution_label(w, h) == expected, f"cas: {label}"


class TestRegressions:
    """Cas reels rencontres en production qui ont reveles des bugs."""

    def test_laigle_1948_academy_format(self):
        """REGRESSION (signale 2026-04-29) : un film Academy 1.37:1 de 1948
        en master 1080p (1480x1080) etait classe en '720p' parce qu'on
        regardait uniquement la WIDTH. Fix : on classe par max(width, height)
        relative aux seuils respectifs."""
        assert _resolution_label(1480, 1080) == "1080p"

    def test_pal_vs_ntsc_disambiguation(self):
        """PAL 720x576 et NTSC 720x480 ont la meme width. Pour ces deux
        seuils, on doit prioriser la HEIGHT (a l'inverse des hautes
        resolutions ou la WIDTH discrimine bien CinemaScope vs Academy)."""
        assert _resolution_label(720, 576) == "576p"
        assert _resolution_label(720, 480) == "480p"

    def test_goat_cinemascope_4k(self):
        """Pour un Cinemascope 2.39:1 4K (3840x1606), c'est la WIDTH qui doit
        compter (la HEIGHT seule ferait classer en 1080p, ce qui est faux)."""
        assert _resolution_label(3840, 1606) == "2160p"
