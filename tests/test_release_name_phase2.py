"""Tests Phase 2 : nouveaux comportements du release_name.

Couvre :
- Inference codec ↔ source (REMUX → HEVC, WEB-DL → H.265, WEBRip → x265)
- Detection writing library MediaInfo (override pour WEB-DL re-encode)
- Aliases convention Gemini : DoVi → DV, HDR10+ → HDR10P, DD+ → DDP
- Drop tokens : 10bit / 8bit / 12bit retires du release_name final
"""
from __future__ import annotations

import pytest

from flox_uploader.core.release_name import (
    _CANONICAL_CASE,
    _has_encode_library,
    _normalize_token_case,
    apply_replacements,
    infer_video_codec,
    is_silent_film,
    remove_tokens,
)


# ============================================================
# infer_video_codec
# ============================================================

class TestInferVideoCodec:
    """REMUX → codec natif (pas de re-encode)."""

    def test_remux_x265_to_hevc(self):
        assert infer_video_codec("x265", "REMUX") == "HEVC"

    def test_remux_x264_to_avc(self):
        assert infer_video_codec("x264", "REMUX") == "AVC"

    def test_remux_hevc_unchanged(self):
        assert infer_video_codec("HEVC", "REMUX") == "HEVC"

    def test_remux_avc_unchanged(self):
        assert infer_video_codec("AVC", "REMUX") == "AVC"

    """WEB-DL = capture native, pas re-encode."""

    def test_webdl_x265_no_mi_to_h265(self):
        assert infer_video_codec("x265", "WEB-DL", has_encode_library=False) == "H.265"

    def test_webdl_x264_no_mi_to_h264(self):
        assert infer_video_codec("x264", "WEB-DL", has_encode_library=False) == "H.264"

    def test_webdl_x265_with_encode_library_kept_as_x265(self):
        """Si MediaInfo confirme un encode (writing library x265), on garde x265
        meme sur source WEB-DL. Cas : team qui re-encode du WEB."""
        assert infer_video_codec("x265", "WEB-DL", has_encode_library=True) == "x265"

    def test_web_alias_treated_as_webdl(self):
        assert infer_video_codec("x265", "WEB", has_encode_library=False) == "H.265"

    """WEBRip / BDRip / TVRip / HDTV = forcement re-encode."""

    @pytest.mark.parametrize("source", ["WEBRip", "BDRip", "DVDRip", "HDRip", "HDTV", "TVRip"])
    def test_rip_sources_force_x265(self, source: str):
        assert infer_video_codec("x265", source) == "x265"

    @pytest.mark.parametrize("source", ["WEBRip", "BDRip", "DVDRip", "HDRip", "HDTV", "TVRip"])
    def test_rip_sources_force_x264(self, source: str):
        assert infer_video_codec("x264", source) == "x264"

    """BluRay = ambigu (untouched HEVC vs encode x265). MediaInfo decide."""

    def test_bluray_x265_no_mi_kept(self):
        assert infer_video_codec("x265", "BluRay") == "x265"

    def test_bluray_with_encode_library_x265(self):
        assert infer_video_codec("x265", "BluRay", has_encode_library=True) == "x265"

    """Cas non-x264/x265 : codec inchange."""

    @pytest.mark.parametrize("codec", ["AV1", "VP9", "MPEG-2", "VC-1"])
    def test_other_codecs_unchanged(self, codec: str):
        assert infer_video_codec(codec, "WEB-DL") == codec
        assert infer_video_codec(codec, "REMUX") == codec
        assert infer_video_codec(codec, "WEBRip") == codec

    """Edge cases : codec ou source absent."""

    def test_no_codec_returns_none(self):
        assert infer_video_codec(None, "REMUX") is None
        assert infer_video_codec("", "WEB-DL") == ""

    def test_no_source_returns_codec_unchanged(self):
        assert infer_video_codec("x265", None) == "x265"
        assert infer_video_codec("x265", "") == "x265"


