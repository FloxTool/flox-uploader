"""Tests pour core/confidence.py (score de confiance par package)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.confidence import (
    PENALTY_DUP_CERTAIN,
    PENALTY_IMDB_MISSING,
    PENALTY_LANG_AMBIGUOUS,
    PENALTY_TMDB_MISSING,
    THRESHOLD_READY,
    THRESHOLD_REVIEW,
    compute_confidence_score,
)
from flox_uploader.core.package_state import (
    PackageState,
    init_state,
    transition,
)


def _write_debug(package_dir: Path, data: dict) -> None:
    """Helper : ecrit _debug/debug.json dans package_dir."""
    debug_dir = package_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "debug.json").write_text(json.dumps(data, ensure_ascii=False))


@pytest.fixture
def pkg(tmp_path: Path) -> Path:
    p = tmp_path / "Foo.2024.1080p.x265-TEAM"
    p.mkdir()
    init_state(p, "Foo.2024.1080p.x265-TEAM", "gemini")
    return p


# ============================================================
# Score parfait
# ============================================================

def test_perfect_score_when_all_signals_ok(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {
            "movie_id": 12345,
            "imdb_id": "tt7654321",
        },
        "lang": ["VFF"],
        "compliance_issues": [],
    })
    s = compute_confidence_score(pkg)
    assert s.score == 100
    # Lot R-C : 100 exact = bucket "parfait" (distinct du "perfect" 95-99)
    assert s.bucket == "parfait"
    assert s.bucket_emoji == "★"
    assert s.penalties == []


# ============================================================
# Penalites individuelles
# ============================================================

def test_tmdb_missing_penalty(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {},
        "lang": ["VFF"],
    })
    s = compute_confidence_score(pkg)
    # round 5 : TMDB -35 + IMDB -15 = 50
    expected = 100 - PENALTY_TMDB_MISSING - PENALTY_IMDB_MISSING
    assert s.score == expected
    assert s.bucket in {"blocked", "review"}
    assert any("TMDB" in r for r in s.reasons)


def test_imdb_missing_penalty_alone(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {"movie_id": 42, "imdb_id": ""},
        "lang": ["VFF"],
    })
    s = compute_confidence_score(pkg)
    assert s.score == 100 - PENALTY_IMDB_MISSING
    # round 5 : IMDB seul = -15 -> 85 -> good (80-89)
    assert s.bucket in {"ready", "good"}


def test_lang_ambiguous_penalty(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {"movie_id": 42, "imdb_id": "tt1"},
        "lang": ["MULTi"],  # MULTi seul = ambigu
    })
    s = compute_confidence_score(pkg)
    assert s.score == 100 - PENALTY_LANG_AMBIGUOUS
    # Le libelle (cf. confidence.py) contient toujours "MULTi" — substring stable
    assert any("MULTi" in r for r in s.reasons)


def test_lang_precise_no_penalty(pkg: Path):
    """MULTi.VFF est precise -> pas de penalite."""
    _write_debug(pkg, {
        "tmdb_context": {"movie_id": 42, "imdb_id": "tt1"},
        "lang": ["MULTi.VFF"],
    })
    s = compute_confidence_score(pkg)
    assert s.score == 100


def test_compliance_errors_penalty(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {"movie_id": 42, "imdb_id": "tt1"},
        "lang": ["VFF"],
        "compliance_issues": [
            "Severity.ERROR: NFO disagrees with release_name",
            "Severity.ERROR: missing field",
            # NOTES round 6 : WARN generique -> -1 (au lieu d'etre ignore)
            "Severity.WARNING: minor issue",
        ],
    })
    s = compute_confidence_score(pkg)
    # 2 ERRORS x 15 = -30 + 1 WARN generique = -1 -> total -31
    assert s.score == 100 - 30 - 1


# ============================================================
# Doublon detecte cote tracker
# ============================================================

def test_aborted_duplicate_blocks_score(pkg: Path):
    """Si le package_state dit ABORTED_DUPLICATE, le score tombe a 0."""
    transition(pkg, PackageState.VALIDATED, infohash="x")
    transition(
        pkg, PackageState.ABORTED_DUPLICATE,
        existing_torrent_id=42,
    )
    _write_debug(pkg, {
        "tmdb_context": {"movie_id": 42, "imdb_id": "tt1"},
        "lang": ["VFF"],
    })
    s = compute_confidence_score(pkg)
    assert s.score == 0
    assert s.bucket == "blocked"
    assert s.bucket_emoji == "✗"


# ============================================================
# Cumul des penalites
# ============================================================

def test_multiple_penalties_stack(pkg: Path):
    _write_debug(pkg, {
        "tmdb_context": {},  # TMDB missing -35, IMDB missing -15 (round 5)
        "lang": ["MULTi"],   # ambigu -20
    })
    s = compute_confidence_score(pkg)
    expected = (
        100
        - PENALTY_TMDB_MISSING
        - PENALTY_IMDB_MISSING
        - PENALTY_LANG_AMBIGUOUS
    )
    assert s.score == expected
    assert s.bucket == "blocked"


def test_score_clamped_to_zero():
    """Meme avec beaucoup de penalites, le score ne descend pas en dessous de 0."""
    # On utilise une fixture standalone car beaucoup de penalites
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "package"
        pkg.mkdir()
        init_state(pkg, "Foo", "gemini")
        transition(pkg, PackageState.VALIDATED, infohash="x")
        transition(pkg, PackageState.ABORTED_DUPLICATE, existing_torrent_id=1)
        _write_debug(pkg, {
            "tmdb_context": {},
            "lang": ["MULTi"],
            "compliance_issues": [
                "Severity.ERROR: x",
                "Severity.ERROR: y",
                "Severity.ERROR: z",
            ],
        })
        s = compute_confidence_score(pkg)
        assert s.score == 0  # clamped
        assert s.bucket == "blocked"


# ============================================================
# Buckets
# ============================================================

def test_bucket_thresholds():
    """Lot R-C : 6 buckets parfait (=100) / perfect (95-99) / ready (90-94) /
    good (80-89) / review (60-79) / blocked (<60).
    Round 5 : TMDB missing = -35, IMDB missing = -15.

    Sprint 5 fix : on invalide explicitement le score cache entre chaque
    re-ecriture de debug.json. Sur Windows (CI), la resolution mtime peut
    etre trop grossiere pour distinguer 3 ecritures rapides — sans
    invalidation explicite, le cache retournait le score precedent et le
    test echouait flaky-ment.
    """
    import tempfile
    from flox_uploader.core.confidence import invalidate_score_cache
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / "p"
        pkg.mkdir()
        init_state(pkg, "Foo", "gemini")
        # Score 100 -> parfait (bucket distinct du "perfect" 95-99)
        _write_debug(pkg, {"tmdb_context": {"movie_id": 1, "imdb_id": "tt1"}, "lang": ["VFF"]})
        invalidate_score_cache(pkg)
        assert compute_confidence_score(pkg).bucket == "parfait"
        # Score 50 (TMDB -35 + IMDB -15) -> blocked (round 5)
        _write_debug(pkg, {"tmdb_context": {}, "lang": ["VFF"]})
        invalidate_score_cache(pkg)
        s = compute_confidence_score(pkg)
        assert s.score == 50
        assert s.bucket == "blocked"
        # Score 30 (gros cumul : -35 -15 -20) -> blocked
        _write_debug(pkg, {"tmdb_context": {}, "lang": ["MULTi"]})
        invalidate_score_cache(pkg)
        s = compute_confidence_score(pkg)
        assert s.score == 30
        assert s.bucket == "blocked"
