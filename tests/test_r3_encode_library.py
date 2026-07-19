"""R3 (audit AUDIT_2026-07-19) : _has_encode_library lit la VRAIE writing
library, pas le champ codec (ancienne tautologie).

Avant : _has_encode_library lisait video["codec"] = "HEVC / x265" -> toujours
True -> la regle « WEB untouched -> H.264/H.265 » ne s'appliquait jamais (111
packages WEB du corpus etaient tous en x26x, en violation du PDF nommage).
"""
from __future__ import annotations

from flox_uploader.core.release_name import _has_encode_library, infer_video_codec


def _mi(writing_library="", encoding_settings="", codec="HEVC / x265"):
    return {"video": {
        "codec": codec,
        "writing_library": writing_library,
        "encoding_settings": encoding_settings,
    }}


def test_untouched_web_is_not_an_encode():
    """WEB-DL natif : pas de writing library -> pas un encode."""
    assert _has_encode_library(_mi()) is False


def test_x265_library_is_an_encode():
    assert _has_encode_library(_mi(writing_library="x265 - 3.5")) is True


def test_x264_library_is_an_encode():
    assert _has_encode_library(_mi(writing_library="x264")) is True


def test_encoding_settings_signal():
    """Sans library mais avec des reglages crf/preset -> encode."""
    assert _has_encode_library(_mi(encoding_settings="cabac=1 / crf=20.0")) is True


def test_web_dl_untouched_yields_h265():
    """La regle du PDF : WEB untouched -> H.265 (plus x265)."""
    mi = _mi()
    assert infer_video_codec("HEVC", "WEB-DL", _has_encode_library(mi)) == "H.265"


def test_web_encode_yields_x265():
    mi = _mi(writing_library="x265")
    assert infer_video_codec("HEVC", "WEB-DL", _has_encode_library(mi)) == "x265"


def test_legacy_debug_without_field_falls_back_to_codec():
    """debug.json d'avant R3 (pas de writing_library) : ancien heuristique."""
    legacy = {"video": {"codec": "HEVC / x265"}}
    assert _has_encode_library(legacy) is True
