"""Tests Sprint D.1 v0.5.0 : extracteur metadata EPUB local + dataclass BookMetadata.

Cree des fichiers .epub factices a la volee avec differents profils de
metadata Dublin Core et verifie l'extraction. Pas de dependance externe :
on construit le ZIP en memoire (zipfile stdlib).

Cf. PLAN-MULTICAT.md §7.4 + §9 Sprint D.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from flox_uploader.core.providers.book_metadata import BookMetadata
from flox_uploader.core.providers.epub_metadata import extract_epub_metadata


# ============================================================
# Helper : fabricant de .epub factices
# ============================================================

# OPF minimal valide (EPUB 2 namespace). Test placeholder %s pour le bloc
# metadata custom.
_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
%s
    </metadata>
    <manifest>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    </manifest>
    <spine toc="ncx"/>
</package>
"""

_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>
"""


def _make_epub(epub_path: Path, metadata_block: str) -> Path:
    """Cree un .epub minimal valide avec le metadata bloc fourni."""
    opf_content = _OPF_TEMPLATE % metadata_block
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # EPUB requires 'mimetype' as first entry, uncompressed
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf_content)
    return epub_path


# ============================================================
# Cas de base : titre + auteur + ISBN
# ============================================================

def test_extract_basic_metadata(tmp_path):
    """Cas standard : titre + auteur + ISBN + langue + annee."""
    epub = _make_epub(tmp_path / "test.epub", """
        <dc:title>Le Seigneur des Anneaux</dc:title>
        <dc:creator>J.R.R. Tolkien</dc:creator>
        <dc:publisher>Christian Bourgois</dc:publisher>
        <dc:language>fr</dc:language>
        <dc:date>1954-07-29</dc:date>
        <dc:identifier scheme="ISBN">9782267027044</dc:identifier>
        <dc:description>Le grand roman fondateur de la fantasy moderne.</dc:description>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.title == "Le Seigneur des Anneaux"
    assert meta.authors == ["J.R.R. Tolkien"]
    assert meta.publisher == "Christian Bourgois"
    assert meta.language == "fr"
    assert meta.publication_year == 1954
    assert meta.isbn_13 == "9782267027044"
    assert "fondateur" in meta.description
    assert meta.file_format == "epub"
    assert meta.file_path == epub
    assert "local_epub" in meta.sources


