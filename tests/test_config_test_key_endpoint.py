"""Tests Sprint 2 (PLAN-V1.md) : endpoint unifie POST /api/config/test-key.

Couvre les 4 kinds : tmdb, omdb, tracker, announce + l'erreur kind inconnu.
Les anciens endpoints /api/setup/test-tmdb et /api/setup/test-tracker sont
conserves comme wrappers legacy ; on verifie qu'ils marchent toujours.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock


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


# ============================================================
# kind=tmdb
# ============================================================

def test_test_key_tmdb_valid(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="ok")
        r = client.post("/api/config/test-key", json={"kind": "tmdb", "api_key": "abc"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_key_tmdb_invalid_key_401(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=401, text="Unauthorized")
        r = client.post("/api/config/test-key", json={"kind": "tmdb", "api_key": "bad"})
    assert r.status_code == 401
    assert "invalide" in r.text.lower()


def test_test_key_tmdb_empty_400(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={"kind": "tmdb", "api_key": ""})
    assert r.status_code == 400
    assert "vide" in r.text.lower()


# ============================================================
# kind=omdb
# ============================================================

def test_test_key_omdb_valid(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Response": "True", "Title": "The Shawshank Redemption"},
        )
        r = client.post("/api/config/test-key", json={"kind": "omdb", "api_key": "abc12345"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_key_omdb_invalid_key(tmp_path, monkeypatch):
    """OMDb retourne 200 mais avec Response=False et un message d'erreur."""
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Response": "False", "Error": "Invalid API key!"},
        )
        r = client.post("/api/config/test-key", json={"kind": "omdb", "api_key": "bad"})
    assert r.status_code == 401
    assert "invalid" in r.text.lower()


def test_test_key_omdb_rate_limit(tmp_path, monkeypatch):
    """Rate limit OMDb : Response=False + 'limit reached' dans Error."""
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"Response": "False", "Error": "Request limit reached!"},
        )
        r = client.post("/api/config/test-key", json={"kind": "omdb", "api_key": "valid"})
    assert r.status_code == 401  # On traite "limit reached" comme un cas auth-like


def test_test_key_omdb_empty_400(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={"kind": "omdb", "api_key": ""})
    assert r.status_code == 400


# ============================================================
# kind=tracker
# ============================================================

def test_test_key_tracker_valid(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="ok")
        r = client.post("/api/config/test-key", json={
            "kind": "tracker",
            "api_url": "https://tracker.local/api",
            "api_key": "abc",
        })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_key_tracker_404_also_ok(tmp_path, monkeypatch):
    """Le tracker peut retourner 404 si pas de torrent id=1 mais l'auth est OK."""
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="not found")
        r = client.post("/api/config/test-key", json={
            "kind": "tracker",
            "api_url": "https://tracker.local/api",
            "api_key": "abc",
        })
    assert r.status_code == 200  # auth OK, on tolere 404


def test_test_key_tracker_invalid_key_401(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=401, text="Unauthorized")
        r = client.post("/api/config/test-key", json={
            "kind": "tracker",
            "api_url": "https://tracker.local/api",
            "api_key": "bad",
        })
    assert r.status_code == 401


def test_test_key_tracker_missing_url_400(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "tracker",
        "api_url": "",
        "api_key": "abc",
    })
    assert r.status_code == 400


# ============================================================
# kind=announce
# ============================================================

def test_test_key_announce_valid_format(tmp_path, monkeypatch):
    """URL bien formee avec /announce/<passkey>."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "announce",
        "announce_url": "https://tracker.example.com/announce/abc123def456",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "format" in body["message"].lower()


def test_test_key_announce_no_scheme(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "announce",
        "announce_url": "tracker.example.com/announce/key",
    })
    assert r.status_code == 400
    assert "scheme" in r.text.lower() or "http" in r.text.lower()


def test_test_key_announce_no_announce_in_path(tmp_path, monkeypatch):
    """URL sans /announce -> rejette."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "announce",
        "announce_url": "https://tracker.example.com/profile",
    })
    assert r.status_code == 400
    assert "announce" in r.text.lower()


def test_test_key_announce_missing_passkey(tmp_path, monkeypatch):
    """URL avec /announce mais sans segment passkey apres."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "announce",
        "announce_url": "https://tracker.example.com/announce",
    })
    assert r.status_code == 400
    assert "passkey" in r.text.lower()


def test_test_key_announce_passkey_via_query(tmp_path, monkeypatch):
    """Format alternatif : passkey en query string (rare mais existe)."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={
        "kind": "announce",
        "announce_url": "https://tracker.example.com/announce?passkey=abc123",
    })
    assert r.status_code == 200


def test_test_key_announce_empty_400(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={"kind": "announce", "announce_url": ""})
    assert r.status_code == 400


# ============================================================
# kind inconnu / payload malforme
# ============================================================

def test_test_key_unknown_kind(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={"kind": "magic", "api_key": "x"})
    assert r.status_code == 400
    assert "kind" in r.text.lower()


def test_test_key_missing_kind(tmp_path, monkeypatch):
    """Pas de kind -> 400 (kind inconnu : '')."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/config/test-key", json={"api_key": "x"})
    assert r.status_code == 400


# ============================================================
# Backward compat : anciens endpoints continuent a marcher
# ============================================================

def test_legacy_setup_test_tmdb_still_works(tmp_path, monkeypatch):
    """L'endpoint /api/setup/test-tmdb (deprecated Sprint 2) reste fonctionnel."""
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="ok")
        r = client.post("/api/setup/test-tmdb", json={"api_key": "abc"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_legacy_setup_test_tracker_still_works(tmp_path, monkeypatch):
    """L'endpoint /api/setup/test-tracker (deprecated Sprint 2) reste fonctionnel."""
    client = _make_client(tmp_path, monkeypatch)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text="ok")
        r = client.post("/api/setup/test-tracker", json={
            "api_url": "https://tracker.local/api",
            "api_key": "abc",
        })
    assert r.status_code == 200


# ============================================================
# Welcome state au 1er run
# ============================================================

def test_setup_page_shows_welcome_on_first_run(tmp_path, monkeypatch):
    """Si .env n'existe pas et aucune cle critique, on affiche le welcome hero."""
    from flox_uploader import config as _cfg
    # Pas de .env, pas de TMDB_API_KEY
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.delenv("TRACKER_API_KEY", raising=False)
    monkeypatch.delenv("TRACKER_API_URL", raising=False)
    monkeypatch.delenv("TRACKER_ANNOUNCE", raising=False)
    (tmp_path / "data").mkdir(exist_ok=True)
    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app())
    r = client.get("/setup")
    assert r.status_code == 200
    # Le welcome hero apparait avec le 👋 (premier run)
    assert "Bienvenue sur Flox Uploader" in r.text


def test_setup_page_compact_on_reconfig(tmp_path, monkeypatch):
    """Si la config est deja la, on affiche la version compacte (pas le hero
    avec emoji main qui salue)."""
    client = _make_client(tmp_path, monkeypatch)
    # On simule un .env present pour passer en mode "reconfig"
    env_file = tmp_path / "no_such.env"
    env_file.write_text("TMDB_API_KEY=test-tmdb\n", encoding="utf-8")
    r = client.get("/setup")
    assert r.status_code == 200
    # Pas le hero avec emoji
    assert "Bienvenue sur Flox Uploader 👋" not in r.text
    # Mais bien la version compacte
    assert "Configuration" in r.text
