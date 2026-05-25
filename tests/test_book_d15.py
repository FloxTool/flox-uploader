"""Tests Sprint D.15 v0.5.0 — liens directs fiches BnF/Google Books.

Verifie :
1. google_books._parse_first_item capture le volumeId (items[0].id).
2. bnf._extract_dc_fields capture l'ARK BnF (pattern ark:/12148/cbXXX).
3. BookMetadata + serialize roundtrip preservent google_books_id + bnf_ark.
4. Template _detail_book.html : lien direct Google Books si volumeId,
   lien direct catalogue BnF si ARK, sinon pas de lien (texte brut).
5. Template BBCode inclut [url=...] direct pour BnF + Google Books.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ============================================================
# google_books volumeId capture
# ============================================================

def test_google_books_captures_volume_id():
    """Sprint D.15 N-Log-2 : items[0].id stocke dans google_books_id."""
    from flox_uploader.core.providers.google_books import _parse_first_item

    fake_response = {
        "items": [{
            "id": "Nw2eEQAAQBAJ",
            "volumeInfo": {
                "title": "Guide Poitiers 2026",
                "authors": ["Dominique Auzias"],
                "publishedDate": "2025-09-01",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9782305108124"},
                ],
            },
        }],
    }
    meta = _parse_first_item(fake_response)
    assert meta is not None
    assert meta.google_books_id == "Nw2eEQAAQBAJ"
    assert meta.title == "Guide Poitiers 2026"
    assert meta.isbn_13 == "9782305108124"


def test_google_books_handles_missing_volume_id():
    """Si pas de id (cas degenere), google_books_id reste vide."""
    from flox_uploader.core.providers.google_books import _parse_first_item

    fake_response = {
        "items": [{
            "volumeInfo": {"title": "Sans ID"},
        }],
    }
    meta = _parse_first_item(fake_response)
    assert meta is not None
    assert meta.google_books_id == ""


# ============================================================
# bnf ARK capture
# ============================================================

def test_bnf_captures_ark_from_identifier():
    """Sprint D.15 N-Bug-1 : ARK pattern ark:/12148/cbXXX trouve dans dc:identifier."""
    from flox_uploader.core.providers.bnf import _parse_first_record

    # Reponse SRU XML minimaliste avec un ARK dans dc:identifier
    fake_xml = """<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"
                       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <numberOfRecords>1</numberOfRecords>
    <records>
        <record>
            <recordData>
                <oai_dc:dc xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
                    <dc:title>Test Book BnF</dc:title>
                    <dc:creator>Test Author</dc:creator>
                    <dc:identifier>ark:/12148/cb45123456p</dc:identifier>
                    <dc:identifier xsi:type="dcterms:ISBN">9782266154116</dc:identifier>
                </oai_dc:dc>
            </recordData>
        </record>
    </records>
</searchRetrieveResponse>"""
    meta = _parse_first_record(fake_xml)
    assert meta is not None
    assert meta.bnf_ark == "cb45123456p"
    assert meta.title == "Test Book BnF"


def test_bnf_handles_missing_ark():
    """Sans ARK, bnf_ark reste vide (sans plantage)."""
    from flox_uploader.core.providers.bnf import _parse_first_record

    fake_xml = """<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
    <numberOfRecords>1</numberOfRecords>
    <records>
        <record>
            <recordData>
                <oai_dc:dc xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
                    <dc:title>Test Book</dc:title>
                    <dc:creator>A</dc:creator>
                </oai_dc:dc>
            </recordData>
        </record>
    </records>
