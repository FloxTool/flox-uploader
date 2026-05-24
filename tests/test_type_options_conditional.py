"""Tests Sprint C.6 v0.5.0 : type_options_for_category() conditionnel
selon la categorie du package.

La dropdown 'Type' de la page detail (Options pour l'upload) ne doit proposer
que les types valides pour la categorie du package : pas de "Full Disc" pour
un livre, pas de "EPUB" pour un film.

Cf. PLAN-MULTICAT.md §5.6 (Brique 5 UI) + §9 Sprint C.
"""
from __future__ import annotations

import pytest


def test_type_options_for_video_categories():
    """Pour les cats video (1, 2, 6, 7, 10, 13, 14, 15) -> TYPE_OPTIONS video."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, TYPE_OPTIONS,
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
        CATEGORY_SPORTS, CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
    )
    for cat in (CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
                CATEGORY_SPORTS, CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW):
        opts = type_options_for_category(cat)
        assert opts is TYPE_OPTIONS, (
            f"Cat {cat} doit retourner TYPE_OPTIONS video, obtenu {opts}"
        )


def test_type_options_for_game():
    """Cat Jeu (3) -> GAME_TYPE_OPTIONS (Windows/PS5/Switch/...)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, GAME_TYPE_OPTIONS, CATEGORY_GAME,
    )
    assert type_options_for_category(CATEGORY_GAME) is GAME_TYPE_OPTIONS


def test_type_options_for_books():
    """Cat Livre (12) -> BOOK_TYPE_OPTIONS (EPUB/PDF/CBR/M4B/...)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, BOOK_TYPE_OPTIONS, CATEGORY_BOOKS,
    )
    assert type_options_for_category(CATEGORY_BOOKS) is BOOK_TYPE_OPTIONS


def test_type_options_for_software():
    """Cat Logiciel (17) -> SOFTWARE_TYPE_OPTIONS (Windows/MacOS/Linux/Autre)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, SOFTWARE_TYPE_OPTIONS, CATEGORY_SOFTWARE,
    )
    assert type_options_for_category(CATEGORY_SOFTWARE) is SOFTWARE_TYPE_OPTIONS


def test_type_options_for_training_defaults_video():
    """Cat Formation (18) -> TYPE_OPTIONS video par defaut (pas de type
    officiel Gemini pour les formations)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, TYPE_OPTIONS, CATEGORY_TRAINING,
    )
    assert type_options_for_category(CATEGORY_TRAINING) is TYPE_OPTIONS


def test_type_options_none_defaults_video():
    """None -> TYPE_OPTIONS video (retro-compat)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, TYPE_OPTIONS,
    )
    assert type_options_for_category(None) is TYPE_OPTIONS


def test_type_options_unknown_defaults_video():
    """Cat inconnue -> TYPE_OPTIONS video (fallback safe)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        type_options_for_category, TYPE_OPTIONS,
    )
    assert type_options_for_category(9999) is TYPE_OPTIONS


def test_each_type_options_non_empty():
    """Toutes les listes de type_options doivent avoir au moins 1 entree."""
    from flox_uploader.trackers.gemini.unit3d_mapping import (
        TYPE_OPTIONS, GAME_TYPE_OPTIONS, BOOK_TYPE_OPTIONS, SOFTWARE_TYPE_OPTIONS,
    )
    assert len(TYPE_OPTIONS) >= 1
    assert len(GAME_TYPE_OPTIONS) >= 1
    assert len(BOOK_TYPE_OPTIONS) >= 1
    assert len(SOFTWARE_TYPE_OPTIONS) >= 1


# ============================================================
# Smoke test : page detail expose les bonnes type_options
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


def test_page_detail_book_shows_book_type_options(client, tmp_path):
    """Pour un package force en Livre, la dropdown Type doit afficher EPUB/PDF
    etc. au lieu des types video."""
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
    # Doit contenir au moins un type ebook (libelles depuis BOOK_TYPE_OPTIONS)
    assert "EPUB" in html or "Livre audio" in html, (
        "La dropdown Type doit afficher des types Livre pour un package cat 12"
    )


def test_page_detail_video_shows_video_type_options(client, tmp_path):
    """Pour un package vidéo classique, la dropdown Type affiche BluRay/WEB-DL/etc."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Test.Movie.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=1,  # Force Film
    )
    write_state(pkg, state)
    (pkg / "release_name.txt").write_text("Test.Movie.2024-TEAM\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}',
        encoding="utf-8",
    )

    resp = client.get("/packages/Test.Movie.2024-TEAM")
    assert resp.status_code == 200
    html = resp.text
    # Doit contenir au moins un type vidéo
    assert "BluRay" in html or "WEBRip" in html or "WEB-DL" in html, (
        "La dropdown Type doit afficher des types vidéo pour un package cat 1"
    )
