"""R2 (audit AUDIT_2026-07-19) : garde-fou anti DNS-rebinding.

Un site web malveillant visite par l'user peut faire pointer un domaine vers
127.0.0.1 (rebinding) et POSTer vers l'API locale (upload reel, DELETE
package...). Le header Host de la requete reboundee porte le domaine de
l'attaquant. TrustedHostMiddleware doit refuser ces requetes (400) en mode
local, tout en laissant passer localhost/127.0.0.1.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from flox_uploader.web.app import create_app


def _make_client(tmp_path: Path, monkeypatch, base_url: str) -> TestClient:
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("FLOX_DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setenv("TRACKER_API_URL", "https://gemini-tracker.test/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test-tracker-key")
    monkeypatch.setenv(
        "TRACKER_ANNOUNCE", "https://gemini-tracker.test/announce/test-passkey"
    )
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb-key")
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)
    return TestClient(create_app(), base_url=base_url)


def test_foreign_host_rejected(tmp_path, monkeypatch):
    """Un Host etranger (attaquant DNS-rebinding) est refuse (400)."""
    client = _make_client(tmp_path, monkeypatch, "http://evil.attacker.com")
    resp = client.get("/inbox")
    assert resp.status_code == 400


def test_localhost_host_allowed(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, "http://localhost:8766")
    resp = client.get("/inbox")
    assert resp.status_code == 200


def test_loopback_ip_host_allowed(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch, "http://127.0.0.1:8766")
    resp = client.get("/inbox")
    assert resp.status_code == 200


def test_insecure_host_mode_allows_any(tmp_path, monkeypatch):
    """En mode --insecure-host explicite, l'user a opte pour l'exposition."""
    monkeypatch.setenv("FLOX_UPLOADER_INSECURE_HOST", "1")
    client = _make_client(tmp_path, monkeypatch, "http://my-nas.local")
    resp = client.get("/inbox")
    assert resp.status_code == 200


# --- R2 : page d'erreur stylee (plus de JSON brut pour la navigation) ---

def test_missing_package_navigation_renders_html(tmp_path, monkeypatch):
    """Navigation navigateur vers un package inexistant -> page HTML stylee."""
    client = _make_client(tmp_path, monkeypatch, "http://localhost:8766")
    resp = client.get(
        "/packages/Does.Not.Exist-FAKE", headers={"accept": "text/html"}
    )
    assert resp.status_code == 404
    assert "text/html" in resp.headers.get("content-type", "")
    assert "introuvable" in resp.text.lower()
    # Ce n'est plus le JSON brut {"detail": ...}
    assert not resp.text.strip().startswith("{")


def test_missing_package_api_still_json(tmp_path, monkeypatch):
    """Les appels API/XHR gardent le JSON structure (le JS front en depend)."""
    client = _make_client(tmp_path, monkeypatch, "http://localhost:8766")
    resp = client.get(
        "/api/packages/Does.Not.Exist-FAKE/torrent-files",
        headers={"accept": "application/json"},
    )
    assert resp.status_code == 404
    assert "application/json" in resp.headers.get("content-type", "")
    assert "detail" in resp.json()
