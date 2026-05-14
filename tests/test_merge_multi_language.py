"""Tests pour merge_multi_language : determination de la variante FR.

Couvre les 4 cas principaux :
- CAS 1 : MULTi (multi-langues)
- CAS 2 : variante precise deja presente (VFF, VFQ, etc.) -> upgrade VFF→VOF si fr-original
- CAS 4 : FRENCH/FR generique -> TMDB en priorite, NFO en fallback
"""
from __future__ import annotations

import pytest

from flox_uploader.core.release_name import merge_multi_language


TMDB_FR_FRANCE = {
    "original_language": "fr",
    "production_countries": ["France"],
}
TMDB_FR_BE_FR = {
    "original_language": "fr",
    "production_countries": ["Belgium", "France"],
}
TMDB_FR_CANADA = {
    "original_language": "fr",
    "production_countries": ["Canada"],
}
TMDB_EN_USA = {
    "original_language": "en",
    "production_countries": ["United States of America"],
}


class TestCase4FrenchGeneric:
    """REGRESSION (signale 2026-04-29) : un release contenant `FRENCH` (et pas
    une variante precise comme VFF) pour un film d'origine francaise etait
    classifie en VFF a cause de l'inference NFO, sans tester TMDB en amont.

    Fix : tester TMDB AVANT le NFO. Seul TMDB peut trancher VO vs doublage.
    Le NFO ne sait que dire "il y a du francais" mais pas si c'est l'original.
    """

    def test_french_generic_with_tmdb_fr_france_returns_vof(self):
        """Cas user : Lart.Detre.Heureux + FRENCH + tmdb fr+France -> VOF."""
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',  # NFO infere VFF (audio FR)
            tmdb_context=TMDB_FR_FRANCE,
            french_audio_count=1,
        )
        assert r == ['VOF']

    def test_french_generic_with_tmdb_belgium_france(self):
        """Coproduction Belgique + France : VOF (France domine)."""
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',
            tmdb_context=TMDB_FR_BE_FR,
            french_audio_count=1,
        )
        assert r == ['VOF']

    def test_french_generic_with_tmdb_canada_returns_voq(self):
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',
            tmdb_context=TMDB_FR_CANADA,
            french_audio_count=1,
        )
        assert r == ['VOQ']

    def test_french_generic_with_foreign_tmdb_falls_back_to_nfo(self):
        """Film americain doublage FR : pas VOF, on prend nfo_variant=VFF."""
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',
            tmdb_context=TMDB_EN_USA,
            french_audio_count=1,
        )
        assert r == ['VFF']

    def test_french_generic_no_tmdb_falls_back_to_nfo(self):
        """Pas de match TMDB : on utilise nfo_variant."""
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',
            tmdb_context=None,
            french_audio_count=1,
        )
        assert r == ['VFF']

    def test_force_fr_overrides_everything(self):
        """force_fr=VFF prevaut sur TMDB et NFO."""
        r = merge_multi_language(
            ['FRENCH'], {},
            nfo_variant='VFF',
            force_fr='VFF',
            tmdb_context=TMDB_FR_FRANCE,
            french_audio_count=1,
        )
        assert r == ['VFF']

    def test_force_vof_directly(self):
        """force_fr=VOF accepte (depuis l'ajout de VOF a ALLOWED_FORCE_FR)."""
        r = merge_multi_language(
            ['FRENCH'], {},
            force_fr='VOF',
            tmdb_context=None,
            french_audio_count=1,
        )
        assert r == ['VOF']


class TestCase2PreciseVariant:
    """CAS 2 : variante precise deja presente (VFF). Upgrade VFF→VOF si TMDB fr-original."""

    def test_vff_with_tmdb_fr_france_upgrades_to_vof(self):
        """Cas que mon test direct verifiait : VFF + tmdb fr+France -> VOF."""
        r = merge_multi_language(
            ['VFF'], {},
            tmdb_context=TMDB_FR_FRANCE,
        )
        assert r == ['VOF']

    def test_vff_with_foreign_tmdb_keeps_vff(self):
        r = merge_multi_language(
            ['VFF'], {},
            tmdb_context=TMDB_EN_USA,
        )
        assert r == ['VFF']

    def test_vff_with_no_tmdb_keeps_vff(self):
        r = merge_multi_language(['VFF'], {}, tmdb_context=None)
        assert r == ['VFF']


def test_multi_no_precision_film_no_die_just_warns():
    """Phase 3b.3 : MULTi ambigu sur un film ne tue plus le pipeline ;
    on retourne ['MULTi'] et on note un warning dans out_warnings."""
    from flox_uploader.core.release_name import merge_multi_language

    warnings: list[str] = []
    r = merge_multi_language(
        ["MULTI"],
        rules={"require_precise_multi_language": True},
        nfo_variant=None,
        force_fr=None,
        tmdb_context=None,
        is_vostfr_from_nfo=False,
        french_audio_count=2,         # film avec FR audio detecte = ambigu
        is_tv_series=False,
        out_warnings=warnings,
    )
    assert r == ["MULTi"]
    assert len(warnings) == 1
    assert "VFF" in warnings[0] or "VFQ" in warnings[0]


def test_multi_no_precision_film_no_audio_no_die():
    """Idem mais avec 0 piste FR : warning emis aussi (require_precise=True)."""
    from flox_uploader.core.release_name import merge_multi_language

    warnings: list[str] = []
    r = merge_multi_language(
        ["MULTI"],
        rules={"require_precise_multi_language": True},
        nfo_variant=None,
        force_fr=None,
        tmdb_context=None,
        is_vostfr_from_nfo=False,
        french_audio_count=0,
        is_tv_series=False,
        out_warnings=warnings,
    )
    assert r == ["MULTi"]
    assert len(warnings) == 1
