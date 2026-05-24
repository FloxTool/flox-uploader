"""Tests Sprint D.9 v0.5.0 — Re-preparer livre + Options upload + MP3 autorise + dynamique cat.

Verifie :
1. MP3 est autorise comme format livre audio (compliance ebook).
2. .mp3 detect comme CATEGORY_BOOKS par early_category_guess.
3. Endpoint /api/packages/{name}/reprepare accepte manual_isbn/author/book_title.
4. jobs_db persiste les overrides livre.
5. Page detail affiche les inputs ISBN/auteur/titre pour profile=book.
6. Page detail expose data-profile-section="video|book" pour le toggle dynamique.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ============================================================
# MP3 autorise comme audiobook
# ============================================================

def test_compliance_accepts_mp3_for_books(tmp_path):
    """Sprint D.9 : MP3 ne doit PLUS etre BLOCKING en cat Livres."""
    from flox_uploader.core.compliance import _check_book_format

    mp3 = tmp_path / "audiobook.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00fake mp3")

    issues = _check_book_format(mp3)
    # Avant D.9 : 1 issue BLOCKING ("Format mp3 non autorise"). Apres : 0 issue.
    assert len(issues) == 0


def test_compliance_still_blocks_unrelated_format(tmp_path):
    """.mkv reste interdit en cat Livres."""
    from flox_uploader.core.compliance import _check_book_format

    mkv = tmp_path / "movie.mkv"
    mkv.write_bytes(b"fake mkv")

    issues = _check_book_format(mkv)
    assert len(issues) == 1
    assert "mkv" in issues[0].message.lower() or "non autorise" in issues[0].message


def test_early_category_detects_mp3_as_book(tmp_path):
    """.mp3 -> CATEGORY_BOOKS (audiobook par defaut, Gemini n'a pas Musique)."""
    from flox_uploader.core.early_category import early_category_guess
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_BOOKS

    mp3 = tmp_path / "audiobook_001.mp3"
    mp3.write_bytes(b"\xff\xfb fake mp3")
    cat = early_category_guess(mp3)
    assert cat == CATEGORY_BOOKS


# ============================================================
# jobs_db persiste les overrides livre
# ============================================================

def test_jobs_db_add_with_book_overrides(tmp_path, monkeypatch):
    """Sprint D.9 : add_job accepte manual_isbn/author/book_title."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    from flox_uploader.core import jobs_db
    job = jobs_db.add_job(
        "C:/test/book.pdf",
        manual_isbn="9782266154116",
        manual_author="J.R.R. Tolkien",
        manual_book_title="Le Hobbit",
    )
    assert job.manual_isbn == "9782266154116"
    assert job.manual_author == "J.R.R. Tolkien"
    assert job.manual_book_title == "Le Hobbit"

    # Reload via get_job pour verifier la persistance
    reloaded = jobs_db.get_job(job.id)
    assert reloaded is not None
    assert reloaded.manual_isbn == "9782266154116"
    assert reloaded.manual_author == "J.R.R. Tolkien"
    assert reloaded.manual_book_title == "Le Hobbit"


def test_jobs_db_default_overrides_empty(tmp_path, monkeypatch):
    """Sans override -> les champs sont vides par defaut."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    from flox_uploader.core import jobs_db
    job = jobs_db.add_job("C:/test/movie.mkv")
    assert job.manual_isbn == ""
    assert job.manual_author == ""
    assert job.manual_book_title == ""


# ============================================================
# /api/packages/{name}/reprepare accepte les overrides livre
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


def test_reprepare_accepts_book_overrides(client, tmp_path, monkeypatch):
    """POST /reprepare avec manual_isbn/author/book_title -> job cree avec ces fields."""
    from flox_uploader.core import jobs_db
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    # Cree un fichier source + job + package factice
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    initial_job = jobs_db.add_job(str(source))
    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Old.Book-Flox"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Old.Book-Flox",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
    ))
    # Lie le job au package via update_job (set package_dir + release_name)
    jobs_db.update_job(
        initial_job.id,
        package_dir=str(pkg),
        release_name="Old.Book-Flox",
        status="done",
    )

    # Mock submit_prepare_job pour ne pas lancer le subprocess
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: None)

    resp = client.post(
        "/api/packages/Old.Book-Flox/reprepare",
        json={
            "manual_isbn": "9782266154116",
            "manual_author": "Tolkien",
            "manual_book_title": "Hobbit",
            "category_id_hint": 12,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    new_job_id = data["job_id"]

    # Verifie que le nouveau job a bien les overrides
    new_job = jobs_db.get_job(new_job_id)
    assert new_job is not None
    assert new_job.manual_isbn == "9782266154116"
    assert new_job.manual_author == "Tolkien"
    assert new_job.manual_book_title == "Hobbit"


# ============================================================
# Page detail : sections data-profile-section visibles selon cat
# ============================================================

def test_page_detail_book_shows_book_section(client, tmp_path):
    """Pour un package livre : section data-profile-section='book' visible,
    'video' cachee."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Test.Book.Manual-Flox"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Book.Manual-Flox",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,
    ))
    (pkg / "release_name.txt").write_text("Test.Book.Manual-Flox\n")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": {
            "title": "Test",
            "isbn_13": "9782266154116",
            "authors": ["Test Author"],
            "file_format": "epub",
        },
    }), encoding="utf-8")

    resp = client.get("/packages/Test.Book.Manual-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Section book doit etre presente et visible (pas hidden)
    assert 'data-profile-section="book"' in html
    # Inputs manuels livre presents
    assert 'id="manual_isbn"' in html
    assert 'id="manual_author"' in html
    assert 'id="manual_book_title"' in html
    # Valeurs prefillees depuis book_metadata
    assert 'value="9782266154116"' in html
    assert 'value="Test Author"' in html
    # La section video DOIT exister (hidden via class) pour permettre le
    # toggle dynamique JS quand l'user change la cat
    assert 'data-profile-section="video"' in html


def test_page_detail_video_shows_video_section(client, tmp_path):
    """Pour un package video : section 'video' visible, 'book' cachee."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg = pkg_root / "Test.Movie.2024-TEAM"
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=1,
    ))
    (pkg / "release_name.txt").write_text("Test.Movie.2024-TEAM\n")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}', encoding="utf-8",
    )

    resp = client.get("/packages/Test.Movie.2024-TEAM")
    assert resp.status_code == 200
    html = resp.text
    # Les inputs livre existent dans le DOM mais leur conteneur est hidden
    assert 'data-profile-section="book"' in html
    assert 'data-profile-section="video"' in html
    # Force FR (video-only) doit etre present
    assert 'name="force_fr"' in html
    # TMDB ID (video-only) doit etre present
    assert 'id="manual_tmdb_id"' in html
