"""Tests Sprint D.48 v0.5.0 — Source forcee + compliance warning.

Cible feedback Louis (batch upload depuis dev) : releases amateurs FR
sans NFO scene + sans source dans le nom d'origine -> SOURCE manquante
dans le release_name (non conforme charte Gemini).

Cas reels Louis :
  - La.Guerre.Des.Boutons.1962.VOF.1080p.AAC1.0.x264-mHDgz
  - Polisse.2011.VOF.1080p.AAC5.1.x265-NoTAG
  - Le.Placard.2001.VOF.1080p.AC35.1.x264-GOLDORAK
  - Hibernatus.1969.VOF.1080p.AC32.0.H.264-LiHDL
  - Le.Sens.De.La.Fete.2017.VOF.1080p.DD5.1.x264-3.5.1-NoTag
"""
from __future__ import annotations

import pytest


_RULES = {
    "source_tokens": [
        "BluRay", "WEB", "WEBRip", "WEB-DL", "HDRip", "BDRip", "BRRip",
        "REMUX", "HDTV", "DVD", "DVDRip", "TVRip",
    ],
}


# ============================================================
# release_has_source
# ============================================================

class TestReleaseHasSource:
    """Detecte si un release_name contient un token SOURCE connu."""

    def test_bluray_detected(self):
        from flox_uploader.core.release_name import release_has_source
        assert release_has_source(
            "Beetlejuice.1988.MULTi.VFF.2160p.DV.HDR.BluRay.DDP5.1.x265-QTZ",
            _RULES,
        )

    def test_web_dl_detected(self):
        from flox_uploader.core.release_name import release_has_source
        assert release_has_source(
            "Movie.2024.MULTi.VFF.1080p.WEB-DL.E-AC3.5.1.x265-Team",
            _RULES,
        )

    def test_webrip_detected(self):
        from flox_uploader.core.release_name import release_has_source
        assert release_has_source(
            "Movie.2024.MULTi.VFF.1080p.WEBRip.AAC.x265-Team",
            _RULES,
        )

    def test_remux_detected(self):
        from flox_uploader.core.release_name import release_has_source
        assert release_has_source(
            "Movie.2024.MULTi.VFF.2160p.REMUX.HEVC-Team",
            _RULES,
        )

    def test_louis_cases_no_source(self):
        """Cas Louis : tous ces releases AMATEURS FR n'ont PAS de source."""
        from flox_uploader.core.release_name import release_has_source
        cases = [
            "La.Guerre.Des.Boutons.1962.VOF.1080p.AAC1.0.x264-mHDgz",
            "Polisse.2011.VOF.1080p.AAC5.1.x265-NoTAG",
            "Le.Placard.2001.VOF.1080p.AC35.1.x264-GOLDORAK",
            "Hibernatus.1969.VOF.1080p.AC32.0.H.264-LiHDL",
            "Le.Sens.De.La.Fete.2017.VOF.1080p.DD5.1.x264-3.5.1-NoTag",
        ]
        for c in cases:
            assert not release_has_source(c, _RULES), f"Faux positif sur {c}"

    def test_empty_release_name(self):
        from flox_uploader.core.release_name import release_has_source
        assert not release_has_source("", _RULES)


# ============================================================
# inject_source_if_missing
# ============================================================

