"""R5 (audit AUDIT_2026-07-19) : score plus honnete.

- fin du triple comptage TMDB (l'IMDb absent n'est plus re-penalise sans match).
- sous-typage du bucket blocked : action_required (reparable) vs refused (dur).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.confidence import compute_confidence_score, invalidate_score_cache
from flox_uploader.core.package_state import PackageState, init_state, transition


def _pkg(tmp_path, debug, state=PackageState.PREPARED, state_kwargs=None):
    p = tmp_path / "pkg"
    p.mkdir(exist_ok=True)
    (p / "_debug").mkdir(exist_ok=True)
    (p / "_debug" / "debug.json").write_text(json.dumps(debug), encoding="utf-8")
    init_state(p, "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM", "gemini")
    if state != PackageState.PREPARED:
        transition(p, state, **(state_kwargs or {}))
    invalidate_score_cache(p)
    return p


# --- Triple comptage TMDB ---

def test_no_tmdb_does_not_double_count_imdb(tmp_path):
    p = _pkg(tmp_path, {"tmdb_context": {}, "lang": ["VFF"]})
    c = compute_confidence_score(p)
    assert c.score == 65   # 100 - 35 (TMDB seul), plus de -15 IMDb
    assert not any("IMDb" in r for r in c.reasons)


def test_tmdb_present_without_imdb_still_penalized(tmp_path):
    """Un match TMDB sans lien IMDb : la penalite IMDb reste legitime."""
    p = _pkg(tmp_path, {"tmdb_context": {"movie_id": 1, "imdb_id": ""}, "lang": ["VFF"]})
    c = compute_confidence_score(p)
    assert any("IMDb" in r for r in c.reasons)


# --- Sous-typage du bucket blocked ---

def test_bucket_kind_action_required_on_needs_choice(tmp_path):
    """MULTi sans variante (lang_needs_choice) -> blocked + action_required."""
    p = _pkg(tmp_path, {
        "tmdb_context": {"movie_id": 1, "imdb_id": "tt1"},
        "lang_needs_choice": True,
        "lang": ["MULTi"],
    })
    c = compute_confidence_score(p)
    assert c.bucket == "blocked"
    assert c.bucket_kind == "action_required"


def test_bucket_kind_refused_on_dup_certain(tmp_path):
    p = _pkg(
        tmp_path,
        {"tmdb_context": {"movie_id": 1, "imdb_id": "tt1"}},
        state=PackageState.ABORTED_DUPLICATE,
        state_kwargs={"existing_torrent_id": 999},
    )
    c = compute_confidence_score(p)
    assert c.bucket == "blocked"
    assert c.bucket_kind == "refused"


def test_bucket_kind_refused_on_blocking_compliance(tmp_path):
    p = _pkg(tmp_path, {
        "tmdb_context": {"movie_id": 1, "imdb_id": "tt1"},
        "lang": ["VFF"],
        "compliance_issues": ["[BLOCKED] Team 'Slay3R' interdite par le tracker"],
    })
    c = compute_confidence_score(p)
    assert c.bucket == "blocked"
    assert c.bucket_kind == "refused"


def test_bucket_kind_none_when_not_blocked(tmp_path):
    p = _pkg(tmp_path, {
        "tmdb_context": {"movie_id": 1, "imdb_id": "tt1"},
        "lang": ["VFF"],
    })
    c = compute_confidence_score(p)
    assert c.bucket in {"parfait", "perfect", "ready", "good"}
    assert c.bucket_kind is None
