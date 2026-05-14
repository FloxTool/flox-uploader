"""Tests NOTES round 7 : VFx -> VOx pour films FR natifs.

Cas reel : "Jusqu'au Déclin" (2020, film québécois natif, audio FR-CA
"Canadian"). Le pipeline taguait VFQ comme s'il s'agissait d'un doublage,
mais c'est la VO du film -> doit etre VOQ.

Regles (delegues a infer_fr_variant_from_tmdb) :
- tmdb_original_language='fr' + France parmi pays  -> VOF (France domine)
- tmdb_original_language='fr' + uniquement Canada  -> VOQ
- tmdb_original_language='fr' + uniquement Belgique -> VOB
- tmdb_original_language='fr' + autre              -> VOF (defaut)
- tmdb_original_language != 'fr'                   -> VFx (doublage)
"""
from __future__ import annotations

from flox_uploader.core.release_name import _enrich_language_from_nfo
from flox_uploader.core.debug import Debug


def _enrich(lang, nfo_variant, inferred, tmdb_ctx, tmp_path):
    debug = Debug(tmp_path / "debug")
    return _enrich_language_from_nfo(
        lang=lang,
        nfo_variant=nfo_variant,
        force_fr=None,
        inferred_nfo=inferred,
        mediainfo_data=None,
        debug=debug,
        tmdb_context=tmdb_ctx,
    )


def test_quebec_native_film_vfq_becomes_voq(tmp_path):
    """Jusqu'au Declin : original_language=fr + Canada -> VOQ."""
    tmdb_ctx = {
        "original_language": "fr",
        "production_countries": ["Canada"],
    }
    inferred = {"french_audio_count": 1, "audio_titles": ["Canadian"]}
    lang = _enrich([], "VFQ", inferred, tmdb_ctx, tmp_path)
    assert lang == ["VOQ"], f"Expected VOQ for Quebec native, got {lang}"


def test_france_native_film_vff_becomes_vof(tmp_path):
    """Film francais natif (production France) -> VOF."""
    tmdb_ctx = {
        "original_language": "fr",
        "production_countries": ["France"],
    }
    inferred = {"french_audio_count": 1, "audio_titles": ["French"]}
    lang = _enrich([], "VFF", inferred, tmdb_ctx, tmp_path)
    assert lang == ["VOF"]


def test_france_canada_coprod_picks_vof(tmp_path):
    """Coproduction France+Canada (France domine) -> VOF."""
    tmdb_ctx = {
        "original_language": "fr",
        "production_countries": ["France", "Canada"],
    }
    inferred = {"french_audio_count": 1, "audio_titles": ["French"]}
    lang = _enrich([], "VFQ", inferred, tmdb_ctx, tmp_path)
    assert lang == ["VOF"]


def test_belgium_native_vfb_becomes_vob(tmp_path):
    """Film belge natif -> VOB."""
    tmdb_ctx = {
        "original_language": "fr",
        "production_countries": ["Belgium"],
    }
    inferred = {"french_audio_count": 1, "audio_titles": ["Belgian French"]}
    lang = _enrich([], "VFB", inferred, tmdb_ctx, tmp_path)
    assert lang == ["VOB"]


def test_non_french_film_keeps_vfx(tmp_path):
    """Film US double en FR-CA -> reste VFQ (c'est bien un doublage)."""
    tmdb_ctx = {
        "original_language": "en",
        "production_countries": ["United States of America"],
    }
    inferred = {"french_audio_count": 1, "audio_titles": ["Canadian"]}
    lang = _enrich([], "VFQ", inferred, tmdb_ctx, tmp_path)
    assert lang == ["VFQ"], "Film US ne doit pas etre converti en VOQ"


def test_no_tmdb_context_falls_back_to_legacy(tmp_path):
    """Pas de contexte TMDB -> comportement legacy (pas de conversion)."""
    inferred = {"french_audio_count": 1, "audio_titles": ["Canadian"]}
    lang = _enrich([], "VFQ", inferred, None, tmp_path)
    assert lang == ["VFQ"]


def test_multi_language_native_fr_quebec(tmp_path):
    """Film QC natif + autres pistes audio (anglais) -> MULTi.VOQ."""
    tmdb_ctx = {
        "original_language": "fr",
        "production_countries": ["Canada"],
    }
    inferred = {
        "french_audio_count": 1,
        "audio_titles": ["Canadian", "English"],  # 1 FR + 1 EN
    }
    lang = _enrich([], "VFQ", inferred, tmdb_ctx, tmp_path)
    assert lang == ["MULTi.VOQ"]
