"""Tests pour F1 : Cancel hard via subprocess.

On teste UNIQUEMENT la logique de cancellation cote runtime (request_job_cancel)
et l'endpoint API. La fonction `_run_prepare_job` qui spawn subprocess est
testee indirectement (mock du Popen).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.web import jobs_runner


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset les structures globales entre chaque test."""
    with jobs_runner._running_procs_lock:
        jobs_runner._running_procs.clear()
    jobs_runner._pre_launch_pkg_snapshot.clear()
    jobs_runner._cancelled_job_ids.clear()
    yield
    with jobs_runner._running_procs_lock:
        jobs_runner._running_procs.clear()
    jobs_runner._pre_launch_pkg_snapshot.clear()
    jobs_runner._cancelled_job_ids.clear()


def test_request_cancel_no_running_proc_returns_false():
    """Pas de subprocess track pour ce job_id -> False."""
    assert jobs_runner.request_job_cancel(999) is False


def test_request_cancel_kills_running_proc():
    """Si le job a un proc track, on l'appelle kill() et on marque cancelled."""
    class FakeProc:
        def __init__(self):
            self.killed = False
        def kill(self):
            self.killed = True

    fake = FakeProc()
    with jobs_runner._running_procs_lock:
        jobs_runner._running_procs[42] = fake

    ok = jobs_runner.request_job_cancel(42)
    assert ok is True
    assert fake.killed is True
    assert 42 in jobs_runner._cancelled_job_ids


def test_request_cancel_handles_already_dead_proc():
    """Si proc.kill() leve OSError (process deja mort), on ne plante pas
    et on marque quand meme cancelled (pour que le wait() suivant le
    detecte)."""
    class DeadProc:
        def kill(self):
            raise OSError("No such process")

    with jobs_runner._running_procs_lock:
        jobs_runner._running_procs[7] = DeadProc()

    ok = jobs_runner.request_job_cancel(7)
    assert ok is True
    assert 7 in jobs_runner._cancelled_job_ids


def test_snapshot_upload_packages_returns_set(monkeypatch, tmp_path):
    """Snapshot retourne les noms des dirs presents dans packages_dir."""
    fake_dir = tmp_path / "upload_packages"
    fake_dir.mkdir()
    (fake_dir / "Package.A").mkdir()
    (fake_dir / "Package.B").mkdir()
    (fake_dir / "stray.txt").touch()  # fichier, pas dir

    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "packages_dir", lambda: fake_dir)

    snap = jobs_runner._snapshot_upload_packages()
    assert snap == {"Package.A", "Package.B"}


def test_snapshot_missing_dir_returns_empty(monkeypatch, tmp_path):
    """Si le dir n'existe pas, snapshot retourne set vide."""
    nonexistent = tmp_path / "absent"
    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "packages_dir", lambda: nonexistent)
    # packages_dir() cree le dir par effet de bord — on patch pour pas creer
    snap = jobs_runner._snapshot_upload_packages()
    # Apres l'appel a packages_dir (qui cree), le dir existe mais est vide
    assert snap == set()


def test_cleanup_partial_deletes_new_dirs_only(monkeypatch, tmp_path):
    """Cleanup ne supprime QUE les dirs apparus apres le snapshot."""
    fake_dir = tmp_path / "upload_packages"
    fake_dir.mkdir()
    (fake_dir / "Existing").mkdir()
    snap = {"Existing"}
    # Cree un nouveau dir
    (fake_dir / "NewPartial").mkdir()
    (fake_dir / "NewPartial" / "data.txt").write_text("partial")

    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "packages_dir", lambda: fake_dir)

    deleted = jobs_runner._cleanup_partial_package(42, snap)
    assert deleted == "NewPartial"
    # Le dir existant n'a pas ete touche
    assert (fake_dir / "Existing").exists()
    # Le partial a bien ete supprime
    assert not (fake_dir / "NewPartial").exists()


def test_cleanup_no_new_dirs_returns_none(monkeypatch, tmp_path):
    """Cleanup quand rien de nouveau -> None et pas d'erreur."""
    fake_dir = tmp_path / "upload_packages"
    fake_dir.mkdir()
    (fake_dir / "Existing").mkdir()
    snap = {"Existing"}

    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "packages_dir", lambda: fake_dir)

    deleted = jobs_runner._cleanup_partial_package(42, snap)
    assert deleted is None


# ============================================================
# Endpoint API : POST /api/jobs/{id}/cancel
# ============================================================

def _make_client(tmp_path, monkeypatch):
    """Cree un TestClient configure : data_dir tmp + vars de config bidons
    pour court-circuiter le middleware first-run."""
    from flox_uploader import config as _cfg
    monkeypatch.setattr(
        _cfg, "env_file", lambda: tmp_path / "no_such.env",
    )
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


def test_api_cancel_404_if_job_unknown(tmp_path, monkeypatch):
    """Job inexistant -> 404."""
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/jobs/99999/cancel")
    assert r.status_code == 404


def test_api_cancel_400_if_job_not_preparing(tmp_path, monkeypatch):
    """Job en status 'pending' (pas en cours) -> 400."""
    client = _make_client(tmp_path, monkeypatch)
    from flox_uploader.core import jobs_db
    j = jobs_db.add_job("/tmp/x.mkv")
    # Reste en pending par defaut
    r = client.post(f"/api/jobs/{j.id}/cancel")
    assert r.status_code == 400
    assert "pas en cours" in r.text.lower()


def test_api_cancel_500_if_subprocess_lost(tmp_path, monkeypatch):
    """Status DB = preparing mais le scheduler ne track aucun subprocess :
    etat incoherent (crash du worker, restart serveur, etc.) -> 500.

    On remet le status preparing APRES le startup parce que
    `_reconcile_stuck_jobs()` demote les 'preparing' orphelins au
    startup."""
    client = _make_client(tmp_path, monkeypatch)
    from flox_uploader.core import jobs_db
    j = jobs_db.add_job("/tmp/x.mkv")
    jobs_db.update_job(j.id, status="preparing")
    r = client.post(f"/api/jobs/{j.id}/cancel")
    assert r.status_code == 500
    assert "incoherent" in r.text.lower()
