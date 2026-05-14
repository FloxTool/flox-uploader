"""Tests Lot F.2 : controle de la file de preparation (pause/move/flush)
+ priorite upload > prepare dans le scheduler.

Le scheduler thread n'est PAS teste end-to-end ici (faut un faux pipeline
qui prend du temps). On teste juste la couche DB + endpoints.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader import config
from flox_uploader.core import jobs_db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Force jobs_db a utiliser un tmp_path frais pour ce test."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(exist_ok=True)
    # jobs_db.db_path() lit data_dir() dynamiquement
    return tmp_path


# ============================================================
# Pause / Resume
# ============================================================

def test_pause_resume_pending_job(fresh_db):
    job = jobs_db.add_job(file_path="/tmp/movie.mkv", force_fr="VFF")
    assert job.is_paused is False

    # Pause
    assert jobs_db.pause_job(job.id) is True
    refreshed = jobs_db.get_job(job.id)
    assert refreshed.is_paused is True

    # Resume
    assert jobs_db.resume_job(job.id) is True
    refreshed = jobs_db.get_job(job.id)
    assert refreshed.is_paused is False


def test_pause_idempotent(fresh_db):
    """Pause sur un job deja pause = OK (pas d'erreur)."""
    job = jobs_db.add_job(file_path="/tmp/x.mkv")
    jobs_db.pause_job(job.id)
    # 2e pause : retourne True (UPDATE a touche 1 ligne meme si valeur identique)
    result = jobs_db.pause_job(job.id)
    assert result is True


def test_pause_only_pending(fresh_db):
    """Pause refuse les jobs preparing/done/failed."""
    job = jobs_db.add_job(file_path="/tmp/x.mkv")
    jobs_db.update_job(job.id, status="preparing")
    assert jobs_db.pause_job(job.id) is False
    jobs_db.update_job(job.id, status="done")
    assert jobs_db.pause_job(job.id) is False


def test_pause_unknown_job(fresh_db):
    assert jobs_db.pause_job(99999) is False


# ============================================================
# Move : up/down/top/bottom
# ============================================================

def test_move_top(fresh_db):
    """Move 'top' place le job avant tous les autres (priority_order min - 1)."""
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    j3 = jobs_db.add_job(file_path="/tmp/3.mkv")
    # Move j3 en top
    assert jobs_db.move_job(j3.id, "top") is True
    refreshed = jobs_db.get_job(j3.id)
    # Le post-fix priority_order=id (round 4) : j1=1, j2=2, j3=3 a la
    # creation. Apres move top : j3.priority_order = min(1,2) - 1 = 0.
    # On verifie juste que j3 est avant les autres dans le tri.
    others = [jobs_db.get_job(j1.id), jobs_db.get_job(j2.id)]
    assert all(refreshed.priority_order < o.priority_order for o in others)


def test_move_bottom(fresh_db):
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    j3 = jobs_db.add_job(file_path="/tmp/3.mkv")
    assert jobs_db.move_job(j1.id, "bottom") is True
    refreshed = jobs_db.get_job(j1.id)
    # j1 doit etre apres les autres dans le tri.
    others = [jobs_db.get_job(j2.id), jobs_db.get_job(j3.id)]
    assert all(refreshed.priority_order > o.priority_order for o in others)


def test_move_invalid_direction(fresh_db):
    j = jobs_db.add_job(file_path="/tmp/x.mkv")
    assert jobs_db.move_job(j.id, "sideways") is False


def test_move_alone_returns_false(fresh_db):
    """Job seul dans la file : aucun voisin a swapper."""
    j = jobs_db.add_job(file_path="/tmp/x.mkv")
    assert jobs_db.move_job(j.id, "up") is False
    assert jobs_db.move_job(j.id, "top") is False  # rien a comparer


# ============================================================
# get_next_pending_job : respect priority_order + is_paused
# ============================================================

def test_next_pending_skips_paused(fresh_db):
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    # Pause j1 -> le scheduler doit retourner j2
    jobs_db.pause_job(j1.id)
    next_job = jobs_db.get_next_pending_job()
    assert next_job is not None
    assert next_job.id == j2.id


def test_next_pending_respects_priority_order(fresh_db):
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    # j2 monte en top
    jobs_db.move_job(j2.id, "top")
    next_job = jobs_db.get_next_pending_job()
    assert next_job.id == j2.id


def test_next_pending_none_when_all_paused(fresh_db):
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    jobs_db.pause_job(j1.id)
    jobs_db.pause_job(j2.id)
    assert jobs_db.get_next_pending_job() is None


def test_next_pending_skips_preparing(fresh_db):
    """Un job preparing n'est pas pioche (il s'execute deja)."""
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    jobs_db.update_job(j1.id, status="preparing")
    next_job = jobs_db.get_next_pending_job()
    assert next_job.id == j2.id


# ============================================================
# Flush
# ============================================================

def test_flush_removes_only_pending(fresh_db):
    """flush ne touche PAS aux jobs en cours (preparing) ni done/failed."""
    j1 = jobs_db.add_job(file_path="/tmp/1.mkv")  # pending
    j2 = jobs_db.add_job(file_path="/tmp/2.mkv")
    j3 = jobs_db.add_job(file_path="/tmp/3.mkv")
    jobs_db.update_job(j2.id, status="preparing")
    jobs_db.update_job(j3.id, status="done")

    n = jobs_db.flush_pending_jobs()
    assert n == 1  # seul j1 etait pending

    assert jobs_db.get_job(j1.id) is None  # supprime
    assert jobs_db.get_job(j2.id) is not None  # toujours la (preparing)
    assert jobs_db.get_job(j3.id) is not None  # toujours la (done)


def test_flush_removes_paused(fresh_db):
    """Les jobs pauses sont aussi flushes (ils sont status='pending')."""
    j = jobs_db.add_job(file_path="/tmp/x.mkv")
    jobs_db.pause_job(j.id)
    n = jobs_db.flush_pending_jobs()
    assert n == 1
    assert jobs_db.get_job(j.id) is None


# ============================================================
# Scheduler internals (smoke test)
# ============================================================

def test_scheduler_module_imports():
    """Smoke test : le module jobs_runner s'importe sans crash apres refactor."""
    from flox_uploader.web import jobs_runner
    assert hasattr(jobs_runner, "submit_prepare_job")
    assert hasattr(jobs_runner, "submit_upload_job")
    assert hasattr(jobs_runner, "shutdown_executor")
    assert hasattr(jobs_runner, "_scheduler_loop")
    assert hasattr(jobs_runner, "_upload_queue")
