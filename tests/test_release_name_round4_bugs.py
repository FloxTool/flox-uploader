"""Tests des 2 bugs release_name remontes round 4 :

1. Jurassic Park II → Jurassic World (cache TMDB obsolete avec ancien algo)
2. Metropolis [reprise 2011] (1927) → "Metropolis reprise" + year=2011
   au lieu de "Metropolis" + year=1927 (notation crochets meta-info)
"""
from __future__ import annotations

import re


def test_brackets_meta_info_stripped():
    """`[reprise 2011]` doit etre retire du source avant tokenization.

    Cas reel : "Metropolis [reprise 2011] (1927) Blu-ray..." -> doit donner
    title="Metropolis", year=1927 (pas 2011, pas "Metropolis reprise").
    """
    # On teste juste le regex de pre-cleaning, pas tout le pipeline
    original = "Metropolis [reprise 2011] (1927) Blu-ray 1080p HDLightHi-Res VOST dts-HD-MA-baron"
    cleaned = re.sub(r"\[[^\]]*\]", " ", original)
    assert "[" not in cleaned
    assert "]" not in cleaned
    assert "reprise" not in cleaned
    assert "2011" not in cleaned
    # Le reste est preserve
    assert "Metropolis" in cleaned
    assert "1927" in cleaned
    assert "Blu-ray" in cleaned


def test_brackets_with_year_only_stripped():
    """`[2011]` seul est aussi retire (annee meta-info, pas annee de prod)."""
    original = "Film [2011] (1995)"
    cleaned = re.sub(r"\[[^\]]*\]", " ", original)
    assert "2011" not in cleaned
    assert "1995" in cleaned


def test_nested_brackets_handled():
    """Cas tordu : crochets imbriques (rare mais defensif)."""
    original = "Film [a [nested] b] (2020)"
    # Notre regex est `[^\]]*` non-greedy -> ne match pas les imbrications
    # On accepte que le 1er '[' jusqu'au 1er ']' soit retire (= "[a [nested")
    cleaned = re.sub(r"\[[^\]]*\]", " ", original)
    # On a au moins le 1er crochet vire
    assert "[a [nested]" not in cleaned


def test_no_brackets_unchanged():
    """Sans crochets, rien ne change."""
    original = "Inception (2010) 1080p BluRay"
    cleaned = re.sub(r"\[[^\]]*\]", " ", original)
    assert cleaned == original


# ============================================================
# Cache TMDB versioning
# ============================================================

def test_cache_version_constant_exists():
    """Le constant _TMDB_CACHE_VERSION doit etre defini et >= 2."""
    from flox_uploader.core.tmdb import _TMDB_CACHE_VERSION
    assert isinstance(_TMDB_CACHE_VERSION, int)
    assert _TMDB_CACHE_VERSION >= 2


def test_is_cache_entry_fresh_missing_version():
    """Une entry sans `_cache_version` est consideree obsolete."""
    from flox_uploader.core.tmdb import _is_cache_entry_fresh
    cached = {"movie_id": 123, "title": "X"}  # pas de _cache_version
    assert _is_cache_entry_fresh(cached) is False


def test_is_cache_entry_fresh_old_version():
    """Une entry avec version < courant est obsolete."""
    from flox_uploader.core.tmdb import _is_cache_entry_fresh
    cached = {"movie_id": 123, "_cache_version": 1}
    # _TMDB_CACHE_VERSION = 2 actuellement
    assert _is_cache_entry_fresh(cached) is False


def test_is_cache_entry_fresh_current_version():
    """Une entry avec version courante est fraiche."""
    from flox_uploader.core.tmdb import _is_cache_entry_fresh, _TMDB_CACHE_VERSION
    cached = {"movie_id": 123, "_cache_version": _TMDB_CACHE_VERSION}
    assert _is_cache_entry_fresh(cached) is True


def test_is_cache_entry_fresh_invalid_type():
    """Une entry avec un _cache_version non-int est obsolete (defensif)."""
    from flox_uploader.core.tmdb import _is_cache_entry_fresh
    cached = {"movie_id": 123, "_cache_version": "v2"}
    assert _is_cache_entry_fresh(cached) is False
    cached = "not a dict"
    assert _is_cache_entry_fresh(cached) is False
