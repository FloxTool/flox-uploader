"""R1 (audit AUDIT_2026-07-19) : split_team ne doit plus avaler les tokens
techniques a tiret (WEB-DL, E-AC3, AC-3, DTS-HD, ...).

Bug corpus : "Flow.2024.2160p.AMZN.WEB-DL.DDP5.1.H.265-FLUX" produisait la
team "DL.DDP5.1.H.265-FLUX" (langue perdue, canaux doubles, 2 codecs) a score
100 "parfait". 7 noms etaient mange, 5 affiches >= 96, 1 uploade (#26255).
Une team Gemini est un token UNIQUE sans point.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.naming._helpers import split_team


@pytest.mark.parametrize("stem,expected_team", [
    ("Flow.2024.2160p.AMZN.WEB-DL.DDP5.1.H.265-FLUX", "FLUX"),
    ("Year.10.2024.1080p.AMZN.WEB-DL.DDP2.0.H.264-BYNDR", "BYNDR"),
    ("Le.sens.de.la.fete.2017.FRENCH.1080p.x264.AC-3.5.1-NoTag", "NoTag"),
    ("Movie.2024.MULTi.VFF.1080p.WEB-DL.DTS-HD.MA.5.1-AZAZE", "AZAZE"),
])
def test_split_team_rejects_dash_tech_tokens(stem, expected_team):
    _base, team = split_team(stem, "NoTAG")
    assert team == expected_team
    # La team ne doit jamais contenir un point (= separateur de tokens charte).
    assert "." not in team


@pytest.mark.parametrize("stem,expected_team", [
    ("Clean.2024.MULTi.VFF.1080p.BluRay.x265-QTZ", "QTZ"),
    ("Manga.T2.2023.FRENCH.CBZ-PapriKa+", "PapriKa+"),
    ("Show.2019.MULTi.VFF.1080p.BluRay.DD5.1.x265-mHDgz-Dread-Team",
     "mHDgz-Dread-Team"),
])
def test_split_team_preserves_legit_teams(stem, expected_team):
    """Les teams legitimes (mono-token, hyphenees, avec +) restent intactes."""
    _base, team = split_team(stem, "NoTAG")
    assert team == expected_team


def test_split_team_base_keeps_technical_tokens():
    """Les tokens techniques restent dans la base (pas avales par la team)."""
    base, team = split_team(
        "Flow.2024.2160p.AMZN.WEB-DL.DDP5.1.H.265-FLUX", "NoTAG"
    )
    assert team == "FLUX"
    assert "WEB-DL" in base
    assert "DDP5.1" in base
