"""Tests pour split_team : extraction du nom de team depuis un release_name.

Couvre les conventions :
- Scene classique : `-TEAM` colle au tiret (ex: `Foo.2024.x265-AMEN`)
- Crochets : `[TEAM]` a la fin (ex: `Foo 2024 [TEAM]`)
- Non-scene : ` -TEAM` espace avant le tiret (ex: `Foo (2024) ... -Punisher694`)
- Format Matrix : `... - TEAM` espaces des deux cotes
"""
from __future__ import annotations

import pytest

from flox_uploader.core.release_name import split_team


class TestSceneStyle:
    """Format scene : `-TEAM` colle, sans espace avant le tiret."""

    def test_basic_scene(self):
        base, team = split_team("Foo.2024.MULTi.VFF.1080p.BluRay.x265-AMEN", "NOTAG")
        assert team == "AMEN"
        assert base == "Foo.2024.MULTi.VFF.1080p.BluRay.x265"

    def test_scene_with_alphanumeric_team(self):
        base, team = split_team("Foo.2024.MULTi.VFF.1080p.BluRay.x265-Punisher694", "NOTAG")
        assert team == "Punisher694"


class TestBracketsStyle:
    """Format crochets : `[TEAM]` a la fin."""

    def test_basic_brackets(self):
        base, team = split_team("Foo.2024.1080p.BluRay [TEAM]", "NOTAG")
        assert team == "TEAM"

    def test_brackets_with_complex_team(self):
        base, team = split_team("Foo.2024 [Punisher694]", "NOTAG")
        assert team == "Punisher694"


class TestSpaceBeforeDashStyle:
    """REGRESSION (signale 2026-04-29) : format non-scene avec espace AVANT
    le tiret mais pas apres : `... 5.0 v2 -Punisher694`. Tous les patterns
    existants ratent ce cas (le pattern scene exige pas d'espace, le pattern
    Matrix exige des espaces des deux cotes). Resultat : la team etait
    perdue, default_team `NOTAG` retourne.

    Fix : ajouter un pattern intermediaire qui matche ` -TEAM` mais exige
    un team de 3+ caracteres alphanumeriques sans tiret/espace interne pour
    eviter les faux positifs.
    """

    def test_user_case_punisher694(self):
        name = "La Colline aux Coquelicots (2011) MULTi 1080p 10bits BluRay x265 AC3 5.0 v2 -Punisher694"
        base, team = split_team(name, "NOTAG")
        assert team == "Punisher694"
        assert "Punisher694" not in base

    def test_short_team_min_3_chars(self):
        """Team de 3+ caracteres OK."""
        base, team = split_team("Foo (2024) BluRay -ABC", "NOTAG")
        assert team == "ABC"

    def test_short_team_with_digits(self):
        base, team = split_team("Foo (2024) -X12", "NOTAG")
        assert team == "X12"


class TestNotMatchedAsTeam:
    """Cas qui doivent rejeter et retourner default_team (eviter les faux positifs)."""

    def test_single_letter_after_space_dash(self):
        """`-A` 1 caractere ne doit PAS etre team (probable continuation de titre)."""
        base, team = split_team("Mission Impossible -A 1996", "NOTAG")
        assert team == "NOTAG"

    def test_two_letters_after_space_dash(self):
        """`-II` 2 caracteres ne doit PAS etre team."""
        base, team = split_team("Star Wars Episode -II 2002", "NOTAG")
        assert team == "NOTAG"

    def test_no_dash_at_all(self):
        base, team = split_team("Foo Bar 2024", "NOTAG")
        assert team == "NOTAG"


class TestMatrixStyle:
    """Format `... - TEAM` avec espaces des deux cotes du tiret."""

    def test_basic_matrix_style(self):
        base, team = split_team("Matrix (1999) MULTi 1080p BluRay x265 - QTZ", "NOTAG")
        assert team == "QTZ"

    def test_matrix_with_alt_title_after_team(self):
        """`... - QTZ (The Matrix)` : on retire la parenthese finale puis team."""
        name = "Matrix (1999) MULTi 1080p BluRay x265 - QTZ (The Matrix)"
        base, team = split_team(name, "NOTAG")
        assert team == "QTZ"


class TestDefaultTeam:
    """Cas pathologiques ou on retombe sur default_team."""

    def test_empty_string(self):
        base, team = split_team("", "NOTAG")
        assert team == "NOTAG"

    def test_only_title(self):
        base, team = split_team("Just A Title 2024", "NOTAG")
        assert team == "NOTAG"
