"""Tests Sprint D.8 v0.5.0 — template BBCode livre harmonise + warning incomplete.

Verifie :
1. template_book.bbcode utilise les memes blocs visuels que template_movie
   (separateurs [img=500] imgur, headers [color=#C9B27D], sections).
2. Le rendu BBCode contient les sections attendues meme avec metadata
   incomplete (placeholders en italique).
3. La page detail affiche un warning si book_metadata est incomplet
   (manque author/description/cover/ISBN).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.bbcode_book import render_book_bbcode
from flox_uploader.core.providers.book_metadata import BookMetadata
from flox_uploader.trackers import get_tracker


# ============================================================
# Template BBCode harmonise
# ============================================================

def test_bbcode_book_has_film_style_sections(monkeypatch):
    """Le template livre doit utiliser les memes blocs que le film."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Le Seigneur des Anneaux",
        authors=["J.R.R. Tolkien"],
        publisher="Christian Bourgois",
        publication_year=1954,
        language="fr",
        page_count=1200,
        isbn_13="9782266154116",
        description="Un long voyage...",
        cover_url="https://example.com/sda.jpg",
        file_format="epub",
        genres=["Fantasy"],
        sources=["bnf", "google_books"],
    )
    bbcode = render_book_bbcode(meta, "Tolkien.LOTR.1954.FRENCH.EPUB-Flox", tracker)

    # Marqueurs visuels harmonises avec template_movie.bbcode
    assert "[color=#C9B27D]" in bbcode  # tag couleur sable Gemini
    assert "[img=500]https://i.imgur.com/" in bbcode  # separateurs visuels
    assert "Informations sur le livre" in bbcode
    assert "Informations sur la release" in bbcode
    assert "Résumé" in bbcode
    assert "Bonne lecture" in bbcode  # remplace "Enjoy & Bon visionnage"

    # Cover en [img=300] (taille livre, plus petite que film [img=500])
    assert "[img=300]https://example.com/sda.jpg[/img]" in bbcode


def test_bbcode_book_placeholder_missing_author(monkeypatch):
    """Si pas d'auteur : affiche '[i]Inconnu[/i]' au lieu de vide."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(title="Anonyme", file_format="pdf")
    bbcode = render_book_bbcode(meta, "Anonyme.PDF-Flox", tracker)
    assert "Auteur inconnu" in bbcode or "[i]Inconnu[/i]" in bbcode


def test_bbcode_book_placeholder_missing_description(monkeypatch):
    """Si pas de description : placeholder italique invitant a editer."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Sans Resume",
        authors=["Author"],
        file_format="epub",
    )
    bbcode = render_book_bbcode(meta, "Author.Sans.Resume.EPUB-Flox", tracker)
    assert "[i]Aucun résumé disponible" in bbcode


# ============================================================
# Warning page detail si presentation incomplete
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


def _make_book_package(pkg_root: Path, name: str, book_meta: dict) -> Path:
    """Helper : cree un package livre avec book_metadata."""
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
        manual_category_id=12,  # Livre
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    # Presentation existante pour que le bloc apparaisse
    (pkg / "presentation.txt").write_text(
        "[b]Test[/b] presentation BBCode placeholder.", encoding="utf-8",
    )
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": book_meta,
    }), encoding="utf-8")
    return pkg


def test_page_detail_book_incomplete_shows_warning(client, tmp_path):
    """Livre avec metadata vide -> warning 'Presentation incomplete' visible."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_package(pkg_root, "Incomplete.Book-Flox", book_meta={
        "title": "Un titre",
        # Pas d'authors, pas de description, pas de cover, pas d'ISBN
        "file_format": "pdf",
    })

    resp = client.get("/packages/Incomplete.Book-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Présentation incomplète" in html
    # Doit mentionner les champs manquants
    assert "auteur" in html
    assert "résumé" in html
    assert "couverture" in html
    assert "ISBN" in html


def test_page_detail_book_complete_no_warning(client, tmp_path):
    """Livre avec tous les champs -> pas de warning."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_package(pkg_root, "Complete.Book-Flox", book_meta={
        "title": "Un titre",
        "authors": ["Un auteur"],
        "description": "Un beau resume",
        "cover_url": "https://example.com/c.jpg",
        "isbn_13": "9782266154116",
        "file_format": "epub",
    })

    resp = client.get("/packages/Complete.Book-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Présentation incomplète" not in html


def test_page_detail_video_no_book_warning(client, tmp_path):
    """Un package video ne montre PAS le warning livre meme si manque metadata."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config
    pkg_root = config.packages_dir()
    pkg = pkg_root / "Test.Movie.2024.FRENCH.BluRay.x265-TEAM"
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Movie.2024.FRENCH.BluRay.x265-TEAM",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=1,  # Film
    ))
    (pkg / "release_name.txt").write_text("Test.Movie.2024.FRENCH.BluRay.x265-TEAM\n")
    (pkg / "presentation.txt").write_text("[b]Film[/b]", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text('{"media_type": "movie", "tmdb_context": {}}', encoding="utf-8")

    resp = client.get("/packages/Test.Movie.2024.FRENCH.BluRay.x265-TEAM")
    assert resp.status_code == 200
    assert "Présentation incomplète" not in resp.text
