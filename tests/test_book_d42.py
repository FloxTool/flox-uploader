"""Tests Sprint D.42 v0.5.0 — Reduire taille images + fallback Imgur.

Cible feedback Louis :
1. Compression aggressive PyMuPDF (zoom 1.2 + JPEG q=80) — gain x6 sur les
   pages rendues EPUB/PDF.
2. Recompression Pillow optionnelle pour CBZ/CBR/MP3 covers — resize si
   > 1200px + JPEG q=80.
3. Fallback Imgur quand imgbb rate-limit. Strategie a 2 etages via
   upload_image(imgbb_api_key=, imgur_client_id=).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================
# 1. Compression PyMuPDF (zoom + jpg_quality)
# ============================================================

def test_pymupdf_zoom_reduced():
    """Le zoom global PyMuPDF est passe a 1.2 (vs 1.7 avant D.42)."""
    from flox_uploader.core.providers.image_extraction import PYMUPDF_ZOOM
    assert PYMUPDF_ZOOM == 1.2


def test_jpeg_quality_reduced():
    """JPEG quality est passee a 80 (vs 95 default PyMuPDF)."""
    from flox_uploader.core.providers.image_extraction import JPEG_QUALITY
    assert JPEG_QUALITY == 80


def test_max_image_width_set():
    """MAX_IMAGE_WIDTH_PX = 1200 (safety net resize)."""
    from flox_uploader.core.providers.image_extraction import MAX_IMAGE_WIDTH_PX
    assert MAX_IMAGE_WIDTH_PX == 1200


# ============================================================
# 2. Recompression Pillow (Pillow installe en dev)
# ============================================================

class TestRecompressionPillow:
    """Sprint D.42 : _maybe_recompress_external_image reduit la taille."""

    def test_recompress_large_jpeg(self, tmp_path):
        """JPEG 2000x3000 -> resize a 1200 + recompression q=80."""
        from PIL import Image
        from flox_uploader.core.providers.image_extraction import (
            _maybe_recompress_external_image, MAX_IMAGE_WIDTH_PX,
        )
        # Cree une image fictive 2000x3000 (gros JPEG)
        img = Image.new("RGB", (2000, 3000), color=(120, 80, 200))
        # Ajouter du bruit pour que ce ne soit pas une couleur uniforme
        # (sinon JPEG compresse a quasi 0)
        import random as _rand
        pixels = img.load()
        _rand.seed(42)
        for x in range(0, 2000, 4):
            for y in range(0, 3000, 4):
                pixels[x, y] = (
                    _rand.randint(0, 255),
                    _rand.randint(0, 255),
                    _rand.randint(0, 255),
                )
        path = tmp_path / "big.jpg"
        img.save(path, "JPEG", quality=95)
        original_size = path.stat().st_size
        # Recompresse
        _maybe_recompress_external_image(path)
        new_size = path.stat().st_size
        # Doit etre plus petit (probablement -50% minimum)
        assert new_size < original_size
        # Doit etre <= MAX_IMAGE_WIDTH_PX
        img2 = Image.open(path)
        assert img2.width <= MAX_IMAGE_WIDTH_PX

    def test_recompress_small_image_not_resized(self, tmp_path):
        """Image deja petite ne doit pas etre resize, juste recompressee."""
        from PIL import Image
        from flox_uploader.core.providers.image_extraction import (
            _maybe_recompress_external_image,
        )
        img = Image.new("RGB", (800, 600), color=(50, 50, 50))
        path = tmp_path / "small.jpg"
        img.save(path, "JPEG", quality=95)
        _maybe_recompress_external_image(path)
        img2 = Image.open(path)
        assert img2.width == 800  # pas de resize
        assert img2.height == 600

    def test_recompress_missing_file_noop(self, tmp_path):
        """Path inexistant -> no-op silencieux."""
        from flox_uploader.core.providers.image_extraction import (
            _maybe_recompress_external_image,
        )
        _maybe_recompress_external_image(tmp_path / "ghost.jpg")  # ne plante pas


# ============================================================
# 3. Fallback Imgur
# ============================================================

class TestImgurFallback:
    """Sprint D.42 : upload_image bascule sur Imgur quand imgbb rate-limit."""

    def _fake_response(self, status_code=200, json_data=None):
        r = MagicMock()
        r.status_code = status_code
        r.ok = status_code == 200
        r.json.return_value = json_data or {}
        r.text = json.dumps(json_data or {})
        return r

    def test_imgur_upload_success(self, tmp_path):
        """upload_to_imgur retourne success=True + host='imgur'."""
        from flox_uploader.core.providers.image_host import upload_to_imgur

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        fake_resp = self._fake_response(
            status_code=200,
            json_data={
                "success": True,
                "data": {
                    "link": "https://i.imgur.com/abc.jpg",
                    "deletehash": "xyz123",
                },
            },
        )
        result = upload_to_imgur(
            img, client_id="fake_id",
            http_post=lambda *a, **kw: fake_resp,
        )
        assert result.success is True
        assert result.url == "https://i.imgur.com/abc.jpg"
        assert result.host == "imgur"

    def test_imgur_rate_limit_detected(self, tmp_path):
        """Imgur HTTP 429 -> rate_limited=True."""
        from flox_uploader.core.providers.image_host import upload_to_imgur

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        fake_resp = self._fake_response(
            status_code=429,
            json_data={"success": False, "data": {"error": "Rate limit hit"}},
        )
        result = upload_to_imgur(
            img, client_id="fake_id",
            http_post=lambda *a, **kw: fake_resp,
        )
        assert result.success is False
        assert result.rate_limited is True

    def test_upload_image_uses_imgbb_when_available(self, tmp_path):
        """Si imgbb OK, on n'appelle PAS Imgur."""
        from flox_uploader.core.providers.image_host import upload_image

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return self._fake_response(
                status_code=200,
                json_data={
                    "success": True,
                    "data": {"url": "https://i.ibb.co/ok.jpg"},
                },
            )

        result = upload_image(
            img,
            imgbb_api_key="ibb_key",
            imgur_client_id="imgur_id",
            http_post=fake_post,
        )
        assert result.success is True
        assert result.host == "imgbb"
        # Une seule call imgbb, pas de fallback Imgur
        assert len(calls) == 1
        assert "imgbb" in calls[0]

    def test_upload_image_fallback_imgur_on_rate_limit(self, tmp_path):
        """Si imgbb rate-limit + Imgur configure -> fallback Imgur."""
        from flox_uploader.core.providers.image_host import upload_image

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            if "imgbb" in url:
                return self._fake_response(
                    status_code=400,
                    json_data={
                        "success": False,
                        "error": {"message": "Rate limit reached."},
                    },
                )
            else:
                # Imgur OK
                return self._fake_response(
                    status_code=200,
                    json_data={
                        "success": True,
                        "data": {
                            "link": "https://i.imgur.com/fallback.jpg",
                            "deletehash": "xyz",
                        },
                    },
                )

        result = upload_image(
            img,
            imgbb_api_key="ibb_key",
            imgur_client_id="imgur_id",
            http_post=fake_post,
        )
        assert result.success is True
        assert result.host == "imgur"
        assert "imgur" in result.url
        # 2 calls : imgbb (echec) puis Imgur (success)
        assert len(calls) == 2

    def test_upload_image_no_fallback_when_imgur_missing(self, tmp_path):
        """Si imgbb rate-limit MAIS Imgur pas configure -> retourne echec imgbb."""
        from flox_uploader.core.providers.image_host import upload_image

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return self._fake_response(
                status_code=400,
                json_data={
                    "success": False,
                    "error": {"message": "Rate limit reached."},
                },
            )

        result = upload_image(
            img,
            imgbb_api_key="ibb_key",
            imgur_client_id="",  # vide
            http_post=fake_post,
        )
        assert result.success is False
        assert result.rate_limited is True
        # Une seule call : imgbb. Pas de fallback Imgur.
        assert len(calls) == 1

    def test_upload_image_direct_imgur_when_no_imgbb(self, tmp_path):
        """Si imgbb absent + Imgur configure -> upload direct Imgur."""
        from flox_uploader.core.providers.image_host import upload_image

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return self._fake_response(
                status_code=200,
                json_data={
                    "success": True,
                    "data": {
                        "link": "https://i.imgur.com/direct.jpg",
                        "deletehash": "xyz",
                    },
                },
            )

        result = upload_image(
            img,
            imgbb_api_key="",  # vide
            imgur_client_id="imgur_id",
            http_post=fake_post,
        )
        assert result.success is True
        assert result.host == "imgur"
        # Une call directe Imgur
        assert len(calls) == 1
        assert "imgur" in calls[0]

    def test_upload_image_no_host_configured(self, tmp_path):
        """Aucun host configure -> echec propre."""
        from flox_uploader.core.providers.image_host import upload_image

        img = tmp_path / "fake.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
        result = upload_image(
            img,
            imgbb_api_key="",
            imgur_client_id="",
        )
        assert result.success is False
        assert "Aucun host" in result.error


# ============================================================
# 4. Config field IMGUR_CLIENT_ID present
# ============================================================

def test_config_field_imgur_client_id_present():
    """Sprint D.42 : le champ IMGUR_CLIENT_ID est expose dans /config."""
    from flox_uploader.web.config_view import SCHEMA as _CONFIG_FIELDS

    keys = {f.key for f in _CONFIG_FIELDS}
    assert "IMGUR_CLIENT_ID" in keys


def test_config_field_imgur_in_metadata_section():
    """Sprint D.42 : IMGUR_CLIENT_ID est dans la meme section que IMGBB."""
    from flox_uploader.web.config_view import SCHEMA as _CONFIG_FIELDS

    imgur_field = next(f for f in _CONFIG_FIELDS if f.key == "IMGUR_CLIENT_ID")
    assert "Metadonnees" in imgur_field.section or "TMDB" in imgur_field.section
