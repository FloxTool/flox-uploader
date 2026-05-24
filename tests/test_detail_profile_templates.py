"""Tests Sprint C.4 v0.5.0 : helper category_profile() + stubs _detail_<profile>.html.

Verifie :
1. category_profile() retourne le bon nom de profil pour chaque cat Gemini.
2. Les 5 stubs (_detail_book/game/show/sport/manual) existent.
3. package_detail.html include le bon stub selon le profil.

Note : en pratique, le profile non-video n'est jamais atteint car la Brique 1
(PR-3) early-return les cats non-video avant la creation du package. Ces tests
verifient l'infrastructure pour Sprints D/E/F/G/H.

Cf. PLAN-MULTICAT.md §5.6 + §9 Sprint C.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ============================================================
# Helper category_profile()
# ============================================================

def test_category_profile_video_categories():
    """Films / Series / Anime / Doc -> 'video'."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
        CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC,
    )
    for cat in (CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME,
                CATEGORY_MOVIE_ANIME, CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC):
        assert category_profile(cat) == "video", f"Cat {cat} doit etre profile 'video'"


def test_category_profile_show():
    """Emission TV (cat 15) -> 'show' (templates UI specifiques)."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_TV_SHOW
    assert category_profile(CATEGORY_TV_SHOW) == "show"


def test_category_profile_sport():
    """Sports (cat 10) -> 'sport' (templates UI specifiques)."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_SPORTS
    assert category_profile(CATEGORY_SPORTS) == "sport"


def test_category_profile_book():
    """Livres (cat 12) -> 'book'."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_BOOKS
    assert category_profile(CATEGORY_BOOKS) == "book"


def test_category_profile_game():
    """Jeux (cat 3) -> 'game'."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_GAME
    assert category_profile(CATEGORY_GAME) == "game"


def test_category_profile_manual_for_software_and_training():
    """Logiciel (17) + Formation (18) -> 'manual' (profil partage)."""
    from flox_uploader.core.category_resolver import category_profile
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        CATEGORY_SOFTWARE, CATEGORY_TRAINING,
    )
    assert category_profile(CATEGORY_SOFTWARE) == "manual"
    assert category_profile(CATEGORY_TRAINING) == "manual"


def test_category_profile_none_defaults_video():
    """None -> 'video' (retro-compat)."""
    from flox_uploader.core.category_resolver import category_profile
    assert category_profile(None) == "video"


def test_category_profile_unknown_defaults_video():
    """ID inconnu -> 'video' (fallback safe)."""
    from flox_uploader.core.category_resolver import category_profile
    assert category_profile(9999) == "video"


# ============================================================
# Existence des 5 stubs _detail_<profile>.html
# ============================================================

@pytest.mark.parametrize("profile", ["book", "game", "show", "sport", "manual"])
def test_detail_stub_template_exists(profile):
    """Chaque profil non-video a son template stub."""
    project_root = Path(__file__).parent.parent
    template_path = project_root / "src" / "flox_uploader" / "web" / "templates" / f"_detail_{profile}.html"
    assert template_path.is_file(), (
        f"Template {template_path.name} manquant. Necessaire pour le profil "
        f"'{profile}' (cf. category_profile() dans category_resolver.py)."
    )


@pytest.mark.parametrize("profile", ["book", "game", "show", "sport", "manual"])
def test_detail_stub_template_non_empty(profile):
    """Les stubs doivent contenir au moins un message visible (pas vides)."""
    project_root = Path(__file__).parent.parent
    template_path = project_root / "src" / "flox_uploader" / "web" / "templates" / f"_detail_{profile}.html"
    content = template_path.read_text(encoding="utf-8")
    # Doit contenir un message qui evoque la categorie
    assert "Catégorie" in content or "categorie" in content.lower(), (
        f"Stub {profile} devrait mentionner sa categorie"
    )
    # Doit pointer vers le Sprint qui implementera le pipeline
    assert "Sprint" in content


# ============================================================
# Smoke test : page detail include le stub correct selon profile
# ============================================================

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")

    from flox_uploader import config
    config.load_env()

    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_video_package_does_not_include_stubs(client, tmp_path):
    """Pour un package vidéo (profile='video'), AUCUN stub n'est inclus."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Test.Video.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Video.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=1,  # Films
    )
    write_state(pkg, state)
    (pkg / "release_name.txt").write_text("Test.Video.2024-TEAM\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}',
        encoding="utf-8",
    )

    resp = client.get("/packages/Test.Video.2024-TEAM")
    assert resp.status_code == 200
    html = resp.text
    # Aucun stub ne doit apparaitre pour un film classique
    assert "Le pipeline livres sera implémenté" not in html
    assert "Le pipeline jeux sera implémenté" not in html
    assert "Le pipeline émission TV sera implémenté" not in html
    assert "Le pipeline sport sera enrichi" not in html
    assert "Le formulaire manuel guidé sera implémenté" not in html


def test_book_package_includes_book_stub(client, tmp_path):
    """Pour un package force en Livre (override manual_category_id=12),
    le stub _detail_book.html est rendu."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Test.Book.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Book.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=12,  # Force Livre
    )
    write_state(pkg, state)
    (pkg / "release_name.txt").write_text("Test.Book.2024-TEAM\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}',
        encoding="utf-8",
    )

    resp = client.get("/packages/Test.Book.2024-TEAM")
    assert resp.status_code == 200
    html = resp.text
    # Stub Livre doit apparaitre
    assert "Catégorie Livre / BD / Manga" in html
    assert "Sprint D" in html
