"""Tests NOTES round 7 : endpoint /api/packages/{name}/torrent-files."""
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


def _make_package_with_torrent(data_dir, release_name, file_paths):
    """Cree un package + un .torrent qui contient `file_paths`."""
    from torf import Torrent
    pkg = data_dir / "upload_packages" / release_name
    pkg.mkdir(parents=True, exist_ok=True)
    # Cree les fichiers reels (torf en a besoin pour generer le hash)
    content_root = pkg / release_name
    content_root.mkdir(exist_ok=True)
    for rel_path in file_paths:
        f = content_root / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 512)  # contenu fictif
    t = Torrent(path=str(content_root), trackers=["http://example.com/announce"])
    t.generate()
    t.write(str(pkg / f"{release_name}.torrent"))
    # state.json minimal
    state_file = pkg / ".package_state.json"
    state_file.write_text(
        '{"state": "prepared", "release_name": "' + release_name + '"}',
        encoding="utf-8",
    )
    return pkg


def test_torrent_files_returns_404_if_no_torrent(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    pkg = tmp_path / "data" / "upload_packages" / "EmptyPkg"
    pkg.mkdir(parents=True)
    r = client.get("/api/packages/EmptyPkg/torrent-files")
    assert r.status_code == 404
    assert ".torrent introuvable" in r.text


def test_torrent_files_returns_list(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    _make_package_with_torrent(
        tmp_path / "data", "Movie.2024.x265-TEAM",
        ["movie.mkv", "movie.nfo"],
    )
    r = client.get("/api/packages/Movie.2024.x265-TEAM/torrent-files")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["root"] == "Movie.2024.x265-TEAM"
    assert data["is_multi"] is True
    assert data["total_size"] > 0
    paths = {f["path"] for f in data["files"]}
    assert any("movie.mkv" in p for p in paths)
    assert any("movie.nfo" in p for p in paths)


def test_torrent_files_single_file(tmp_path, monkeypatch):
    """Cas single-file : 1 fichier sans dossier englobant."""
    from torf import Torrent
    client = _make_client(tmp_path, monkeypatch)
    pkg = tmp_path / "data" / "upload_packages" / "Single"
    pkg.mkdir(parents=True)
    f = pkg / "single.mkv"
    f.write_bytes(b"x" * 1024)
    t = Torrent(path=str(f), trackers=["http://example.com/announce"])
    t.generate()
    t.write(str(pkg / "Single.torrent"))
    (pkg / ".package_state.json").write_text(
        '{"state": "prepared", "release_name": "Single"}',
        encoding="utf-8",
    )
    r = client.get("/api/packages/Single/torrent-files")
    assert r.status_code == 200
    data = r.json()
    assert data["is_multi"] is False
    assert len(data["files"]) == 1
