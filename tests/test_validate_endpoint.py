"""Tests NOTES round 7+ : endpoint POST /api/packages/{name}/validate."""
from __future__ import annotations

from pathlib import Path


def _make_client(tmp_path, monkeypatch):
    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("TRACKER_API_URL", "https://test.local/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test-key")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.local/announce/x")
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb")
    (tmp_path / "browse").mkdir(exist_ok=True)
    (tmp_path / "data" / "upload_packages").mkdir(parents=True, exist_ok=True)
    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _make_pkg_with_state(tmp_path, name, state):
    """Cree un package avec un state.json minimal dans l'etat demande."""
    from flox_uploader.core.package_state import init_state, transition, PackageState
    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    # Le state initial est PREPARED par init_state. On peut transitionner
    # si on veut un autre etat de depart.
    return pkg


def test_validate_prepared_package_succeeds(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    r = client.post("/api/packages/Movie.X-TEAM/validate")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["new_state"] == "validated"


def test_validate_already_validated_returns_409(tmp_path, monkeypatch):
    from flox_uploader.core.package_state import transition, PackageState
    client = _make_client(tmp_path, monkeypatch)
    pkg = _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    transition(pkg, PackageState.VALIDATED, note="setup test")
    r = client.post("/api/packages/Movie.X-TEAM/validate")
    assert r.status_code == 409
    assert "validated" in r.text.lower()


def test_validate_uploaded_package_returns_409(tmp_path, monkeypatch):
    from flox_uploader.core.package_state import transition, PackageState
    client = _make_client(tmp_path, monkeypatch)
    pkg = _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    transition(pkg, PackageState.VALIDATED, note="step")
    transition(pkg, PackageState.UPLOADED, note="step", uploaded_torrent_id=42)
    r = client.post("/api/packages/Movie.X-TEAM/validate")
    assert r.status_code == 409


def test_validate_missing_package_returns_404(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/packages/NoSuchPkg/validate")
    assert r.status_code == 404


# ============================================================
# NOTES round 7+ : /unvalidate (rollback toggle)
# ============================================================

def test_unvalidate_validated_package_succeeds(tmp_path, monkeypatch):
    """VALIDATED -> PREPARED rollback via POST /unvalidate."""
    from flox_uploader.core.package_state import transition, PackageState
    client = _make_client(tmp_path, monkeypatch)
    pkg = _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    transition(pkg, PackageState.VALIDATED, note="setup")
    r = client.post("/api/packages/Movie.X-TEAM/unvalidate")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["new_state"] == "prepared"


def test_unvalidate_prepared_package_returns_409(tmp_path, monkeypatch):
    """Pas en validated -> 409 (rien a devalider)."""
    client = _make_client(tmp_path, monkeypatch)
    _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    r = client.post("/api/packages/Movie.X-TEAM/unvalidate")
    assert r.status_code == 409


def test_validate_unvalidate_roundtrip(tmp_path, monkeypatch):
    """Toggle complet : prepared -> validated -> prepared."""
    client = _make_client(tmp_path, monkeypatch)
    _make_pkg_with_state(tmp_path, "Movie.X-TEAM", "prepared")
    # Valide
    r1 = client.post("/api/packages/Movie.X-TEAM/validate")
    assert r1.status_code == 200
    assert r1.json()["new_state"] == "validated"
    # Devalide
    r2 = client.post("/api/packages/Movie.X-TEAM/unvalidate")
    assert r2.status_code == 200
    assert r2.json()["new_state"] == "prepared"
    # Re-valide (toggle back)
    r3 = client.post("/api/packages/Movie.X-TEAM/validate")
    assert r3.status_code == 200
    assert r3.json()["new_state"] == "validated"
