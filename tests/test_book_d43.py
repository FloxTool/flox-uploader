"""Tests Sprint D.43 v0.5.0 — 5 fixes feedback Louis.

1. Score reflete la difficulte du match (title court, volume mismatch,
   similarity faible).
2. Banner imgbb rate-limit place au meme niveau que les autres warnings.
3. Cover hover label conditionnel (hosted vs web fallback vs locale).
4. Type par defaut = Livre (eff_category > 0 = CATEGORY_BOOKS) au lieu
   de BDRip qui n'est meme pas une option valide pour les livres.
5. Sous-type retire de Options upload.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ============================================================
# Fixtures
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


def _make_book_pkg(
    pkg_root: Path, name: str, book_meta: dict, scene_parsed: dict = None,
) -> Path:
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name=name,
        tracker_key="gemini",
        created_at="2026-05-26T00:00:00Z",
        updated_at="2026-05-26T00:00:00Z",
        manual_category_id=12,
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    (pkg / "presentation.txt").write_text("[b]Test[/b]", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    debug_data = {
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": book_meta,
    }
    if scene_parsed is not None:
        debug_data["scene_parsed"] = scene_parsed
    (debug / "debug.json").write_text(json.dumps(debug_data), encoding="utf-8")
    return pkg


# ============================================================
# 1. Score : penalites match faible
# ============================================================

class TestScoreMatchFaible:
    """Sprint D.43 (feedback Louis) : score reflete difficulte match."""

    def _compute_score(self, pkg_dir):
        from flox_uploader.core.confidence_strategies.book import (
            BookConfidenceStrategy,
        )
        return BookConfidenceStrategy().compute(pkg_dir)

    def test_score_penalty_title_year_only(self, tmp_path):
        """Title scene = '2021' (cas Space Brothers T33) -> -15 pts."""
        pkg = _make_book_pkg(
            tmp_path, "Test.Year.Title-Flox",
            book_meta={
                "title": "Space Brothers",
                "authors": ["Chuya Koyama"],
                "publication_year": 2021,
                "language": "fr",
                "file_format": "cbz",
                "isbn_13": "9784091234567",
                "description": "x" * 200,
                "cover_url": "https://i.ibb.co/x/c.jpg",
                "google_books_id": "ABC",
                "series_index": 0,
            },
            scene_parsed={"title": "2021", "series_index": 33, "year": 2021},
        )
        score = self._compute_score(pkg)
        # Le score doit etre < 95 a cause des penalites match faible
        assert score.score < 95
        # On verifie qu'au moins une penalite mentionne le titre suspect
        labels = " ".join(score.reasons).lower()
        assert "suspect" in labels or "court" in labels or "ressemble" in labels

    def test_score_penalty_title_chapter_only(self, tmp_path):
        """Title scene = 'C1180' (cas One Piece fanscan) -> -15 pts."""
        pkg = _make_book_pkg(
            tmp_path, "Test.Chapter-Flox",
            book_meta={
                "title": "One Piece",
                "authors": ["Eiichiro Oda"],
                "publication_year": 2026,
                "language": "fr",
                "file_format": "cbz",
                "description": "x" * 200,
                "isbn_13": "9784088802367",
                "google_books_id": "ABC",
            },
            scene_parsed={"title": "C1180", "year": 2026},
        )
        score = self._compute_score(pkg)
        labels = " ".join(score.reasons).lower()
        assert "suspect" in labels or "court" in labels or "ressemble" in labels

    def test_score_penalty_volume_mismatch(self, tmp_path):
        """scene_vol=33 mais meta_vol=40 -> penalite mauvais tome."""
        pkg = _make_book_pkg(
            tmp_path, "Test.Volume.Mismatch-Flox",
            book_meta={
                "title": "Space Brothers Tome 40",
                "authors": ["Koyama"],
                "publication_year": 2022,
                "language": "fr",
                "file_format": "cbz",
                "description": "x" * 200,
                "isbn_13": "1234567890123",
                "google_books_id": "ABC",
                "series_index": 40,
                "cover_url": "https://i.ibb.co/x/c.jpg",
            },
            scene_parsed={
                "title": "Space Brothers", "year": 2021, "series_index": 33,
            },
        )
        score = self._compute_score(pkg)
        labels = " ".join(score.reasons).lower()
        assert "tome" in labels and ("≠" in " ".join(score.reasons) or "different" in labels or "mauvais" in labels)

    def test_score_penalty_title_dissimilar(self, tmp_path):
        """Title scene tres different du title canonique -> penalite."""
        pkg = _make_book_pkg(
            tmp_path, "Test.Title.Dissim-Flox",
            book_meta={
                # Title canonique tres different du scene
                "title": "Encyclopedie complete du XIXe siecle volume 7",
                "authors": ["Auteur"],
                "publication_year": 2020,
                "language": "fr",
                "file_format": "pdf",
                "description": "x" * 200,
                "isbn_13": "1234567890123",
                "google_books_id": "ABC",
                "cover_url": "https://i.ibb.co/x/c.jpg",
            },
            scene_parsed={"title": "Spartacus Blood and Sand", "year": 2011},
        )
        score = self._compute_score(pkg)
        labels = " ".join(score.reasons).lower()
        assert "similar" in labels or "different" in labels

    def test_score_no_penalty_when_match_clean(self, tmp_path):
        """Match parfait avec scene_parsed coherent -> aucune penalite D.43."""
        pkg = _make_book_pkg(
            tmp_path, "Test.Clean.Match-Flox",
            book_meta={
                "title": "Le Seigneur des Anneaux",
                "authors": ["Tolkien"],
                "publication_year": 1954,
                "language": "fr",
                "file_format": "epub",
                "description": "x" * 200,
                "isbn_13": "9782266154116",
                "cover_url": "https://i.ibb.co/x/c.jpg",
                "google_books_id": "ABC",
            },
            scene_parsed={
                "title": "Le Seigneur des Anneaux",
                "year": 1954,
                "series_index": 0,
            },
        )
        score = self._compute_score(pkg)
        # Doit etre >= 95 (perfect ou parfait)
        assert score.score >= 95

    def test_score_imgbb_rate_limit_penalty(self, tmp_path):
        """imgbb_rate_limited=True -> -5 pts."""
        pkg = _make_book_pkg(
            tmp_path, "Test.RL.Score-Flox",
            book_meta={
                "title": "Test",
                "authors": ["A"],
                "publication_year": 2024,
                "language": "fr",
                "file_format": "epub",
                "description": "x" * 200,
                "isbn_13": "9782266154116",
                "imgbb_rate_limited": True,
                "imgbb_failed_images": ["cover", "preview_1"],
                "google_books_id": "ABC",
            },
            scene_parsed={"title": "Test", "year": 2024},
        )
        score = self._compute_score(pkg)
        labels = " ".join(score.reasons).lower()
        assert "imgbb" in labels and "rate" in labels


# ============================================================
# 2. Banner imgbb position
# ============================================================

def test_banner_imgbb_rendered_outside_book_card(client):
    """Sprint D.43 : banner imgbb est dans package_detail.html (avec les
    autres warnings) et plus dans _detail_book.html (carte Livre)."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Banner.Pos-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
        "imgbb_rate_limited": True,
        "imgbb_failed_images": ["cover"],
    })
    resp = client.get("/packages/Test.Banner.Pos-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Le banner existe
    assert "imgbb a atteint sa limite" in html
    # Le banner doit etre AVANT la section "Upload vers le tracker"
    pos_banner = html.find("imgbb a atteint sa limite")
    pos_upload = html.find("Upload vers le tracker")
    if pos_upload > 0:  # Upload section visible
        assert pos_banner < pos_upload, (
            f"Banner imgbb (pos {pos_banner}) devrait etre AVANT 'Upload vers "
            f"le tracker' (pos {pos_upload})"
        )


# ============================================================
# 3. Cover hover label conditionnel
# ============================================================

def test_cover_label_imgbb_hosted(client):
    """cover_url=imgbb.co -> label 'fichier' + tooltip mentionne imgbb."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Cover.Imgbb-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
        "cover_url": "https://i.ibb.co/abc/cover.jpg",
    })
    resp = client.get("/packages/Test.Cover.Imgbb-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Label 'fichier' present + tooltip mentionne imgbb (pas Imgur)
    assert "uploadée sur imgbb" in html


def test_cover_label_imgur_hosted(client):
    """cover_url=imgur.com -> tooltip mentionne Imgur."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Cover.Imgur-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
        "cover_url": "https://i.imgur.com/abc.jpg",
    })
    resp = client.get("/packages/Test.Cover.Imgur-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "uploadée sur Imgur" in html


def test_cover_label_web_fallback(client):
    """cover_url=books.google.com -> label 'web' + tooltip 'Google Books'."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Cover.Web-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
        "cover_url": "https://books.google.com/books/content?id=abc",
        "google_books_id": "abc",
    })
    resp = client.get("/packages/Test.Cover.Web-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Doit dire que la cover est trouvee via Google Books (fallback)
    assert "Cover trouvée via Google Books" in html
    # Et pas dire qu'elle est uploadee sur imgbb
    assert "uploadée sur imgbb" not in html


# ============================================================
# 4. Type par defaut Livre quand eff_category=12
# ============================================================

def test_type_default_is_book_when_category_is_book(client):
    """Quand eff_category=12 (Livre), le auto_type doit etre TYPE_BOOK_*
    (27-33), pas BDRip (type video par defaut)."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.Type.Default-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
    })
    resp = client.get("/packages/Test.Type.Default-Flox")
    assert resp.status_code == 200
    html = resp.text
    # On verifie que le label de type affiche est un type livre, pas BDRip.
    # Pour ca on cherche la dropdown gemini-type et son option hidden default.
    import re
    # L'option hidden contient le label par defaut (eff_type)
    pat = re.compile(
        r'<select[^>]*id="gemini-type"[^>]*>\s*'
        r'<option value="0"[^>]*hidden>\s*([^<]+?)\s*</option>',
    )
    m = pat.search(html)
    assert m, "Dropdown gemini-type introuvable"
    default_label = m.group(1).strip()
    # Le label par defaut ne doit pas etre BDRip / Encode / Bluray
    assert "BDRip" not in default_label
    assert "Encode" not in default_label
    # Doit etre un des labels livre (Livre / BD / Comics / Mangas / etc.)
    book_labels = {
        "Livre", "BD", "Comics", "Mangas", "Magazine", "Presse", "Audio",
        "Livre audio", "Livre audio M4B", "Livre audio MP3",
    }
    # Default doit etre dans book_labels OU contenir un de ces mots
    assert any(b in default_label for b in book_labels), (
        f"Default Type label '{default_label}' doit etre un type livre"
    )


