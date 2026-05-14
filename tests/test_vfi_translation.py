"""Tests : detection VFi dans le NFO + traduction explicite vers VFF.

Cas reel rapporte par Louis : The.Time.Machine.2002 avec audio_track
title "AC-3 5.1 (VFI)". Avant : tombait sur le faux signal "VFF par defaut".
Apres : signal SIG_LANG_VFI_TO_VFF dedie qui dit la verite.
"""
from __future__ import annotations

from flox_uploader.core.nfo import infer_french_variant_from_nfo


# ============================================================
# Detection VFi dans les titres de track audio
# ============================================================

def test_vfi_in_track_title_detected_as_vff():
    """Cas reel The.Time.Machine.2002 : 'AC-3 5.1 (VFI)' → variant=VFF
    + flag vfi_detected=True."""
    nfo = """
General
Format                                   : Matroska

Audio #1
Format                                   : AC-3
Language                                 : French
Title                                    : AC-3 5.1 (VFI)

Audio #2
Format                                   : AC-3
Language                                 : English
Title                                    : AC-3 5.1
"""
    result = infer_french_variant_from_nfo(nfo)
    assert result["variant"] == "VFF"
    assert result["vfi_detected"] is True
    assert "VFF" in result["found_variants"]


def test_vfi_uppercase_variants():
    """VFI / VFi / vfi : tous detectes."""
    for tag in ("VFI", "VFi", "vfi", "(VFI)", " VFI "):
        nfo = f"""
Audio
Format : AC-3
Language : French
Title : Audio {tag} 5.1
"""
        result = infer_french_variant_from_nfo(nfo)
        assert result["variant"] == "VFF", f"Failed for tag '{tag}'"
        assert result["vfi_detected"] is True, f"Failed for tag '{tag}'"


def test_vff_explicit_no_vfi_flag():
    """Si VFF est explicite (pas VFi), vfi_detected reste False."""
    nfo = """
Audio
Format : AC-3
Language : French
Title : VFF 5.1
"""
    result = infer_french_variant_from_nfo(nfo)
    assert result["variant"] == "VFF"
    assert result["vfi_detected"] is False


def test_no_french_audio_no_vfi_flag():
    """Pas de piste FR du tout -> pas de flag vfi (trivial)."""
    nfo = """
Audio
Format : AC-3
Language : English
Title : Original VO
"""
    result = infer_french_variant_from_nfo(nfo)
    assert result["vfi_detected"] is False


# ============================================================
# Constantes du signal
# ============================================================

def test_sig_vfi_to_vff_constant_exists():
    from flox_uploader.core.naming_signals import (
        SIG_LANG_VFI_TO_VFF,
        SIGNAL_METADATA,
    )
    assert SIG_LANG_VFI_TO_VFF in SIGNAL_METADATA
    penalty, label = SIGNAL_METADATA[SIG_LANG_VFI_TO_VFF]
    # Penalite legere (info bleu, pas grave)
    assert penalty == 1
    assert "VFi" in label
    assert "VFF" in label
    # Le label doit etre informatif (pas le faux "VFF par defaut")
    assert "défaut" not in label.lower() or "traduit" in label.lower()


# ============================================================
# Integration : pipeline emet le bon signal
# ============================================================

def test_pipeline_vfi_emits_vfi_to_vff_not_default(monkeypatch, tmp_path):
    """Test integration : quand le NFO contient VFi, le pipeline emet
    SIG_LANG_VFI_TO_VFF et PAS SIG_LANG_DEFAULT_VFF_USED."""
    from flox_uploader.core.debug import Debug
    from flox_uploader.core.release_name import _enrich_language_from_nfo

    debug = Debug(tmp_path)
    inferred_nfo = {
        "variant": "VFF",
        "found_variants": ["VFF"],
        "audio_titles": ["AC-3 5.1 (VFI)", "AC-3 5.1"],
        "has_french_audio": True,
        "has_french_subtitle": True,
        "is_vostfr": False,
        "french_audio_count": 1,
        "vfi_detected": True,
    }
    mediainfo = {
        "audio_tracks": [
            {"language": "fr", "codec": "DD", "channels": "5.1"},
            {"language": "en", "codec": "DD", "channels": "5.1"},
        ],
    }
    new_lang = _enrich_language_from_nfo(
        lang=[],
        nfo_variant="VFF",
        force_fr=None,
        inferred_nfo=inferred_nfo,
        mediainfo_data=mediainfo,
        debug=debug,
    )
    # Le tag MULTi.VFF doit etre genere (2 pistes audio FR + EN)
    assert new_lang == ["MULTi.VFF"]
    # Le signal VFi doit etre present, le default NON
    sigs = debug.data.get("naming_signals") or {}
    assert sigs.get("lang_vfi_to_vff") is True
    # Le signal default ne doit PAS etre la (ce serait trompeur)
    assert sigs.get("lang_default_vff_used") is None or sigs.get("lang_default_vff_used") is False


def test_pipeline_no_vfi_emits_default_vff_when_unknown(monkeypatch, tmp_path):
    """Reciproque : si le NFO n'a pas VFi et pas de variante claire, on
    tombe sur le defaut VFF generique (signal lang_default_vff_used)."""
    from flox_uploader.core.debug import Debug
    from flox_uploader.core.release_name import _enrich_language_from_nfo

    debug = Debug(tmp_path)
    inferred_nfo = {
        "variant": None,                 # aucune variante detectee
        "found_variants": [],
        "audio_titles": ["", ""],
        "has_french_audio": True,
        "has_french_subtitle": False,
        "is_vostfr": False,
        "french_audio_count": 1,
        "vfi_detected": False,
    }
    mediainfo = {
        "audio_tracks": [
            {"language": "fr", "codec": "DDP", "channels": "5.1"},
            {"language": "en", "codec": "DDP", "channels": "5.1"},
        ],
    }
    _enrich_language_from_nfo(
        lang=[],
        nfo_variant=None,
        force_fr=None,
        inferred_nfo=inferred_nfo,
        mediainfo_data=mediainfo,
        debug=debug,
    )
    sigs = debug.data.get("naming_signals") or {}
    # On a bien le default (faute de mieux)
    assert sigs.get("lang_default_vff_used") is True
    # Pas de VFi (rien n'indique VFi dans ce cas)
    assert sigs.get("lang_vfi_to_vff") is None or sigs.get("lang_vfi_to_vff") is False
