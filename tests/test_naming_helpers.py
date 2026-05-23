"""Tests Sprint B.1 v0.5.0 : extraction des helpers naming vers naming/_helpers.py.

Verifie :
1. Les helpers extraits fonctionnent identiquement a leur ancien comportement.
2. Les anciens chemins d'import (`from flox_uploader.core.release_name import ...`)
   continuent de fonctionner via re-export -> retro-compat 100% NO-OP.
3. Les nouveaux chemins (`from flox_uploader.core.naming._helpers import ...`)
   sont disponibles pour les futures strategies non-video.

Cf. PLAN-MULTICAT.md §5.5 (extraction préparatoire NO-OP).
"""
from __future__ import annotations


# ============================================================
# Retro-compat : les anciens chemins d'import doivent marcher
# ============================================================

def test_release_name_reexports_split_team():
    """`from release_name import split_team` continue de fonctionner."""
    from flox_uploader.core.release_name import split_team
    assert callable(split_team)
    base, team = split_team("Test.2024.1080p.x265-TEAM", "NoTAG")
    assert base == "Test.2024.1080p.x265"
    assert team == "TEAM"


def test_release_name_reexports_normalize_separators():
    from flox_uploader.core.release_name import normalize_separators
    assert callable(normalize_separators)
    assert normalize_separators("Foo Bar Baz") == "Foo.Bar.Baz"


def test_release_name_reexports_collapse_dots():
    from flox_uploader.core.release_name import collapse_dots
    assert collapse_dots("a...b..c.") == "a.b.c"


def test_release_name_reexports_ascii_fold():
    from flox_uploader.core.release_name import ascii_fold
    assert ascii_fold("Capharnaüm") == "Capharnaum"
    assert ascii_fold("Dìdi") == "Didi"


def test_release_name_reexports_normalize_token_case():
    from flox_uploader.core.release_name import _normalize_token_case
    assert _normalize_token_case("bluray") == "BluRay"
    assert _normalize_token_case("x265") == "x265"
    assert _normalize_token_case("ddp5.1") == "DDP5.1"


def test_release_name_reexports_looks_minimal():
    from flox_uploader.core.release_name import _looks_minimal
    assert _looks_minimal("Just A Title") is True
    assert _looks_minimal("Some.2024.1080p.BluRay.x265") is False


def test_release_name_reexports_dedupe_keep_order():
    from flox_uploader.core.release_name import dedupe_keep_order
    assert dedupe_keep_order(["a", "B", "a", "b", "C"]) == ["a", "B", "C"]


def test_release_name_reexports_constants():
    """Les constantes mutualisees restent accessibles via release_name."""
    from flox_uploader.core.release_name import (
        _CANONICAL_CASE, _LOOKS_MINIMAL_TECH_PATTERN, _TECH_TOKENS, _TECH_UPPER,
    )
    assert "x265" in _TECH_TOKENS
    assert "X265" in _TECH_UPPER
    assert _CANONICAL_CASE["BLURAY"] == "BluRay"
    # Le pattern doit matcher un nom techy
    assert _LOOKS_MINIMAL_TECH_PATTERN.search("Foo.1080p.BluRay.x265") is not None


# ============================================================
# Nouveaux chemins : naming/_helpers.py est utilisable directement
# ============================================================

def test_new_path_helpers_module_loadable():
    """Le nouveau module naming/_helpers.py est importable."""
    from flox_uploader.core.naming import _helpers
    assert hasattr(_helpers, "split_team")
    assert hasattr(_helpers, "normalize_separators")
    assert hasattr(_helpers, "collapse_dots")
    assert hasattr(_helpers, "ascii_fold")
    assert hasattr(_helpers, "_normalize_token_case")
    assert hasattr(_helpers, "_looks_minimal")
    assert hasattr(_helpers, "dedupe_keep_order")
    assert hasattr(_helpers, "_TECH_TOKENS")
    assert hasattr(_helpers, "_TECH_UPPER")
    assert hasattr(_helpers, "_CANONICAL_CASE")
    assert hasattr(_helpers, "_LOOKS_MINIMAL_TECH_PATTERN")


