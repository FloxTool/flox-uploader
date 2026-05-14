"""Tests des cas reels rapportes par Louis (NOTES.md round 3).

Couvre les bugs Lot O (detection / TMDB) et Lot P (enrichissement nom).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from flox_uploader.core.media_type import (
    EPISODE_PATTERNS,
    detect_media_type,
    _extract_season_episode,
)
from flox_uploader.core.release_name import (
    _AMBIGUOUS_DROP_TOKENS_UPPER,
    _enrich_audio_video_from_mediainfo,
    remove_tokens,
)


# ============================================================
# O.1 — Furiosa S01E265 : 1x265 ne doit plus matcher
# ============================================================

def test_o1_furiosa_5_1_x265_pas_classe_episode():
    """Le release `Furiosa.une.Saga.Mad Max.2024.MULTi.VFF.4K.2160p...5.1x265-Elcrackito`
    contient `5.1x265` qui matchait `1x265` -> S01E265 (faux). Doit retourner None."""
    name = "Furiosa.une.Saga.Mad Max.2024.MULTi.VFF.4K.2160p.10bit.HDR10Plus.DV.WEBRip.DDP.Atmos.5.1x265-Elcrackito"
    season, episode = _extract_season_episode(name)
    assert season is None and episode is None, (
        f"Got S{season}E{episode} on a movie name (false positive)"
    )


def test_o1_legit_1x01_alt_pattern_works():
    """Anciens releases scene type `Show.1x01.Episode.Title-TEAM` doivent
    encore matcher (pattern alt legit)."""
    season, episode = _extract_season_episode("Show.1x01.Episode-TEAM")
    assert (season, episode) == (1, 1)


def test_o1_s01e01_standard_pattern_works():
    season, episode = _extract_season_episode("Show.S01E15.Title-TEAM")
    assert (season, episode) == (1, 15)


def test_o1_x264_x265_codec_no_false_episode():
    """Codecs purs ne doivent jamais matcher comme episode."""
    for name in [
        "Movie.2024.1080p.x264-TEAM",
        "Movie.2024.2160p.x265-TEAM",
        "Movie.2024.1080p.H.264-TEAM",
        "Movie.2024.2160p.H.265-TEAM",
    ]:
        season, episode = _extract_season_episode(name)
        assert season is None and episode is None, f"false episode in {name!r}"


def test_o1_3_digit_alt_episode_rejected():
    """Le pattern alt '1x01' est borne a 99 max -> 1x265 rejette."""
    season, episode = _extract_season_episode("ClipName.1x265.Title")
    assert season is None and episode is None


def test_o1_episode_99_alt_pattern_works():
    """E99 max est OK pour le pattern alt."""
    season, episode = _extract_season_episode("Show.1x99.Title-TEAM")
    assert (season, episode) == (1, 99)


# ============================================================
# O.3 — Drop MAX/streaming services protege avant l'annee
# ============================================================

def test_o3_max_in_title_preserved():
    """Le mot 'Max' dans 'Mad Max' avant l'annee ne doit PAS etre drop."""
    text = "Furiosa.une.Saga.Mad.Max.2024.MULTi.VFF.4K.MAX-TEAM"
    out = remove_tokens(text, ["MAX", "4KLight"])
    # Avant 2024 -> on garde "Max" (mot du titre)
    assert "Max" in out.split(".")
    # Apres 2024 -> on drop "MAX" (service streaming)
    out_parts = out.split(".")
    year_idx = out_parts.index("2024")
    after_year = out_parts[year_idx + 1:]
    assert "MAX" not in after_year, (
        f"MAX (streaming service) doit etre drop apres l'annee, got: {after_year}"
    )


def test_o3_nf_streaming_drop_after_year():
    """NF (Netflix) drop apres l'annee mais pas avant."""
    text = "NF.Adventures.2024.MULTi.NF-TEAM"
    out = remove_tokens(text, ["NF"])
    parts = out.split(".")
    # Avant annee : "NF" garde (suppose mot du titre, peut-etre faux mais
    # heuristique conservatrice — l'user override si besoin).
    assert "NF" in parts[: parts.index("2024")]
    # Apres annee : "NF" drop.
    assert "NF" not in parts[parts.index("2024") + 1:]


def test_o3_safe_tokens_always_dropped():
    """Les tokens non ambigus (10bit, mHD, NoTAG) sont drop partout."""
    text = "Movie.10bit.2024.MULTi.NoTAG.mHD-TEAM"
    out = remove_tokens(text, ["10bit", "NoTAG", "mHD"])
    parts = out.split(".")
    assert "10bit" not in parts
    assert "NoTAG" not in parts
    assert "mHD" not in parts


def test_o3_ambiguous_tokens_constants_documented():
    """Verification que les tokens ambigus connus sont dans la liste."""
    assert "MAX" in _AMBIGUOUS_DROP_TOKENS_UPPER
    assert "NFLX" in _AMBIGUOUS_DROP_TOKENS_UPPER
    assert "ATMOS" in _AMBIGUOUS_DROP_TOKENS_UPPER


# ============================================================
# Lot P — Enrichissement audio + video depuis MediaInfo
# ============================================================

def _rules_min():
    """Forge un rules minimal compatible Lot L."""
    return {
        "audio_codec_tokens": ["DD", "DDP", "AAC", "DTS", "DTS-HDMA",
                                "TrueHD", "AC3", "E-AC3", "FLAC", "OPUS"],
        "audio_channel_tokens": ["1.0", "2.0", "5.1", "7.1", "6.1", "4.0"],
    }


