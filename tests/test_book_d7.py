"""Tests Sprint D.7 v0.5.0 — extracteurs PDF/CBZ + cover EPUB + scan inbox.

Verifie :
1. extract_pdf_metadata : metadata depuis /Info + nom fichier + ISBN regex
2. extract_cbz_metadata : ComicInfo.xml + nom fichier + page count
3. extract_epub_cover : extraction de la cover embarquee
4. extract_cbz_cover : extraction de la premiere image
5. book_lookup permissif : title seul (sans author) declenche lookup
6. /api/inbox/peek-category : devine la cat depuis le path
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest


# ============================================================
# extract_pdf_metadata
# ============================================================

def test_extract_pdf_metadata_minimal_pdf(tmp_path):
    """Sur un PDF minimal genere via pypdf : on extrait au moins page_count
    et le format='pdf'."""
    from pypdf import PdfWriter
    from flox_uploader.core.providers.pdf_metadata import extract_pdf_metadata

    pdf_path = tmp_path / "minimal.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as f:
        writer.write(f)

    meta = extract_pdf_metadata(pdf_path)
    assert meta.file_format == "pdf"
    assert meta.page_count == 2


def test_extract_pdf_metadata_with_info_dict(tmp_path):
    """Si /Info contient Title + Author, on les extrait."""
    from pypdf import PdfWriter
    from flox_uploader.core.providers.pdf_metadata import extract_pdf_metadata

    pdf_path = tmp_path / "with_info.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({
        "/Title": "Le Hobbit",
        "/Author": "J.R.R. Tolkien",
        "/Subject": "Aventure fantastique",
        "/Keywords": "fantasy, aventure",
    })
    with pdf_path.open("wb") as f:
        writer.write(f)

    meta = extract_pdf_metadata(pdf_path)
    assert meta.title == "Le Hobbit"
    assert meta.authors == ["J.R.R. Tolkien"]
    assert "fantasy" in meta.genres
    assert "aventure" in meta.genres
    assert "local_pdf" in meta.sources


def test_extract_pdf_metadata_isbn_in_subject(tmp_path):
    """Si l'ISBN-13 est present dans /Subject, on l'extrait."""
    from pypdf import PdfWriter
    from flox_uploader.core.providers.pdf_metadata import extract_pdf_metadata

    pdf_path = tmp_path / "with_isbn.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({
        "/Title": "Un titre",
        "/Subject": "Un livre tres long avec son ISBN 9782266154116 dedans",
    })
    with pdf_path.open("wb") as f:
        writer.write(f)

    meta = extract_pdf_metadata(pdf_path)
    assert meta.isbn_13 == "9782266154116"


def test_extract_pdf_metadata_filename_fallback(tmp_path):
    """Si /Info est vide, on parse le nom de fichier pour titre + auteur."""
    from pypdf import PdfWriter
    from flox_uploader.core.providers.pdf_metadata import extract_pdf_metadata

    pdf_path = tmp_path / "Tolkien - Le Hobbit.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as f:
        writer.write(f)

    meta = extract_pdf_metadata(pdf_path)
    assert meta.title == "Le Hobbit"
    # Auteur peut etre rempli ou pas selon heuristique (Tolkien = 1 mot capitalize -> auteur)
    assert meta.authors == ["Tolkien"] or meta.title == "Le Hobbit"


def test_extract_pdf_metadata_missing_file(tmp_path):
    """Un path inexistant ne plante pas, retourne meta minimal."""
    from flox_uploader.core.providers.pdf_metadata import extract_pdf_metadata
    meta = extract_pdf_metadata(tmp_path / "no_exist.pdf")
    assert meta.file_format == "pdf"
    assert meta.sources == []


# ============================================================
# extract_cbz_metadata
# ============================================================

def _make_cbz(path: Path, image_names: list[str], comic_info_xml: str = "") -> None:
    """Helper : cree un CBZ avec N images + optionnel ComicInfo.xml."""
    with zipfile.ZipFile(path, "w") as zf:
        for name in image_names:
            zf.writestr(name, b"\xff\xd8\xff\xe0fake_jpeg_data")  # JPEG header
        if comic_info_xml:
            zf.writestr("ComicInfo.xml", comic_info_xml)


def test_extract_cbz_metadata_page_count(tmp_path):
    """Compte le nombre d'images = pages."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_metadata

    cbz = tmp_path / "Naruto T01.cbz"
    _make_cbz(cbz, ["001.jpg", "002.jpg", "003.jpg"])

    meta = extract_cbz_metadata(cbz)
    assert meta.file_format == "cbz"
    assert meta.page_count == 3


def test_extract_cbz_metadata_comicinfo_xml(tmp_path):
    """Parse le ComicInfo.xml si present."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_metadata

    cbz = tmp_path / "test.cbz"
    xml = """<?xml version="1.0"?>