# ============================================================
# _has_encode_library
# ============================================================

class TestHasEncodeLibrary:
    def test_format_hevc_x265(self):
        """Format typique : 'HEVC / x265' indique un encode x265."""
        mi = {"video": {"codec": "HEVC / x265"}}
        assert _has_encode_library(mi) is True

    def test_format_avc_x264(self):
        mi = {"video": {"codec": "AVC / x264"}}
        assert _has_encode_library(mi) is True

    def test_format_hevc_pure_no_lib(self):
        """HEVC sans suffixe = pas d'encode library detectee."""
        mi = {"video": {"codec": "HEVC"}}
        assert _has_encode_library(mi) is False

    def test_format_avc_pure_no_lib(self):
        mi = {"video": {"codec": "AVC"}}
        assert _has_encode_library(mi) is False

    def test_no_mediainfo(self):
        assert _has_encode_library(None) is False
        assert _has_encode_library({}) is False
        assert _has_encode_library({"video": None}) is False
        assert _has_encode_library({"video": {}}) is False


# ============================================================
# Aliases Gemini : DoVi -> DV, HDR10+ -> HDR10P, DD+ -> DDP
# ============================================================

class TestGeminiAliases:
    REPLACE = {
        "DOVI": "DV",
        "DOLBYVISION": "DV",
        "DV": "DV",
        "HDR10PLUS": "HDR10P",
        "HDR10+": "HDR10P",
        "HDR10P": "HDR10P",
        "DD+": "DDP",
        "DDPLUS": "DDP",
    }

    @pytest.mark.parametrize("input_token,expected", [
        ("DoVi", "DV"),
        ("DOVI", "DV"),
        ("DolbyVision", "DV"),
        ("DV", "DV"),
        ("HDR10+", "HDR10P"),
        ("HDR10PLUS", "HDR10P"),
        ("HDR10P", "HDR10P"),
        ("DD+", "DDP"),
        ("DDPlus", "DDP"),
    ])
    def test_alias_replacement(self, input_token: str, expected: str):
        assert apply_replacements(input_token, self.REPLACE) == expected

    def test_combined_release_name(self):
        """Sur un release_name complet : DoVi.HDR10+ -> DV.HDR10P."""
        rn = "GOAT.2026.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265-Amen"
        # split-team simule en passant la partie pre-team
        base = "GOAT.2026.MULTi.VF2.2160p.DoVi.HDR10+.WEBRip.E-AC3.5.1.x265"
        out = apply_replacements(base, self.REPLACE)
        assert ".DV." in out
        assert ".HDR10P." in out
        assert ".DoVi." not in out
        assert ".HDR10+." not in out


# ============================================================
# Drop tokens : 10bit / 8bit / 12bit
# ============================================================

class TestDropBitDepth:
    """Convention Gemini : on ne garde pas le bit depth dans le release_name."""

    def test_drop_10bit_canonical(self):
        out = remove_tokens("Foo.2024.1080p.10Bit.BluRay.x265", ["10Bit", "10BIT"])
        assert out == "Foo.2024.1080p.BluRay.x265"

    def test_drop_10bit_variants(self):
        # input lowercase
        assert remove_tokens("Foo.10bit.x265", ["10Bit", "10BIT"]) == "Foo.x265"
        # input uppercase
        assert remove_tokens("Foo.10BIT.x265", ["10Bit", "10BIT"]) == "Foo.x265"

    @pytest.mark.parametrize("token", ["8Bit", "12Bit", "8BIT", "12BIT"])
    def test_drop_other_bit_depths(self, token: str):
        out = remove_tokens(f"Foo.{token}.x265", [token])
        assert out == "Foo.x265"


# ============================================================
# Casse canonique : DV / HDR10P / 10Bit
# ============================================================

