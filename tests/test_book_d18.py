"""Tests Sprint D.18 v0.5.0 — cover BBCode externe vs locale + regen endpoint.

Cible notes Louis N-Feat-1 + Q2 :
- Le BBCode tracker ne doit inclure que les cover_url externes (https)
  car le tracker ne peut pas atteindre /packages/.../cover du serveur local.
- Les covers locales extraites (D.7) sont affichees dans la page detail
  (badge 'locale') mais NON dans le BBCode.
- Endpoint /regenerate-presentation pour re-render le BBCode apres saisie
  manual_cover_url sans relancer toute la prepare.

Verifie :
1. is_external_cover_url() : True pour https, False pour /packages/, vide
2. pick_bbcode_cover_url() : prefere manual > meta.cover_url externe, ignore local
3. render_book_bbcode : utilise la cover externe choisie, vide sinon
4. Endpoint /regenerate-presentation : re-render OK avec manual_cover_url
5. Badge UI 'externe' vs 'locale' sur la page detail
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest


# ============================================================
# Helpers cover
# ============================================================

def test_is_external_cover_url_http():
    """http(s)://... -> True."""
    from flox_uploader.core.bbcode_book import is_external_cover_url
    assert is_external_cover_url("https://example.com/c.jpg") is True
    assert is_external_cover_url("http://example.com/c.jpg") is True


def test_is_external_cover_url_local():
    """/packages/... ou path relatif -> False."""
    from flox_uploader.core.bbcode_book import is_external_cover_url
    assert is_external_cover_url("/packages/Foo/cover") is False
    assert is_external_cover_url("cover.jpg") is False
    assert is_external_cover_url("./cover.jpg") is False


def test_is_external_cover_url_empty():
    """Vide -> False."""
    from flox_uploader.core.bbcode_book import is_external_cover_url
    assert is_external_cover_url("") is False
    assert is_external_cover_url(None) is False


# ============================================================
# pick_bbcode_cover_url
# ============================================================

def test_pick_bbcode_cover_url_prefers_manual():
    """manual_cover_url externe a priorite sur meta.cover_url."""
    from flox_uploader.core.bbcode_book import pick_bbcode_cover_url
    from flox_uploader.core.providers.book_metadata import BookMetadata

    meta = BookMetadata(cover_url="https://bnf.fr/auto.jpg")
    out = pick_bbcode_cover_url(meta, manual_cover_url="https://user.com/custom.jpg")
    assert out == "https://user.com/custom.jpg"


def test_pick_bbcode_cover_url_uses_meta_if_no_manual():
    """Pas de manual : on prend meta.cover_url si externe."""
    from flox_uploader.core.bbcode_book import pick_bbcode_cover_url
    from flox_uploader.core.providers.book_metadata import BookMetadata

    meta = BookMetadata(cover_url="https://bnf.fr/auto.jpg")
    out = pick_bbcode_cover_url(meta, manual_cover_url="")
    assert out == "https://bnf.fr/auto.jpg"


def test_pick_bbcode_cover_url_filters_local_only():
    """Cover locale uniquement : retourne vide (le tracker ne peut pas y acceder)."""
    from flox_uploader.core.bbcode_book import pick_bbcode_cover_url
    from flox_uploader.core.providers.book_metadata import BookMetadata

    meta = BookMetadata(cover_url="/packages/Foo/cover")
    out = pick_bbcode_cover_url(meta, manual_cover_url="")
    assert out == ""


def test_pick_bbcode_cover_url_manual_local_ignored():
    """Si manual_cover_url est local (cas degenere), on l'ignore aussi."""
    from flox_uploader.core.bbcode_book import pick_bbcode_cover_url
    from flox_uploader.core.providers.book_metadata import BookMetadata

    meta = BookMetadata(cover_url="https://bnf.fr/auto.jpg")
    out = pick_bbcode_cover_url(meta, manual_cover_url="/local/bad.jpg")
    # manual_cover_url local ignore, fallback sur meta.cover_url externe
    assert out == "https://bnf.fr/auto.jpg"


# ============================================================
# render_book_bbcode avec covers
# ============================================================

def test_render_bbcode_local_cover_not_in_output(monkeypatch):
    """Une cover locale ne doit PAS apparaitre dans le [img=300] du BBCode."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="T", authors=["A"], file_format="epub",
        cover_url="/packages/Foo/cover",  # locale
    )
    bbcode = render_book_bbcode(meta, "Rel", tracker)
    # Pas de [img=300] avec la cover locale
    assert "/packages/Foo/cover" not in bbcode
    # Pas de [img=300] tout court (puisque la seule cover est locale)
    assert "[img=300]" not in bbcode


def test_render_bbcode_external_cover_included(monkeypatch):
    """Une cover externe DOIT apparaitre dans le [img=300]."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="T", authors=["A"], file_format="epub",
        cover_url="https://bnf.fr/cover.jpg",
    )
    bbcode = render_book_bbcode(meta, "Rel", tracker)
    assert "[img=300]https://bnf.fr/cover.jpg[/img]" in bbcode