class TestInjectSource:
    """Injecte une SOURCE quand absente du release_name."""

    def test_inject_after_resolution(self):
        """1080p -> BluRay inject apres 1080p, avant AAC."""
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "La.Guerre.Des.Boutons.1962.VOF.1080p.AAC1.0.x264-mHDgz",
            "BluRay", _RULES,
        )
        assert result == "La.Guerre.Des.Boutons.1962.VOF.1080p.BluRay.AAC1.0.x264-mHDgz"

    def test_inject_polisse(self):
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Polisse.2011.VOF.1080p.AAC5.1.x265-NoTAG", "BluRay", _RULES,
        )
        assert result == "Polisse.2011.VOF.1080p.BluRay.AAC5.1.x265-NoTAG"

    def test_inject_resolution_2160p(self):
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Movie.2024.MULTi.VFF.2160p.DDP5.1.x265-Team", "BluRay", _RULES,
        )
        assert "2160p.BluRay.DDP5.1.x265-Team" in result

    def test_inject_resolution_720p(self):
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Movie.2010.VFF.720p.AAC.x264-Test", "BluRay", _RULES,
        )
        assert "720p.BluRay.AAC.x264-Test" in result

    def test_inject_noop_if_already_has_source(self):
        """Si BluRay deja present, on ne touche pas, meme si manual_source diff."""
        from flox_uploader.core.release_name import inject_source_if_missing
        original = "Beetlejuice.1988.MULTi.VFF.2160p.BluRay.DDP5.1.x265-QTZ"
        result = inject_source_if_missing(original, "WEB-DL", _RULES)
        assert result == original

    def test_inject_noop_if_manual_source_empty(self):
        from flox_uploader.core.release_name import inject_source_if_missing
        original = "Movie.2024.1080p.x264-Team"
        assert inject_source_if_missing(original, "", _RULES) == original

    def test_inject_noop_if_manual_source_unknown(self):
        """Source non listee dans rules.source_tokens -> no-op."""
        from flox_uploader.core.release_name import inject_source_if_missing
        original = "Movie.2024.1080p.x264-Team"
        assert inject_source_if_missing(original, "BogusSource", _RULES) == original

    def test_inject_normalizes_casing(self):
        """User saisit 'bluray' minuscule -> canonical 'BluRay' utilise."""
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Movie.2024.1080p.AAC.x264-Team", "bluray", _RULES,
        )
        assert "BluRay" in result
        assert "bluray." not in result

    def test_inject_with_web_dl_dash(self):
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Movie.2024.1080p.AAC.x264-Team", "WEB-DL", _RULES,
        )
        assert "1080p.WEB-DL.AAC.x264-Team" in result

    def test_inject_no_resolution_fallback_to_year(self):
        """Sans resolution, on inject apres annee."""
        from flox_uploader.core.release_name import inject_source_if_missing
        result = inject_source_if_missing(
            "Movie.2024.VFF.AAC.x264-Team", "BluRay", _RULES,
        )
        # 2024 puis BluRay puis le reste
        assert "2024.BluRay." in result


# ============================================================
# Signal SIG_SOURCE_MISSING
# ============================================================

def test_signal_source_missing_exists():
    """SIG_SOURCE_MISSING est defini avec penalite + label clair."""
    from flox_uploader.core.naming_signals import (
        SIG_SOURCE_MISSING, SIGNAL_METADATA,
    )
    assert SIG_SOURCE_MISSING == "source_missing"
    assert SIG_SOURCE_MISSING in SIGNAL_METADATA
    penalty, label = SIGNAL_METADATA[SIG_SOURCE_MISSING]
    assert penalty == 5
    assert "source" in label.lower()
    assert "bluray" in label.lower() or "web-dl" in label.lower()


# ============================================================
# CLI accepte --source
# ============================================================

def test_cli_accepts_source_arg():
    """Le CLI prepare accepte --source BluRay."""
    from flox_uploader.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["prepare", "/fake/path.mkv", "--source", "BluRay"])
    assert getattr(args, "manual_source", "") == "BluRay"


def test_cli_source_choices_validation():
    """Le CLI rejette les sources inconnues."""
    from flox_uploader.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["prepare", "/fake/path.mkv", "--source", "BogusSource"])


# ============================================================
# PendingJob accepte manual_source
# ============================================================

def test_pending_job_has_manual_source_field():
    from flox_uploader.core.jobs_db import PendingJob

    job = PendingJob(
        id=0, file_path="/x.mkv", status="pending", force_fr="",
        created_at="", updated_at="", package_dir="", release_name="",
        log_path="", error="",
    )
    assert hasattr(job, "manual_source")
    assert job.manual_source == ""