class TestSilentFilm:
    """Detection film muet (zxx ISO 639-2 = no linguistic content)."""

    def test_all_zxx_is_silent(self):
        mi = {"audio_tracks": [
            {"language": "zxx", "codec": "AC3"},
            {"language": "zxx", "codec": "FLAC"},
        ]}
        assert is_silent_film(mi) is True

    def test_single_zxx_track_is_silent(self):
        mi = {"audio_tracks": [{"language": "zxx", "codec": "AC3"}]}
        assert is_silent_film(mi) is True

    def test_zxx_uppercase_also_works(self):
        mi = {"audio_tracks": [{"language": "ZXX", "codec": "AC3"}]}
        assert is_silent_film(mi) is True

    def test_french_track_is_not_silent(self):
        mi = {"audio_tracks": [
            {"language": "fr", "codec": "AC3"},
            {"language": "en", "codec": "AC3"},
        ]}
        assert is_silent_film(mi) is False

    def test_mixed_zxx_and_fr_not_silent(self):
        """Une piste zxx + une piste fr = pas un film muet (la piste fr
        contient probablement les dialogues)."""
        mi = {"audio_tracks": [
            {"language": "zxx"},
            {"language": "fr"},
        ]}
        assert is_silent_film(mi) is False

    def test_no_audio_tracks_not_silent(self):
        """Pas d'audio du tout != muet (probable erreur de parse)."""
        assert is_silent_film({"audio_tracks": []}) is False
        assert is_silent_film({}) is False
        assert is_silent_film(None) is False


class TestAudioCodecCompoundCase:
    """REGRESSION (signale 2026-04-29) : les codecs audio composes (codec colle
    aux channels) etaient mal-casses par le fallback "Capitalize" :
    `DTS2.0` -> `Dts2.0`, `E-AC3.5.1` -> `E-ac3.5.1`, etc.
    Fix : detecter le pattern `<codec><sep?><X.Y>` dans `_normalize_token_case`.
    """

    @pytest.mark.parametrize("input_token,expected", [
        # Codecs sans tiret, channels collees (charte Gemini)
        ("DTS2.0", "DTS2.0"),
        ("DTS5.1", "DTS5.1"),
        ("DTS7.1", "DTS7.1"),
        ("DDP5.1", "DDP5.1"),
        ("DDP7.1", "DDP7.1"),
        ("DD5.1", "DD5.1"),
        ("AAC2.0", "AAC2.0"),
        ("AAC5.1", "AAC5.1"),
        ("AC35.1", "AC35.1"),
        ("AC32.0", "AC32.0"),
        ("TrueHD7.1", "TrueHD7.1"),
        # Codecs avec tiret -> point separateur conserve
        ("E-AC3.5.1", "E-AC3.5.1"),
        ("E-AC3.7.1", "E-AC3.7.1"),
        ("DTS-HDMA.5.1", "DTS-HDMA.5.1"),
        ("DTS-HD.5.1", "DTS-HD.5.1"),
        # Inputs en mauvaise casse -> normalises
        ("dts2.0", "DTS2.0"),
        ("Dts5.1", "DTS5.1"),
        ("ddp5.1", "DDP5.1"),
        ("e-ac3.5.1", "E-AC3.5.1"),
        ("truehd7.1", "TrueHD7.1"),
    ])
    def test_compound_audio_codec(self, input_token: str, expected: str):
        from flox_uploader.core.release_name import _normalize_token_case
        assert _normalize_token_case(input_token) == expected


class TestCanonicalCase:
    @pytest.mark.parametrize("input_token,expected", [
        ("dv", "DV"),
        ("DV", "DV"),
        ("dovi", "DV"),
        ("DoVi", "DV"),
        ("dolbyvision", "DV"),
        ("hdr10p", "HDR10P"),
        ("HDR10P", "HDR10P"),
        ("hdr10+", "HDR10P"),
        ("hdr10plus", "HDR10P"),
        ("10bit", "10Bit"),
        ("10BIT", "10Bit"),
        ("imax", "IMAX"),
    ])
    def test_canonical_case(self, input_token: str, expected: str):
        assert _normalize_token_case(input_token) == expected
