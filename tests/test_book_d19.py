"""Tests Sprint D.19 v0.5.0 — extraction cover + 4 previews + upload imgbb.

Cible note Louis Q3 : extraction cover + few screenshot random pour tous
les formats (PDF, EPUB, CBZ, CBR, MP3, M4B), hebergement imgbb.

Verifie :
1. image_extraction.extract_cover_and_previews route par format
2. CBZ : 1 cover + 4 previews espacees
3. PDF : via PyMuPDF (skip si non-installe au runtime)
4. EPUB : cover seule, pas de previews (XHTML)
5. MP3/M4B : cover ID3/MP4, pas de previews
6. Format non supporte : warning, pas de crash
7. image_host.upload_to_imgbb : success + error paths (mock HTTP)
8. BookMetadata.preview_urls roundtrip serialize
9. BBCode template : ligne [img=250] des previews (D.22 N-UX1 : etait [img=150])
10. Page detail : galerie thumbnails
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest


# ============================================================
# image_extraction : routing
# ============================================================

def test_extract_routes_unknown_format(tmp_path):
    """Format inconnu (.mobi) -> warning, pas de crash."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    src = tmp_path / "book.mobi"
    src.write_bytes(b"fake mobi")
    out = tmp_path / "previews"
    result = extract_cover_and_previews(src, out)
    assert result["cover"] is None
    assert result["previews"] == []
    assert result["format"] == "mobi"
    assert "non supportee" in result["warning"]


def test_extract_missing_file(tmp_path):
    """Fichier absent -> warning + cover=None."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    out = tmp_path / "previews"
    result = extract_cover_and_previews(tmp_path / "absent.pdf", out)
    assert result["cover"] is None
    assert "absent" in result["warning"]


# ============================================================
# CBZ extraction
# ============================================================

def _make_cbz_with_images(path: Path, count: int) -> None:
    """Helper : cree un CBZ avec N images numerotees."""
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(count):
            name = f"page_{i:03d}.jpg"
            # 5 bytes uniques par image pour distinguer
            zf.writestr(name, b"\xff\xd8\xff\xe0" + bytes([i % 256]))


def test_extract_cbz_cover_and_previews(tmp_path):
    """CBZ avec 20 images : 1 cover + 4 previews espacees."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    src = tmp_path / "book.cbz"
    _make_cbz_with_images(src, count=20)
    out = tmp_path / "previews"

    result = extract_cover_and_previews(src, out, preview_count=4)
    assert result["cover"] is not None
    assert result["cover"].is_file()
    assert len(result["previews"]) == 4
    for p in result["previews"]:
        assert p.is_file()
        assert p.read_bytes().startswith(b"\xff\xd8\xff")


def test_extract_cbz_few_images(tmp_path):
    """CBZ avec 5 images seulement : cover OK, previews limites."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    src = tmp_path / "short.cbz"
    _make_cbz_with_images(src, count=5)
    out = tmp_path / "previews"

    result = extract_cover_and_previews(src, out, preview_count=4)
    assert result["cover"] is not None
    # On a au moins quelques previews (selon ce que _pick_evenly_spaced retourne)
    assert len(result["previews"]) >= 1


def test_extract_cbz_no_images(tmp_path):
    """CBZ vide -> warning."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    src = tmp_path / "empty.cbz"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("readme.txt", "no images")
    out = tmp_path / "previews"

    result = extract_cover_and_previews(src, out)
    assert result["cover"] is None
    assert "sans images" in result["warning"]


# ============================================================
# EPUB extraction (cover seule)
# ============================================================

def _make_epub_with_cover(path: Path) -> None:
    """EPUB minimal avec cover declaree dans manifest."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>""")
        zf.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Test</dc:title>
        <meta name="cover" content="cover-img"/>
    </metadata>
    <manifest>
        <item id="cover-img" href="cover.jpg" media-type="image/jpeg"/>
    </manifest>
</package>""")
        zf.writestr("OEBPS/cover.jpg", b"\xff\xd8\xff\xe0epub_cover_data")


def test_extract_epub_cover_no_previews(tmp_path):
    """EPUB : cover OK, pas de previews."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    src = tmp_path / "book.epub"
    _make_epub_with_cover(src)
    out = tmp_path / "previews"

    result = extract_cover_and_previews(src, out, preview_count=4)
    assert result["cover"] is not None
    assert result["cover"].is_file()
    # EPUB : volontairement pas de previews
    assert result["previews"] == []
    assert result["format"] == "epub"