def test_extract_multiple_authors(tmp_path):
    """Plusieurs auteurs : liste preservee dans l'ordre EPUB."""
    epub = _make_epub(tmp_path / "duo.epub", """
        <dc:title>Co-authored Book</dc:title>
        <dc:creator>Alice Author</dc:creator>
        <dc:creator>Bob Writer</dc:creator>
        <dc:language>en</dc:language>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.authors == ["Alice Author", "Bob Writer"]
    assert meta.primary_author == "Alice Author"


def test_extract_isbn_10(tmp_path):
    """ISBN-10 detecte correctement."""
    epub = _make_epub(tmp_path / "old.epub", """
        <dc:title>Old Book</dc:title>
        <dc:creator>Author Old</dc:creator>
        <dc:identifier scheme="ISBN">0747532699</dc:identifier>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.isbn_10 == "0747532699"
    assert meta.isbn_13 == ""
    assert meta.isbn == "0747532699"  # property fallback


def test_extract_isbn_with_dashes_and_spaces(tmp_path):
    """ISBN formatte (tirets, espaces, prefixe urn:isbn:) est nettoye."""
    epub = _make_epub(tmp_path / "fmt.epub", """
        <dc:title>Formatted ISBN</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:identifier scheme="ISBN">urn:isbn:978-2-267-02704-4</dc:identifier>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.isbn_13 == "9782267027044"


def test_extract_language_normalization(tmp_path):
    """Codes langue varies normalises en ISO 639-1 court."""
    for raw, expected in [
        ("fr", "fr"),
        ("fr-FR", "fr"),
        ("FR", "fr"),
        ("eng", "en"),
        ("en-US", "en"),
        ("fra", "fr"),
        ("fre", "fr"),
        ("jpn", "ja"),
    ]:
        epub = _make_epub(tmp_path / f"lang_{raw}.epub", f"""
            <dc:title>Lang Test</dc:title>
            <dc:creator>Author</dc:creator>
            <dc:language>{raw}</dc:language>
        """)
        meta = extract_epub_metadata(epub)
        assert meta.language == expected, f"langue '{raw}' devrait normaliser en '{expected}', obtenu '{meta.language}'"


def test_extract_date_with_year_only(tmp_path):
    """Annee extraite depuis une date partielle."""
    epub = _make_epub(tmp_path / "year.epub", """
        <dc:title>Year Test</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:date>2024</dc:date>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.publication_year == 2024


def test_extract_genres_from_subjects(tmp_path):
    """Les dc:subject deviennent des genres."""
    epub = _make_epub(tmp_path / "genres.epub", """
        <dc:title>Multi-Genre</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:subject>Fantasy</dc:subject>
        <dc:subject>Aventure</dc:subject>
        <dc:subject>Jeunesse</dc:subject>
    """)
    meta = extract_epub_metadata(epub)
    assert "Fantasy" in meta.genres
    assert "Aventure" in meta.genres
    assert "Jeunesse" in meta.genres


def test_extract_calibre_series(tmp_path):
    """Serie Calibre detectee via meta name=calibre:series."""
    epub = _make_epub(tmp_path / "series.epub", """
        <dc:title>Tome 3 - La Tour Sombre</dc:title>
        <dc:creator>Stephen King</dc:creator>
        <meta name="calibre:series" content="La Tour Sombre"/>
        <meta name="calibre:series_index" content="3"/>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.series == "La Tour Sombre"
    assert meta.series_index == 3.0


def test_extract_calibre_series_float_index(tmp_path):
    """series_index peut etre un float (tomes hors-serie : 0.5, 2.5...)."""
    epub = _make_epub(tmp_path / "series_hs.epub", """
        <dc:title>HS Tome 0.5</dc:title>
        <dc:creator>Author</dc:creator>
        <meta name="calibre:series" content="My Series"/>
        <meta name="calibre:series_index" content="0.5"/>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.series_index == 0.5


# ============================================================
# Cas degenere : fichier corrompu, absent, partiel
# ============================================================

def test_nonexistent_file_returns_minimal(tmp_path):
    """Fichier qui n'existe pas : pas de plantage, BookMetadata minimal."""
    meta = extract_epub_metadata(tmp_path / "ghost.epub")
    assert meta.file_format == "epub"
    assert meta.title == ""
    assert meta.authors == []
    assert meta.sources == []


def test_not_a_zip_file_returns_minimal(tmp_path):
    """Fichier qui n'est pas un ZIP : pas de plantage."""
    fake = tmp_path / "fake.epub"
    fake.write_text("this is not a zip", encoding="utf-8")
    meta = extract_epub_metadata(fake)
    assert meta.title == ""
    assert meta.sources == []


def test_corrupted_zip_returns_minimal(tmp_path):
    """ZIP corrompu (pas de container.xml ni d'OPF) : minimal."""
    fake = tmp_path / "corrupt.epub"
    with zipfile.ZipFile(fake, "w") as zf:
        zf.writestr("just_some_file.txt", "hello")
    meta = extract_epub_metadata(fake)
    assert meta.title == ""
    assert meta.sources == []


def test_missing_essential_fields_no_source_set(tmp_path):
    """Si title ET authors sont vides : sources reste vide (= extraction "ratee")."""
    epub = _make_epub(tmp_path / "empty.epub", "")  # bloc metadata vide
    meta = extract_epub_metadata(epub)
    assert meta.title == ""
    assert meta.authors == []
    assert "local_epub" not in meta.sources


def test_partial_metadata_title_only(tmp_path):
    """Titre seul sans auteur : sources marquee mais champs partiels."""
    epub = _make_epub(tmp_path / "titleonly.epub", """
        <dc:title>Just A Title</dc:title>
    """)
    meta = extract_epub_metadata(epub)
    assert meta.title == "Just A Title"
    assert meta.authors == []
    assert "local_epub" in meta.sources  # title fait suffit
    assert not meta.has_essential_fields()  # auteur manquant


# ============================================================
# BookMetadata.merge_from()
# ============================================================

def test_merge_completes_empty_fields():
    """merge_from() remplit les champs vides sans ecraser les non-vides."""
    base = BookMetadata(
        title="Title Local",
        authors=["Auteur Local"],
    )
    enrichment = BookMetadata(
        title="Title Distant",  # ne doit PAS ecraser
        authors=["Auteur Distant"],  # ne doit PAS ecraser
        publisher="Editeur Distant",  # COMPLETE
        isbn_13="9781234567890",  # COMPLETE
        description="Resume distant",  # COMPLETE
    )
    base.merge_from(enrichment, source_name="google_books")
    # Champs originaux preserves
    assert base.title == "Title Local"
    assert base.authors == ["Auteur Local"]
    # Champs completes
    assert base.publisher == "Editeur Distant"
    assert base.isbn_13 == "9781234567890"
    assert base.description == "Resume distant"
    # Source trackee
    assert "google_books" in base.sources


def test_merge_preserves_numeric_zero_as_empty():
    """publication_year=0 ou page_count=0 sont consideres comme 'vides'."""
    base = BookMetadata()
    enrichment = BookMetadata(publication_year=2024, page_count=350)
    base.merge_from(enrichment, source_name="bnf")
    assert base.publication_year == 2024
    assert base.page_count == 350


def test_merge_preserves_existing_year():
    """publication_year deja > 0 n'est PAS ecrase."""
    base = BookMetadata(publication_year=1954)
    enrichment = BookMetadata(publication_year=2000)
    base.merge_from(enrichment)
    assert base.publication_year == 1954


def test_merge_appends_unique_sources():
    """Si on merge plusieurs fois, la liste sources accumule sans doublons."""
    base = BookMetadata(sources=["local_epub"])
    base.merge_from(BookMetadata(publisher="x"), source_name="bnf")
    base.merge_from(BookMetadata(description="y"), source_name="google_books")
    base.merge_from(BookMetadata(cover_url="z"), source_name="bnf")  # doublon
    assert base.sources == ["local_epub", "bnf", "google_books"]


def test_merge_from_does_not_mutate_source():
    """merge_from() ne modifie PAS l'objet `other`."""
    base = BookMetadata()
    enrichment = BookMetadata(title="X", authors=["Y"])
    base.merge_from(enrichment, source_name="bnf")
    # enrichment doit etre intact
    assert enrichment.title == "X"
    assert enrichment.authors == ["Y"]
    assert "bnf" not in enrichment.sources


# ============================================================
# Smoke : BookMetadata helpers
# ============================================================

def test_has_essential_fields():
    assert BookMetadata(title="T", authors=["A"]).has_essential_fields()
    assert not BookMetadata(title="T").has_essential_fields()
    assert not BookMetadata(authors=["A"]).has_essential_fields()
    assert not BookMetadata().has_essential_fields()


def test_isbn_property_prefers_13():
    assert BookMetadata(isbn_13="9781234567890", isbn_10="0123456789").isbn == "9781234567890"
    assert BookMetadata(isbn_10="0123456789").isbn == "0123456789"
    assert BookMetadata().isbn == ""


def test_primary_author_empty_when_no_authors():
    assert BookMetadata().primary_author == ""
    assert BookMetadata(authors=["Solo"]).primary_author == "Solo"
    assert BookMetadata(authors=["First", "Second"]).primary_author == "First"
