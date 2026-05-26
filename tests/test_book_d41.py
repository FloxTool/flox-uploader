"""Tests Sprint D.41 v0.5.0 — imgbb rate-limit + Gemini cover_url/banner_url.

Cible feedback Louis :
1. Detection 'Rate limit reached' dans la reponse imgbb -> flag rate_limited
2. Pipeline marque book_meta['imgbb_rate_limited']=True + emit signal naming
3. UI affiche un banner orange suggerant re-prepare plus tard
4. build_upload_payload envoie cover_url + banner_url au tracker Gemini
   pour les categories Livre (cat 12).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================
# 1. Detection imgbb rate-limit dans le ImgbbUploadResult
# ============================================================

class TestImgbbRateLimitDetection:
    """Sprint D.41 : upload_to_imgbb detecte 'rate limit'."""

    def _make_fake_response(self, status_code=200, json_data=None):
        r = MagicMock()
        r.status_code = status_code
        r.ok = status_code == 200
        r.json.return_value = json_data or {}
        r.text = json.dumps(json_data or {})
        return r

    def test_rate_limit_message_in_error(self, tmp_path):
        """imgbb HTTP 400 + message 'Rate limit reached' -> rate_limited=True."""
        from flox_uploader.core.providers.image_host import upload_to_imgbb

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)  # fake jpeg

        fake_resp = self._make_fake_response(
            status_code=400,
            json_data={
                "status_code": 400,
                "error": {"message": "Rate limit reached."},
                "success": False,
            },
        )
        result = upload_to_imgbb(img, api_key="fake", http_post=lambda *a, **kw: fake_resp)
        assert result.success is False
        assert result.rate_limited is True
        assert "Rate limit" in result.error or "rate limit" in result.error.lower()

    def test_http_429_is_rate_limited(self, tmp_path):
        """HTTP 429 standard -> rate_limited=True."""
        from flox_uploader.core.providers.image_host import upload_to_imgbb

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

        fake_resp = self._make_fake_response(
            status_code=429,
            json_data={"success": False, "error": {"message": "Too many requests"}},
        )
        result = upload_to_imgbb(img, api_key="fake", http_post=lambda *a, **kw: fake_resp)
        assert result.success is False
        assert result.rate_limited is True

    def test_other_failures_not_rate_limited(self, tmp_path):
        """Autres echecs (cle invalide, fichier trop gros, etc.) -> rate_limited=False."""
        from flox_uploader.core.providers.image_host import upload_to_imgbb

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

        fake_resp = self._make_fake_response(
            status_code=400,
            json_data={"success": False, "error": {"message": "Invalid API key"}},
        )
        result = upload_to_imgbb(img, api_key="fake", http_post=lambda *a, **kw: fake_resp)
        assert result.success is False
        assert result.rate_limited is False

    def test_success_not_rate_limited(self, tmp_path):
        """Upload reussi -> rate_limited=False, success=True."""
        from flox_uploader.core.providers.image_host import upload_to_imgbb

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)

        fake_resp = self._make_fake_response(
            status_code=200,
            json_data={
                "success": True,
                "data": {
                    "url": "https://i.ibb.co/abc/fake.jpg",
                    "delete_url": "https://ibb.co/del/123",
                },
            },
        )
        result = upload_to_imgbb(img, api_key="fake", http_post=lambda *a, **kw: fake_resp)
        assert result.success is True
        assert result.rate_limited is False
        assert result.url == "https://i.ibb.co/abc/fake.jpg"


# ============================================================
# 2. Signal naming SIG_IMGBB_RATE_LIMITED
# ============================================================

def test_signal_metadata_has_imgbb_rate_limited():
    """Le signal SIG_IMGBB_RATE_LIMITED existe + a une penalite et un label."""
    from flox_uploader.core.naming_signals import (
        SIG_IMGBB_RATE_LIMITED,
        SIGNAL_METADATA,
    )

    assert SIG_IMGBB_RATE_LIMITED == "imgbb_rate_limited"
    assert SIG_IMGBB_RATE_LIMITED in SIGNAL_METADATA
    penalty, label = SIGNAL_METADATA[SIG_IMGBB_RATE_LIMITED]
    assert penalty == 5
    assert "imgbb" in label.lower()
    assert "re-prép" in label.lower() or "re-prep" in label.lower()


# ============================================================
# 3. Banner UI affichage
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


def test_banner_displayed_when_rate_limited(client):
    """Page detail affiche un banner orange quand bm.imgbb_rate_limited=True."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.RL-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
        "imgbb_rate_limited": True,
        "imgbb_failed_images": ["cover", "preview_1", "preview_2"],
    })
    resp = client.get("/packages/Test.RL-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Banner present : titre + suggestion re-prepare
    assert "imgbb a atteint sa limite" in html
    assert "Re-prépare" in html or "Re-prepare" in html
    # Mention des fichiers concernes
    assert "3 image" in html


def test_no_banner_when_not_rate_limited(client):
    """Pas de banner si imgbb_rate_limited absent ou False."""
    from flox_uploader import config
    _make_book_pkg(config.packages_dir(), "Test.NoRL-Flox", book_meta={
        "title": "Test", "authors": ["A"], "file_format": "epub",
    })
    resp = client.get("/packages/Test.NoRL-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "imgbb a atteint sa limite" not in html


# ============================================================
# 4. build_upload_payload envoie cover_url + banner_url
# ============================================================

def test_payload_includes_cover_url_from_manual_cover(tmp_path):
    """Si state.manual_cover_url est une URL http(s), elle est envoyee."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader.core.upload_orchestrator import (
        PackageBundle, build_upload_payload, UploadConfig,
    )
    from flox_uploader.core.media_type import MediaType

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="X-Flox",
        tracker_key="gemini",
        created_at="", updated_at="",
        manual_category_id=12,
        manual_type_id=27,
        manual_cover_url="https://i.ibb.co/abc/cover.jpg",
        manual_banner_url="https://i.ibb.co/xyz/banner.jpg",
    ))

    bundle = PackageBundle(
        package_dir=pkg,
        release_name="X-Flox",
        description="",
        mediainfo="",
        torrent_path=pkg / "x.torrent",
        nfo_path=None,
        infohash="",
        size_bytes=0,
        tmdb_id=0,
        imdb_id=0,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
    )
    cfg = UploadConfig(api_url="", api_key="", anonymous=False, dry_run=True)
    payload = build_upload_payload(bundle, cfg)

    assert payload.extra.get("cover_url") == "https://i.ibb.co/abc/cover.jpg"
    assert payload.extra.get("banner_url") == "https://i.ibb.co/xyz/banner.jpg"


def test_payload_cover_url_fallback_from_book_metadata(tmp_path):
    """Si pas de manual_cover_url, fallback sur book_metadata.cover_url (imgbb)."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader.core.upload_orchestrator import (
        PackageBundle, build_upload_payload, UploadConfig,
    )
    from flox_uploader.core.media_type import MediaType

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="X-Flox",
        tracker_key="gemini",
        created_at="", updated_at="",
        manual_category_id=12,
        manual_type_id=27,
    ))
    # debug.json avec book_metadata.cover_url
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "book_metadata": {"cover_url": "https://i.ibb.co/auto/cover.jpg"},
    }))

    bundle = PackageBundle(
        package_dir=pkg,
        release_name="X-Flox",
        description="",
        mediainfo="",
        torrent_path=pkg / "x.torrent",
        nfo_path=None,
        infohash="",
        size_bytes=0,
        tmdb_id=0,
        imdb_id=0,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
    )
    cfg = UploadConfig(api_url="", api_key="", anonymous=False, dry_run=True)
    payload = build_upload_payload(bundle, cfg)
    assert payload.extra.get("cover_url") == "https://i.ibb.co/auto/cover.jpg"
    # Pas de banner si pas saisi
    assert "banner_url" not in payload.extra


