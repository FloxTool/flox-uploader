"""Tests Sprint D.40 v0.5.0 — UI livres : URL Google Books, type auto-fill, textes.

Cible feedback Louis :
1. Champ "URL Google Books forcée" + parser extract_volume_id_from_url
2. Champ "Banner URL" dans Options upload livre
3. Dropdown Type limite aux 7 IDs livres (27-33)
4. Auto-fill du Type via book_type_id_for()
5. Liens d'aide ISBN / Google Books dans la section override
6. Resolution masquee pour profil livre
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.providers.google_books import (
    extract_volume_id_from_url,
)
from flox_uploader.trackers.gemini.unit3d_mapping import (
    BOOK_TYPE_OPTIONS,
    TYPE_BOOK_AUDIO,
    TYPE_BOOK_BD,
    TYPE_BOOK_COMICS,
    TYPE_BOOK_EBOOK,
    TYPE_BOOK_MAGAZINE,
    TYPE_BOOK_MANGAS,
    TYPE_BOOK_PRESSE,
    book_type_id_for,
)


# ============================================================
# 1. Extract volume_id depuis URL Google Books
# ============================================================

class TestExtractVolumeIdFromUrl:
    """Sprint D.40 : parser URL Google Books -> volumeId."""

    def test_modern_books_edition_url(self):
        url = "https://www.google.ca/books/edition/Sorceleur/4eeGAQAAQBAJ?hl=fr"
        assert extract_volume_id_from_url(url) == "4eeGAQAAQBAJ"

    def test_legacy_books_id_url(self):
        url = "https://books.google.com/books?id=YPvVEQAAQBAJ&hl=fr"
        assert extract_volume_id_from_url(url) == "YPvVEQAAQBAJ"

    def test_play_store_url(self):
        url = "https://play.google.com/store/books/details?id=AbCdEfGhIjKl"
        assert extract_volume_id_from_url(url) == "AbCdEfGhIjKl"

    def test_raw_volume_id_accepted(self):
        """Si l'user colle juste l'ID brut sans URL, on accepte."""
        assert extract_volume_id_from_url("4eeGAQAAQBAJ") == "4eeGAQAAQBAJ"

    def test_invalid_url_returns_empty(self):
        assert extract_volume_id_from_url("invalid") == ""
        assert extract_volume_id_from_url("") == ""
        assert extract_volume_id_from_url("https://example.com/") == ""

    def test_url_with_extra_query_params(self):
        url = (
            "https://books.google.fr/books?id=BWibDwAAQBAJ&hl=fr&gbpv=0"
            "&dq=clos+de+bourgogne"
        )
        assert extract_volume_id_from_url(url) == "BWibDwAAQBAJ"

    def test_url_with_slug_accents(self):
        url = (
            "https://www.google.com/books/edition/"
            "Guide_Poitiers_2026_Petit_Fut%C3%A9_Escapades/Nw2eEQAAQBAJ?hl=fr"
        )
        assert extract_volume_id_from_url(url) == "Nw2eEQAAQBAJ"


# ============================================================
# 2. BOOK_TYPE_OPTIONS limite aux 7 IDs livres
# ============================================================

class TestBookTypeOptionsLimite:
    """Sprint D.40 (feedback Louis) : dropdown Type livre = 7 entrees fixes."""

    def test_exactly_7_options(self):
        assert len(BOOK_TYPE_OPTIONS) == 7

    def test_ids_are_27_to_33(self):
        ids = {opt[0] for opt in BOOK_TYPE_OPTIONS}
        assert ids == {27, 28, 29, 30, 31, 32, 33}

    def test_no_m4b_mp3_specifiques(self):
        ids = {opt[0] for opt in BOOK_TYPE_OPTIONS}
        # M4B (25) et MP3 (26) absorbes dans Audio (33)
        assert 25 not in ids
        assert 26 not in ids


# ============================================================
# 3. book_type_id_for() auto-fill
# ============================================================

class TestBookTypeIdFor:
    """Sprint D.40 : auto-fill du type livre."""

    def test_ebook_format_epub(self):
        type_id, src = book_type_id_for(file_format="epub")
        assert type_id == TYPE_BOOK_EBOOK
        assert "ebook" in src.lower() or "Livre" in src

    def test_ebook_format_pdf(self):
        type_id, _ = book_type_id_for(file_format="pdf")
        assert type_id == TYPE_BOOK_EBOOK

    def test_audio_format_mp3(self):
        type_id, src = book_type_id_for(file_format="mp3")
        assert type_id == TYPE_BOOK_AUDIO
        assert "audio" in src.lower()

    def test_audio_format_m4b(self):
        type_id, _ = book_type_id_for(file_format="m4b")
        assert type_id == TYPE_BOOK_AUDIO

    def test_cbz_default_bd(self):
        """CBZ sans hint specifique -> BD par defaut FR."""
        type_id, src = book_type_id_for(file_format="cbz")
        assert type_id == TYPE_BOOK_BD
        assert "BD" in src

    def test_cbz_japanese_language_manga(self):
        type_id, src = book_type_id_for(file_format="cbz", language="ja")
        assert type_id == TYPE_BOOK_MANGAS
        assert "japon" in src.lower() or "Mangas" in src

    def test_cbz_isbn_4_manga(self):
        type_id, _ = book_type_id_for(file_format="cbz", isbn_13="9784088802367")
        assert type_id == TYPE_BOOK_MANGAS

    def test_cbz_english_comics(self):
        type_id, src = book_type_id_for(file_format="cbz", language="en")
        assert type_id == TYPE_BOOK_COMICS
        assert "comics" in src.lower() or "anglais" in src.lower()

    def test_cbz_isbn_1_comics(self):
        type_id, _ = book_type_id_for(file_format="cbz", isbn_13="9781401234567")
        assert type_id == TYPE_BOOK_COMICS

    def test_cbz_subtype_manga_forced(self):
        type_id, src = book_type_id_for(
            file_format="cbz", book_subtype="manga", language="fr"
        )
        assert type_id == TYPE_BOOK_MANGAS
        assert "force" in src.lower()

    def test_periodical_quotidien_presse(self):
        type_id, src = book_type_id_for(
            is_periodical=True, publication_name="Ouest-France 23-24 Mai 2026"
        )
        assert type_id == TYPE_BOOK_PRESSE
        assert "quotidien" in src.lower() or "Presse" in src

    def test_periodical_magazine_par_defaut(self):
        type_id, src = book_type_id_for(
            is_periodical=True, publication_name="Rolling Stone France Juin 2026"
        )
        assert type_id == TYPE_BOOK_MAGAZINE
        assert "periodique" in src.lower() or "Magazine" in src

    def test_unknown_format_returns_zero(self):
        """Format inconnu -> 0 (non devinable). Le caller emettra le malus."""
        type_id, src = book_type_id_for()
        assert type_id == 0
        assert "non devinable" in src.lower() or "inconnu" in src.lower()

    def test_unknown_format_other_extension(self):
        type_id, _ = book_type_id_for(file_format="xyz")
        assert type_id == 0


# ============================================================
# 4. PendingJob accepte manual_google_books_url
# ============================================================

class TestPendingJobGoogleBooksUrl:
    """Sprint D.40 : jobs_db persiste manual_google_books_url."""

    def test_pending_job_has_field(self):
        from flox_uploader.core.jobs_db import PendingJob

        # Le dataclass doit avoir le nouveau champ avec default ""
        job = PendingJob(
            id=0,
            file_path="/x/y.epub",
            status="pending",
            force_fr="",
            created_at="",
            updated_at="",
            package_dir="",
            release_name="",
            log_path="",
            error="",
        )
        assert hasattr(job, "manual_google_books_url")
        assert job.manual_google_books_url == ""


# ============================================================
# 5. PackageStateData accepte manual_banner_url
# ============================================================

class TestPackageStateBannerUrl:
    """Sprint D.40 : state persiste manual_banner_url."""

    def test_state_has_field(self):
        from flox_uploader.core.package_state import PackageStateData, PackageState

        state = PackageStateData(
            state=PackageState.PREPARED,
            release_name="x",
            tracker_key="gemini",
            created_at="",
            updated_at="",
        )
        assert hasattr(state, "manual_banner_url")
        assert state.manual_banner_url == ""


# ============================================================
# 6. Template : URL Google Books field present pour livre
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
        created_at="2026-05-25T00:00:00Z",
        updated_at="2026-05-25T00:00:00Z",
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


def test_template_has_google_books_url_field(client):
    """La section override pour livre contient le champ URL Google Books."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Book.Gb-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024,
    })
    resp = client.get("/packages/Test.Book.Gb-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Champ URL Google Books + lien d'aide vers books.google.com
    assert 'id="manual_google_books_url"' in html
    assert "books.google.com" in html


def test_template_has_isbn_help_link(client):
    """Le champ ISBN propose un lien vers une source d'aide."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Book.Isbn-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
    })
    resp = client.get("/packages/Test.Book.Isbn-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Lien vers catalogue.bnf.fr ou isbnsearch.org
    assert "catalogue.bnf.fr" in html or "isbnsearch.org" in html


def test_template_has_banner_url_field(client):
    """Options upload livre contient le champ Banner URL."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Banner-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
    })
    resp = client.get("/packages/Test.Banner-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="manual_banner_url"' in html


def test_template_book_resolution_hidden(client):
    """Pour un livre, la Resolution est masquee (display:none)."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.NoRes-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
    })
    resp = client.get("/packages/Test.NoRes-Flox")
    assert resp.status_code == 200
    html = resp.text
    # On verifie qu'un element avec id="gemini-resolution" est dans un wrapper
    # data-profile-section="video" qui a style="display:none" pour les livres.
    import re
    pattern = re.compile(
        r'data-profile-section="video"[^>]*style="display:none"',
        re.IGNORECASE,
    )
    assert pattern.search(html), (
        "Au moins un wrapper data-profile-section=video doit etre cache pour un livre"
    )


def test_template_book_type_dropdown_limited(client):
    """Pour un livre, la dropdown Type ne contient QUE les 7 IDs livres."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.TypeLim-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
    })
    resp = client.get("/packages/Test.TypeLim-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Extraire la section <select id="gemini-type">...</select>
    import re
    sel_match = re.search(
        r'<select[^>]*id="gemini-type"[^>]*>([\s\S]*?)</select>',
        html,
    )
    assert sel_match, "Dropdown gemini-type introuvable"
    select_body = sel_match.group(1)
    # Pour un livre, on ne doit voir QUE les value=27..33 (+ value=0 auto).
    # On ne doit pas voir des types video comme value="1" (Full Disc).
    options = re.findall(r'<option value="(\d+)"', select_body)
    book_type_ids = {"27", "28", "29", "30", "31", "32", "33"}
    visible = set(options) - {"0"}
    # visible doit etre SOUS-ENSEMBLE des IDs livres (pas de pollution video)
    assert visible.issubset(book_type_ids), (
        f"Dropdown contient des types non-livre : {visible - book_type_ids}"
    )