</searchRetrieveResponse>"""
    meta = _parse_first_record(fake_xml)
    assert meta is not None
    assert meta.bnf_ark == ""


# ============================================================
# BookMetadata roundtrip
# ============================================================

def test_book_metadata_serialize_external_ids():
    """google_books_id + bnf_ark sont serialises + deserialises."""
    from flox_uploader.core.providers.book_metadata import (
        BookMetadata, book_from_dict, book_to_dict,
    )
    original = BookMetadata(
        title="T", google_books_id="Nw2eEQAAQBAJ", bnf_ark="cb45123456p",
    )
    d = book_to_dict(original)
    assert d["google_books_id"] == "Nw2eEQAAQBAJ"
    assert d["bnf_ark"] == "cb45123456p"

    restored = book_from_dict(d)
    assert restored.google_books_id == "Nw2eEQAAQBAJ"
    assert restored.bnf_ark == "cb45123456p"


# ============================================================
# Page detail : liens directs si dispo, sinon retire
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


def test_detail_book_renders_direct_google_books_link(client, tmp_path):
    """Si google_books_id present, lien direct books.google.com?id=X."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Direct.GB.Link-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "google_books_id": "Nw2eEQAAQBAJ",
    })

    resp = client.get("/packages/Direct.GB.Link-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Sprint D.35 v0.5.0 : format moderne /books/edition/<slug>/<id>?hl=fr
    # (au lieu de l'ancien books?id= qui ouvre une page basique).
    assert "www.google.com/books/edition/" in html
    assert "/Nw2eEQAAQBAJ?hl=fr" in html
    # Plus de lien de recherche generique
    assert "google.com/search?tbm=bks" not in html


def test_detail_book_no_google_books_link_without_id(client, tmp_path):
    """Si pas de google_books_id, pas de lien Google Books du tout."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "No.GB.Link-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        # PAS de google_books_id
    })

    resp = client.get("/packages/No.GB.Link-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Pas de lien direct (volumeId absent)
    assert "books.google.com/books?id=" not in html
    assert "www.google.com/books/edition/" not in html
    # Pas non plus de lien de recherche (on a retire le fallback search)
    assert "google.com/search?tbm=bks" not in html


def test_detail_book_renders_direct_bnf_link_with_ark(client, tmp_path):
    """Si bnf_ark present, ISBN lie au catalogue BnF direct."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Direct.BnF.Link-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "isbn_13": "9782266154116",
        "bnf_ark": "cb45123456p",
    })

    resp = client.get("/packages/Direct.BnF.Link-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "catalogue.bnf.fr/ark:/12148/cb45123456p" in html
    # Pas de lien search bnf.fr/recherche
    assert "bnf.fr/fr/recherche/general" not in html


def test_detail_book_isbn_no_link_without_ark(client, tmp_path):
    """ISBN sans ARK : affichage texte brut, pas de lien (decision Louis)."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "ISBN.Text.Only-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "isbn_13": "9782266154116",
        # PAS de bnf_ark
    })

    resp = client.get("/packages/ISBN.Text.Only-Flox")
    assert resp.status_code == 200
    html = resp.text
    # L'ISBN doit etre affiche
    assert "9782266154116" in html
    # Mais PAS de lien BnF (search ou catalog)
    assert "bnf.fr/fr/recherche/general" not in html
    assert "catalogue.bnf.fr/ark" not in html


# ============================================================
# BBCode : liens [url=...] direct fiche
# ============================================================

def test_bbcode_includes_direct_links_when_ids_present(monkeypatch):
    """BBCode rendu : [url=...] pour BnF + Google Books si IDs."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Test", authors=["A"], publication_year=2024,
        language="fr", file_format="epub", isbn_13="9782266154116",
        google_books_id="Nw2eEQAAQBAJ",
        bnf_ark="cb45123456p",
    )
    bbcode = render_book_bbcode(meta, "Test.Release", tracker)
    assert "[url=https://catalogue.bnf.fr/ark:/12148/cb45123456p]" in bbcode
    # Sprint D.35 : format moderne /books/edition/<slug>/<id>?hl=fr
    assert "[url=https://www.google.com/books/edition/" in bbcode
    assert "/Nw2eEQAAQBAJ?hl=fr]" in bbcode


def test_bbcode_no_direct_links_without_ids(monkeypatch):
    """Sans IDs externes, pas de section liens dans le BBCode."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Test", authors=["A"], file_format="epub",
    )
    bbcode = render_book_bbcode(meta, "Test.Release", tracker)
    assert "catalogue.bnf.fr/ark" not in bbcode
    assert "books.google.com/books?id=" not in bbcode
    assert "www.google.com/books/edition/" not in bbcode