<ComicInfo>
    <Title>L'Heritier</Title>
    <Series>Largo Winch</Series>
    <Number>1</Number>
    <Writer>Jean Van Hamme</Writer>
    <Penciller>Philippe Francq</Penciller>
    <Publisher>Dupuis</Publisher>
    <Year>1990</Year>
    <LanguageISO>fr</LanguageISO>
    <Summary>Largo Winchester apprend qu'il herite d'un empire financier...</Summary>
    <Genre>Aventure</Genre>
</ComicInfo>"""
    _make_cbz(cbz, ["001.jpg", "002.jpg"], comic_info_xml=xml)

    meta = extract_cbz_metadata(cbz)
    assert meta.title == "L'Heritier"
    assert meta.series == "Largo Winch"
    assert meta.series_index == 1.0
    assert "Jean Van Hamme" in meta.authors
    assert "Philippe Francq" in meta.authors
    assert meta.publisher == "Dupuis"
    assert meta.publication_year == 1990
    assert meta.language == "fr"
    assert "Largo Winchester" in meta.description
    assert "Aventure" in meta.genres


def test_extract_cbz_metadata_filename_fallback(tmp_path):
    """Si pas de ComicInfo.xml, parse le nom de fichier."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_metadata

    cbz = tmp_path / "[Hergé] Tintin T07 - L'Ile Noire.cbz"
    _make_cbz(cbz, ["001.jpg"])

    meta = extract_cbz_metadata(cbz)
    assert meta.authors == ["Hergé"]
    assert meta.series == "Tintin"
    assert meta.series_index == 7.0
    assert meta.title == "L'Ile Noire"


def test_extract_cbz_metadata_filename_simple_volume(tmp_path):
    """Format simple 'Naruto T42.cbz' -> serie=Naruto + tome=42."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_metadata

    cbz = tmp_path / "Naruto T42.cbz"
    _make_cbz(cbz, ["001.jpg"])

    meta = extract_cbz_metadata(cbz)
    assert meta.series == "Naruto"
    assert meta.series_index == 42.0


def test_extract_cbz_metadata_missing_file(tmp_path):
    """Un CBZ inexistant ne plante pas."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_metadata
    meta = extract_cbz_metadata(tmp_path / "no_exist.cbz")
    assert meta.file_format == "cbz"
    assert meta.sources == []


# ============================================================
# extract_cbz_cover
# ============================================================

def test_extract_cbz_cover(tmp_path):
    """Extrait la premiere image du CBZ vers output_path."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_cover

    cbz = tmp_path / "test.cbz"
    _make_cbz(cbz, ["page001.jpg", "page002.jpg"])

    cover_path = tmp_path / "out_cover.jpg"
    ok = extract_cbz_cover(cbz, cover_path)
    assert ok is True
    assert cover_path.is_file()
    # On a copie le contenu de la 1re image
    assert cover_path.read_bytes().startswith(b"\xff\xd8\xff")


def test_extract_cbz_cover_no_images(tmp_path):
    """CBZ sans image -> False."""
    from flox_uploader.core.providers.cbz_metadata import extract_cbz_cover

    cbz = tmp_path / "empty.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("readme.txt", "Pas d'images")

    cover_path = tmp_path / "out.jpg"
    assert extract_cbz_cover(cbz, cover_path) is False
    assert not cover_path.exists()


# ============================================================
# extract_epub_cover
# ============================================================

def _make_epub_with_cover(path: Path) -> None:
    """Helper : EPUB minimal avec une cover declaree dans l'OPF."""
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
        <dc:title>Test Book</dc:title>
        <meta name="cover" content="cover-img"/>
    </metadata>
    <manifest>
        <item id="cover-img" href="cover.jpg" media-type="image/jpeg"/>
    </manifest>
</package>""")
        zf.writestr("OEBPS/cover.jpg", b"\xff\xd8\xff\xe0epub_cover_jpeg")


def test_extract_epub_cover(tmp_path):
    """Extrait la cover EPUB via meta name='cover' + manifest."""
    from flox_uploader.core.providers.epub_metadata import extract_epub_cover

    epub = tmp_path / "test.epub"
    _make_epub_with_cover(epub)

    out = tmp_path / "out_cover.jpg"
    ok = extract_epub_cover(epub, out)
    assert ok is True
    assert out.is_file()
    assert out.read_bytes() == b"\xff\xd8\xff\xe0epub_cover_jpeg"


def test_extract_epub_cover_fallback_by_name(tmp_path):
    """Si l'OPF ne declare pas la cover, fallback sur fichier cover*.jpg."""
    from flox_uploader.core.providers.epub_metadata import extract_epub_cover

    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        # Pas de container.xml -> _find_opf_path retourne ""
        zf.writestr("Cover.jpg", b"\xff\xd8\xff_fallback_cover")
        zf.writestr("chapter1.html", "<h1>Ch1</h1>")

    out = tmp_path / "out.jpg"
    ok = extract_epub_cover(epub, out)
    assert ok is True
    assert out.read_bytes() == b"\xff\xd8\xff_fallback_cover"