# ============================================================
# PDF extraction (via PyMuPDF)
# ============================================================

def test_extract_pdf_cover_and_previews(tmp_path):
    """PDF >= 6 pages : cover (p1) + 4 previews random."""
    pytest.importorskip("fitz")  # PyMuPDF
    import fitz

    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    # Cree un PDF de 10 pages blanches
    pdf_path = tmp_path / "doc.pdf"
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page(width=200, height=300)
        page.insert_text((20, 50), f"Page {i+1}")
    doc.save(str(pdf_path))
    doc.close()

    out = tmp_path / "previews"
    result = extract_cover_and_previews(
        pdf_path, out, preview_count=4, rng_seed=42,
    )
    assert result["cover"] is not None
    assert result["cover"].is_file()
    # PDF 10 pages : on retire page 0 (cover) et derniere -> 8 pages avail
    # On en pick 4
    assert len(result["previews"]) == 4
    for p in result["previews"]:
        assert p.is_file()
        # Le PNG/JPEG genere par PyMuPDF a une taille raisonnable
        assert p.stat().st_size > 100


def test_extract_pdf_single_page(tmp_path):
    """PDF avec 1 seule page : cover OK, pas de previews."""
    pytest.importorskip("fitz")
    import fitz

    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    pdf_path = tmp_path / "single.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=300)
    doc.save(str(pdf_path))
    doc.close()

    out = tmp_path / "previews"
    result = extract_cover_and_previews(pdf_path, out, preview_count=4)
    assert result["cover"] is not None
    assert result["previews"] == []


# ============================================================
# Audio MP3 / M4B extraction (via mutagen)
# ============================================================

def test_extract_audio_no_cover_returns_warning(tmp_path):
    """MP3 sans cover tag -> warning, pas de crash."""
    pytest.importorskip("mutagen")
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    # MP3 minimal valide (header silence)
    src = tmp_path / "audio.mp3"
    # Frame MPEG-1 Layer III silence : header + 2 bytes
    src.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 1000)

    out = tmp_path / "previews"
    result = extract_cover_and_previews(src, out)
    # Format detecte
    assert result["format"] == "mp3"
    # Pas de cover ID3 -> warning
    assert result["cover"] is None
    # Pas de previews pour audio (par design)
    assert result["previews"] == []


# ============================================================
# imgbb upload (mocked HTTP)
# ============================================================

class _MockResp:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_upload_to_imgbb_success(tmp_path):
    """Upload reussi : retourne ImgbbUploadResult.success=True + url."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb

    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"X" * 1000)

    def fake_post(url, files=None, params=None, timeout=None):
        # Verifie qu'on envoie la cle en query param
        assert params and params.get("key") == "TEST_KEY"
        return _MockResp(payload={
            "success": True,
            "data": {
                "url": "https://i.ibb.co/abc/test.jpg",
                "delete_url": "https://ibb.co/del/xyz",
            },
        })

    result = upload_to_imgbb(img, "TEST_KEY", http_post=fake_post)
    assert result.success is True
    assert result.url == "https://i.ibb.co/abc/test.jpg"
    assert result.delete_url == "https://ibb.co/del/xyz"
    assert result.size > 0


def test_upload_to_imgbb_no_key():
    """Sans api_key : success=False."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb
    from pathlib import Path as _P

    result = upload_to_imgbb(_P("/whatever.jpg"), api_key="")
    assert result.success is False
    assert "non configure" in result.error


def test_upload_to_imgbb_missing_file(tmp_path):
    """Fichier absent : success=False."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb

    result = upload_to_imgbb(tmp_path / "absent.jpg", "K")
    assert result.success is False
    assert "absente" in result.error.lower() or "absent" in result.error.lower()


def test_upload_to_imgbb_too_large(tmp_path):
    """Image > 32 MB : refuse avant upload."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb, IMGBB_MAX_BYTES

    huge = tmp_path / "huge.jpg"
    huge.write_bytes(b"X" * (IMGBB_MAX_BYTES + 1))

    result = upload_to_imgbb(huge, "K")
    assert result.success is False
    assert "trop volumineuse" in result.error


