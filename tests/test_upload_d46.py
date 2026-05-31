"""Tests Sprint D.46 v0.5.0 — Upload .torrent shortened + log persistence.

Cible feedback Louis :
1. .torrent au nom raccourci (Windows MAX_PATH=260) introuvable par
   _torrent_path_for qui cherchait le nom exact -> fallback scan dir.
2. Upload log non visible apres redemarrage serveur (status en memoire
   perdu) -> fallback md5 deterministe sur fichier disque.
3. Section "Log d'upload" cachee si state != failed/aborted_duplicate
   -> visible si upload_log_exists, meme en state=validated.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


# ============================================================
# Fix 1 : _torrent_path_for fallback scan dir
# ============================================================

class TestTorrentPathFallback:
    """Sprint D.46 : si nom exact pas trouve, scan le dir pour .torrent."""

    def _make_package(self, root: Path, name: str, torrent_name: str | None = None) -> Path:
        """Cree un package_dir avec un .torrent eventuellement nomme differemment."""
        from flox_uploader.core.package_state import (
            PackageState, PackageStateData, write_state,
        )
        pkg = root / name
        pkg.mkdir(parents=True, exist_ok=True)
        write_state(pkg, PackageStateData(
            state=PackageState.PREPARED,
            release_name=name,
            tracker_key="gemini",
            created_at="2026-05-31T00:00:00Z",
            updated_at="2026-05-31T00:00:00Z",
        ))
        # Cree le .torrent (vide, on test juste la detection)
        torrent_filename = (torrent_name or name) + ".torrent"
        (pkg / torrent_filename).write_bytes(b"\x00" * 100)
        return pkg

    def test_exact_match(self, tmp_path):
        """Cas nominal : nom exact trouve."""
        from flox_uploader.core.upload_orchestrator import _torrent_path_for
        pkg = self._make_package(tmp_path, "Release.Name-Flox")
        path = _torrent_path_for(pkg, "Release.Name-Flox")
        assert path.is_file()
        assert path.name == "Release.Name-Flox.torrent"

    def test_shortened_match_fallback(self, tmp_path):
        """Cas Louis : .torrent shortened (MULTFF au lieu de MULTi.VFF) -> fallback."""
        from flox_uploader.core.upload_orchestrator import _torrent_path_for

        # Simule le cas Louis : release_name complet mais .torrent raccourci
        full_name = "Back.To.The.Future.Part.III.1990.MULTi.VFF.2160p.BluRay-QTZ"
        short_name = "Back.To.The.Future.Part.III.1990.MULTFF.2160p.BluRay-QTZ"
        pkg = self._make_package(tmp_path, full_name, torrent_name=short_name)

        # Le .torrent existe avec le nom raccourci -> fallback doit le trouver
        path = _torrent_path_for(pkg, full_name)
        assert path.is_file()
        assert path.name == short_name + ".torrent"

    def test_no_torrent_fails(self, tmp_path):
        """Cas vraie absence : aucun .torrent -> SystemExit avec message."""
        from flox_uploader.core.package_state import (
            PackageState, PackageStateData, write_state,
        )
        from flox_uploader.core.upload_orchestrator import _torrent_path_for
        pkg = tmp_path / "Empty.Package"
        pkg.mkdir()
        write_state(pkg, PackageStateData(
            state=PackageState.PREPARED,
            release_name="Empty.Package",
            tracker_key="gemini",
            created_at="",
            updated_at="",
        ))
        # Pas de .torrent du tout
        with pytest.raises(SystemExit):
            _torrent_path_for(pkg, "Empty.Package")

    def test_multiple_torrents_fails(self, tmp_path):
        """Cas ambigu : plusieurs .torrent + aucun match exact -> SystemExit."""
        from flox_uploader.core.upload_orchestrator import _torrent_path_for
        pkg = self._make_package(tmp_path, "Release.Name-Flox", torrent_name="A")
        (pkg / "B.torrent").write_bytes(b"\x00")
        with pytest.raises(SystemExit):
            _torrent_path_for(pkg, "Release.Name-Flox")


# ============================================================
# Fix 2 : API upload log fallback md5 deterministe
# ============================================================

class TestUploadLogFallback:
    """Sprint D.46 : si status memoire perdu (restart serveur), on
    retrouve le log via md5 deterministe."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("TRACKER_ANNOUNCE", "https://t/announce/pk")
        monkeypatch.setenv("TRACKER_API_URL", "https://t/api")
        monkeypatch.setenv("TRACKER_API_KEY", "k")
        monkeypatch.setenv("TMDB_API_KEY", "t")
        from flox_uploader import config
        config.load_env()
        from flox_uploader.web.app import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app())

    def _make_package_with_log(self, pkg_root: Path, name: str, log_content: str) -> Path:
        from flox_uploader.core.package_state import (
            PackageState, PackageStateData, write_state,
        )
        pkg = pkg_root / name
        pkg.mkdir(parents=True, exist_ok=True)
        write_state(pkg, PackageStateData(
            state=PackageState.VALIDATED,
            release_name=name,
            tracker_key="gemini",
            created_at="",
            updated_at="",
        ))
        (pkg / "release_name.txt").write_text(name + "\n")
        (pkg / "presentation.txt").write_text("[b]Test[/b]")
        (pkg / "_debug").mkdir()
        (pkg / "_debug" / "debug.json").write_text(json.dumps({
            "media_type": "movie", "tmdb_context": {},
        }))
        # Cree le log file selon le md5 deterministe
        from flox_uploader.core import jobs_db
        digest = hashlib.md5(str(pkg).encode("utf-8")).hexdigest()[:12]
        log_dir = jobs_db.jobs_log_dir()
        log_file = log_dir / f"upload_{digest}.log"
        log_file.write_text(log_content, encoding="utf-8")
        return pkg

    def test_log_endpoint_finds_log_via_md5_fallback(self, client):
        """Status pas en memoire (restart simule), mais fichier log existe sur
        disque via md5 deterministe -> on le retrouve."""
        from flox_uploader import config
        log_content = "[ERREUR] Upload echoue (exit code 1)\nFichier .torrent introuvable"
        pkg = self._make_package_with_log(
            config.packages_dir(), "Test.Log.Fallback-Flox", log_content,
        )
        # _upload_status est vide (jamais d'upload tracke en memoire ici)
        resp = client.get(f"/api/uploads/{pkg.name}/log")
        assert resp.status_code == 200
        data = resp.json()
        assert "[ERREUR] Upload echoue" in data["content"]
        assert ".torrent introuvable" in data["content"]

    def test_log_endpoint_404_when_no_log(self, client):
        """Pas de log file -> 404."""
        from flox_uploader.core.package_state import (
            PackageState, PackageStateData, write_state,
        )
        from flox_uploader import config
        pkg = config.packages_dir() / "Test.NoLog-Flox"
        pkg.mkdir(parents=True)
        write_state(pkg, PackageStateData(
            state=PackageState.PREPARED,
            release_name="Test.NoLog-Flox",
            tracker_key="gemini",
            created_at="", updated_at="",
        ))
        (pkg / "release_name.txt").write_text("Test.NoLog-Flox\n")
        (pkg / "presentation.txt").write_text("[b]X[/b]")
        (pkg / "_debug").mkdir()
        (pkg / "_debug" / "debug.json").write_text("{}")
        resp = client.get("/api/uploads/Test.NoLog-Flox/log")
        assert resp.status_code == 404