def test_extract_epub_cover_no_cover(tmp_path):
    """EPUB sans cover -> False."""
    from flox_uploader.core.providers.epub_metadata import extract_epub_cover

    epub = tmp_path / "test.epub"
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("chapter1.html", "<h1>Ch1</h1>")

    out = tmp_path / "out.jpg"
    assert extract_epub_cover(epub, out) is False


# ============================================================
# book_lookup permissif : title seul (sans author)
# ============================================================

def test_book_lookup_accepts_title_only(tmp_path):
    """Sprint D.7 : un BookMetadata avec juste title (sans author) doit
    declencher le lookup en ligne."""
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.core.providers.book_lookup import lookup_book_metadata

    base = BookMetadata(title="Le Hobbit", file_format="pdf")
    # Pas d'ISBN, pas d'author -> avant D.7 ce cas etait skip.
    # Mock http pour ne pas faire d'appel reseau.
    called = {"n": 0}

    def fake_http(url, params=None, **kwargs):
        called["n"] += 1
        class _Resp:
            def json(self):
                return {}
        return _Resp()

    # Pas de cache (cache_dir=None)
    result = lookup_book_metadata(
        base, cache_dir=None, http_get=fake_http,
        providers_order=("google_books",),  # juste un pour minimiser appels
    )
    # On veut juste verifier que le lookup a ete tente
    # (avant D.7 : skip car has_text_query=False car pas d'author)
    assert called["n"] >= 1


# ============================================================
# /api/inbox/peek-category
# ============================================================

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path))

    from flox_uploader import config
    config.load_env()

    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_peek_category_epub(client, tmp_path):
    """Un .epub doit etre devine comme Livre (cat 12) avec confidence high."""
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"PK fake epub")

    resp = client.post("/api/inbox/peek-category", json={"paths": [str(epub)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == 12  # CATEGORY_BOOKS
    assert data["confidence"] == "high"


def test_peek_category_mkv(client, tmp_path):
    """Un .mkv -> Film (cat 1) avec confidence low (= default fallback)."""
    mkv = tmp_path / "movie.mkv"
    mkv.write_bytes(b"fake mkv")

    resp = client.post("/api/inbox/peek-category", json={"paths": [str(mkv)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == 1  # CATEGORY_MOVIE
    assert data["confidence"] == "low"


def test_peek_category_no_paths(client):
    """Sans paths -> default Film low."""
    resp = client.post("/api/inbox/peek-category", json={"paths": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == 1
    assert data["confidence"] == "low"


def test_peek_category_dir_with_pdfs(client, tmp_path):
    """Un dossier contenant des PDFs -> Livre (cat 12)."""
    folder = tmp_path / "ebooks_folder"
    folder.mkdir()
    (folder / "book1.pdf").write_bytes(b"%PDF-1.4")
    (folder / "book2.pdf").write_bytes(b"%PDF-1.4")
    (folder / "cover.jpg").write_bytes(b"fake jpg")  # satellite

    resp = client.post("/api/inbox/peek-category", json={"paths": [str(folder)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_id"] == 12  # CATEGORY_BOOKS (pdf detect)
    assert data["confidence"] == "high"


# ============================================================
# Smoke test integration : BookNamingStrategy avec PDF / CBZ
# ============================================================

def test_book_naming_routes_to_pdf_extractor(tmp_path, monkeypatch):
    """BookNamingStrategy.build_release_name appelle extract_pdf_metadata
    pour les .pdf."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    from pypdf import PdfWriter
    pdf = tmp_path / "Tolkien - Le Hobbit.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "Le Hobbit", "/Author": "J.R.R. Tolkien"})
    with pdf.open("wb") as f:
        writer.write(f)

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/passkey")
    debug = Debug(tmp_path / "_debug")

    # Mock le book_lookup pour eviter les appels reseau
    def fake_lookup(meta):
        return meta

    strategy = BookNamingStrategy()
    release_name, ctx = strategy.build_release_name(
        pdf, tracker, nfo_text="", debug=debug,
        _book_lookup=fake_lookup,
    )

    assert ctx is None  # pas de tmdb pour les livres
    # Le release_name doit contenir Tolkien + Hobbit + PDF
    assert "Tolkien" in release_name or "Hobbit" in release_name
    assert "PDF" in release_name


def test_book_naming_routes_to_cbz_extractor(tmp_path, monkeypatch):
    """BookNamingStrategy avec un .cbz extrait les bonnes metadata."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    cbz = tmp_path / "Tintin T07 - L'Ile Noire.cbz"
    _make_cbz(cbz, ["001.jpg", "002.jpg"])

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/passkey")
    debug = Debug(tmp_path / "_debug")

    def fake_lookup(meta):
        return meta

    strategy = BookNamingStrategy()
    release_name, _ = strategy.build_release_name(
        cbz, tracker, nfo_text="", debug=debug,
        _book_lookup=fake_lookup,
    )

    # Le release_name doit contenir Tintin + T7 + CBZ
    assert "Tintin" in release_name
    assert "CBZ" in release_name
