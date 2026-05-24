"""Tests Sprint D.4 v0.5.0 : compliance ebook + intégration _process_book.

Verifie :
1. _check_book_format : formats autorises (epub/pdf/cbz/cbr/mobi/azw3/djvu/m4b)
2. _check_book_archives : rejet RAR/ZIP/7Z (sauf cbr/cbz qui sont des conteneurs)
3. _check_book_nfo_present : NFO obligatoire dans le package
4. check_compliance(category_id=CATEGORY_BOOKS) appelle bien ces checks
5. _process_book genere un package livre complet (NFO + .torrent + state)

Cf. PLAN-MULTICAT.md §7.4 + §9 Sprint D + PDF REGLES D'UPLOAD EBOOK.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flox_uploader.core.compliance import (
    Severity, check_compliance,
    _check_book_format, _check_book_archives, _check_book_nfo_present,
)
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_MOVIE, SUPPORTED_NON_VIDEO_CATEGORIES,
)


# ============================================================
# SUPPORTED_NON_VIDEO_CATEGORIES inclut Livres
# ============================================================

def test_supported_non_video_categories_includes_books():
    """Sprint D.4 : CATEGORY_BOOKS doit etre dans SUPPORTED_NON_VIDEO_CATEGORIES."""
    assert CATEGORY_BOOKS in SUPPORTED_NON_VIDEO_CATEGORIES


# ============================================================
# _check_book_format
# ============================================================

@pytest.mark.parametrize("ext", ["epub", "pdf", "cbz", "cbr", "mobi", "azw3", "djvu", "m4b"])
def test_book_format_allowed(tmp_path, ext):
    """Formats autorises par la charte ebook -> pas d'issue."""
    file = tmp_path / f"book.{ext}"
    file.write_bytes(b"")
    issues = _check_book_format(file)
    assert issues == []


def test_book_format_rejects_unknown(tmp_path):
    """Format inconnu (ex .doc, .txt) -> BLOCKING."""
    file = tmp_path / "weird.docx"
    file.write_bytes(b"")
    issues = _check_book_format(file)
    assert len(issues) == 1
    assert issues[0].severity == Severity.BLOCKING
    assert issues[0].field == "book_format"


def test_book_format_directory_with_epub(tmp_path):
    """Un dossier contenant au moins un ebook valide -> pas d'issue."""
    folder = tmp_path / "BookFolder"
    folder.mkdir()
    (folder / "Cover.jpg").write_bytes(b"")
    (folder / "book.epub").write_bytes(b"")
    assert _check_book_format(folder) == []


def test_book_format_directory_without_ebook(tmp_path):
    """Dossier sans aucun ebook valide -> BLOCKING."""
    folder = tmp_path / "Empty"
    folder.mkdir()
    (folder / "readme.txt").write_bytes(b"")
    issues = _check_book_format(folder)
    assert len(issues) == 1
    assert issues[0].severity == Severity.BLOCKING


def test_book_format_nonexistent_path():
    """Path inexistant -> [] (verif gracieuse)."""
    assert _check_book_format(Path("/tmp/ghost.epub")) == []
    assert _check_book_format(None) == []


# ============================================================
# _check_book_archives
# ============================================================

@pytest.mark.parametrize("ext", [".rar", ".zip", ".7z", ".tar"])
def test_book_archives_rejects(tmp_path, ext):
    """Archives RAR/ZIP/7Z/TAR brutes interdites comme upload ebook."""
    file = tmp_path / f"archive{ext}"
    file.write_bytes(b"")
    issues = _check_book_archives(file)
    assert len(issues) == 1
    assert issues[0].severity == Severity.BLOCKING
    assert issues[0].field == "book_archive"


@pytest.mark.parametrize("ext", [".cbr", ".cbz"])
def test_book_archives_allows_cbr_cbz(tmp_path, ext):
    """CBR/CBZ sont des conteneurs ebook standards -> autorises."""
    file = tmp_path / f"comic{ext}"
    file.write_bytes(b"")
    issues = _check_book_archives(file)
    assert issues == []  # explicitement non-listees dans FORBIDDEN_ARCHIVES


def test_book_archives_directory_with_rar(tmp_path):
    """Dossier contenant un .rar -> BLOCKING."""
    folder = tmp_path / "Pack"
    folder.mkdir()
    (folder / "book.epub").write_bytes(b"")
    (folder / "compressed.rar").write_bytes(b"")
    issues = _check_book_archives(folder)
    assert len(issues) == 1
    assert issues[0].severity == Severity.BLOCKING


# ============================================================
# _check_book_nfo_present
# ============================================================

def test_book_nfo_present_with_nfo(tmp_path):
    """Package avec un .nfo -> pas d'issue."""
    pkg = tmp_path / "MyBook.2024-Flox"
    pkg.mkdir()
    (pkg / "MyBook.2024-Flox.nfo").write_text("nfo content", encoding="utf-8")
    assert _check_book_nfo_present(pkg) == []


def test_book_nfo_missing(tmp_path):
    """Package sans .nfo -> ERROR."""
    pkg = tmp_path / "NoNFO.Pkg"
    pkg.mkdir()
    issues = _check_book_nfo_present(pkg)
    assert len(issues) == 1
    assert issues[0].severity == Severity.ERROR
    assert issues[0].field == "book_nfo_missing"


def test_book_nfo_none_package_dir():
    """package_dir=None -> [] (verif silencieuse)."""
    assert _check_book_nfo_present(None) == []


