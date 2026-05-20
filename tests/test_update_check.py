"""Tests Sprint 6 PLAN-V1 — auto-update v1.

Couvre :
- Parsing semver strict (accepte X.Y.Z, rejette pre-releases)
- Comparateur is_newer
- Cache disque (lecture, ecriture, JSON corrompu, atomic write)
- Fetch silent fail (timeout, 4xx, 5xx, network error)
- Refresh stale logic
- read_cached_update_info() retourne UpdateInfo coherent
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from flox_uploader.core import update_check as uc


# ============================================================================
# _parse_version + is_newer
# ============================================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.3.5", (0, 3, 5)),
        ("v0.3.5", (0, 3, 5)),
        ("V1.0.0", (1, 0, 0)),
        ("  v2.10.42  ", (2, 10, 42)),
        ("0.0.0", (0, 0, 0)),
        ("100.200.300", (100, 200, 300)),
    ],
)
def test_parse_version_valid(raw, expected):
    assert uc._parse_version(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "v",
        "0.3",                # pas 3 composants
        "0.3.5.1",            # 4 composants
        "0.3.5-rc1",          # pre-release
        "v0.4.0-beta",        # pre-release
        "0.3.5+build123",     # build metadata
        "0.3.5_dev",          # underscore
        "abc",
        "0.3.x",              # non numerique
        "-0.3.5",             # negatif (le lstrip "vV" ne mange pas le -)
        "0.-3.5",
    ],
)
def test_parse_version_rejects(raw):
    assert uc._parse_version(raw) is None


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        # Patch bumps
        ("0.3.6", "0.3.5", True),
        ("0.3.5", "0.3.5", False),  # egalite : pas de banner
        ("0.3.4", "0.3.5", False),  # downgrade : pas de banner
        # Minor bumps
        ("0.4.0", "0.3.5", True),
        ("0.4.0", "0.3.99", True),
        # Major bumps
        ("1.0.0", "0.99.99", True),
        # Prefixe v
        ("v0.4.0", "0.3.5", True),
        ("0.4.0", "v0.3.5", True),
        # Pre-releases : aucun banner (parse echec)
        ("0.4.0-rc1", "0.3.5", False),
        ("0.3.6", "0.3.5-rc1", False),
        # Strings invalides : aucun banner
        ("", "0.3.5", False),
        ("0.3.5", "", False),
        ("abc", "0.3.5", False),
    ],
)
def test_is_newer(latest, current, expected):
    assert uc.is_newer(latest, current) is expected


# ============================================================================
# Cache disque
# ============================================================================

@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isole le data dir dans tmp_path pour ne pas polluer le vrai cache."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(data))
    return data


def test_load_cache_returns_none_when_missing(isolated_data_dir):
    assert uc._load_cache() is None


def test_save_then_load_cache_roundtrip(isolated_data_dir):
    payload = {
        "checked_at_epoch": 12345.6,
        "checked_at_iso": "2026-05-15T10:00:00+00:00",
        "latest": "v0.4.0",
        "release_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
        "release_notes": "## v0.4.0\nFirst public release",
    }
    uc._save_cache(payload)
    loaded = uc._load_cache()
    assert loaded == payload


def test_load_cache_returns_none_when_json_corrupted(isolated_data_dir):
    """Cache illisible (crash mid-write) → traite comme absent."""
    cache_path = isolated_data_dir / uc.CACHE_FILENAME
    cache_path.write_text("{not valid json", encoding="utf-8")
    assert uc._load_cache() is None


def test_save_cache_is_atomic(isolated_data_dir):
    """Le write passe par un fichier .tmp puis os.replace : si on lit
    pendant l'ecriture, on ne voit jamais un fichier tronque."""
    payload = {"latest": "0.4.0", "checked_at_epoch": 1.0}
    uc._save_cache(payload)
    # Aucun .tmp orphelin
    tmps = list(isolated_data_dir.glob("*.tmp"))
    assert tmps == []
    # Le fichier final existe et est complet
    cache_path = isolated_data_dir / uc.CACHE_FILENAME
    assert json.loads(cache_path.read_text()) == payload


