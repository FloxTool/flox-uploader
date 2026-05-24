"""Tests Sprint D.5 v0.5.0 : BookConfidenceStrategy + template BBCode livre + page detail.

Cf. PLAN-MULTICAT.md §7.4 + §9 Sprint D.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flox_uploader.core.bbcode_book import render_book_bbcode
from flox_uploader.core.confidence_strategies.book import BookConfidenceStrategy
from flox_uploader.core.providers.book_metadata import BookMetadata
from flox_uploader.trackers import get_tracker


# ============================================================
# Helpers
# ============================================================

_OPF_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
%s
    </metadata>
    <manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>
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
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _OPF_TEMPLATE % metadata_block)
        zf.writestr("OEBPS/dummy.txt", "x" * 1024)
    return epub_path


def _make_book_package(tmp_path: Path, book_meta_dict: dict, state_value: str = "prepared") -> Path:
    """Cree un package livre minimal sur disque pour tester BookConfidenceStrategy."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = tmp_path / "Test.Book.Pkg"
    pkg.mkdir()
    state_enum = PackageState(state_value)
    state = PackageStateData(
        state=state_enum,
        release_name="Test.Book.Pkg",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
    )
    write_state(pkg, state)
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        json.dumps({"book_metadata": book_meta_dict}),
        encoding="utf-8",
    )
    return pkg


# ============================================================
# BookConfidenceStrategy : penalites
# ============================================================