def test_payload_local_cover_path_not_sent(tmp_path):
    """Un cover_url local (file://, path) ne doit PAS etre envoye."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader.core.upload_orchestrator import (
        PackageBundle, build_upload_payload, UploadConfig,
    )
    from flox_uploader.core.media_type import MediaType

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="X-Flox",
        tracker_key="gemini",
        created_at="", updated_at="",
        manual_category_id=12,
        manual_type_id=27,
    ))
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "book_metadata": {"cover_url": "C:/local/path/cover.jpg"},  # path local
    }))

    bundle = PackageBundle(
        package_dir=pkg,
        release_name="X-Flox",
        description="",
        mediainfo="",
        torrent_path=pkg / "x.torrent",
        nfo_path=None,
        infohash="",
        size_bytes=0,
        tmdb_id=0,
        imdb_id=0,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
    )
    cfg = UploadConfig(api_url="", api_key="", anonymous=False, dry_run=True)
    payload = build_upload_payload(bundle, cfg)
    # Le path local n'est PAS envoye (tracker ne peut pas l'atteindre)
    assert "cover_url" not in payload.extra


def test_payload_form_data_includes_cover_banner(tmp_path):
    """to_form_data() doit serialiser cover_url + banner_url depuis extra."""
    from flox_uploader.core.gemini_api import UploadPayload

    payload = UploadPayload(
        name="X-Flox",
        description="",
        mediainfo="",
        torrent_path=tmp_path / "x.torrent",
        category_id=12,
        type_id=27,
        extra={"cover_url": "https://x/c.jpg", "banner_url": "https://x/b.jpg"},
    )
    form = payload.to_form_data()
    assert form["cover_url"] == "https://x/c.jpg"
    assert form["banner_url"] == "https://x/b.jpg"