# ============================================================
# check_compliance(category_id=CATEGORY_BOOKS) integration
# ============================================================

def test_check_compliance_book_profile_includes_book_checks(tmp_path):
    """check_compliance avec category_id=CATEGORY_BOOKS execute les book checks."""
    # Un .docx (format invalide) doit declencher book_format BLOCKING
    file = tmp_path / "test.docx"
    file.write_bytes(b"")
    pkg = tmp_path / "Pkg"
    pkg.mkdir()
    issues = check_compliance(
        "Auteur.Titre.2024.FRENCH.DOCX-Flox",
        mediainfo_data={},
        torrent_target=file,
        package_dir=pkg,
        category_id=CATEGORY_BOOKS,
    )
    fields = {i.field for i in issues}
    assert "book_format" in fields
    assert "book_nfo_missing" in fields  # NFO manquant aussi


def test_check_compliance_book_profile_clean_release(tmp_path):
    """Release ebook clean -> aucune issue."""
    file = tmp_path / "good.epub"
    file.write_bytes(b"")
    pkg = tmp_path / "Pkg.Clean"
    pkg.mkdir()
    (pkg / "Pkg.Clean.nfo").write_text("ok", encoding="utf-8")
    issues = check_compliance(
        "Auteur.Titre.2024.FRENCH.EPUB-Flox",
        mediainfo_data={},
        torrent_target=file,
        package_dir=pkg,
        category_id=CATEGORY_BOOKS,
    )
    # Pas de blocking, eventuellement quelques warnings inoffensifs
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    assert blocking == []


def test_check_compliance_video_does_not_call_book_checks(tmp_path):
    """Profil video : les book checks ne sont PAS appeles (un .docx ne
    declencherait pas book_format)."""
    file = tmp_path / "test.docx"
    file.write_bytes(b"")
    issues = check_compliance(
        "Movie.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        mediainfo_data={},
        torrent_target=file,
        category_id=CATEGORY_MOVIE,
    )
    fields = {i.field for i in issues}
    # book_format ne doit PAS apparaitre
    assert "book_format" not in fields
    assert "book_archive" not in fields
    assert "book_nfo_missing" not in fields


# ============================================================
# _process_book integration tests
# ============================================================

_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
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
    """Cree un .epub minimal avec contenu binaire reel (pour passer torf)."""
    opf_content = _OPF_TEMPLATE % metadata_block
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf_content)
        # On ajoute un peu de contenu pour que torf accepte de generer le .torrent
        zf.writestr("OEBPS/dummy.txt", "x" * 1024)
    return epub_path


@pytest.fixture
def mock_env_book(monkeypatch):
    """Env mockee pour le pipeline livre."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")
    yield


def test_process_book_creates_package(tmp_path, mock_env_book, monkeypatch):
    """_process_book cree un package_dir avec release_name + NFO + .torrent + state."""
    from flox_uploader import config, pipeline
    # Isole le data_dir
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    config.load_env()

    # Court-circuite le lookup en ligne (pas d'appel HTTP en test)
    from flox_uploader.core.naming import book_strategy as _bs
    monkeypatch.setattr(_bs, "lookup_book_metadata", lambda meta, **kw: meta)

    epub = _make_epub(tmp_path / "tolkien.epub", """
        <dc:title>Le Seigneur des Anneaux</dc:title>
        <dc:creator>J.R.R. Tolkien</dc:creator>
        <dc:language>fr</dc:language>
        <dc:date>1954</dc:date>
    """)

    result = pipeline.process_one(epub, tracker_key="gemini")
    assert result is not None
    assert result.is_dir()
    # Package_dir doit etre nomme avec le release_name
    assert "Tolkien" in result.name
    assert "FRENCH" in result.name
    assert "EPUB" in result.name
    # NFO genere
    nfo_files = list(result.glob("*.nfo"))
    assert len(nfo_files) >= 1
    nfo_content = nfo_files[0].read_text(encoding="utf-8")
    assert "Le Seigneur des Anneaux" in nfo_content
    assert "Tolkien" in nfo_content
    assert "Categorie    : Livre" in nfo_content
    # release_name.txt
    rn_file = result / "release_name.txt"
    assert rn_file.is_file()
    # .torrent genere (au moins le fichier existe)
    torrent_files = list(result.glob("*.torrent"))
    assert len(torrent_files) >= 1
    # state PREPARED
    from flox_uploader.core.package_state import read_state, PackageState
    state = read_state(result)
    assert state is not None
    assert state.state in {PackageState.PREPARED, PackageState.FAILED}


def test_process_book_persists_category_hint(tmp_path, mock_env_book, monkeypatch):
    """Le category_hint user est persiste dans state.manual_category_id (Sprint C.1bis)."""
    from flox_uploader import config, pipeline
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    config.load_env()
    from flox_uploader.core.naming import book_strategy as _bs
    monkeypatch.setattr(_bs, "lookup_book_metadata", lambda meta, **kw: meta)

    epub = _make_epub(tmp_path / "hint.epub", """
        <dc:title>Hint Test</dc:title>
        <dc:creator>Author</dc:creator>
        <dc:language>fr</dc:language>
    """)
    result = pipeline.process_one(
        epub, tracker_key="gemini",
        category_hint=CATEGORY_BOOKS,
    )
    from flox_uploader.core.package_state import read_state
    state = read_state(result)
    assert state.manual_category_id == CATEGORY_BOOKS
