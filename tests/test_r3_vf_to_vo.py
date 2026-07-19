"""R3 (audit AUDIT_2026-07-19) : conversion VFx->VOx qui PRESERVE la region.

Bug : le CAS 2 de merge_multi_language appendait `tmdb_variant` (region
dominante TMDB, France pour une coprod) au lieu de `vf_to_vo[t]`. Un film
quebecois taggé VFQ ressortait VOF (score 100 « parfait », tag faux). La
valeur du dict n'etait jamais lue.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from flox_uploader.core.release_name import merge_multi_language

_RULES = json.loads(
    pathlib.Path(
        "src/flox_uploader/trackers/gemini/rules.json"
    ).read_text(encoding="utf-8")
)


def _run(tags, countries, out=None):
    return merge_multi_language(
        tags,
        _RULES,
        tmdb_context={
            "original_language": "fr",
            "production_countries": countries,
        },
        out_warnings=out,
    )


def test_vfq_coprod_france_preserves_quebec_region():
    """VFQ + coprod France+Canada : region preservee (VOQ), PAS VOF."""
    warns = []
    out = _run(["VFQ"], ["France", "Canada"], warns)
    assert out == ["VOQ"]           # region du tag preservee
    assert out != ["VOF"]           # le bug d'origine
    assert len(warns) == 1          # divergence region -> review


def test_vfq_pure_quebec_no_warning():
    warns = []
    out = _run(["VFQ"], ["Canada"], warns)
    assert out == ["VOQ"]
    assert warns == []


def test_vff_france_converts_silently():
    warns = []
    out = _run(["VFF"], ["France"], warns)
    assert out == ["VOF"]
    assert warns == []


def test_vfb_belgium_preserves_region():
    warns = []
    out = _run(["VFB"], ["Belgium"], warns)
    assert out == ["VOB"]
    assert warns == []


def test_vff_dubbing_not_converted():
    """TMDB non-fr (doublage) : le tag VFF reste VFF (pas de conversion VO)."""
    out = merge_multi_language(
        ["VFF"], _RULES,
        tmdb_context={"original_language": "en",
                      "production_countries": ["United States"]},
    )
    assert out == ["VFF"]
