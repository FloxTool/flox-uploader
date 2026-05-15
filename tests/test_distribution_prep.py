"""Tests Sprint 4 (PLAN-V1.md) : préparation distribution.

Couvre :
1. Détection legacy data (dev mode vs packaged mode)
2. Stats descriptives du legacy
3. Migration douce (dry_run + réel, non-destructive, skip overwrite)
4. Endpoints HTTP /api/data-dir/legacy-status + /migrate
5. Protocol TrackerClient — GeminiClient le satisfait structurellement
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


# ============================================================
# 1. Détection legacy_data_dir()
# ============================================================

def test_legacy_data_returns_none_in_dev_mode(tmp_path, monkeypatch):
    """En mode dev (_is_dev_install True), on n'a JAMAIS de legacy à migrer
    parce qu'on UTILISE <repo>/data/ comme data_dir."""
    from flox_uploader import config
    # On force le mode dev (par défaut c'est dev de toute façon)
    monkeypatch.setattr(config, "_is_dev_install", lambda: True)
    assert config.legacy_data_dir() is None


def test_legacy_data_returns_none_when_no_legacy_dir(tmp_path, monkeypatch):
    """Mode packagé mais pas de <repo>/data/ → rien à migrer."""
    from flox_uploader import config
    monkeypatch.setattr(config, "_is_dev_install", lambda: False)
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", fake_root)
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data_target"))
    assert config.legacy_data_dir() is None


def test_legacy_data_returns_none_when_legacy_empty(tmp_path, monkeypatch):
    """<repo>/data/ existe mais vide → pas de legacy utile."""
    from flox_uploader import config
    monkeypatch.setattr(config, "_is_dev_install", lambda: False)
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    (fake_root / "data" / "upload_packages").mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", fake_root)
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data_target"))
    assert config.legacy_data_dir() is None


def test_legacy_data_detects_when_packages_present(tmp_path, monkeypatch):
    """Mode packagé + <repo>/data/upload_packages/ avec des packages
    + data_dir() pointe ailleurs → legacy detectee."""
    from flox_uploader import config
    monkeypatch.setattr(config, "_is_dev_install", lambda: False)
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    legacy_packages = fake_root / "data" / "upload_packages"
    legacy_packages.mkdir(parents=True)
    (legacy_packages / "Movie.X-TEAM").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", fake_root)
    # data_dir doit pointer ailleurs que <fake_root>/data
    target_dir = tmp_path / "data_target"
    target_dir.mkdir()
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(target_dir))

    detected = config.legacy_data_dir()
    assert detected is not None
    assert detected.resolve() == (fake_root / "data").resolve()


def test_legacy_data_returns_none_when_legacy_equals_target(tmp_path, monkeypatch):
    """Edge case : si data_dir() pointe sur <repo>/data/, c'est la meme
    chose, pas un legacy."""
    from flox_uploader import config
    monkeypatch.setattr(config, "_is_dev_install", lambda: False)
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    legacy_packages = fake_root / "data" / "upload_packages"
    legacy_packages.mkdir(parents=True)
    (legacy_packages / "Movie.X-TEAM").mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", fake_root)
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(fake_root / "data"))
    assert config.legacy_data_dir() is None


# ============================================================
# 2. Stats descriptives
# ============================================================

def test_legacy_data_stats_counts_and_sizes(tmp_path):
    from flox_uploader.config import legacy_data_stats
    legacy = tmp_path / "data"
    upload = legacy / "upload_packages"
    upload.mkdir(parents=True)
    # 3 packages, dont 2 avec contenu
    (upload / "Foo.2020-TEAM").mkdir()
    (upload / "Foo.2020-TEAM" / "Foo.2020-TEAM.mkv").write_bytes(b"\x00" * 1024)
    (upload / "Bar.2021-TEAM").mkdir()
    (upload / "Bar.2021-TEAM" / "Bar.2021-TEAM.mkv").write_bytes(b"\x00" * 2048)
    (upload / "Baz.2022-TEAM").mkdir()
    # Fichiers a la racine
    (legacy / ".env").write_text("X=1", encoding="utf-8")
    (legacy / "jobs.db").write_bytes(b"sqlite\x00fake")
    # tmdb cache : non present

    stats = legacy_data_stats(legacy)
    assert stats["package_count"] == 3
    assert stats["total_size_bytes"] >= 1024 + 2048
    assert stats["has_env"] is True
    assert stats["has_jobs_db"] is True
    assert stats["has_tmdb_cache"] is False


