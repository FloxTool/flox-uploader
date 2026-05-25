"""Tests Sprint D.14 v0.5.0 — fix faux warning Format + banners sous Score.

Verifie :
1. book_to_dict serialise bien file_format (fix racine du faux warning N-Log-1/3).
2. book_from_dict deserialise file_format.
3. Page detail livre : warnings book sont SOUS le panneau Detail du score
   (note N-UX-1).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ============================================================
# Fix racine : file_format dans book_to_dict / book_from_dict
# ============================================================

def test_book_to_dict_includes_file_format():
    """Sprint D.14 N-Log-1/3 : file_format DOIT etre serialise."""
    from flox_uploader.core.providers.book_metadata import (
        BookMetadata, book_to_dict,
    )
    meta = BookMetadata(title="T", file_format="epub")
    d = book_to_dict(meta)
    assert "file_format" in d
    assert d["file_format"] == "epub"


def test_book_from_dict_restores_file_format():
    """book_from_dict relit file_format depuis le dict."""
    from flox_uploader.core.providers.book_metadata import book_from_dict
    meta = book_from_dict({"title": "T", "file_format": "pdf"})
    assert meta.file_format == "pdf"


def test_book_to_from_dict_roundtrip_file_format():
    """Le round-trip preserve file_format."""
    from flox_uploader.core.providers.book_metadata import (
        BookMetadata, book_from_dict, book_to_dict,
    )
    original = BookMetadata(title="T", authors=["A"], file_format="cbz")
    d = book_to_dict(original)
    restored = book_from_dict(d)
    assert restored.file_format == "cbz"
    assert restored.title == "T"
    assert restored.authors == ["A"]


# ============================================================
# Page detail : ordre Score d'abord, puis warnings book
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


def test_warnings_appear_after_score_panel(client, tmp_path):
    """Sprint D.14 N-UX-1 : les warnings book doivent etre SOUS le panneau
    'Detail du score', pas au-dessus."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Order.Test-Flox", book_meta={
        # ISBN manquant -> warning Presentation incomplete
        "title": "T", "authors": ["A"], "publication_year": 2024,
        "language": "fr", "file_format": "epub",
        "description": "ok", "cover_url": "https://x.com/c.jpg",
    })

    resp = client.get("/packages/Order.Test-Flox")
    assert resp.status_code == 200
    html = resp.text

    # Trouver les positions
    score_panel = html.find("Détail du score")
    score_close = html.find("</section>", score_panel)
    presentation_warning = html.find("Présentation incomplète")

    assert score_panel > 0, "Le panneau Detail du score doit etre present"
    assert score_close > score_panel, "Score panel doit fermer son section"
    assert presentation_warning > 0, "Warning presentation doit etre present"
    # Le warning DOIT venir APRES la fermeture du score panel
    assert presentation_warning > score_close, (
        f"Le warning Presentation ({presentation_warning}) doit etre APRES "
        f"la fermeture du score panel ({score_close})."
    )


def test_warning_format_disappears_when_format_present(client, tmp_path):
    """Sprint D.14 N-Log-1/3 : si file_format est present dans book_metadata,
    aucun warning 'Format manquant' ne doit apparaitre.

    Cas reel : un EPUB extrait correctement a file_format='epub'. Le warning
    ne devrait JAMAIS s'afficher dans ce cas."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Format.Present-Flox", book_meta={
        "title": "T", "authors": ["A"], "publication_year": 2024,
        "language": "fr",
        "file_format": "epub",  # PRESENT
        "isbn_13": "9782266154116",
        "description": "ok", "cover_url": "x",
    })

    resp = client.get("/packages/Format.Present-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Aucun warning Format
    assert "Format fichier manquant" not in html
    # Pas de warning 'Format' dans la liste des champs Gemini manquants
    # (peut y avoir 'Format' ailleurs dans la page, on cherche un pattern precis)
    assert "Format de release Gemini incomplet" not in html


def test_warning_format_appears_when_file_format_empty(client, tmp_path):
    """Si VRAIMENT file_format est vide (cas degenere), le warning apparait."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Format.Missing-Flox", book_meta={
        "title": "T", "authors": ["A"], "publication_year": 2024,
        "language": "fr",
        "file_format": "",  # VIDE
        "isbn_13": "9782266154116",
        "description": "ok", "cover_url": "x",
    })

    resp = client.get("/packages/Format.Missing-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Format de release Gemini incomplet" in html


def test_full_pipeline_book_persists_file_format(tmp_path, monkeypatch):
    """End-to-end : un EPUB minimal passe par BookNamingStrategy ->
    file_format='epub' apparait dans debug.json."""
    import zipfile
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/x")
    debug = Debug(tmp_path / "_debug")
    strategy = BookNamingStrategy()
    strategy.build_release_name(
        epub, tracker, nfo_text="", debug=debug,
        _book_lookup=lambda m: m,
    )

    bm = debug.data.get("book_metadata") or {}
    # CRITIQUE : la clé file_format DOIT exister et valoir 'epub'
    assert "file_format" in bm
    assert bm["file_format"] == "epub"
