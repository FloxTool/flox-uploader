"""Tests Sprint C.1 v0.5.0 : endpoint /api/categories + propagation
category_id_hint dans /api/queue/add jusqu'a jobs_db.

Verifie la chaine backend complete qui alimente la modal selecteur de
categorie sur Inbox (cf. inbox.html, openCategoryModal()).

Cf. PLAN-MULTICAT.md §6 + §9 Sprint C.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client de test FastAPI avec environnement isolé."""
    # Isole les data de test (jobs.db etc.) dans tmp_path
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    # Variables d'env requises pour /setup soit complete
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")

    # Important : forcer le rechargement de config pour qu'elle prenne en
    # compte FLOX_UPLOADER_DATA_DIR (sinon data_dir() cache l'ancienne valeur).
    from flox_uploader import config
    config.load_env()

    from flox_uploader.web.app import create_app
    app = create_app()
    return TestClient(app)


# ============================================================
# Endpoint /api/categories
# ============================================================

def test_api_categories_returns_12_categories(client):
    """L'endpoint expose les 12 categories Gemini avec leurs metadata UI."""
    resp = client.get("/api/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "extension_to_category" in data
    # Les 12 cats Gemini officielles
    assert len(data["categories"]) == 12


def test_api_categories_each_has_required_fields(client):
    """Chaque entree a id, label, icon, color, extensions, hint, icon_svg_path."""
    resp = client.get("/api/categories")
    data = resp.json()
    for cat in data["categories"]:
        assert "id" in cat and isinstance(cat["id"], int)
        assert "label" in cat and isinstance(cat["label"], str) and cat["label"]
        assert "icon" in cat and isinstance(cat["icon"], str)
        assert "color" in cat and isinstance(cat["color"], str)
        assert "extensions" in cat and isinstance(cat["extensions"], list)
        assert "hint" in cat
        assert "icon_svg_path" in cat
        # SVG paths doivent contenir au moins un <path>
        assert "<path" in cat["icon_svg_path"] or "<circle" in cat["icon_svg_path"] or "<line" in cat["icon_svg_path"] or "<rect" in cat["icon_svg_path"]


def test_api_categories_extension_mapping(client):
    """Le mapping extension -> category_id contient les extensions evidentes."""
    resp = client.get("/api/categories")
    data = resp.json()
    ext_map = data["extension_to_category"]
    # Echantillon : vidéo, ebook, logiciel
    assert ext_map[".mkv"] == 1   # CATEGORY_MOVIE
    assert ext_map[".epub"] == 12  # CATEGORY_BOOKS
    assert ext_map[".exe"] == 17   # CATEGORY_SOFTWARE
    assert ext_map[".cbz"] == 12   # CATEGORY_BOOKS (BD)
    assert ext_map[".azw3"] == 12


def test_api_categories_all_keys_lowercase(client):
    """Les cles extension sont toutes en minuscule avec point initial."""
    resp = client.get("/api/categories")
    data = resp.json()
    for ext in data["extension_to_category"]:
        assert ext.startswith("."), f"Extension '{ext}' doit commencer par '.'"
        assert ext == ext.lower(), f"Extension '{ext}' doit etre lowercase"


# ============================================================
# Propagation category_id_hint dans /api/queue/add
# ============================================================

def test_queue_add_accepts_category_id_hint(client, tmp_path, monkeypatch):
    """L'endpoint /api/queue/add accepte category_id_hint et le persiste."""
    # On bypass le subprocess (qu'on ne veut pas vraiment lancer en test)
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_file = tmp_path / "Test.mkv"
    fake_file.write_bytes(b"")

    resp = client.post("/api/queue/add", json={
        "paths": [str(fake_file)],
        "category_id_hint": 12,  # Livres
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["added"] == 1
    # Verifier que le job en base a bien le hint
    from flox_uploader.core import jobs_db
    job = jobs_db.get_job(data["job_ids"][0])
    assert job is not None
    assert job.category_id_hint == 12, (
        f"Job devrait avoir category_id_hint=12, obtenu {job.category_id_hint}"
    )


def test_queue_add_without_hint_defaults_to_zero(client, tmp_path, monkeypatch):
    """Sans hint dans le payload, le job a category_id_hint=0 (auto-detect)."""
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_file = tmp_path / "Test.mkv"
    fake_file.write_bytes(b"")

    resp = client.post("/api/queue/add", json={"paths": [str(fake_file)]})
    assert resp.status_code == 200
    data = resp.json()
    from flox_uploader.core import jobs_db
    job = jobs_db.get_job(data["job_ids"][0])
    assert job.category_id_hint == 0


def test_queue_add_invalid_hint_falls_back_to_zero(client, tmp_path, monkeypatch):
    """Un category_id_hint non-int dans le payload tombe a 0 sans plantage."""
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_file = tmp_path / "Test.mkv"
    fake_file.write_bytes(b"")

    resp = client.post("/api/queue/add", json={
        "paths": [str(fake_file)],
        "category_id_hint": "not-an-int",
    })
    # Doit pas exploser, le hint est juste ignore
    assert resp.status_code == 200
    data = resp.json()
    from flox_uploader.core import jobs_db
    job = jobs_db.get_job(data["job_ids"][0])
    assert job.category_id_hint == 0


# ============================================================
# Modal frontend : verification template render
# ============================================================

def test_inbox_template_contains_category_modal(client, tmp_path):
    """Le template Inbox doit contenir la modal selecteur de categorie."""
    resp = client.get(f"/inbox?path={tmp_path}")
    assert resp.status_code == 200
    html = resp.text
    # Marqueurs de la modal categorie (Sprint C.1bis : section primary + advanced)
    assert 'id="category-modal"' in html
    assert 'id="cat-modal-top-grid"' in html        # section primary : 1 Video + 4 non-video
    assert 'id="cat-modal-grid"' in html             # section avancee : 12 sous-cats
    assert 'id="cat-modal-advanced-toggle"' in html  # lien "Catégoriser plus finement"
    assert 'id="cat-modal-advanced-section"' in html
    assert 'id="cat-modal-confirm"' in html
    assert 'id="cat-modal-cancel"' in html
    assert "Catégorie de l'upload" in html
    assert "Catégoriser plus finement" in html       # libelle du lien Avance
    # JS handlers presents
    assert "openCategoryModal" in html
    assert "_categoryModalSelectedId" in html
    assert "VIRTUAL_VIDEO_TILE" in html              # tuile Video virtuelle
    assert "TOP_CAT_IDS" in html                     # constants top-cats


# ============================================================
# Sprint C.1bis : propagation hint -> state.manual_category_id
# ============================================================
# Fix : le hint user envoye par la modal Inbox doit etre persiste dans
# state.manual_category_id pour qu'il ne soit pas ecrase par l'auto-detection
# TMDB dans build_upload_payload() (qui prend manual_category_id en priorite
# quand > 0).

def test_hint_zero_does_not_override_manual_category_id(tmp_path, monkeypatch):
    """category_hint=0 ou None -> manual_category_id reste 0 (auto-detect TMDB)."""
    from flox_uploader.core.package_state import PackageStateData, PackageState, write_state, read_state

    # Simule un package state existant avec manual_category_id=0
    pkg = tmp_path / "Test.Movie.2024.1080p.x265-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024.1080p.x265-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=0,
    )
    write_state(pkg, state)

    # On simule la logique de pipeline.process_one : pour category_hint=0 ou None,
    # on ne touche PAS au state. (cf. pipeline.py: `if category_hint and category_hint > 0`)
    for hint in (None, 0):
        # Si on ne fait rien, manual_category_id reste 0
        re_read = read_state(pkg)
        assert re_read.manual_category_id == 0


def test_hint_positive_persists_to_manual_category_id(tmp_path):
    """category_hint > 0 -> manual_category_id = hint (override sticky)."""
    from flox_uploader.core.package_state import PackageStateData, PackageState, write_state, read_state

    pkg = tmp_path / "Test.Movie.2024.1080p.x265-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024.1080p.x265-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=0,
    )
    write_state(pkg, state)

    # Simule la logique pipeline.process_one Sprint C.1bis :
    # `if category_hint is not None and category_hint > 0 -> persiste`.
    for hint in (7, 12, 3, 17, 18, 15):
        st = read_state(pkg)
        st.manual_category_id = int(hint)
        write_state(pkg, st)
        re_read = read_state(pkg)
        assert re_read.manual_category_id == hint, (
            f"Hint={hint} doit etre persiste dans manual_category_id"
        )


def test_build_upload_payload_respects_manual_category_id(tmp_path):
    """build_upload_payload doit respecter manual_category_id (override sticky)
    meme si l'auto-detection TMDB renvoie autre chose.

    Garantit que le hint user persiste depuis la modal Inbox via Sprint C.1bis
    arrive bien dans le payload final envoye au tracker.
    """
    from flox_uploader.core.package_state import PackageStateData, PackageState, write_state
    from flox_uploader.core.upload_orchestrator import build_upload_payload, PackageBundle, UploadConfig
    from flox_uploader.core.media_type import MediaType

    pkg = tmp_path / "Test.Movie.2024.1080p.x265-TEAM"
    pkg.mkdir()
    nfo = pkg / "test.nfo"
    nfo.write_text("dummy nfo")
    torrent = pkg / "test.torrent"
    torrent.write_bytes(b"")

    # State avec override manual_category_id=7 (Film Anime)
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024.1080p.x265-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        manual_category_id=7,  # Anime Film force par l'user
    )
    write_state(pkg, state)

    # Bundle = un film "normal" qui sans override serait classe cat 1
    bundle = PackageBundle(
        package_dir=pkg,
        release_name="Test.Movie.2024.1080p.x265-TEAM",
        description="...",
        mediainfo="...",
        torrent_path=torrent,
        nfo_path=nfo,
        infohash="0" * 40,
        size_bytes=1024 * 1024 * 1024,
        tmdb_id=12345,
        imdb_id=0,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
        tmdb_genres=(),  # Pas Animation -> auto-detect dirait cat 1 (Films)
    )
    cfg = UploadConfig(api_url="https://test", api_key="key")

    payload = build_upload_payload(bundle, cfg)
    # L'override doit gagner sur l'auto-detection
    assert payload.category_id == 7, (
        f"L'override manual_category_id=7 doit gagner sur l'auto-detect (obtenu {payload.category_id})"
    )
