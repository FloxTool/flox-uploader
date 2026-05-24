"""Tests Sprint C.5 v0.5.0 : Protocol ConfidenceStrategy + 6 stubs.

Verifie :
1. Le Protocol ConfidenceStrategy est defini et runtime_checkable.
2. Les 6 strategies (video + 5 stubs) satisfont le Protocol.
3. Le dispatcher route correctement selon la categorie.
4. La strategy video wrap strictement compute_confidence_score (= NO-OP).

Cf. PLAN-MULTICAT.md §5.4 Brique 3 + §9 Sprint C.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.confidence_strategies.strategy import (
    ConfidenceStrategy, get_confidence_strategy,
)
from flox_uploader.core.confidence_strategies.video import VideoConfidenceStrategy
from flox_uploader.core.confidence_strategies.book import BookConfidenceStrategy
from flox_uploader.core.confidence_strategies.game import GameConfidenceStrategy
from flox_uploader.core.confidence_strategies.show import ShowConfidenceStrategy
from flox_uploader.core.confidence_strategies.sport import SportConfidenceStrategy
from flox_uploader.core.confidence_strategies.manual import ManualConfidenceStrategy
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC, CATEGORY_SOFTWARE, CATEGORY_SPORTS, CATEGORY_TRAINING,
    CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
)


# ============================================================
# Protocol et 6 strategies
# ============================================================

@pytest.mark.parametrize("strategy_cls,expected_name", [
    (VideoConfidenceStrategy, "video"),
    (BookConfidenceStrategy, "book"),
    (GameConfidenceStrategy, "game"),
    (ShowConfidenceStrategy, "show"),
    (SportConfidenceStrategy, "sport"),
    (ManualConfidenceStrategy, "manual"),
])
def test_strategy_satisfies_protocol(strategy_cls, expected_name):
    """Chaque strategy doit satisfaire le Protocol ConfidenceStrategy."""
    instance = strategy_cls()
    assert isinstance(instance, ConfidenceStrategy), (
        f"{strategy_cls.__name__} ne satisfait pas le Protocol ConfidenceStrategy"
    )
    assert instance.name == expected_name
    assert callable(instance.compute)


# ============================================================
# Dispatcher get_confidence_strategy
# ============================================================

@pytest.mark.parametrize("cat_id,expected_name", [
    # Cats video -> 'video'
    (CATEGORY_MOVIE, "video"),
    (CATEGORY_TV, "video"),
    (CATEGORY_TV_ANIME, "video"),
    (CATEGORY_MOVIE_ANIME, "video"),
    (CATEGORY_MOVIE_DOC, "video"),
    (CATEGORY_TV_DOC, "video"),
    # Cats specifiques
    (CATEGORY_TV_SHOW, "show"),
    (CATEGORY_SPORTS, "sport"),
    (CATEGORY_BOOKS, "book"),
    (CATEGORY_GAME, "game"),
    (CATEGORY_SOFTWARE, "manual"),
    (CATEGORY_TRAINING, "manual"),
])
def test_get_strategy_routes_by_category(cat_id, expected_name):
    """Le dispatcher route correctement selon la categorie."""
    strategy = get_confidence_strategy(cat_id)
    assert strategy.name == expected_name


def test_get_strategy_none_returns_video():
    """None -> 'video' (retro-compat)."""
    assert get_confidence_strategy(None).name == "video"


def test_get_strategy_unknown_returns_video():
    """ID inconnu -> 'video' (fallback safe)."""
    assert get_confidence_strategy(9999).name == "video"


# ============================================================
# NO-OP : video strategy wrap strictement compute_confidence_score
# ============================================================

def test_video_strategy_wraps_compute_confidence_score(tmp_path):
    """VideoConfidenceStrategy.compute() == compute_confidence_score() direct."""
    from flox_uploader.core.confidence import compute_confidence_score
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )

    # Package factice minimal pour pouvoir calculer un score
    pkg = tmp_path / "TestPkg"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Pkg.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
    ))
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text("{}", encoding="utf-8")

    direct = compute_confidence_score(pkg)
    via_strategy = VideoConfidenceStrategy().compute(pkg)

    assert direct.score == via_strategy.score
    assert direct.bucket == via_strategy.bucket


def test_stubs_delegate_to_video_for_now(tmp_path):
    """Sprint C.5 / D.5+ : les stubs *encore* non specialises delegent au
    profil video. Sprint D.5 a specialise BookConfidenceStrategy avec ses
    propres penalites (auteur/ISBN/cover) — il est donc EXCLU de ce test.
    Sprints E-H remplaceront a leur tour Game/Show/Sport/Manual."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )

    pkg = tmp_path / "TestPkgStub"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Stub.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
    ))
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text("{}", encoding="utf-8")

    video_score = VideoConfidenceStrategy().compute(pkg)
    # BookConfidenceStrategy specialisee en D.5 -> exclue du test NO-OP.
    for stub_cls in (GameConfidenceStrategy,
                     ShowConfidenceStrategy, SportConfidenceStrategy,
                     ManualConfidenceStrategy):
        stub_score = stub_cls().compute(pkg)
        assert stub_score.score == video_score.score, (
            f"{stub_cls.__name__} doit delegate au video score"
        )
