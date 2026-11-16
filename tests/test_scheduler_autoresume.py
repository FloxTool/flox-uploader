"""Bugfix (2026-07-19, remonté par Louis) : après un redémarrage, un batch de
jobs déjà en file ne reprenait pas — le scheduler ne démarrait qu'à l'AJOUT
d'un nouveau job. create_app() doit relancer le scheduler au boot s'il reste
des jobs 'pending'.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")


def _base_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    monkeypatch.setenv("FLOX_DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setenv("TRACKER_API_URL", "https://gemini.test/api")
    monkeypatch.setenv("TRACKER_API_KEY", "k")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://gemini.test/announce/pk")
    monkeypatch.setenv("TMDB_API_KEY", "t")
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)


def test_scheduler_started_when_pending_jobs_exist(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch)
    from flox_uploader.core import jobs_db
    jobs_db.add_job(file_path="/x/movie.mkv")  # 1 job pending

    called = {"n": 0}
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "_ensure_scheduler_started",
                        lambda: called.__setitem__("n", called["n"] + 1))

    from flox_uploader.web.app import create_app
    create_app()
    assert called["n"] >= 1  # le scheduler a été (re)lancé au boot


def test_scheduler_not_started_when_no_pending(tmp_path, monkeypatch):
    _base_env(tmp_path, monkeypatch)  # aucune job

    called = {"n": 0}
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "_ensure_scheduler_started",
                        lambda: called.__setitem__("n", called["n"] + 1))

    from flox_uploader.web.app import create_app
    create_app()
    assert called["n"] == 0  # rien à faire -> pas de démarrage au boot