def test_p1_dragons_2_aac_codec_ajoute():
    """Cas reel Dragons 2 : nom contient 5.1 mais pas de codec audio. MediaInfo
    dit AAC -> on ajoute AAC avant 5.1."""
    audio = ["5.1"]
    vcodec = "x265"
    mi = {
        "audio_tracks": [{
            "codec": "AAC", "channels": "5.1",
            "is_commentary": False, "is_audio_description": False,
        }],
        "video": {"codec": "HEVC / x265"},
    }
    audio_out, vcodec_out, signals = _enrich_audio_video_from_mediainfo(
        audio, vcodec, mi, _rules_min(),
    )
    assert "AAC" in audio_out
    assert "5.1" in audio_out
    # AAC doit etre AVANT 5.1 dans l'ordre
    assert audio_out.index("AAC") < audio_out.index("5.1")
    assert any("AAC" in s for s in signals)


def test_p2_i_am_love_ddp_2_0_ajoutes():
    """Cas reel I.Am.Love : nom n'a ni codec ni layout. MediaInfo dit DDP 2.0."""
    audio = []
    vcodec = "x264"
    mi = {
        "audio_tracks": [{
            "codec": "DDP", "channels": "2.0",
            "is_commentary": False, "is_audio_description": False,
        }],
        "video": {"codec": "AVC / x264"},
    }
    audio_out, _vcodec, signals = _enrich_audio_video_from_mediainfo(
        audio, vcodec, mi, _rules_min(),
    )
    assert "DDP" in audio_out
    assert "2.0" in audio_out


def test_p3_codec_present_pas_double_ajoute():
    """Si DDP est deja dans le nom, on ne l'ajoute pas."""
    audio = ["DDP", "5.1"]
    mi = {
        "audio_tracks": [{
            "codec": "DDP", "channels": "5.1",
            "is_commentary": False, "is_audio_description": False,
        }],
        "video": {"codec": "HEVC / x265"},
    }
    audio_out, _vc, signals = _enrich_audio_video_from_mediainfo(
        audio, "x265", mi, _rules_min(),
    )
    assert audio_out.count("DDP") == 1
    assert audio_out.count("5.1") == 1


def test_p4_compound_codec_layout_pas_double():
    """Compound DDP.5.1 deja present -> pas de double ajout."""
    audio = ["DDP.5.1"]
    mi = {
        "audio_tracks": [{
            "codec": "DDP", "channels": "5.1",
            "is_commentary": False, "is_audio_description": False,
        }],
        "video": {},
    }
    audio_out, _vc, signals = _enrich_audio_video_from_mediainfo(
        audio, None, mi, _rules_min(),
    )
    # On ne double pas DDP ni 5.1
    assert audio_out == ["DDP.5.1"]


def test_p5_vcodec_x265_ajoute_si_absent():
    """Si vcodec absent et MediaInfo dit HEVC -> on ajoute x265."""
    mi = {
        "audio_tracks": [],
        "video": {"codec": "HEVC / x265"},
    }
    _audio, vcodec_out, signals = _enrich_audio_video_from_mediainfo(
        [], None, mi, _rules_min(),
    )
    assert vcodec_out == "x265"


def test_p6_vcodec_x264_ajoute():
    mi = {"audio_tracks": [], "video": {"codec": "AVC / x264"}}
    _a, vc, _s = _enrich_audio_video_from_mediainfo(
        [], None, mi, _rules_min(),
    )
    assert vc == "x264"


def test_p7_vcodec_av1():
    mi = {"audio_tracks": [], "video": {"codec": "AV1"}}
    _a, vc, _s = _enrich_audio_video_from_mediainfo(
        [], None, mi, _rules_min(),
    )
    assert vc == "AV1"


def test_p8_skip_commentary_audio_track():
    """Une piste de commentaire ne doit pas etre prise comme principale."""
    audio = []
    mi = {
        "audio_tracks": [
            {"codec": "AC3", "channels": "2.0",
             "is_commentary": True, "is_audio_description": False},
            {"codec": "DDP", "channels": "5.1",
             "is_commentary": False, "is_audio_description": False},
        ],
        "video": {"codec": "HEVC / x265"},
    }
    audio_out, _vc, _s = _enrich_audio_video_from_mediainfo(
        audio, None, mi, _rules_min(),
    )
    # On doit prendre la 2e piste (DDP.5.1), pas la 1ere (commentary AC3.2.0)
    assert "DDP" in audio_out
    assert "AC3" not in audio_out


def test_p9_no_mediainfo_returns_unchanged():
    """Sans MediaInfo data, rien ne change."""
    audio = ["5.1"]
    audio_out, vc_out, signals = _enrich_audio_video_from_mediainfo(
        audio, None, None, _rules_min(),
    )
    assert audio_out == ["5.1"]
    assert vc_out is None
    assert signals == []


def test_p10_dts_hd_ma_token_canonique():
    """DTS-HD MA depuis MediaInfo -> token canonique 'DTS-HDMA'."""
    audio = ["5.1"]
    mi = {
        "audio_tracks": [{
            "codec": "DTS-HD MA", "channels": "5.1",
            "is_commentary": False, "is_audio_description": False,
        }],
        "video": {},
    }
    audio_out, _vc, _s = _enrich_audio_video_from_mediainfo(
        audio, None, mi, _rules_min(),
    )
    assert "DTS-HDMA" in audio_out
