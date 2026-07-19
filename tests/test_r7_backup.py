"""R7 (audit AUDIT_2026-07-19) : backup / export des donnees.

Comble le trou « perte disque = perte passkey + historique ». Export ZIP de la
config + l'historique, sans les fichiers volumineux / regenerables.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from flox_uploader.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "upload_packages" / "Pkg1").mkdir(parents=True)
    (data / "upload_packages" / "Pkg1" / "package_state.json").write_text("{}", encoding="utf-8")
    (data / ".env").write_text("TMDB_API_KEY=secret", encoding="utf-8")
    # jobs.db est cree par l'app au boot (vrai fichier SQLite).
    # Contenu qui doit etre EXCLU :
    (data / "temp").mkdir()
    (data / "temp" / "scratch.tmp").write_text("junk", encoding="utf-8")
    (data / "jobs").mkdir()
    (data / "jobs" / "42.log").write_text("log line", encoding="utf-8")
    big = data / "upload_packages" / "Pkg1" / "cover.jpg"
    big.write_bytes(b"x" * (6 * 1024 * 1024))  # > 5 Mo -> exclu

    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(data))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("FLOX_DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setenv("TRACKER_API_URL", "https://gemini.test/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test-key")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://gemini.test/announce/pk")
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb")
    (tmp_path / "browse").mkdir()
    return TestClient(create_app())


def test_data_info(client):
    r = client.get("/api/data/info")
    assert r.status_code == 200
    j = r.json()
    assert j["package_count"] == 1
    assert j["total_bytes"] > 0
    # backup_bytes exclut le gros cover.jpg -> < total
    assert j["backup_bytes"] < j["total_bytes"]


def test_data_export_zip_contents(client):
    r = client.get("/api/data/export")
    assert r.status_code == 200
    assert "application/zip" in r.headers.get("content-type", "")
    assert "attachment" in r.headers.get("content-disposition", "")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    # Inclus : config + historique
    assert ".env" in names
    assert "upload_packages/Pkg1/package_state.json" in names
    # Exclus : temp/, logs, gros fichiers
    assert not any(n.startswith("temp/") for n in names)
    assert not any(n.endswith(".log") for n in names)
    assert not any(n.endswith("cover.jpg") for n in names)
