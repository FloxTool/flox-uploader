"""R1 (audit AUDIT_2026-07-19) : garde-fou coherence nom <-> TMDB (video) +
borne d'annee plausible.

Cas reel corpus : "Blade.Runner.2049" (2017) matchait le film de 1982 (id 78)
et s'affichait 98 "quasi parfait". La regex annee prenait "2049" (nombre du
titre) comme annee, et le score video n'avait aucun garde-fou de coherence.
"""
from __future__ import annotations

import json

from flox_uploader.core.confidence import (
    _check_tmdb_name_coherence,
    _title_similarity,
    compute_confidence_score,
    invalidate_score_cache,
)
from flox_uploader.core.release_name import _is_year_token, classify_parts


# --- Borne d'annee plausible ---

def test_year_token_rejects_future_title_number():
    assert _is_year_token("2049") is False   # Blade Runner 2049
    assert _is_year_token("2050") is False   # Death Race 2050
    assert _is_year_token("2999") is False


def test_year_token_accepts_real_years():
    for y in ("1982", "1999", "2017", "2024", "2026"):
        assert _is_year_token(y) is True


def test_classify_prefers_plausible_year_over_title_number():
    """'Blade Runner 2049' (2017) : 2049 reste dans le titre, 2017 = annee."""
    import pathlib
    rules = json.loads(
        pathlib.Path(
            "src/flox_uploader/trackers/gemini/rules.json"
        ).read_text(encoding="utf-8")
    )
    parts = "Blade.Runner.2049.2017.MULTi.VFF.2160p.BluRay.x265".split(".")
    d = classify_parts(parts, rules)
    assert d["year"] == "2017"
    assert "2049" in d["title_parts"]


# --- Garde-fou coherence nom <-> TMDB ---

def test_title_similarity_identical():
    assert _title_similarity("Blade Runner", "Blade Runner") == 1.0


def test_title_similarity_very_different():
    assert _title_similarity("Some Random Movie", "Blade Runner") < 0.5


def test_coherence_flags_year_mismatch():
    debug = {
        "media_type": "movie",
        "year": "2049",
        "title_parts_resolved": ["Blade", "Runner"],
    }
    tmdb_ctx = {"title": "Blade Runner", "release_date": "1982-06-25"}
    issues = _check_tmdb_name_coherence(debug, tmdb_ctx)
    assert any("année" in lbl.lower() for lbl, _ in issues)


def test_coherence_flags_title_mismatch():
    debug = {
        "media_type": "movie",
        "year": "2020",
        "title_parts_resolved": ["Totally", "Different", "Film"],
    }
    tmdb_ctx = {"title": "Blade Runner", "release_date": "2020-01-01"}
    issues = _check_tmdb_name_coherence(debug, tmdb_ctx)
    assert any("titre" in lbl.lower() for lbl, _ in issues)


def test_coherence_silent_when_consistent():
    debug = {
        "media_type": "movie",
        "year": "2017",
        "title_parts_resolved": ["Blade", "Runner", "2049"],
    }
    tmdb_ctx = {"title": "Blade Runner 2049", "release_date": "2017-10-04"}
    assert _check_tmdb_name_coherence(debug, tmdb_ctx) == []


def test_coherence_skips_books():
    """Un livre (media_type non video) ne passe pas par ce garde-fou."""
    debug = {
        "media_type": "book",
        "year": "2049",
        "title_parts_resolved": ["Whatever"],
    }
    tmdb_ctx = {"title": "Blade Runner", "release_date": "1982-06-25"}
    assert _check_tmdb_name_coherence(debug, tmdb_ctx) == []
