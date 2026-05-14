"""Tests Lot L (rules.json extensions) + Lot M (CRF parser, config helpers)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader import config
from flox_uploader.core.mediainfo_parser import _extract_crf


# ============================================================
# Lot L : rules.json — nouvelles entrees
# ============================================================

@pytest.fixture(scope="module")
def rules() -> dict:
    p = Path(__file__).parent.parent / "src" / "flox_uploader" / "trackers" / "gemini" / "rules.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_l_brrip_in_source_tokens(rules):
    assert "BRRip" in rules["source_tokens"]


def test_l_dvdrip_in_source_tokens(rules):
    assert "DVDRip" in rules["source_tokens"]


def test_l_tvrip_in_source_tokens(rules):
    assert "TVRip" in rules["source_tokens"]


def test_l_brrip_normalisation(rules):
    """BRRIP en CAPS -> BRRip."""
    assert rules["replace_tokens"].get("BRRIP") == "BRRip"


def test_l_tvrip_normalisation(rules):
    assert rules["replace_tokens"].get("TVRIP") == "TVRip"


def test_l_he_aac_in_audio_codec_tokens(rules):
    assert "HE-AAC" in rules["audio_codec_tokens"]


def test_l_aac_lc_in_audio_codec_tokens(rules):
    assert "AAC-LC" in rules["audio_codec_tokens"]


def test_l_flac_in_audio_codec_tokens(rules):
    """FLAC etait absent de la liste audio_codec_tokens jusqu'au Lot L."""
    assert "FLAC" in rules["audio_codec_tokens"]


def test_l_vp9_in_video_codec_tokens(rules):
    assert "VP9" in rules["video_codec_tokens"]


def test_l_3d_tags_in_optional(rules):
    """3D / SBS / HSBS / TAB / HTAB / MVC sont des tags 3D scene legitimes."""
    optional = set(rules["allowed_optional_tokens"])
    for tag in ("3D", "SBS", "HSBS", "TAB", "HTAB", "MVC"):
        assert tag in optional, f"Tag 3D manquant : {tag}"


def test_l_dirfix_in_optional(rules):
    optional = set(rules["allowed_optional_tokens"])
    # On accepte les deux casses, l'une suffit (le pipeline normalise).
    assert "DiRFiX" in optional or "DIRFIX" in optional


def test_l_uncensored_in_optional(rules):
    assert "UNCENSORED" in rules["allowed_optional_tokens"]


def test_l_read_nfo_in_optional(rules):
    assert "READ.NFO" in rules["allowed_optional_tokens"]


def test_l_leak_in_optional(rules):
    assert "LEAK" in rules["allowed_optional_tokens"]


def test_l_nogrp_in_drop_tokens(rules):
    """NoGRP / NoTAG / NoGroup sont des marqueurs 'team manquante' a virer."""
    drops = set(rules["drop_tokens"])
    assert "NoGRP" in drops
    assert "NoTag" in drops or "NoTAG" in drops


# ============================================================
# Lot M : _extract_crf parser
# ============================================================

def test_m_extract_crf_x265():
    settings = (
        "cpuid=1111039 / frame-threads=4 / numa-pools=8,8 / wpp / pmode / "
        "pme / psy-rd=2.00 / crf=20.0 / qcomp=0.60 / qpmin=0 / qpmax=69 / "
        "qpstep=4"
    )
    assert _extract_crf(settings) == 20.0


def test_m_extract_crf_x264():
    settings = (
        "cabac=1 / ref=4 / deblock=1:-3:-3 / analyse=0x3:0x113 / me=umh / "
        "subme=8 / psy=1 / psy_rd=1.00:0.00 / crf=18.5 / qcomp=0.60"
    )
    assert _extract_crf(settings) == 18.5


def test_m_extract_crf_int_value():
    """Some encoders emit integer crf (no decimal)."""
    settings = "ref=4 / crf=22 / qcomp=0.60"
    assert _extract_crf(settings) == 22.0


def test_m_extract_crf_absent():
    """AV1 / VP9 souvent : pas de crf= dans Encoding_settings."""
    assert _extract_crf("preset=4 / aq-mode=2 / qp=23") is None


def test_m_extract_crf_empty():
    assert _extract_crf("") is None
    assert _extract_crf(None) is None  # type: ignore[arg-type]


# ============================================================
# Lot K : config.banned_teams_list()
# ============================================================

def test_banned_teams_empty(monkeypatch):
    monkeypatch.delenv("BANNED_TEAMS", raising=False)
    assert config.banned_teams_list() == []


def test_banned_teams_comma(monkeypatch):
    monkeypatch.setenv("BANNED_TEAMS", "TeamA,TeamB,TeamC")
    assert config.banned_teams_list() == ["TeamA", "TeamB", "TeamC"]


def test_banned_teams_semicolon(monkeypatch):
    monkeypatch.setenv("BANNED_TEAMS", "TeamA;TeamB; TeamC")
    assert config.banned_teams_list() == ["TeamA", "TeamB", "TeamC"]


def test_banned_teams_newline(monkeypatch):
    monkeypatch.setenv("BANNED_TEAMS", "TeamA\nTeamB\nTeamC")
    assert config.banned_teams_list() == ["TeamA", "TeamB", "TeamC"]


def test_banned_teams_mixed_separators(monkeypatch):
    monkeypatch.setenv("BANNED_TEAMS", "TeamA, TeamB;\nTeamC")
    assert config.banned_teams_list() == ["TeamA", "TeamB", "TeamC"]


def test_banned_teams_strips_empty(monkeypatch):
    monkeypatch.setenv("BANNED_TEAMS", "TeamA,,, ,TeamB,")
    assert config.banned_teams_list() == ["TeamA", "TeamB"]
