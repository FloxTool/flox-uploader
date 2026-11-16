"""Bugfix first-run (2026-07-19) : les boutons « Tester » / « Vérifier » du
wizard /setup appellent /api/config/test-key, qui était bloqué par le
middleware first-run (503 « Aller sur /setup ») tant que la config était
incomplète — c'est-à-dire exactement au moment où on en a besoin.

Le fix ajoute /api/config/test-key aux _SETUP_BYPASS_PREFIXES.
"""
from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from flox_uploader.web.app import create_app


@pytest.fixture
def unconfigured_client(tmp_path, monkeypatch):
    """App en first-run : config VOLONTAIREMENT incomplète (pas de clés)."""
    from flox_uploader import config as _cfg
    # Neutralise le .env legacy du repo (sinon les vraies clés de Louis
    # rendraient is_setup_complete() True).
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("FLOX_DISABLE_UPDATE_CHECK", "1")
    for k in ("TRACKER_API_KEY", "TRACKER_API_URL", "TRACKER_ANNOUNCE",
              "TMDB_API_KEY", "OMDB_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)
    return TestClient(create_app())


def test_test_key_works_during_first_run(unconfigured_client):
    """Le bouton « Vérifier » (announce) doit répondre 200 en first-run,
    pas 503 « Aller sur /setup »."""
    from flox_uploader import config as _cfg
    assert _cfg.is_setup_complete() is False  # on est bien en first-run
    r = unconfigured_client.post(
        "/api/config/test-key",
        json={
            "kind": "announce",
            "announce_url": "https://gemini-tracker.org/announce/"
                            "abcdef0123456789abcdef0123456789",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_key_tmdb_reachable_during_first_run(unconfigured_client):
    """Même une clé TMDB invalide doit donner une VRAIE réponse de test
    (pas le 503 first-run). On accepte tout code sauf 503."""
    r = unconfigured_client.post(
        "/api/config/test-key",
        json={"kind": "tmdb", "api_key": "cle-bidon"},
    )
    assert r.status_code != 503


def test_action_endpoints_still_blocked_in_first_run(unconfigured_client):
    """Défense : les endpoints d'ACTION restent bien bloqués en first-run
    (on n'a pas ouvert une brèche générale)."""
    r = unconfigured_client.post("/api/queue/add", json={"paths": ["/x"]})
    assert r.status_code == 503
