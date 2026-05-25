"""Tests Sprint D.10 v0.5.0 — extraction dossier + INTEGRALE + HTML cleanup.

Verifie :
1. dir_parser.parse_book_dir_name : extrait format [EPUB], serie, tome, range, annee.
2. dir_parser.find_primary_ebook : trouve le fichier ebook principal d'un dossier.
3. dir_parser.merge_book_dir_hints : merge avec warnings si conflit.
4. _html.strip_html : nettoie le HTML des descriptions BnF/Google.
5. BookNamingStrategy : pour un dossier, analyse le fichier ebook interne +
   parse le nom de dossier + merge.
6. Release_name avec range T01-T06.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


# ============================================================
# parse_book_dir_name
# ============================================================

def test_parse_dir_format_bracket():
    """[EPUB] en prefix extrait le format."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("[EPUB].Historica.Cosmos.Tome.13.Legendes.et.contes.de.Bretagne")
    assert r.format_hint == "EPUB"
    assert r.volume == 13
    assert "Historica" in (r.series or r.title)
    assert r.year == 0  # pas d'annee dans ce nom


def test_parse_dir_multi_formats():
    """[EPUB + PDF] extrait les 2 formats."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("[EPUB+PDF].Author.Title.2024")
    assert r.format_hint == "EPUB"
    assert "PDF" in r.multi_formats
    assert r.year == 2024


def test_parse_dir_range_tomes():
    """T01-T06 extrait le range de tomes."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("Star.Wars.Rebellion.T01-T06.FRENCH.EPUB-NoTAG")
    assert r.volume_range == "1-6"
    assert r.format_hint == "EPUB"


def test_parse_dir_range_tomes_with_a():
    """T01 a T06 et 'Tomes 1 a 6' aussi reconnus."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r1 = parse_book_dir_name("Manga.Naruto.Tomes.1.a.10")
    assert r1.volume_range == "1-10"
    r2 = parse_book_dir_name("Series.T1.a.T6.EPUB")
    assert r2.volume_range == "1-6"


def test_parse_dir_volume_unique():
    """T07 extrait le tome unique."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("Tintin.T07.L'Ile.Noire")
    assert r.volume == 7
    assert r.series == "Tintin"
    assert "Ile Noire" in r.title


def test_parse_dir_bracketed_author():
    """[Hergé] Tintin T07 extrait l'auteur."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("[Hergé] Tintin T07 - L'Ile Noire (1958)")
    assert r.author == "Hergé"
    assert r.series == "Tintin"
    assert r.volume == 7
    assert r.year == 1958


def test_parse_dir_year_extracted():
    """L'annee de publication est extraite."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("Le.Hobbit.1937.FRENCH.EPUB")
    assert r.year == 1937
    assert r.format_hint == "EPUB"


def test_parse_dir_empty_input():
    """Nom vide -> resultat vide sans plantage."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("")
    assert not r.has_any_data


def test_parse_dir_no_format_no_volume():
    """Juste un titre -> title rempli, rien d'autre."""
    from flox_uploader.core.providers.dir_parser import parse_book_dir_name
    r = parse_book_dir_name("Le Seigneur des Anneaux")
    assert r.title == "Le Seigneur des Anneaux"
    assert r.volume == 0
    assert r.format_hint == ""


# ============================================================
# find_primary_ebook
# ============================================================

def test_find_primary_ebook_single_file(tmp_path):
    """Dossier avec 1 fichier .epub -> retourne ce fichier."""
    from flox_uploader.core.providers.dir_parser import find_primary_ebook
    folder = tmp_path / "MyBook"
    folder.mkdir()
    epub = folder / "book.epub"
    epub.write_bytes(b"PK fake")
    (folder / "cover.jpg").write_bytes(b"fake jpg")  # satellite

    result = find_primary_ebook(folder)
    assert result == epub