# ============================================================
# Fix 3 : Section "Log d'upload" visible si log existe
# ============================================================

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://t/announce/pk")
    monkeypatch.setenv("TRACKER_API_URL", "https://t/api")
    monkeypatch.setenv("TRACKER_API_KEY", "k")
    monkeypatch.setenv("TMDB_API_KEY", "t")
    from flox_uploader import config
    config.load_env()
    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _make_pkg_with_log(pkg_root: Path, name: str, state_value: str) -> Path:
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader.core import jobs_db
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState(state_value),
        release_name=name,
        tracker_key="gemini",
        created_at="",
        updated_at="",
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    (pkg / "presentation.txt").write_text("[b]Test[/b]")
    (pkg / "_debug").mkdir()
    (pkg / "_debug" / "debug.json").write_text(json.dumps({
        "media_type": "movie", "tmdb_context": {},
    }))
    # Cree log file
    digest = hashlib.md5(str(pkg).encode("utf-8")).hexdigest()[:12]
    log_file = jobs_db.jobs_log_dir() / f"upload_{digest}.log"
    log_file.write_text("[ERREUR] Upload echoue (exit code 1)\n")
    return pkg


def test_upload_log_section_visible_when_validated_with_log(client):
    """state=validated + log existe -> section 'Log d'upload' visible avec
    annotation 'tentative precedente'."""
    from flox_uploader import config
    _make_pkg_with_log(config.packages_dir(), "Test.Val.Log-Flox", "validated")
    resp = client.get("/packages/Test.Val.Log-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Log d'upload" in html
    assert "tentative précédente" in html or "tentative precedente" in html


def test_upload_log_section_visible_when_failed(client):
    """state=failed -> section 'Log d'upload' visible (comportement legacy)."""
    from flox_uploader import config
    _make_pkg_with_log(config.packages_dir(), "Test.Fail.Log-Flox", "failed")
    resp = client.get("/packages/Test.Fail.Log-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Log d'upload" in html
    # Pas l'annotation 'tentative precedente' (state IS failed)
    assert "tentative précédente" not in html


def test_upload_log_section_hidden_when_no_log_and_prepared(client):
    """state=prepared + pas de log -> pas de section 'Log d'upload'."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config
    pkg = config.packages_dir() / "Test.Prep.NoLog-Flox"
    pkg.mkdir(parents=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Prep.NoLog-Flox",
        tracker_key="gemini",
        created_at="", updated_at="",
    ))
    (pkg / "release_name.txt").write_text("Test.Prep.NoLog-Flox\n")
    (pkg / "presentation.txt").write_text("[b]X[/b]")
    (pkg / "_debug").mkdir()
    (pkg / "_debug" / "debug.json").write_text("{}")
    resp = client.get("/packages/Test.Prep.NoLog-Flox")
    assert resp.status_code == 200
    html = resp.text
    # On verifie qu'il n'y a PAS d'id="btn-load-upload-log" (les autres
    # 'Log d'upload' peuvent apparaitre dans les sections jobs / queue)
    assert 'id="btn-load-upload-log"' not in html
