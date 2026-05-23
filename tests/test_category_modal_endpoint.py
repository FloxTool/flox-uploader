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
    # Marqueurs de la modal categorie
    assert 'id="category-modal"' in html
    assert 'id="cat-modal-grid"' in html
    assert 'id="cat-modal-confirm"' in html
    assert 'id="cat-modal-cancel"' in html
    assert "Catégorie de l'upload" in html
    # JS handlers presents
    assert "openCategoryModal" in html
    assert "_categoryModalSelectedId" in html
