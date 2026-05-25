"""Tests Sprint D.25 v0.5.0 — Hierarchie dossiers preservee dans BBCode.

Cible note Louis N-R4 : "LARGO_WINCH_INTEGRALE/PDF/+CBZ/ : il faudrait
garder cette hierarchi quand on presente le contenu du torrent dans la
presentation bbcode."

Verifie que _build_tree_lines produit une representation hierarchique
indentee depuis une liste de fichiers, et que le template BBCode l'utilise.
"""
from __future__ import annotations

import pytest


# ============================================================
# _build_tree_lines
# ============================================================

def test_build_tree_lines_flat_files():
    """Fichiers sans sous-dossier : liste plate, pas d'indentation."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [
        {"name": "Tome_01.pdf", "size_pretty": "45 Mo"},
        {"name": "Tome_02.pdf", "size_pretty": "43 Mo"},
    ]
    lines = _build_tree_lines(files)
    assert lines == [
        "Tome_01.pdf (45 Mo)",
        "Tome_02.pdf (43 Mo)",
    ]


def test_build_tree_lines_two_subfolders_largo_winch():
    """Cas reel Louis N-R4 : LARGO_WINCH avec PDF/ + CBZ/ sous-dossiers."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [
        {"name": "PDF/Tome_01.pdf", "size_pretty": "45 Mo"},
        {"name": "PDF/Tome_02.pdf", "size_pretty": "43 Mo"},
        {"name": "CBZ/Tome_01.cbz", "size_pretty": "12 Mo"},
        {"name": "CBZ/Tome_02.cbz", "size_pretty": "11 Mo"},
    ]
    lines = _build_tree_lines(files)
    # On doit voir les sous-dossiers PDF/ et CBZ/ comme entetes indentes
    assert "PDF/" in lines
    assert "CBZ/" in lines
    # Et les fichiers indentes sous leur dossier
    assert "  Tome_01.pdf (45 Mo)" in lines
    assert "  Tome_01.cbz (12 Mo)" in lines


def test_build_tree_lines_nested_deeper():
    """Hierarchie profonde : Foo/Bar/Baz/file.pdf"""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [
        {"name": "Foo/Bar/file.pdf", "size_pretty": "1 Mo"},
    ]
    lines = _build_tree_lines(files)
    # On doit avoir Foo/, Bar/ comme dossiers indentes
    assert "Foo/" in lines
    assert "  Bar/" in lines
    assert "    file.pdf (1 Mo)" in lines


def test_build_tree_lines_no_size():
    """Si pas de size_pretty, pas de suffix '(X Mo)'."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [{"name": "PDF/Tome_01.pdf", "size_pretty": ""}]
    lines = _build_tree_lines(files)
    assert "  Tome_01.pdf" in lines
    assert "(45 Mo)" not in str(lines)


def test_build_tree_lines_empty():
    """Liste vide -> liste vide."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    assert _build_tree_lines([]) == []


def test_build_tree_lines_windows_paths():
    """Path Windows avec backslash -> normalise en /."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [{"name": "PDF\\Tome_01.pdf", "size_pretty": "45 Mo"}]
    lines = _build_tree_lines(files)
    assert "PDF/" in lines


def test_build_tree_lines_preserves_order():
    """L'ordre des fichiers est preserve (pas de tri agressif)."""
    from flox_uploader.core.bbcode_book import _build_tree_lines
    files = [
        {"name": "Z/file.txt", "size_pretty": ""},
        {"name": "A/file.txt", "size_pretty": ""},
    ]
    lines = _build_tree_lines(files)
    # Z/ doit apparaitre avant A/ (ordre d'apparition dans input)
    z_idx = lines.index("Z/")
    a_idx = lines.index("A/")
    assert z_idx < a_idx


# ============================================================
# build_torrent_info inclut tree_lines
# ============================================================

def test_build_torrent_info_includes_tree_lines(tmp_path):
    """Le dict torrent_info contient maintenant 'tree_lines'."""
    from flox_uploader.core.bbcode_book import build_torrent_info
    from flox_uploader.core.torrent import create_torrent
    import zipfile

    # Cree un torrent avec 2 sous-dossiers PDF/ et CBZ/
    src_dir = tmp_path / "LARGO_WINCH"
    src_dir.mkdir()
    pdf_dir = src_dir / "PDF"
    pdf_dir.mkdir()
    (pdf_dir / "Tome_01.pdf").write_bytes(b"X" * 100)
    cbz_dir = src_dir / "CBZ"
    cbz_dir.mkdir()
    (cbz_dir / "Tome_01.cbz").write_bytes(b"X" * 80)

    torrent_path = tmp_path / "test.torrent"
    create_torrent(
        src_dir, torrent_path,
        announce_url="https://test/announce/passkey",
        source="TEST",
        private=True,
    )

    info = build_torrent_info(torrent_path)
    assert "tree_lines" in info
    assert isinstance(info["tree_lines"], list)
    assert len(info["tree_lines"]) > 0
    # Le tree doit montrer les sous-dossiers PDF/ et CBZ/
    tree_str = "\n".join(info["tree_lines"])
    assert "PDF/" in tree_str
    assert "CBZ/" in tree_str


# ============================================================
# Template BBCode utilise tree_lines
# ============================================================

def test_bbcode_template_renders_tree_hierarchy(monkeypatch):
    """Le BBCode rendu utilise tree_lines pour le 'Contenu du torrent'."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test/announce/passkey")
    meta = BookMetadata(
        title="LARGO WINCH", authors=["Van Hamme"], file_format="pdf",
    )
    torrent_info = {
        "size_pretty": "100 Mo",
        "file_count": 4,
        "files": [
            {"name": "PDF/Tome_01.pdf", "size_pretty": "45 Mo"},
            {"name": "CBZ/Tome_01.cbz", "size_pretty": "12 Mo"},
        ],
        "tree_lines": [
            "PDF/",
            "  Tome_01.pdf (45 Mo)",
            "CBZ/",
            "  Tome_01.cbz (12 Mo)",
        ],
        "truncated": False,
    }
    bbcode = render_book_bbcode(
        meta, "Rel", tracker, torrent_info=torrent_info,
    )
    # On doit voir les sous-dossiers indentes
    assert "PDF/" in bbcode
    assert "CBZ/" in bbcode
    assert "Tome_01.pdf (45 Mo)" in bbcode
    assert "Tome_01.cbz (12 Mo)" in bbcode


def test_bbcode_fallback_flat_if_no_tree_lines(monkeypatch):
    """Si tree_lines absent (ancien torrent_info), fallback liste flat."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test/announce/passkey")
    meta = BookMetadata(title="T", authors=["A"], file_format="pdf")
    torrent_info = {
        "size_pretty": "10 Mo",
        "file_count": 2,
        "files": [
            {"name": "a.pdf", "size_pretty": "5 Mo"},
            {"name": "b.pdf", "size_pretty": "5 Mo"},
        ],
        # Pas de tree_lines (ancien run)
        "truncated": False,
    }
    bbcode = render_book_bbcode(
        meta, "Rel", tracker, torrent_info=torrent_info,
    )
    # Fallback : on voit a.pdf et b.pdf
    assert "a.pdf" in bbcode
    assert "b.pdf" in bbcode
