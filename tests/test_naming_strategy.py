"""Tests Sprint B.2/B.3 v0.5.0 : Protocol NamingStrategy + VideoNamingStrategy
+ dispatcher get_strategy().

Verifie :
1. Le Protocol est defini et runtime_checkable.
2. VideoNamingStrategy implemente correctement le Protocol.
3. Le dispatcher retourne la bonne strategy par category_id.
4. Le wrap de build_release_name donne strictement le meme resultat que
   l'appel direct (preuve NO-OP).

Cf. PLAN-MULTICAT.md §5.5 (Brique 4 - Strategy pattern).
"""
from __future__ import annotations

import pytest

from flox_uploader.core.naming.strategy import NamingStrategy, get_strategy
from flox_uploader.core.naming.video_strategy import VideoNamingStrategy
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC, CATEGORY_SOFTWARE, CATEGORY_SPORTS, CATEGORY_TRAINING,
    CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
)


# ============================================================
# Protocol NamingStrategy
# ============================================================

def test_video_strategy_implements_protocol():
    """VideoNamingStrategy doit satisfaire le Protocol NamingStrategy."""
    strategy = VideoNamingStrategy()
    assert isinstance(strategy, NamingStrategy), (
        "VideoNamingStrategy ne satisfait pas le Protocol NamingStrategy"
    )


def test_video_strategy_has_required_attributes():
    """L'attribut `name` et les methodes du Protocol sont presents."""
    strategy = VideoNamingStrategy()
    assert strategy.name == "video"
    assert callable(strategy.build_release_name)
    assert callable(strategy.compliance_profile)


def test_video_strategy_compliance_profile_is_video():
    """compliance_profile() retourne 'video' (alignement avec compliance.py)."""
    strategy = VideoNamingStrategy()
    assert strategy.compliance_profile() == "video"


def test_video_strategy_compliance_profile_aligned_with_compliance_module():
    """Doit retourner la meme valeur que `compliance._profile_for_category`
    pour les categories video.
    """
    from flox_uploader.core.compliance import _profile_for_category
    strategy = VideoNamingStrategy()
    for cat in (
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
        CATEGORY_SPORTS, CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
    ):
        assert _profile_for_category(cat) == strategy.compliance_profile(), (
            f"Desynchro pour cat {cat} : compliance dit "
            f"'{_profile_for_category(cat)}' mais VideoStrategy dit "
            f"'{strategy.compliance_profile()}'"
        )


# ============================================================
# Dispatcher get_strategy
# ============================================================

@pytest.mark.parametrize("cat_id", [
    # Toutes les cats video : doivent toutes retourner VideoNamingStrategy
    CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW, CATEGORY_SPORTS,
])
def test_get_strategy_returns_video_for_video_categories(cat_id):
    strategy = get_strategy(cat_id)
    assert isinstance(strategy, VideoNamingStrategy)
    assert strategy.name == "video"


@pytest.mark.parametrize("cat_id", [
    # Sprint D.3 v0.5.0 : CATEGORY_BOOKS est desormais cable sur
    # BookNamingStrategy -> retire de ce test. Les autres cats non-video
    # restent sur VideoNamingStrategy en attendant Sprints E/H.
    CATEGORY_GAME, CATEGORY_SOFTWARE, CATEGORY_TRAINING,
])
def test_get_strategy_returns_video_for_non_video_categories_in_b23(cat_id):
    """Cats non-video sans strategy dediee retournent VideoNamingStrategy.

    Sprint D.3 a specialise BookNamingStrategy pour cat 12, donc Livres
    sortent de ce test. Sprints E/H ajouteront Game/Manual et reduiront
    encore cette liste.

    Note : le pipeline early-return AVANT naming pour les cats non-video
    (PR-3 Brique 1 dans pipeline.process_one), donc ces strategies de
    fallback ne sont pas appelees en pratique.
    """
    strategy = get_strategy(cat_id)
    assert isinstance(strategy, VideoNamingStrategy)


def test_get_strategy_none_returns_video():
    """category_id=None -> VideoNamingStrategy (compat retro)."""
    strategy = get_strategy(None)
    assert isinstance(strategy, VideoNamingStrategy)


def test_get_strategy_unknown_id_returns_video():
    """category_id inconnu -> VideoNamingStrategy (fallback safe)."""
    strategy = get_strategy(9999)
    assert isinstance(strategy, VideoNamingStrategy)


# ============================================================
# VideoNamingStrategy.build_release_name == direct call (NO-OP)
# ============================================================
# Le but : prouver que la strategy ne change RIEN au comportement par rapport
# a un appel direct de `release_name.build_release_name`. C'est la garantie
# critique du Sprint B (refactor strictement NO-OP).

def test_video_strategy_build_extra_payload_returns_empty_dict():
    """Sprint B.5 : VideoNamingStrategy.build_extra_payload() retourne {}
    par defaut (les champs video extra restent inline dans build_upload_payload).
    """
    strategy = VideoNamingStrategy()
    # state_data peut etre n'importe quoi : None ou un mock — la video strategy
    # n'utilise pas state_data en Sprint B.
    assert strategy.build_extra_payload(None) == {}
    assert strategy.build_extra_payload(object()) == {}


def test_video_strategy_build_release_name_equals_direct_call(tmp_path, monkeypatch):
    """Le wrap doit produire EXACTEMENT le meme resultat que l'appel direct."""
    # On evite tout appel reseau TMDB en passant un resolver mock qui retourne
    # toujours (parts, None) — pas de TMDB context.
    from flox_uploader.core.release_name import build_release_name as direct
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers import get_tracker

    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test/announce/passkey")
    tracker = get_tracker("gemini", "https://test/announce/passkey")

    fake_video = tmp_path / "Movie.2024.1080p.BluRay.x265-TEAM.mkv"
    fake_video.write_bytes(b"")
    nfo_text = ""

    def no_tmdb_resolver(parts, year, debug, release_lang_hint=None):
        return parts, None  # pas de context TMDB

    # Appel direct
    debug_direct = Debug(tmp_path / "debug_direct")
    direct_result = direct(
        fake_video, tracker, nfo_text, debug_direct,
        tmdb_resolver=no_tmdb_resolver,
    )

    # Appel via strategy
    debug_strategy = Debug(tmp_path / "debug_strategy")
    strategy = VideoNamingStrategy()
    strategy_result = strategy.build_release_name(
        fake_video, tracker, nfo_text, debug_strategy,
        tmdb_resolver=no_tmdb_resolver,
    )

    assert direct_result == strategy_result, (
        f"Strategy diverge de l'appel direct :\n"
        f"  direct   = {direct_result}\n"
        f"  strategy = {strategy_result}"
    )