def test_find_primary_ebook_multi_files_picks_first(tmp_path):
    """Dossier avec plusieurs ebooks -> 1er alphabetique."""
    from flox_uploader.core.providers.dir_parser import find_primary_ebook
    folder = tmp_path / "Series"
    folder.mkdir()
    (folder / "T03.epub").write_bytes(b"x")
    (folder / "T01.epub").write_bytes(b"x")
    (folder / "T02.epub").write_bytes(b"x")

    result = find_primary_ebook(folder)
    assert result.name == "T01.epub"


def test_find_primary_ebook_no_ebooks(tmp_path):
    """Dossier sans ebook -> None."""
    from flox_uploader.core.providers.dir_parser import find_primary_ebook
    folder = tmp_path / "Empty"
    folder.mkdir()
    (folder / "readme.txt").write_text("nope")
    (folder / "cover.jpg").write_bytes(b"x")

    assert find_primary_ebook(folder) is None


def test_find_primary_ebook_not_a_dir(tmp_path):
    """Fichier (pas dossier) -> None."""
    from flox_uploader.core.providers.dir_parser import find_primary_ebook
    f = tmp_path / "single.epub"
    f.write_bytes(b"x")
    assert find_primary_ebook(f) is None


# ============================================================
# merge_book_dir_hints
# ============================================================

def test_merge_dir_fills_empty_file_meta():
    """Si le fichier a peu d'info, le dossier complete."""
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.core.providers.dir_parser import (
        merge_book_dir_hints, parse_book_dir_name,
    )

    file_meta = BookMetadata(file_format="epub")
    dir_hints = parse_book_dir_name("[EPUB].Naruto.T15.Aventures")

    merged, warns = merge_book_dir_hints(file_meta, dir_hints)
    assert merged.series == "Naruto"
    assert merged.series_index == 15.0
    assert not warns  # pas de conflit


def test_merge_dir_conflict_dir_priority():
    """Si conflit, dossier prioritaire + warning emis."""
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.core.providers.dir_parser import (
        merge_book_dir_hints, parse_book_dir_name,
    )

    # Fichier extrait dit Tome 1, dossier dit Tome 13 (cas reel : EPUB
    # interne mal etiquete, l'user a organise le dossier correctement)
    file_meta = BookMetadata(title="Old", series="Stories", series_index=1.0)
    dir_hints = parse_book_dir_name("Stories.Tome.13.Nouveau.Titre")

    merged, warns = merge_book_dir_hints(file_meta, dir_hints, dir_priority=True)
    assert merged.series_index == 13.0
    assert any("Conflit tome" in w for w in warns)


def test_merge_dir_range_always_from_dir():
    """Le range tomes vient toujours du dossier (le fichier individuel
    ne peut pas savoir)."""
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.core.providers.dir_parser import (
        merge_book_dir_hints, parse_book_dir_name,
    )

    file_meta = BookMetadata(title="T01", series="Rebellion", series_index=1.0)
    dir_hints = parse_book_dir_name("Star.Wars.Rebellion.T01-T06.EPUB")

    merged, warns = merge_book_dir_hints(file_meta, dir_hints)
    assert merged.series_index_range == "1-6"


# ============================================================
# strip_html
# ============================================================

def test_strip_html_basic():
    """Tags HTML simples retires."""
    from flox_uploader.core.providers._html import strip_html
    out = strip_html("<b>Bold</b> and <i>italic</i>")
    assert out == "Bold and italic"


def test_strip_html_block_tags_newlines():
    """<p>, <div>, <br> produisent des sauts de ligne."""
    from flox_uploader.core.providers._html import strip_html
    out = strip_html("<p>Paragraphe 1</p><p>Paragraphe 2</p>")
    assert "Paragraphe 1" in out
    assert "Paragraphe 2" in out
    assert out.count("\n") >= 1  # au moins un retour ligne


def test_strip_html_entities_decoded():
    """&amp;, &eacute; decodes correctement."""
    from flox_uploader.core.providers._html import strip_html
    out = strip_html("Tom &amp; Jerry &eacute;tait l&agrave;")
    assert out == "Tom & Jerry était là"


def test_strip_html_bnf_real_sample():
    """Cas reel BnF : description avec <div align="justify"><b>..."""
    from flox_uploader.core.providers._html import strip_html
    raw = '<div><div align="justify"><b>Le futur roi Arthur, alors jeune garçon...</b></div></div>'
    out = strip_html(raw)
    assert "<div>" not in out
    assert "<b>" not in out
    assert "Le futur roi Arthur" in out


