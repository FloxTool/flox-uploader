"""Tests Sprint D.12 v0.5.0 — BBCode enrichi + N8 Options upload livre.

Verifie :
1. build_torrent_info : extrait taille + liste fichiers d'un .torrent reel.
2. Template BBCode livre inclut taille, nb fichiers, contenu du torrent
   (quand applicable).
3. Section Options upload livre : Cover URL forcée + sous-type dropdown.
4. POST /api/packages/{name}/options accepte manual_cover_url +
   manual_book_subtype et valide (URL http/https, subtype dans whitelist).
5. PackageStateData persiste les nouveaux fields.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


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


def _make_book_pkg(pkg_root: Path, name: str, book_meta: dict) -> Path:
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name=name,
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    (pkg / "presentation.txt").write_text("[b]Test[/b]", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": book_meta,
    }), encoding="utf-8")
    return pkg


# ============================================================
# build_torrent_info
# ============================================================

def test_build_torrent_info_real_torrent(tmp_path):
    """Sur un vrai .torrent : retourne size_pretty + file_count + files."""
    from flox_uploader.core.bbcode_book import build_torrent_info
    from torf import Torrent

    # Crée un dossier avec 2 fichiers et fabrique un torrent
    folder = tmp_path / "MyBook"
    folder.mkdir()
    (folder / "book1.epub").write_bytes(b"x" * 10_000)
    (folder / "book2.epub").write_bytes(b"y" * 20_000)

    t = Torrent(path=folder, trackers=["https://test/announce/x"])
    t.generate()
    tpath = tmp_path / "test.torrent"
    t.write(str(tpath))

    info = build_torrent_info(tpath)
    assert info["file_count"] == 2
    assert info["size_bytes"] >= 30_000
    assert "Ko" in info["size_pretty"] or "Mo" in info["size_pretty"]
    assert len(info["files"]) == 2
    assert info["truncated"] is False


def test_build_torrent_info_missing_file(tmp_path):
    """Path inexistant -> dict vide sans plantage."""
    from flox_uploader.core.bbcode_book import build_torrent_info
    info = build_torrent_info(tmp_path / "no_exist.torrent")
    assert info == {}


# ============================================================
# Template BBCode enrichi
# ============================================================

def test_bbcode_includes_torrent_size(monkeypatch):
    """Le BBCode rendu doit inclure la taille totale si torrent_info fourni."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Test", authors=["A"], publication_year=2024,
        language="fr", file_format="epub",
    )
    bbcode = render_book_bbcode(
        meta, "Test.Release", tracker,
        torrent_info={
            "size_bytes": 12345678,
            "size_pretty": "11.8 Mo",
            "file_count": 1,
            "files": [{"name": "book.epub", "size_pretty": "11.8 Mo"}],
            "truncated": False,
        },
    )
    assert "Taille totale" in bbcode
    assert "11.8 Mo" in bbcode


def test_bbcode_includes_multi_file_contents(monkeypatch):
    """Multi-fichiers (>1) : le bloc 'Contenu du torrent' apparait."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Series", authors=["A"], publication_year=2024,
        language="fr", file_format="epub",
    )
    bbcode = render_book_bbcode(
        meta, "Series.T01-T03", tracker,
        torrent_info={
            "size_bytes": 50000,
            "size_pretty": "48.8 Ko",
            "file_count": 3,
            "files": [
                {"name": "T01.epub", "size_pretty": "16.3 Ko"},
                {"name": "T02.epub", "size_pretty": "16.3 Ko"},
                {"name": "T03.epub", "size_pretty": "16.3 Ko"},
            ],
            "truncated": False,
        },
    )
    assert "Contenu du torrent" in bbcode
    assert "T01.epub" in bbcode
    assert "T02.epub" in bbcode
    assert "T03.epub" in bbcode
    assert "Nombre de fichiers" in bbcode


def test_bbcode_no_contents_for_single_file(monkeypatch):
    """Single-file : pas de bloc 'Contenu du torrent' (redondant avec format)."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Solo", authors=["A"], publication_year=2024,
        language="fr", file_format="epub",
    )
    bbcode = render_book_bbcode(
        meta, "Solo.Release", tracker,
        torrent_info={
            "size_bytes": 50000,
            "size_pretty": "48.8 Ko",
            "file_count": 1,
            "files": [{"name": "book.epub", "size_pretty": "48.8 Ko"}],
            "truncated": False,
        },
    )
    # Pas de bloc Contenu du torrent (single file)
    assert "Contenu du torrent" not in bbcode
    # Pas de "Nombre de fichiers" (single file)
    assert "Nombre de fichiers" not in bbcode