def test_new_and_old_paths_return_same_object():
    """Old import (release_name) et new import (naming._helpers) doivent
    pointer sur le MEME objet en memoire — preuve qu'il n'y a pas eu de
    duplication accidentelle de code.
    """
    from flox_uploader.core import release_name as rn
    from flox_uploader.core.naming import _helpers
    assert rn.split_team is _helpers.split_team
    assert rn.normalize_separators is _helpers.normalize_separators
    assert rn._normalize_token_case is _helpers._normalize_token_case
    assert rn._TECH_TOKENS is _helpers._TECH_TOKENS
    assert rn._CANONICAL_CASE is _helpers._CANONICAL_CASE


# ============================================================
# Helpers individuels — comportement attendu
# ============================================================

def test_split_team_scene_dash():
    from flox_uploader.core.naming._helpers import split_team
    base, team = split_team("Movie.2024.1080p.BluRay.x265-Punisher694", "NoTAG")
    assert base == "Movie.2024.1080p.BluRay.x265"
    assert team == "Punisher694"


def test_split_team_preserves_team_case():
    """Casse signature de la team preservee (regle critique)."""
    from flox_uploader.core.naming._helpers import split_team
    _, team = split_team("Movie.2024-mHDgz", "NoTAG")
    assert team == "mHDgz", "La casse signature mHDgz NE DOIT PAS etre alteree"


def test_split_team_brackets():
    from flox_uploader.core.naming._helpers import split_team
    base, team = split_team("Movie.2024.1080p.BluRay.x265 [TEAM]", "NoTAG")
    assert team == "TEAM"
    assert "BluRay" in base


def test_split_team_no_team_fallback():
    """Sans team detectable, on retourne le default_team."""
    from flox_uploader.core.naming._helpers import split_team
    base, team = split_team("Just A Title", "NoTAG")
    assert team == "NoTAG"


def test_split_team_rejects_codec_as_team():
    """`x265` ne doit jamais etre traite comme team (token technique connu)."""
    from flox_uploader.core.naming._helpers import split_team
    _, team = split_team("Movie.2024.E-AC3.5.1.x265-Amen", "NoTAG")
    assert team == "Amen", f"Team attendue 'Amen', obtenu '{team}'"


def test_normalize_separators_dots():
    from flox_uploader.core.naming._helpers import normalize_separators
    assert normalize_separators("Foo Bar") == "Foo.Bar"
    assert normalize_separators("Foo Bar_Baz") == "Foo.Bar.Baz"


def test_normalize_separators_apostrophes():
    from flox_uploader.core.naming._helpers import normalize_separators
    assert normalize_separators("L'Homme") == "LHomme"
    assert normalize_separators("Don't Move") == "Dont.Move"


def test_normalize_separators_ascii_fold():
    from flox_uploader.core.naming._helpers import normalize_separators
    assert normalize_separators("Capharnaüm 2024") == "Capharnaum.2024"


def test_normalize_token_case_canonical():
    from flox_uploader.core.naming._helpers import _normalize_token_case
    assert _normalize_token_case("BLURAY") == "BluRay"
    assert _normalize_token_case("bluray") == "BluRay"
    assert _normalize_token_case("HEVC") == "HEVC"
    assert _normalize_token_case("multi") == "MULTi"


def test_normalize_token_case_audio_composed():
    from flox_uploader.core.naming._helpers import _normalize_token_case
    assert _normalize_token_case("ddp5.1") == "DDP5.1"
    assert _normalize_token_case("e-ac3.5.1") == "E-AC3.5.1"
    assert _normalize_token_case("truehd7.1") == "TrueHD7.1"


def test_normalize_token_case_title_word():
    """Mots du titre : capitalize la 1ere lettre."""
    from flox_uploader.core.naming._helpers import _normalize_token_case
    assert _normalize_token_case("matrix") == "Matrix"
    assert _normalize_token_case("delicieux") == "Delicieux"


def test_looks_minimal_detects_techy():
    from flox_uploader.core.naming._helpers import _looks_minimal
    assert _looks_minimal("Movie.2024.1080p.BluRay.x265-TEAM") is False
    assert _looks_minimal("Some.WEB-DL.MULTi") is False


def test_looks_minimal_detects_plain():
    from flox_uploader.core.naming._helpers import _looks_minimal
    assert _looks_minimal("Just A Plain Title") is True
    assert _looks_minimal("") is True


def test_dedupe_keep_order_case_insensitive():
    from flox_uploader.core.naming._helpers import dedupe_keep_order
    assert dedupe_keep_order(["VFF", "vff", "VFQ"]) == ["VFF", "VFQ"]
    assert dedupe_keep_order([]) == []