# ============================================================
# 3. Migration non-destructive
# ============================================================

def test_migrate_legacy_data_dry_run_does_not_touch_files(tmp_path, monkeypatch):
    from flox_uploader.config import migrate_legacy_data
    legacy = tmp_path / "data_legacy"
    target = tmp_path / "data_target"
    (legacy / "upload_packages").mkdir(parents=True)
    (legacy / "upload_packages" / "PkgA").mkdir()
    (legacy / "upload_packages" / "PkgA" / "a.mkv").write_bytes(b"x")
    (legacy / "jobs.db").write_bytes(b"db")

    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(target))
    result = migrate_legacy_data(legacy, dry_run=True)

    assert result["copied_packages"] == 1
    assert "jobs.db" in result["copied_files"]
    # Rien n'a ete copie en vrai
    assert not (target / "upload_packages" / "PkgA").exists()
    assert not (target / "jobs.db").exists()


def test_migrate_legacy_data_real_copy(tmp_path, monkeypatch):
    from flox_uploader.config import migrate_legacy_data
    legacy = tmp_path / "data_legacy"
    target = tmp_path / "data_target"
    (legacy / "upload_packages").mkdir(parents=True)
    (legacy / "upload_packages" / "PkgA").mkdir()
    (legacy / "upload_packages" / "PkgA" / "a.mkv").write_bytes(b"hello")
    (legacy / "jobs.db").write_bytes(b"db-content")

    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(target))
    result = migrate_legacy_data(legacy, dry_run=False)

    assert result["copied_packages"] == 1
    assert "jobs.db" in result["copied_files"]
    assert (target / "upload_packages" / "PkgA" / "a.mkv").read_bytes() == b"hello"
    assert (target / "jobs.db").read_bytes() == b"db-content"
    # Le legacy reste intact (non-destructive)
    assert (legacy / "upload_packages" / "PkgA" / "a.mkv").exists()
    assert (legacy / "jobs.db").exists()


def test_migrate_skip_packages_already_present(tmp_path, monkeypatch):
    """Si un package existe deja dans target, on le skip (pas d'ecrasement)."""
    from flox_uploader.config import migrate_legacy_data
    legacy = tmp_path / "data_legacy"
    target = tmp_path / "data_target"
    # Source
    (legacy / "upload_packages" / "PkgA").mkdir(parents=True)
    (legacy / "upload_packages" / "PkgA" / "src.mkv").write_bytes(b"NEW")
    # Target deja peuple
    (target / "upload_packages" / "PkgA").mkdir(parents=True)
    (target / "upload_packages" / "PkgA" / "existing.mkv").write_bytes(b"OLD")

    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(target))
    result = migrate_legacy_data(legacy, dry_run=False)

    assert result["copied_packages"] == 0
    assert result["skipped_packages"] == 1
    # Le contenu existant n'a pas ete touche
    assert (target / "upload_packages" / "PkgA" / "existing.mkv").read_bytes() == b"OLD"
    assert not (target / "upload_packages" / "PkgA" / "src.mkv").exists()