def test_bbcode_works_without_torrent_info(monkeypatch):
    """torrent_info=None ou {} : le rendu fonctionne sans erreur."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(title="Test", authors=["A"], file_format="epub")
    # Test avec None
    bbcode = render_book_bbcode(meta, "Rel", tracker, torrent_info=None)
    assert "Test" in bbcode
    # Test avec dict vide
    bbcode2 = render_book_bbcode(meta, "Rel", tracker, torrent_info={})
    assert "Test" in bbcode2


# ============================================================
# Section Options upload livre + endpoint /options
# ============================================================

def test_options_section_book_has_cover_url_input(client, tmp_path):
    """Pour cat livre : section Options upload contient manual_cover_url."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Options.Book-Flox", book_meta={
        "title": "T", "authors": ["A"], "publication_year": 2024,
        "language": "fr", "file_format": "epub",
    })

    resp = client.get("/packages/Options.Book-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="manual_cover_url"' in html
    assert 'id="manual_book_subtype"' in html
    # Dropdown sous-type avec les bonnes options
    assert "Roman" in html
    assert "BD" in html
    assert "Manga" in html
    assert "Comics" in html
    assert "Livre audio" in html


def test_options_section_video_hides_book_inputs(client, tmp_path):
    """Pour cat video : la section book reste presente mais cachee
    (toggle dynamique JS si user change la cat)."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config
    pkg_root = config.packages_dir()
    pkg = pkg_root / "Movie.2024-TEAM"
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED, release_name="Movie.2024-TEAM",
        tracker_key="gemini", created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z", manual_category_id=1,
    ))
    (pkg / "release_name.txt").write_text("Movie.2024-TEAM\n")
    (pkg / "presentation.txt").write_text("x", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text('{"media_type": "movie", "tmdb_context": {}}', encoding="utf-8")

    resp = client.get("/packages/Movie.2024-TEAM")
    assert resp.status_code == 200
    html = resp.text
    # Le DOM contient les inputs (pour toggle JS) mais wrappes en class hidden
    assert 'id="manual_cover_url"' in html
    assert 'data-profile-section="book"' in html
    # Les inputs video (IMDB) doivent etre visibles
    assert 'id="manual_imdb_id"' in html


def test_options_endpoint_accepts_cover_url(client, tmp_path):
    """POST /options avec manual_cover_url URL valide -> ok 200."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Save.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"],
    })

    resp = client.post("/api/packages/Save.Cover-Flox/options", json={
        "manual_cover_url": "https://example.com/cover.jpg",
    })
    assert resp.status_code == 200, resp.text

    # Verifier la persistance
    from flox_uploader.core.package_state import read_state
    state = read_state(pkg_root / "Save.Cover-Flox")
    assert state.manual_cover_url == "https://example.com/cover.jpg"


def test_options_endpoint_rejects_non_url_cover(client, tmp_path):
    """Cover URL pas http(s) -> 400."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Bad.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"],
    })

    resp = client.post("/api/packages/Bad.Cover-Flox/options", json={
        "manual_cover_url": "not_a_url",
    })
    assert resp.status_code == 400
    assert "http" in resp.text.lower()


def test_options_endpoint_accepts_book_subtype(client, tmp_path):
    """POST /options avec manual_book_subtype valide -> ok 200."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Subtype.Test-Flox", book_meta={
        "title": "T", "authors": ["A"],
    })

    resp = client.post("/api/packages/Subtype.Test-Flox/options", json={
        "manual_book_subtype": "manga",
    })
    assert resp.status_code == 200

    from flox_uploader.core.package_state import read_state
    state = read_state(pkg_root / "Subtype.Test-Flox")
    assert state.manual_book_subtype == "manga"


def test_options_endpoint_rejects_invalid_subtype(client, tmp_path):
    """Subtype hors whitelist -> 400."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Bad.Subtype-Flox", book_meta={
        "title": "T", "authors": ["A"],
    })

    resp = client.post("/api/packages/Bad.Subtype-Flox/options", json={
        "manual_book_subtype": "haiku",  # pas dans la liste
    })
    assert resp.status_code == 400


def test_options_endpoint_accepts_empty_book_subtype(client, tmp_path):
    """Subtype vide (= auto) -> ok."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Auto.Subtype-Flox", book_meta={
        "title": "T", "authors": ["A"],
    })

    resp = client.post("/api/packages/Auto.Subtype-Flox/options", json={
        "manual_book_subtype": "",
    })
    assert resp.status_code == 200