def test_render_bbcode_manual_cover_overrides(monkeypatch):
    """manual_cover_url remplace meta.cover_url meme si meta est externe."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="T", authors=["A"], file_format="epub",
        cover_url="https://bnf.fr/auto.jpg",
    )
    bbcode = render_book_bbcode(
        meta, "Rel", tracker,
        manual_cover_url="https://user.com/perso.jpg",
    )
    assert "https://user.com/perso.jpg" in bbcode
    # L'auto n'apparait plus (override)
    assert "https://bnf.fr/auto.jpg" not in bbcode


# ============================================================
# Endpoint /regenerate-presentation
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


def _make_book_pkg(pkg_root: Path, name: str, book_meta: dict, manual_cover_url: str = "") -> Path:
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name=name,
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,
        manual_cover_url=manual_cover_url,
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    (pkg / "presentation.txt").write_text("old BBCode", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": book_meta,
    }), encoding="utf-8")
    return pkg


def test_regenerate_presentation_uses_manual_cover(client, tmp_path):
    """POST /regenerate-presentation utilise manual_cover_url du state."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Regen.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "cover_url": "",  # pas de cover auto
    }, manual_cover_url="https://user.com/perso.jpg")

    resp = client.post(
        "/api/packages/Regen.Cover-Flox/regenerate-presentation",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["cover_used"] == "https://user.com/perso.jpg"

    # presentation.txt a ete reecrit
    pkg = pkg_root / "Regen.Cover-Flox"
    bbcode = (pkg / "presentation.txt").read_text(encoding="utf-8")
    assert "https://user.com/perso.jpg" in bbcode
    assert "old BBCode" not in bbcode


def test_regenerate_presentation_ignores_local_cover(client, tmp_path):
    """Si cover_url est local + pas de manual : cover_is_local=True, cover_used vide."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Regen.Local.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "cover_url": "/packages/Foo/cover",
    })

    resp = client.post(
        "/api/packages/Regen.Local.Cover-Flox/regenerate-presentation",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cover_is_local"] is True
    assert data["cover_used"] == ""
    # BBCode genere sans [img]
    pkg = pkg_root / "Regen.Local.Cover-Flox"
    bbcode = (pkg / "presentation.txt").read_text(encoding="utf-8")
    assert "/packages/Foo/cover" not in bbcode
    assert "[img=300]" not in bbcode


def test_regenerate_presentation_video_package_rejected(client, tmp_path):
    """Pour un package video : 400 (endpoint reserve aux livres)."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg = pkg_root / "Video.Pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED, release_name="Video.Pkg",
        tracker_key="gemini", created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z", manual_category_id=1,
    ))
    (pkg / "release_name.txt").write_text("Video.Pkg\n")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text('{"media_type":"movie","tmdb_context":{}}', encoding="utf-8")

    resp = client.post("/api/packages/Video.Pkg/regenerate-presentation")
    assert resp.status_code == 400


def test_regenerate_presentation_no_state_404(client, tmp_path):
    """Package inexistant : 404 (via _resolve_package_dir)."""
    resp = client.post("/api/packages/Does.Not.Exist/regenerate-presentation")
    assert resp.status_code in (404, 422)


# ============================================================
# Page detail : badge externe vs locale
# ============================================================

def test_page_detail_book_external_cover_shows_badge(client, tmp_path):
    """Cover externe (https) -> badge 'externe' visible."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Ext.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "cover_url": "https://bnf.fr/c.jpg",
    })

    resp = client.get("/packages/Ext.Cover-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "externe" in html
    # L'image est rendue
    assert "https://bnf.fr/c.jpg" in html


def test_page_detail_book_local_cover_shows_warning_badge(client, tmp_path):
    """Cover locale -> badge 'locale' avec tooltip explicatif."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Loc.Cover-Flox", book_meta={
        "title": "T", "authors": ["A"], "file_format": "epub",
        "cover_url": "/packages/Loc.Cover-Flox/cover",
    })

    resp = client.get("/packages/Loc.Cover-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Badge "locale" visible
    assert ">locale" in html or "locale<" in html or "locale " in html
    # Le tooltip explicatif est present
    assert "NON accessible par le tracker" in html