# ============================================================================
# _is_cache_stale
# ============================================================================

def test_is_cache_stale_when_missing(isolated_data_dir):
    assert uc._is_cache_stale() is True


def test_is_cache_stale_when_old(isolated_data_dir):
    # Timestamp d'il y a 7h (> TTL 6h)
    old_ts = time.time() - (7 * 3600)
    uc._save_cache({"latest": "v0.4.0", "checked_at_epoch": old_ts})
    assert uc._is_cache_stale() is True


def test_is_cache_fresh_when_recent(isolated_data_dir):
    # Timestamp d'il y a 1h (< TTL 6h)
    recent_ts = time.time() - 3600
    uc._save_cache({"latest": "v0.4.0", "checked_at_epoch": recent_ts})
    assert uc._is_cache_stale() is False


def test_is_cache_stale_when_epoch_missing_or_invalid(isolated_data_dir):
    uc._save_cache({"latest": "v0.4.0"})  # pas de checked_at_epoch
    assert uc._is_cache_stale() is True

    uc._save_cache({"latest": "v0.4.0", "checked_at_epoch": "not-a-number"})
    assert uc._is_cache_stale() is True


# ============================================================================
# _fetch_latest_release — silent fail
# ============================================================================

def test_fetch_returns_error_on_404():
    """Pas de release => 404 GitHub => (None, error_msg). Sprint 8 hotfix v10."""
    with patch.object(uc.requests, "get") as mock_get:
        mock_get.return_value.status_code = 404
        data, err = uc._fetch_latest_release()
        assert data is None
        assert "404" in err


def test_fetch_returns_error_on_5xx():
    with patch.object(uc.requests, "get") as mock_get:
        mock_get.return_value.status_code = 503
        data, err = uc._fetch_latest_release()
        assert data is None
        assert "503" in err


def test_fetch_returns_error_on_403_rate_limit():
    """Sprint 8 hotfix v15 : 403 + body 'rate limit' -> message specifique
    (pas juste 'HTTP 403') + heure de reset si dispo dans X-RateLimit-Reset."""
    import time as _t
    reset_epoch = int(_t.time()) + 30 * 60  # reset dans 30 min
    with patch.object(uc.requests, "get") as mock_get:
        mock_get.return_value.status_code = 403
        mock_get.return_value.json.return_value = {
            "message": "API rate limit exceeded for 1.2.3.4. (But here's the good news: ...)"
        }
        mock_get.return_value.headers = {"X-RateLimit-Reset": str(reset_epoch)}
        data, err = uc._fetch_latest_release()
        assert data is None
        # Le message doit etre explicite sur le rate limit + indiquer le temps de reset
        assert "Limite GitHub" in err or "rate" in err.lower()
        assert "min" in err  # temps de reset present


def test_fetch_403_without_rate_limit_message():
    """403 sans 'rate limit' dans le body -> message HTTP generique."""
    with patch.object(uc.requests, "get") as mock_get:
        mock_get.return_value.status_code = 403
        mock_get.return_value.json.return_value = {"message": "Forbidden"}
        mock_get.return_value.headers = {}
        data, err = uc._fetch_latest_release()
        assert data is None
        assert "403" in err


def test_fetch_returns_error_on_network_error():
    """Offline / DNS / timeout : requests raise → (None, msg explicatif),
    jamais d'exception qui remonte au caller."""
    with patch.object(uc.requests, "get", side_effect=Exception("network down")):
        data, err = uc._fetch_latest_release()
        assert data is None
        assert err  # non-vide


def test_fetch_returns_dict_on_200():
    with patch.object(uc.requests, "get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "tag_name": "v0.4.0",
            "html_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
            "body": "First release",
        }
        data, err = uc._fetch_latest_release()
        assert data is not None
        assert data["tag_name"] == "v0.4.0"
        assert err == ""