def test_book_score_perfect_metadata(tmp_path):
    """Metadata complete -> score 100 / parfait."""
    pkg = _make_book_package(tmp_path, {
        "title": "Le Hobbit",
        "authors": ["J.R.R. Tolkien"],
        "isbn_13": "9782266154116",
        "description": "Bilbo Sacquet part a l'aventure.",
        "cover_url": "https://example.com/cover.jpg",
        "sources": ["local_epub", "bnf", "google_books"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 100
    assert score.bucket == "parfait"
    assert score.penalties == []


def test_book_score_no_author(tmp_path):
    """Auteur absent -> -20."""
    pkg = _make_book_package(tmp_path, {
        "title": "Solo",
        "authors": [],
        "isbn_13": "9782266154116",
        "description": "Resume",
        "cover_url": "x",
        "sources": ["local_epub", "bnf"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 80  # 100 - 20
    assert "Auteur manquant" in score.reasons


def test_book_score_no_isbn(tmp_path):
    """ISBN absent -> -15."""
    pkg = _make_book_package(tmp_path, {
        "title": "Sans ISBN",
        "authors": ["Author"],
        "isbn_13": "",
        "isbn_10": "",
        "description": "Resume",
        "cover_url": "x",
        "sources": ["local_epub", "bnf"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 85  # 100 - 15
    assert "ISBN manquant" in score.reasons


def test_book_score_no_description(tmp_path):
    """Description vide -> -5."""
    pkg = _make_book_package(tmp_path, {
        "title": "Sans Resume",
        "authors": ["Author"],
        "isbn_13": "9782266154116",
        "description": "",
        "cover_url": "x",
        "sources": ["local_epub", "bnf"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 95
    assert "Resume vide" in score.reasons


def test_book_score_no_cover(tmp_path):
    """Pas de couverture -> -3."""
    pkg = _make_book_package(tmp_path, {
        "title": "Sans Cover",
        "authors": ["Author"],
        "isbn_13": "9782266154116",
        "description": "Resume",
        "cover_url": "",
        "sources": ["local_epub", "bnf"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 97
    assert "Couverture absente" in score.reasons


def test_book_score_no_online_providers(tmp_path):
    """Que extraction locale -> -3 (no online lookup)."""
    pkg = _make_book_package(tmp_path, {
        "title": "Local Only",
        "authors": ["Author"],
        "isbn_13": "9782266154116",
        "description": "Resume",
        "cover_url": "x",
        "sources": ["local_epub"],
    })
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 97
    assert "Pas de lookup en ligne" in score.reasons[0] or any(
        "lookup" in r for r in score.reasons
    )


def test_book_score_cumulative_penalties(tmp_path):
    """Plusieurs penalties s'ajoutent."""
    pkg = _make_book_package(tmp_path, {
        "title": "Mauvaise Fiche",
        "authors": [],            # -20
        "isbn_13": "",            # -15
        "isbn_10": "",
        "description": "",        # -5
        "cover_url": "",          # -3
        "sources": ["local_epub"],  # -3 (no online lookup)
    })
    score = BookConfidenceStrategy().compute(pkg)
    # 100 - 20 - 15 - 5 - 3 - 3 = 54
    assert score.score == 54
    assert score.bucket == "blocked"  # < 60


def test_book_score_failed_state_blocked(tmp_path):
    """State FAILED -> score 0, bucket blocked."""
    pkg = _make_book_package(tmp_path, {
        "title": "Failed Book", "authors": ["X"], "isbn_13": "9782266154116",
        "description": "ok", "cover_url": "x", "sources": ["local_epub", "bnf"],
    }, state_value="failed")
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 0
    assert score.bucket == "blocked"


def test_book_score_no_state_returns_blocked(tmp_path):
    """Pas de state -> blocked."""
    pkg = tmp_path / "no_state"
    pkg.mkdir()
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 0
    assert score.bucket == "blocked"


def test_book_score_compliance_blocking_penalty(tmp_path):
    """compliance_issues avec [BLOCKED] -> -25."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = tmp_path / "Blocked.Pkg"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Blocked.Pkg",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
    ))
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(json.dumps({
        "book_metadata": {
            "title": "T", "authors": ["A"], "isbn_13": "9782266154116",
            "description": "ok", "cover_url": "x",
            "sources": ["local_epub", "bnf"],
        },
        "compliance_issues": ["[BLOCKED] book_format: Format invalide"],
    }), encoding="utf-8")
    score = BookConfidenceStrategy().compute(pkg)
    assert score.score == 75
    assert any("bloquante" in r.lower() or "blocked" in r.lower() for r in score.reasons)


# ============================================================
# template_book.bbcode rendering
# ============================================================

def test_bbcode_book_renders_full(monkeypatch):
    """Render BBCode complet avec tous les champs."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Le Hobbit",
        subtitle="ou la, et retour",
        authors=["J.R.R. Tolkien"],
        publisher="Pocket Jeunesse",
        publication_year=2004,
        language="fr",
        page_count=384,
        isbn_13="9782266154116",
        description="Bilbo Sacquet part a l'aventure...",
        cover_url="https://example.com/hobbit.jpg",
        file_format="epub",
        genres=["Fantasy", "Aventure"],
        sources=["local_epub", "bnf", "google_books"],
    )
    bbcode = render_book_bbcode(meta, "J.R.R.Tolkien.Le.Hobbit.2004.FRENCH.EPUB-Flox", tracker)
    # Verifications essentielles : titre, auteur, ISBN, langue libellee
    assert "Le Hobbit" in bbcode
    assert "J.R.R. Tolkien" in bbcode
    assert "9782266154116" in bbcode
    assert "Français" in bbcode  # mapping lang
    assert "EPUB" in bbcode
    assert "Pocket Jeunesse" in bbcode
    # Sprint D.8 v0.5.0 : la cover est rendue via [img=300]...[/img]
    # (harmonisation avec template_movie.bbcode qui utilise aussi [img=N]).
    assert "https://example.com/hobbit.jpg" in bbcode
    assert "[img=300]" in bbcode or "[img]" in bbcode
    assert "Bilbo Sacquet" in bbcode
    assert "Fantasy" in bbcode
    # BBCode tags presents (alignes avec template film)
    assert "[center]" in bbcode
    # Sprint D.8 : nouveaux marqueurs harmonises avec template_movie
    assert "Informations sur le livre" in bbcode
    assert "Informations sur la release" in bbcode
    assert "Résumé" in bbcode


def test_bbcode_book_handles_missing_cover(monkeypatch):
    """Pas de cover_url -> pas de [img=300] pour la couverture (mais le
    template peut contenir des [img=500]...imgur.com pour les separateurs)."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Sans Cover", authors=["Author"], language="fr", file_format="pdf",
    )
    bbcode = render_book_bbcode(meta, "Author.Sans.Cover.FRENCH.PDF-Flox", tracker)
    # Sprint D.8 : sans cover_url, pas de [img=300] (taille reservee a la cover)
    # mais les separateurs visuels [img=500]...imgur restent presents.
    assert "[img=300]" not in bbcode
    assert "Sans Cover" in bbcode


def test_bbcode_book_series_with_tome(monkeypatch):
    """Serie + tome affichee."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Terres Perdues",
        authors=["Stephen King"],
        series="La Tour Sombre",
        series_index=3.0,
        language="fr",
        file_format="epub",
    )
    bbcode = render_book_bbcode(meta, "test", tracker)
    assert "La Tour Sombre" in bbcode
    assert "tome 3" in bbcode


def test_bbcode_book_handles_no_description(monkeypatch):
    """Pas de description -> pas de section Resume."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="Sans Resume", authors=["Author"], language="fr", file_format="epub",
    )
    bbcode = render_book_bbcode(meta, "test", tracker)
    assert "[quote]" not in bbcode


# ============================================================
# Page detail livre : book_metadata expose + rendu HTML
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


def test_page_detail_book_renders_metadata(client, tmp_path):
    """La page detail d'un livre affiche les metadonnees enrichies."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Tolkien.Hobbit.2004-Flox"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Tolkien.Hobbit.2004-Flox",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,  # Force Livre
    ))
    (pkg / "release_name.txt").write_text("Tolkien.Hobbit.2004-Flox\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": {
            "title": "Le Hobbit",
            "authors": ["J.R.R. Tolkien"],
            "publisher": "Pocket Jeunesse",
            "publication_year": 2004,
            "language": "fr",
            "page_count": 384,
            "isbn_13": "9782266154116",
            "description": "Bilbo part a l'aventure.",
            "cover_url": "https://example.com/hobbit.jpg",
            "file_format": "epub",
            "genres": ["Fantasy"],
            "sources": ["local_epub", "bnf", "google_books"],
        },
    }), encoding="utf-8")

    resp = client.get("/packages/Tolkien.Hobbit.2004-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Marqueurs de la section Livre (Sprint D.6 : titre = "Livre" ; remplace
    # la grille Media+Technique pour les packages de profil book).
    assert "Livre" in html
    assert "Fichier" in html
    assert "Le Hobbit" in html
    assert "J.R.R. Tolkien" in html
    assert "Pocket Jeunesse" in html
    assert "9782266154116" in html
    assert "Français" in html  # mapping langue
    assert "384" in html  # page_count
    # Sources providers (badges)
    assert "bnf" in html
    assert "google_books" in html
    # Couverture image
    assert "https://example.com/hobbit.jpg" in html
    # Sprint D.6 : la carte Fichier (droite) doit afficher le chemin du
    # package (preserve depuis l'ancienne carte Technique).
    assert "Package" in html  # label de la ligne path
    # Sprint D.6 : la carte Media+Technique video ne doit PAS etre rendue
    # (replaced par _detail_book.html).
    assert ">Média<" not in html
    assert ">Technique<" not in html


def test_page_detail_book_without_metadata_shows_fallback(client, tmp_path):
    """Si pas de book_metadata, on a un fallback warning lisible."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Empty.Book"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Empty.Book",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,
    ))
    (pkg / "release_name.txt").write_text("Empty.Book\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    # Pas de book_metadata dans le debug
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}', encoding="utf-8",
    )

    resp = client.get("/packages/Empty.Book")
    assert resp.status_code == 200
    html = resp.text
    # Sprint D.6 : le fallback (sans book_metadata) doit afficher un
    # message d'aide pour completer manuellement.
    assert "Aucune métadonnée extraite" in html