# ============================================================
# 5. Sous-type retire de Options upload
# ============================================================

def test_subtype_dropdown_removed_from_ui(client):
    """Sprint D.43 : le dropdown manual_book_subtype n'est plus dans l'UI."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.NoSubtype-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "publication_year": 2024, "language": "fr",
    })
    resp = client.get("/packages/Test.NoSubtype-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="manual_book_subtype"' not in html
    # Pas non plus de label "Sous-type"
    assert "Sous-type" not in html or "Sous-Type" not in html


# ============================================================
# Helpers internes : similarity + suspicious title
# ============================================================

def test_titles_similarity_identical():
    from flox_uploader.core.confidence_strategies.book import _titles_similarity
    assert _titles_similarity("Le Seigneur des Anneaux", "Le Seigneur des Anneaux") == 1.0


def test_titles_similarity_different():
    from flox_uploader.core.confidence_strategies.book import _titles_similarity
    sim = _titles_similarity("Spartacus Blood and Sand", "Encyclopedie XIXe siecle")
    assert sim < 0.4


def test_titles_similarity_tome_normalized():
    """'Le Mythe T1' vs 'Le Mythe Tome 1' devrait etre similaire (tome strippe)."""
    from flox_uploader.core.confidence_strategies.book import _titles_similarity
    sim = _titles_similarity("Le Mythe T1", "Le Mythe Tome 1")
    assert sim > 0.8


def test_is_suspicious_title_year_only():
    from flox_uploader.core.confidence_strategies.book import _is_suspicious_title
    assert _is_suspicious_title("2021") != ""


def test_is_suspicious_title_chapter():
    from flox_uploader.core.confidence_strategies.book import _is_suspicious_title
    assert _is_suspicious_title("C1180") != ""


def test_is_suspicious_title_short():
    from flox_uploader.core.confidence_strategies.book import _is_suspicious_title
    assert _is_suspicious_title("ab") != ""


def test_is_suspicious_title_normal_title():
    from flox_uploader.core.confidence_strategies.book import _is_suspicious_title
    assert _is_suspicious_title("Le Seigneur des Anneaux") == ""
