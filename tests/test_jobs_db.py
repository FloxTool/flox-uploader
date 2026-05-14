"""Tests pour core/jobs_db.py (persistence SQLite des jobs)."""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core import jobs_db


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Force config.data_dir() vers tmp_path pour ne pas polluer."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path))
    yield


def test_add_job_creates_pending():
    job = jobs_db.add_job("/tmp/film.mkv")
    assert job.id > 0
    assert job.file_path == "/tmp/film.mkv"
    assert job.status == "pending"
    assert job.force_fr == ""
    assert job.created_at != ""
    assert job.log_path.endswith(f"{job.id}.log")


def test_add_job_with_force_fr():
    job = jobs_db.add_job("/tmp/film.mkv", force_fr="VOF")
    assert job.force_fr == "VOF"


def test_get_job_returns_none_for_missing():
    assert jobs_db.get_job(999) is None


def test_get_job_roundtrip():
    job = jobs_db.add_job("/tmp/foo.mkv")
    fetched = jobs_db.get_job(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.file_path == "/tmp/foo.mkv"


def test_list_jobs_orders_pending_by_scheduler_order():
    """Lot F.2 : pour les jobs `pending`, list_jobs retourne l'ordre EXACT
    du scheduler (priority_order ASC). Par defaut priority_order = id, donc
    FIFO : le premier inserce passe en premier (haut de la liste).

    Avant Lot F.2, list_jobs retournait `id DESC` => incompatible avec
    le scheduler => les fleches up/down ne reordonnaient pas visuellement.
    """
    j1 = jobs_db.add_job("/tmp/1.mkv")
    j2 = jobs_db.add_job("/tmp/2.mkv")
    jobs = jobs_db.list_jobs()
    assert len(jobs) == 2
    # FIFO : j1 (insere en premier) = prochain a etre traite = haut de liste
    assert jobs[0].id == j1.id
    assert jobs[1].id == j2.id


def test_list_jobs_pending_order_follows_move_job():
    """Quand l'utilisateur clique la fleche, list_jobs DOIT refleter
    le nouvel ordre (sinon le clic semble ne rien faire)."""
    j1 = jobs_db.add_job("/tmp/1.mkv")
    j2 = jobs_db.add_job("/tmp/2.mkv")
    j3 = jobs_db.add_job("/tmp/3.mkv")
    # Ordre initial : j1, j2, j3
    assert [j.id for j in jobs_db.list_jobs()] == [j1.id, j2.id, j3.id]
    # On envoie j3 en haut
    jobs_db.move_job(j3.id, "top")
    assert [j.id for j in jobs_db.list_jobs()] == [j3.id, j1.id, j2.id]


def test_list_jobs_preparing_appears_before_pending():
    """Le job 'preparing' (en cours) doit etre AU-DESSUS des pending,
    car c'est lui qui se traite en ce moment."""
    j1 = jobs_db.add_job("/tmp/1.mkv")
    j2 = jobs_db.add_job("/tmp/2.mkv")
    jobs_db.update_job(j2.id, status="preparing")
    jobs = jobs_db.list_jobs()
    assert jobs[0].id == j2.id  # preparing en tete
    assert jobs[1].id == j1.id


def test_list_jobs_filters_by_status():
    j1 = jobs_db.add_job("/tmp/1.mkv")
    j2 = jobs_db.add_job("/tmp/2.mkv")
    jobs_db.update_job(j2.id, status="done")

    pending = jobs_db.list_jobs(statuses=["pending"])
    assert len(pending) == 1
    assert pending[0].id == j1.id

    done = jobs_db.list_jobs(statuses=["done"])
    assert len(done) == 1
    assert done[0].id == j2.id


def test_update_job_changes_fields_and_timestamp():
    job = jobs_db.add_job("/tmp/foo.mkv")
    initial_updated = job.updated_at

    import time
    time.sleep(1.01)  # > 1 sec pour avoir un timestamp different (resolution seconde)

    updated = jobs_db.update_job(
        job.id,
        status="preparing",
        package_dir="/data/packages/Foo",
        release_name="Foo.2024.1080p.x265-TEAM",
    )
    assert updated is not None
    assert updated.status == "preparing"
    assert updated.package_dir == "/data/packages/Foo"
    assert updated.release_name == "Foo.2024.1080p.x265-TEAM"
    assert updated.updated_at > initial_updated


def test_update_job_rejects_unknown_field():
    job = jobs_db.add_job("/tmp/foo.mkv")
    with pytest.raises(ValueError, match="Champs invalides"):
        jobs_db.update_job(job.id, invalid_field="x")


def test_update_job_with_no_fields_returns_current():
    job = jobs_db.add_job("/tmp/foo.mkv")
    same = jobs_db.update_job(job.id)
    assert same is not None
    assert same.id == job.id


def test_delete_job():
    job = jobs_db.add_job("/tmp/foo.mkv")
    assert jobs_db.delete_job(job.id) is True
    assert jobs_db.get_job(job.id) is None
    assert jobs_db.delete_job(job.id) is False  # already gone