def test_migrate_skip_files_already_present(tmp_path, monkeypatch):
    """Si .env existe deja dans target, on ne l'ecrase pas avec celui de legacy."""
    from flox_uploader.config import migrate_legacy_data
    legacy = tmp_path / "data_legacy"
    target = tmp_path / "data_target"
    (legacy / "upload_packages").mkdir(parents=True)
    (legacy / ".env").write_text("X=NEW", encoding="utf-8")
    target.mkdir()
    (target / ".env").write_text("X=OLD", encoding="utf-8")

    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(target))
    result = migrate_legacy_data(legacy, dry_run=False)

    assert ".env" not in result["copied_files"]
    assert (target / ".env").read_text() == "X=OLD"


# ============================================================
# 4. Endpoints HTTP
# ============================================================

def _make_client(tmp_path, monkeypatch):
    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data_target"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("TRACKER_API_URL", "https://test.local/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test-key")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.local/announce/x")
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb")
    (tmp_path / "browse").mkdir(exist_ok=True)
    (tmp_path / "data_target" / "upload_packages").mkdir(parents=True, exist_ok=True)
    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_endpoint_legacy_status_returns_available_false_in_dev(tmp_path, monkeypatch):
    """Mode dev : pas de legacy."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.get("/api/data-dir/legacy-status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["legacy_path"] == ""


def test_endpoint_legacy_status_when_packaged_with_legacy(tmp_path, monkeypatch):
    """Mode packagé simulé avec legacy."""
    from flox_uploader import config as _cfg
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    legacy_packages = fake_root / "data" / "upload_packages"
    legacy_packages.mkdir(parents=True)
    (legacy_packages / "Movie.X-TEAM").mkdir()
    (legacy_packages / "Movie.X-TEAM" / "a.mkv").write_bytes(b"x")

    monkeypatch.setattr(_cfg, "PROJECT_ROOT", fake_root)
    monkeypatch.setattr(_cfg, "_is_dev_install", lambda: False)
    client = _make_client(tmp_path, monkeypatch)

    r = client.get("/api/data-dir/legacy-status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert "fake_repo" in body["legacy_path"]
    assert body["stats"]["package_count"] == 1


def test_endpoint_migrate_dry_run(tmp_path, monkeypatch):
    """Dry run : retourne ce qu'on copierait mais ne copie pas."""
    from flox_uploader import config as _cfg
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    legacy_packages = fake_root / "data" / "upload_packages"
    legacy_packages.mkdir(parents=True)
    (legacy_packages / "Movie.X-TEAM").mkdir()
    (legacy_packages / "Movie.X-TEAM" / "a.mkv").write_bytes(b"x")

    monkeypatch.setattr(_cfg, "PROJECT_ROOT", fake_root)
    monkeypatch.setattr(_cfg, "_is_dev_install", lambda: False)
    client = _make_client(tmp_path, monkeypatch)

    r = client.post("/api/data-dir/migrate", json={"dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["copied_packages"] == 1
    # Rien n'a vraiment ete copie
    target = tmp_path / "data_target" / "upload_packages" / "Movie.X-TEAM"
    assert not target.exists()


def test_endpoint_migrate_returns_404_when_no_legacy(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/data-dir/migrate", json={"dry_run": False})
    assert r.status_code == 404


# ============================================================
# 5. Protocol TrackerClient
# ============================================================

def test_gemini_client_satisfies_tracker_client_protocol():
    """GeminiClient doit etre considere comme un TrackerClient grace au
    duck typing renforce par runtime_checkable."""
    from flox_uploader.trackers.base import TrackerClient
    from flox_uploader.core.gemini_api import GeminiClient
    # On a besoin d'une instance pour isinstance() avec un Protocol
    # runtime_checkable. Pas besoin d'init reseau, juste verifier la forme.
    client = GeminiClient(api_url="https://x.local/api", api_key="abc")
    assert isinstance(client, TrackerClient)


def test_tracker_client_protocol_rejects_random_class():
    """Une classe sans les methodes requises ne doit PAS etre un TrackerClient."""
    from flox_uploader.trackers.base import TrackerClient

    class NotATracker:
        def some_other_method(self):
            pass

    assert not isinstance(NotATracker(), TrackerClient)
