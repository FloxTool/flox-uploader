"""Tests NOTES round 6 F1 : endpoint /api/queue/add-bundle.

Permet de packager 2+ items non-emboites (fichiers ou dossiers)
en un seul torrent. Le backend cree un dossier temp avec hardlinks
puis lance le pipeline normalement.
"""
from __future__ import annotations

from pathlib import Path

import pytest


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


def test_bundle_requires_at_least_2_paths(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    src = tmp_path / "browse" / "x.mkv"
    src.write_text("fake")
    r = client.post("/api/queue/add-bundle",
                    json={"paths": [str(src)], "bundle_name": "X"})
    assert r.status_code == 400
    assert "2 items" in r.text.lower()


def test_bundle_requires_name(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    a = tmp_path / "browse" / "a.mkv"
    b = tmp_path / "browse" / "b.mkv"
    a.write_text("a"); b.write_text("b")
    r = client.post("/api/queue/add-bundle",
                    json={"paths": [str(a), str(b)], "bundle_name": ""})
    assert r.status_code == 400
    assert "nom" in r.text.lower()


def test_bundle_rejects_name_with_spaces(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    a = tmp_path / "browse" / "a.mkv"
    b = tmp_path / "browse" / "b.mkv"
    a.write_text("a"); b.write_text("b")
    r = client.post("/api/queue/add-bundle",
                    json={"paths": [str(a), str(b)],
                          "bundle_name": "Has Spaces"})
    assert r.status_code == 400
    assert "espace" in r.text.lower()


def test_bundle_rejects_path_traversal_in_name(tmp_path, monkeypatch):
    """Refuse les noms contenant des separateurs OU '..' pour eviter
    le path traversal qui ecrirait hors de data/temp/."""
    client = _make_client(tmp_path, monkeypatch)
    a = tmp_path / "browse" / "a.mkv"
    b = tmp_path / "browse" / "b.mkv"
    a.write_text("a"); b.write_text("b")
    for bad_name in ("../escape", "x/y", "x\\y", "..hidden..z"):
        r = client.post("/api/queue/add-bundle",
                        json={"paths": [str(a), str(b)],
                              "bundle_name": bad_name})
        assert r.status_code == 400, f"Should reject {bad_name!r}"


def test_bundle_creates_temp_dir_and_returns_job_id(tmp_path, monkeypatch):
    """Cas nominal : 2 fichiers + nom valide -> bundle cree, job lance."""
    client = _make_client(tmp_path, monkeypatch)
    a = tmp_path / "browse" / "movie.mkv"
    b = tmp_path / "browse" / "movie.nfo"
    a.write_text("fake video"); b.write_text("nfo content")
    r = client.post("/api/queue/add-bundle",
                    json={"paths": [str(a), str(b)],
                          "bundle_name": "Movie.2024.MULTi.VFF.x265-TEAM"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert "job_id" in data
    assert data["items"] == 2
    # Le bundle_path doit exister + contenir les 2 items
    bundle_path = Path(data["bundle_path"])
    assert bundle_path.is_dir()
    assert (bundle_path / "movie.mkv").exists()
    assert (bundle_path / "movie.nfo").exists()


def test_bundle_with_directory_input(tmp_path, monkeypatch):
    """Bundle d'1 dossier + 1 fichier (cas type 'saison + nfo' en
    non-emboite)."""
    client = _make_client(tmp_path, monkeypatch)
    season_dir = tmp_path / "browse" / "S01"
    season_dir.mkdir()
    (season_dir / "ep01.mkv").write_text("ep1")
    (season_dir / "ep02.mkv").write_text("ep2")
    nfo = tmp_path / "browse" / "show.nfo"
    nfo.write_text("nfo")
    r = client.post("/api/queue/add-bundle",
                    json={"paths": [str(season_dir), str(nfo)],
                          "bundle_name": "Show.S01.x265-TEAM"})
    assert r.status_code == 200, r.text
    data = r.json()
    bundle_path = Path(data["bundle_path"])
    # Le dossier season est dans le bundle
    assert (bundle_path / "S01").is_dir()
    assert (bundle_path / "S01" / "ep01.mkv").exists()
    # Et le NFO orphelin aussi
    assert (bundle_path / "show.nfo").exists()
