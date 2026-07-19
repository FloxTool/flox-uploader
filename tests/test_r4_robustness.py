"""R4 (audit AUDIT_2026-07-19) : robustesse batch/multi-process.

- claim_next_pending_job : reservation atomique (pas de double-claim).
- WAL + busy_timeout sur la connexion SQLite.
- verrou single-instance par data dir (fichier OS auto-libere).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest


@pytest.fixture
def jobsdb(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader.core import jobs_db
    return jobs_db


def test_claim_returns_distinct_jobs(jobsdb):
    for i in range(3):
        jobsdb.add_job(file_path=f"/x/f{i}.mkv")
    got = [jobsdb.claim_next_pending_job() for _ in range(4)]
    ids = [c.id for c in got if c]
    assert got[3] is None
    assert len(set(ids)) == 3          # 3 jobs distincts
    assert all(c.status == "preparing" for c in got if c)


def test_concurrent_claims_never_double(jobsdb):
    """Sous concurrence de threads, aucun job n'est reserve deux fois."""
    N = 20
    for i in range(N):
        jobsdb.add_job(file_path=f"/x/f{i}.mkv")
    claimed_ids = []
    lock = threading.Lock()

    def worker():
        while True:
            job = jobsdb.claim_next_pending_job()
            if job is None:
                return
            with lock:
                claimed_ids.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed_ids) == N                 # tous reserves
    assert len(set(claimed_ids)) == N            # aucun doublon


def test_wal_mode_enabled(jobsdb):
    jobsdb.add_job(file_path="/x/a.mkv")
    con = sqlite3.connect(jobsdb.db_path())
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert mode.lower() == "wal"


# --- Verrou single-instance ---

def test_instance_lock_acquire_and_release(tmp_path):
    from flox_uploader.core.instance_lock import (
        acquire_single_instance_lock,
        release_single_instance_lock,
    )
    d = tmp_path / "data"
    assert acquire_single_instance_lock(d) is True
    # deja acquis par ce process -> re-acquire renvoie True (idempotent)
    assert acquire_single_instance_lock(d) is True
    release_single_instance_lock()
    # apres release, on peut re-acquerir
    assert acquire_single_instance_lock(d) is True
    release_single_instance_lock()


def test_instance_lock_is_a_real_os_lock(tmp_path):
    """Un 2e handle brut sur la meme region doit etre bloque."""
    from flox_uploader.core.instance_lock import (
        acquire_single_instance_lock,
        release_single_instance_lock,
        _LOCK_NAME,
    )
    d = tmp_path / "data"
    assert acquire_single_instance_lock(d) is True
    fh2 = open(d / _LOCK_NAME, "a+", encoding="utf-8")
    blocked = False
    try:
        if os.name == "nt":
            import msvcrt
            fh2.seek(0)
            msvcrt.locking(fh2.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh2.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        blocked = True
    finally:
        fh2.close()
    release_single_instance_lock()
    assert blocked is True


# --- Timeout MediaInfo (protege le worker mono-thread) ---

def test_generate_nfo_dies_on_mediainfo_timeout(tmp_path, monkeypatch):
    """Un MediaInfo qui bloque -> TimeoutExpired -> die() (SystemExit), pas de hang."""
    import subprocess
    from flox_uploader.core import nfo

    video = tmp_path / "movie.mkv"
    video.write_bytes(b"fake")

    def _fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="mediainfo", timeout=k.get("timeout", 1))

    monkeypatch.setattr(nfo.subprocess, "run", _fake_run)
    with pytest.raises(SystemExit):
        nfo.generate_nfo(video, tmp_path / "out.nfo")


def test_generate_nfo_passes_timeout_kwarg(tmp_path, monkeypatch):
    """generate_nfo passe bien un timeout= a subprocess.run."""
    import subprocess
    from flox_uploader.core import nfo

    video = tmp_path / "movie.mkv"
    video.write_bytes(b"fake")
    captured = {}

    class _R:
        returncode = 0
        stdout = "General\nFormat : Matroska"
        stderr = ""

    def _fake_run(*a, **k):
        captured["timeout"] = k.get("timeout")
        return _R()

    monkeypatch.setattr(nfo.subprocess, "run", _fake_run)
    nfo.generate_nfo(video, tmp_path / "out.nfo")
    assert captured["timeout"] == nfo.MEDIAINFO_TIMEOUT_S
    assert captured["timeout"] > 0