def test_strip_html_no_html_passthrough():
    """Si pas de HTML, retourne le texte trimme."""
    from flox_uploader.core.providers._html import strip_html
    assert strip_html("  hello world  ") == "hello world"


def test_strip_html_empty():
    """String vide -> string vide."""
    from flox_uploader.core.providers._html import strip_html
    assert strip_html("") == ""
    assert strip_html(None) == ""


# ============================================================
# Integration : BookNamingStrategy avec dossier
# ============================================================

def _make_epub_minimal(path: Path, title: str = "", author: str = "") -> None:
    """Cree un EPUB minimal avec title/author optionnels."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>""")
        meta_lines = []
        if title:
            meta_lines.append(f"<dc:title>{title}</dc:title>")
        if author:
            meta_lines.append(f"<dc:creator>{author}</dc:creator>")
        meta_block = "\n        ".join(meta_lines)
        zf.writestr("OEBPS/content.opf", f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        {meta_block}
    </metadata>
</package>""")


def test_book_strategy_handles_directory_input(tmp_path, monkeypatch):
    """Si video_path est un dossier, on analyse le fichier ebook dedans
    + on parse le nom de dossier."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    # Crée un dossier "[EPUB].Historica.Cosmos.Tome.13.Legendes" avec
    # un .epub minimal dedans (sans metadata).
    folder = tmp_path / "[EPUB].Historica.Cosmos.Tome.13.Legendes.et.contes.de.Bretagne"
    folder.mkdir()
    inner_epub = folder / "book.epub"
    _make_epub_minimal(inner_epub, title="", author="")

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/passkey")
    debug = Debug(tmp_path / "_debug")

    def fake_lookup(meta):
        return meta

    strategy = BookNamingStrategy()
    release_name, _ = strategy.build_release_name(
        folder, tracker, nfo_text="", debug=debug,
        _book_lookup=fake_lookup,
    )

    # Le release_name doit refleter le tome 13 et le format EPUB
    assert "T13" in release_name
    assert "EPUB" in release_name
    # Le debug doit montrer qu'on a analyse le fichier interne
    assert debug.data.get("book_inner_file") == "book.epub"


def test_book_strategy_integrale_range(tmp_path, monkeypatch):
    """Un dossier T01-T06 produit un release_name avec T01-T06."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    folder = tmp_path / "Star.Wars.Rebellion.T01-T06.FRENCH.EPUB-NoTAG"
    folder.mkdir()
    epub = folder / "T01.epub"
    _make_epub_minimal(epub, title="Rebellion", author="Hartley")

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/passkey")
    debug = Debug(tmp_path / "_debug")

    strategy = BookNamingStrategy()
    release_name, _ = strategy.build_release_name(
        folder, tracker, nfo_text="", debug=debug,
        _book_lookup=lambda m: m,
    )

    # Doit contenir le range T01-T06 (format Gemini scene)
    assert "T01-T06" in release_name
    assert "EPUB" in release_name


def test_book_strategy_directory_no_inner_ebook(tmp_path, monkeypatch):
    """Dossier sans ebook interne -> on extrait quand meme depuis le nom."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    folder = tmp_path / "[PDF].Auteur.Titre.2024"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(b"x")  # satellite uniquement

    from flox_uploader.core.naming.book_strategy import BookNamingStrategy
    from flox_uploader.core.debug import Debug
    from flox_uploader.trackers.gemini.tracker import load_gemini_tracker

    tracker = load_gemini_tracker("https://test.tracker/announce/passkey")
    debug = Debug(tmp_path / "_debug")

    strategy = BookNamingStrategy()
    release_name, _ = strategy.build_release_name(
        folder, tracker, nfo_text="", debug=debug,
        _book_lookup=lambda m: m,
    )

    # Doit avoir extrait PDF + 2024 + Titre depuis le nom de dossier
    assert "PDF" in release_name
    assert "2024" in release_name
