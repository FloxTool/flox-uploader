"""Tests Sprint D.3 v0.5.0 : BookNamingStrategy + dispatcher get_strategy.

Verifie que le naming livre genere le format Gemini officiel :
    Auteur.Titre.Date.Langue.Format-TEAM

Tests autonomes : on injecte un orchestrateur de lookup fake via _book_lookup
pour eviter tout appel HTTP. La strategy est testable sans dependance externe.

Cf. PLAN-MULTICAT.md §5.5 + §7.4 + §9 Sprint D.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flox_uploader.core.debug import Debug
from flox_uploader.core.naming.book_strategy import BookNamingStrategy
from flox_uploader.core.naming.strategy import (
    NamingStrategy, get_strategy,
)
from flox_uploader.core.providers.book_metadata import BookMetadata
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_MOVIE,
)


# ============================================================
# Helper : fabricant de .epub factices (reutilise de test_epub_metadata)
# ============================================================

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
    """Cree un .epub minimal valide."""
    opf_content = _OPF_TEMPLATE % metadata_block
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf_content)
    return epub_path


def _make_tracker(default_team: str = "Flox"):
    """Fabrique un Tracker stub minimal (just default_team)."""
    tracker = MagicMock()
    tracker.default_team = default_team
    tracker.rules = {}
    return tracker


def _no_lookup(meta: BookMetadata) -> BookMetadata:
    """Lookup orchestrateur factice : retourne le meta tel quel (pas d'enrichissement).

    Permet de tester la generation du release_name avec seulement les
    metadonnees locales.
    """
    return meta


# ============================================================
# Smoke : la strategy satisfait le Protocol
# ============================================================

def test_strategy_satisfies_protocol():
    strategy = BookNamingStrategy()
    assert isinstance(strategy, NamingStrategy)
    assert strategy.name == "book"
    assert callable(strategy.build_release_name)
    assert callable(strategy.compliance_profile)
    assert callable(strategy.build_extra_payload)


def test_compliance_profile_returns_book():
    assert BookNamingStrategy().compliance_profile() == "book"


def test_build_extra_payload_returns_empty_dict():
    """Sprint D.3 : pas encore de champs ebook dans le payload."""
    assert BookNamingStrategy().build_extra_payload(None) == {}


# ============================================================
# Dispatcher get_strategy() route correctement
# ============================================================

def test_get_strategy_books_returns_book_strategy():
    strategy = get_strategy(CATEGORY_BOOKS)
    assert isinstance(strategy, BookNamingStrategy)
    assert strategy.name == "book"


def test_get_strategy_movie_still_returns_video():
    """Sprint B.4 : cats video continuent de retourner VideoNamingStrategy."""
    from flox_uploader.core.naming.video_strategy import VideoNamingStrategy
    strategy = get_strategy(CATEGORY_MOVIE)
    assert isinstance(strategy, VideoNamingStrategy)


# ============================================================
# Cas standard : .epub avec metadata locale complete
# ============================================================

def test_release_name_basic_book(tmp_path):
    """EPUB avec titre + auteur + annee + langue + format -> nom Gemini standard."""
    epub = _make_epub(tmp_path / "tolkien.epub", """
        <dc:title>Le Seigneur des Anneaux</dc:title>
        <dc:creator>J.R.R. Tolkien</dc:creator>
        <dc:language>fr</dc:language>
        <dc:date>1954</dc:date>
    """)
    debug = Debug(tmp_path / "debug")
    strategy = BookNamingStrategy()
    release_name, ctx = strategy.build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # Format : Auteur.Titre.Annee.Langue.Format-TEAM
    assert release_name == "J.R.R.Tolkien.Le.Seigneur.Des.Anneaux.1954.FRENCH.EPUB-Flox"
    assert ctx is None  # TMDB pas applicable aux livres


def test_release_name_with_accents(tmp_path):
    """Les accents sont folded en ASCII (Hergé -> Herge, Élise -> Elise)."""
    epub = _make_epub(tmp_path / "herge.epub", """
        <dc:title>Tintin au pays des Soviets</dc:title>
        <dc:creator>Hergé</dc:creator>
        <dc:language>fr</dc:language>
        <dc:date>1930</dc:date>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert "Herge" in release_name
    assert "é" not in release_name
    assert release_name == "Herge.Tintin.Au.Pays.Des.Soviets.1930.FRENCH.EPUB-Flox"


def test_release_name_english_book(tmp_path):
    """Langue en -> token ENGLISH."""
    epub = _make_epub(tmp_path / "potter.epub", """
        <dc:title>Harry Potter and the Philosopher's Stone</dc:title>
        <dc:creator>J.K. Rowling</dc:creator>
        <dc:language>en</dc:language>
        <dc:date>1997</dc:date>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert "J.K.Rowling" in release_name
    assert "ENGLISH" in release_name
    assert "1997" in release_name
    assert "EPUB" in release_name
    # apostrophe collee : "Philosopher's" -> "Philosophers"
    assert "Philosophers" in release_name


def test_release_name_japanese_manga(tmp_path):
    """Manga JP : ja -> JAPANESE token."""
    epub = _make_epub(tmp_path / "manga.epub", """
        <dc:title>One Piece Vol 1</dc:title>
        <dc:creator>Eiichiro Oda</dc:creator>
        <dc:language>ja</dc:language>
        <dc:date>1997</dc:date>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert "JAPANESE" in release_name
    assert "Eiichiro.Oda" in release_name


# ============================================================
# Series / BD / Manga avec tome
# ============================================================

def test_release_name_with_series_and_tome(tmp_path):
    """Serie Calibre + series_index -> format Serie.T<num>.Sous-titre."""
    epub = _make_epub(tmp_path / "tour_sombre.epub", """
        <dc:title>Terres Perdues</dc:title>
        <dc:creator>Stephen King</dc:creator>
        <dc:language>fr</dc:language>
        <dc:date>1991</dc:date>
        <meta name="calibre:series" content="La Tour Sombre"/>
        <meta name="calibre:series_index" content="3"/>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # Format attendu : Stephen.King.La.Tour.Sombre.T3.Terres.Perdues.1991.FRENCH.EPUB-Flox
    assert "Stephen.King" in release_name
    assert "La.Tour.Sombre" in release_name
    assert "T3" in release_name
    assert "Terres.Perdues" in release_name
    assert "FRENCH" in release_name


def test_release_name_series_index_float(tmp_path):
    """series_index=0.5 (tome HS) -> T0.5."""
    epub = _make_epub(tmp_path / "hs.epub", """
        <dc:title>Tome Hors-Serie</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:language>fr</dc:language>
        <meta name="calibre:series" content="My Series"/>
        <meta name="calibre:series_index" content="0.5"/>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert "T0.5" in release_name


def test_release_name_series_title_same_as_serie(tmp_path):
    """Si meta.title == meta.series, on ne duplique pas."""
    epub = _make_epub(tmp_path / "same.epub", """
        <dc:title>One Piece</dc:title>
        <dc:creator>Eiichiro Oda</dc:creator>
        <dc:language>ja</dc:language>
        <meta name="calibre:series" content="One Piece"/>
        <meta name="calibre:series_index" content="1"/>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # "One Piece" ne doit apparaitre qu'une fois
    assert release_name.count("One.Piece") == 1
    assert "T1" in release_name


# ============================================================
# Formats non-EPUB (CBZ, PDF, MOBI...)
# ============================================================

def test_release_name_cbz_no_local_extractor(tmp_path):
    """Un .cbz n'a pas d'extracteur local, on a juste le file_format.
    L'enrichissement (via _book_lookup mock) fournit titre+auteur."""
    cbz = tmp_path / "tintin.cbz"
    cbz.write_bytes(b"")  # ZIP vide, l'extracteur n'est meme pas appele

    def fake_lookup(meta: BookMetadata) -> BookMetadata:
        # Simule un enrichissement BnF/Google reussi
        meta.title = "Tintin Reporter"
        meta.authors = ["Hergé"]
        meta.publication_year = 1929
        meta.language = "fr"
        meta.sources.append("bnf")
        return meta

    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        cbz, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=fake_lookup,
    )
    assert release_name == "Herge.Tintin.Reporter.1929.FRENCH.CBZ-Flox"


def test_release_name_pdf_format(tmp_path):
    """Un .pdf devient le token PDF dans le release_name."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"")

    def fake_lookup(meta: BookMetadata) -> BookMetadata:
        meta.title = "Document Important"
        meta.authors = ["Anonymous"]
        meta.language = "fr"
        meta.publication_year = 2024
        return meta

    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        pdf, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=fake_lookup,
    )
    assert ".PDF" in release_name


@pytest.mark.parametrize("ext,expected_token", [
    (".epub", "EPUB"),
    (".pdf", "PDF"),
    (".cbz", "CBZ"),
    (".cbr", "CBR"),
    (".mobi", "MOBI"),
    (".azw3", "AZW3"),
    (".djvu", "DJVU"),
])
def test_release_name_format_token_uppercase(tmp_path, ext, expected_token):
    """Le format est toujours en majuscule dans le release_name."""
    fake = tmp_path / f"book{ext}"
    fake.write_bytes(b"")

    def lookup(meta: BookMetadata) -> BookMetadata:
        meta.title = "Test"
        meta.authors = ["Author"]
        meta.language = "fr"
        return meta

    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        fake, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=lookup,
    )
    assert f".{expected_token}-" in release_name


# ============================================================
# Cas degeneres
# ============================================================

def test_release_name_no_metadata_at_all(tmp_path):
    """Aucune meta (extracteur retourne minimal, lookup ne trouve rien) ->
    fallback sur le stem du fichier."""
    epub = _make_epub(tmp_path / "Mystery_Book.epub", "")  # metadata vide
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # Au minimum on a le format + team
    assert ".EPUB-Flox" in release_name
    # Le stem du fichier est utilise comme fallback titre
    assert "Mystery" in release_name


def test_release_name_no_year_omits_year(tmp_path):
    """Si pas d'annee, le token est juste omis."""
    epub = _make_epub(tmp_path / "noyear.epub", """
        <dc:title>Sans Annee</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:language>fr</dc:language>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert release_name == "Author.Sans.Annee.FRENCH.EPUB-Flox"
    # Pas de "1990" ou autre annee fantome
    import re
    assert not re.search(r"\.\d{4}\.", release_name)


def test_release_name_no_language_omits_language(tmp_path):
    """Si pas de langue, le token est juste omis (pas de FRENCH par defaut)."""
    epub = _make_epub(tmp_path / "nolang.epub", """
        <dc:title>Sans Langue</dc:title>
        <dc:creator>Author</dc:creator>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # Pas de FRENCH / ENGLISH / etc.
    for lang in ("FRENCH", "ENGLISH", "JAPANESE"):
        assert lang not in release_name


def test_release_name_default_team_fallback(tmp_path):
    """Si tracker.default_team vide, fallback NoTAG."""
    epub = _make_epub(tmp_path / "noteam.epub", """
        <dc:title>Solo</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:language>fr</dc:language>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker(""), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    assert release_name.endswith("-NoTAG")


def test_release_name_team_with_dash_cleaned(tmp_path):
    """default_team contenant '-' est nettoye (sinon split scene casse)."""
    epub = _make_epub(tmp_path / "dashteam.epub", """
        <dc:title>Dash Team</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:language>fr</dc:language>
    """)
    debug = Debug(tmp_path / "debug")
    release_name, _ = BookNamingStrategy().build_release_name(
        epub, _make_tracker("My-Team"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    # "My-Team" -> "MyTeam"
    assert release_name.endswith("-MyTeam")


# ============================================================
# Debug : les metadonnees sont stockees dans debug["book_metadata"]
# ============================================================

def test_debug_stores_book_metadata(tmp_path):
    """La strategy persiste les metadonnees dans debug['book_metadata']."""
    epub = _make_epub(tmp_path / "store.epub", """
        <dc:title>Store Test</dc:title>
        <dc:creator>Author Store</dc:creator>
        <dc:language>fr</dc:language>
        <dc:date>2024</dc:date>
    """)
    debug = Debug(tmp_path / "debug")
    BookNamingStrategy().build_release_name(
        epub, _make_tracker("Flox"), nfo_text="", debug=debug,
        _book_lookup=_no_lookup,
    )
    stored = debug.data.get("book_metadata")
    assert stored is not None
    assert stored["title"] == "Store Test"
    assert stored["authors"] == ["Author Store"]
    assert stored["publication_year"] == 2024