# ============================================================================
# _refresh_now + read_cached_update_info
# ============================================================================

def test_refresh_now_writes_cache_on_success(isolated_data_dir):
    with patch.object(uc, "_fetch_latest_release") as mock_fetch:
        mock_fetch.return_value = ({
            "tag_name": "v0.4.0",
            "html_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
            "body": "First public release",
        }, "")
        ok, err = uc._refresh_now()
        assert ok is True
        assert err == ""

    cache = uc._load_cache()
    assert cache is not None
    assert cache["latest"] == "v0.4.0"
    assert cache["release_url"] == "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0"
    assert cache["release_notes"] == "First public release"
    assert "checked_at_epoch" in cache
    assert "checked_at_iso" in cache


def test_refresh_now_keeps_old_cache_on_fetch_fail(isolated_data_dir):
    """Silent fail : si fetch echoue ET cache existe → on garde le cache,
    on ne le perd pas en remplacant par du vide. Error msg propage."""
    # Cache initial
    uc._save_cache({
        "checked_at_epoch": time.time() - (10 * 3600),  # stale
        "latest": "v0.4.0",
        "release_url": "https://example.com/old",
        "release_notes": "old notes",
    })
    # Fetch echoue
    with patch.object(uc, "_fetch_latest_release", return_value=(None, "GitHub down")):
        ok, err = uc._refresh_now()
        assert ok is False
        assert err == "GitHub down"

    # Cache toujours present, intact
    cache = uc._load_cache()
    assert cache is not None
    assert cache["latest"] == "v0.4.0"
    assert cache["release_url"] == "https://example.com/old"


def test_read_cached_update_info_no_cache(isolated_data_dir):
    """Pas de cache => UpdateInfo vide, available=False."""
    info = uc.read_cached_update_info()
    assert info.available is False
    assert info.latest == ""
    assert info.release_url == ""
    assert info.release_notes == ""
    assert info.fetched_at == ""
    assert info.current  # __version__ injected


def test_read_cached_update_info_with_newer_version(isolated_data_dir, monkeypatch):
    """Cache contient une version > current => available=True."""
    monkeypatch.setattr(uc, "__version__", "0.3.5")
    uc._save_cache({
        "checked_at_epoch": time.time(),
        "checked_at_iso": "2026-05-15T10:00:00+00:00",
        "latest": "v0.4.0",
        "release_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
        "release_notes": "release notes here",
    })
    info = uc.read_cached_update_info()
    assert info.available is True
    assert info.current == "0.3.5"
    assert info.latest == "v0.4.0"
    assert info.release_url == "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0"
    assert info.release_notes == "release notes here"
    assert info.fetched_at == "2026-05-15T10:00:00+00:00"


def test_read_cached_update_info_same_version_no_banner(isolated_data_dir, monkeypatch):
    """Cache contient la meme version que current => available=False."""
    monkeypatch.setattr(uc, "__version__", "0.4.0")
    uc._save_cache({
        "checked_at_epoch": time.time(),
        "latest": "v0.4.0",
    })
    info = uc.read_cached_update_info()
    assert info.available is False
    assert info.latest == "v0.4.0"


def test_read_cached_update_info_prerelease_no_banner(isolated_data_dir, monkeypatch):
    """Pre-release dans le cache (cas degenere, /releases/latest les exclut
    normalement) => parse echoue => available=False."""
    monkeypatch.setattr(uc, "__version__", "0.3.5")
    uc._save_cache({
        "checked_at_epoch": time.time(),
        "latest": "v0.4.0-rc1",
    })
    info = uc.read_cached_update_info()
    assert info.available is False


def test_read_cached_update_info_to_dict_is_json_serializable(isolated_data_dir):
    info = uc.read_cached_update_info()
    d = info.to_dict()
    # Round-trip JSON OK
    serialized = json.dumps(d)
    assert json.loads(serialized) == d
    # Cles attendues
    assert set(d.keys()) == {
        "available", "current", "latest", "release_url", "release_notes", "fetched_at"
    }
