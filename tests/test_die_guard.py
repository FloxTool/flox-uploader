"""Bugfix (2026-07-19) : un die() (sys.exit) dans un handler de requete tuait
tout le serveur. Le middleware _guard_request_systemexit doit le convertir en
500 sans faire tomber le process.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from flox_uploader.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("FLOX_DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setenv("TRACKER_API_URL", "https://gemini.test/api")
    monkeypatch.setenv("TRACKER_API_KEY", "k")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://gemini.test/announce/pk")
    monkeypatch.setenv("TMDB_API_KEY", "t")
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)
    # raise_server_exceptions=False : on veut voir la reponse 500, pas que le
    # test re-leve l'exception.
    return TestClient(create_app(), raise_server_exceptions=False)


def test_systemexit_in_handler_returns_500_not_crash(client, monkeypatch):
    # Force /api/diagnostic a faire un die() (SystemExit) comme le pipeline.
    from flox_uploader.core import diagnostic as _diag

    def _boom():
        raise SystemExit("die() simule (mediainfo manquant, etc.)")

    monkeypatch.setattr(_diag, "collect_diagnostic", _boom)
    r = client.get("/api/diagnostic")
    assert r.status_code == 500
    assert r.json()["ok"] is False
    # Le serveur est toujours vivant : une 2e requete passe normalement.
    r2 = client.get("/api/data/info")
    assert r2.status_code == 200