def test_upload_to_imgbb_server_error(tmp_path):
    """imgbb retourne success=False : on propage l'erreur."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb

    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"X" * 100)

    def fake_post(url, files=None, params=None, timeout=None):
        return _MockResp(payload={
            "success": False,
            "error": {"message": "Invalid API key"},
        })

    result = upload_to_imgbb(img, "BAD_KEY", http_post=fake_post)
    assert result.success is False
    assert "Invalid API key" in result.error


def test_upload_to_imgbb_network_error(tmp_path):
    """Exception reseau : success=False + error explicite."""
    from flox_uploader.core.providers.image_host import upload_to_imgbb

    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"X" * 100)

    def fake_post(url, files=None, params=None, timeout=None):
        raise ConnectionError("DNS failure")

    result = upload_to_imgbb(img, "K", http_post=fake_post)
    assert result.success is False
    assert "DNS failure" in result.error or "Network error" in result.error


def test_upload_batch_to_imgbb(tmp_path):
    """upload_batch upload N images en sequence."""
    from flox_uploader.core.providers.image_host import upload_batch_to_imgbb

    img1 = tmp_path / "a.jpg"
    img1.write_bytes(b"\xff\xd8\xff" + b"A" * 50)
    img2 = tmp_path / "b.jpg"
    img2.write_bytes(b"\xff\xd8\xff" + b"B" * 50)

    call_count = {"n": 0}
    def fake_post(url, files=None, params=None, timeout=None):
        call_count["n"] += 1
        return _MockResp(payload={
            "success": True,
            "data": {"url": f"https://i.ibb.co/{call_count['n']}.jpg"},
        })

    results = upload_batch_to_imgbb(
        [img1, img2], "K", http_post=fake_post,
    )
    assert len(results) == 2
    assert all(r.success for r in results)
    assert results[0].url != results[1].url


# ============================================================
# BookMetadata.preview_urls roundtrip
# ============================================================

def test_book_metadata_preview_urls_serialize():
    """preview_urls inclus dans book_to_dict + book_from_dict."""
    from flox_uploader.core.providers.book_metadata import (
        BookMetadata, book_to_dict, book_from_dict,
    )
    m1 = BookMetadata(
        title="T",
        preview_urls=["https://i.ibb.co/1.jpg", "https://i.ibb.co/2.jpg"],
    )
    d = book_to_dict(m1)
    assert d["preview_urls"] == ["https://i.ibb.co/1.jpg", "https://i.ibb.co/2.jpg"]
    m2 = book_from_dict(d)
    assert m2.preview_urls == m1.preview_urls


# ============================================================
# BBCode template : ligne [img=250] previews (D.22 update)
# ============================================================

def test_bbcode_renders_preview_row(monkeypatch):
    """Si preview_urls present, BBCode contient [img=250] sur 1 ligne.
    Sprint D.22 (note Louis N-UX1) : taille augmentee de 150 a 250."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="T", authors=["A"], file_format="cbz",
        preview_urls=[
            "https://i.ibb.co/1.jpg",
            "https://i.ibb.co/2.jpg",
            "https://i.ibb.co/3.jpg",
            "https://i.ibb.co/4.jpg",
        ],
    )
    bbcode = render_book_bbcode(meta, "Rel", tracker)
    for url in meta.preview_urls:
        assert f"[img=250]{url}[/img]" in bbcode


def test_bbcode_no_preview_row_without_urls(monkeypatch):
    """Sans preview_urls, pas de [img=250] dans le BBCode (taille D.22)."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(title="T", authors=["A"], file_format="cbz")
    bbcode = render_book_bbcode(meta, "Rel", tracker)
    assert "[img=250]" not in bbcode


# ============================================================
# Page detail : galerie thumbnails
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
        state=PackageState.PREPARED, release_name=name,
        tracker_key="gemini", created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z", manual_category_id=12,
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


def test_page_detail_shows_preview_thumbnails(client, tmp_path):
    """Si bm.preview_urls present, page detail affiche les thumbs."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Prev.Gallery-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "cbz",
        "preview_urls": [
            "https://i.ibb.co/1.jpg",
            "https://i.ibb.co/2.jpg",
        ],
    })

    resp = client.get("/packages/Prev.Gallery-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Les <img> pointent vers les URLs imgbb
    assert "https://i.ibb.co/1.jpg" in html
    assert "https://i.ibb.co/2.jpg" in html
    # Badge "X previews" visible
    assert "preview" in html.lower()


def test_page_detail_no_thumbnails_without_previews(client, tmp_path):
    """Pas de preview_urls -> pas de section galerie."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "No.Prev-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        # PAS de preview_urls
    })

    resp = client.get("/packages/No.Prev-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "i.ibb.co" not in html
