"""Tests Sprint D.13 v0.5.0 — bulk-reprepare endpoint pour reanalyser
les packages existants apres une evolution majeure de l'extracteur.

Verifie :
1. /api/packages/bulk-reprepare filtre par category_id correctement.
2. Skip les packages uploades sauf si include_uploaded=true.
3. Skip les packages legacy sans job source.
4. dry_run=true ne supprime rien et ne lance pas de jobs.
5. Le mode normal relance les jobs avec preservation des overrides.
6. category_id manquant ou invalide -> 400.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")

    from flox_uploader import config
    config.load_env()

    from flox_uploader.web.app import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def _make_pkg_with_job(
    tmp_path: Path,
    name: str,
    cat: int,
    state: str = "prepared",
    has_source: bool = True,
) -> Path:
    """Helper : cree un package + un job source associe."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader.core import jobs_db
    from flox_uploader import config

    pkg_root = config.packages_dir()
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState(state),
        release_name=name,
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=cat,
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}', encoding="utf-8",
    )

    if has_source:
        source = tmp_path / f"{name}_source"
        source.write_bytes(b"fake")
        job = jobs_db.add_job(str(source))
        jobs_db.update_job(
            job.id, package_dir=str(pkg),
            release_name=name, status="done",
        )
    return pkg


def test_bulk_reprepare_requires_category_id(client, tmp_path):
    """Body sans category_id -> 400."""
    resp = client.post("/api/packages/bulk-reprepare", json={})
    assert resp.status_code == 400


def test_bulk_reprepare_invalid_category_id(client, tmp_path):
    """category_id=0 ou negatif -> 400."""
    resp = client.post("/api/packages/bulk-reprepare", json={"category_id": 0})
    assert resp.status_code == 400


def test_bulk_reprepare_empty_packages_dir(client, tmp_path):
    """Aucun package -> scanned=0, ok."""
    resp = client.post(
        "/api/packages/bulk-reprepare", json={"category_id": 12},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanned"] == 0
    assert data["matching"] == 0


def test_bulk_reprepare_filters_by_category(client, tmp_path, monkeypatch):
    """Seuls les packages de la cat ciblee sont relances."""
    _make_pkg_with_job(tmp_path, "Book.A-Flox", cat=12)
    _make_pkg_with_job(tmp_path, "Book.B-Flox", cat=12)
    _make_pkg_with_job(tmp_path, "Movie.A-TEAM", cat=1)

    # Mock submit_prepare_job pour ne pas lancer le subprocess
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: None)

    resp = client.post("/api/packages/bulk-reprepare", json={"category_id": 12})
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanned"] == 3
    assert data["matching"] == 2  # 2 livres
    assert len(data["relaunched"]) == 2
    relaunched_names = {r["name"] for r in data["relaunched"]}
    assert "Book.A-Flox" in relaunched_names
    assert "Book.B-Flox" in relaunched_names
    assert "Movie.A-TEAM" not in relaunched_names


def test_bulk_reprepare_skips_uploaded_by_default(client, tmp_path, monkeypatch):
    """Les packages uploades sont skip par defaut."""
    _make_pkg_with_job(tmp_path, "Book.New-Flox", cat=12, state="prepared")
    _make_pkg_with_job(tmp_path, "Book.Done-Flox", cat=12, state="uploaded")

    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: None)

    resp = client.post("/api/packages/bulk-reprepare", json={"category_id": 12})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matching"] == 2
    assert data["skipped_uploaded"] == 1
    assert len(data["relaunched"]) == 1


def test_bulk_reprepare_include_uploaded(client, tmp_path, monkeypatch):
    """include_uploaded=True relance aussi les uploades."""
    _make_pkg_with_job(tmp_path, "Book.Done-Flox", cat=12, state="uploaded")

    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: None)

    resp = client.post(
        "/api/packages/bulk-reprepare",
        json={"category_id": 12, "include_uploaded": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_uploaded"] == 0
    assert len(data["relaunched"]) == 1


def test_bulk_reprepare_skips_legacy_no_source(client, tmp_path):
    """Package legacy (pas de job source) -> skip + reason."""
    _make_pkg_with_job(tmp_path, "Legacy-Flox", cat=12, has_source=False)

    resp = client.post("/api/packages/bulk-reprepare", json={"category_id": 12})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matching"] == 1
    assert data["skipped_no_source"] == 1
    assert len(data["relaunched"]) == 0
    # Verifier la reason dans skipped_other
    assert any(
        "legacy" in s["reason"].lower() or "pas de job" in s["reason"].lower()
        for s in data["skipped_other"]
    )


def test_bulk_reprepare_dry_run(client, tmp_path, monkeypatch):
    """dry_run=True : retourne ce qui SERAIT fait, ne supprime rien."""
    pkg = _make_pkg_with_job(tmp_path, "Dry.Run.Book-Flox", cat=12)

    submit_calls = []
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: submit_calls.append(jid))

    resp = client.post(
        "/api/packages/bulk-reprepare",
        json={"category_id": 12, "dry_run": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert len(data["relaunched"]) == 1
    # Pas de job lance
    assert submit_calls == []
    # Le package existe TOUJOURS (pas de rmtree en dry-run)
    assert pkg.is_dir()
