"""Tests Sprint C.3 v0.5.0 : bouton "Changer de categorie" sur page detail
+ extension de l'endpoint /api/packages/<name>/reprepare avec category_id_hint.

Verifie :
1. /reprepare accepte category_id_hint et le persiste dans le nouveau job.
2. Le smoke template package_detail.html contient le bouton + modal.
3. Sans hint, le comportement reprepare reste inchange (compat v0.4.x).

Cf. PLAN-MULTICAT.md §6.3 cas 3 (override page detail) + §9 Sprint C.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client de test FastAPI avec environnement isole."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TRACKER_API_URL", "https://test.tracker/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test_key")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")

    from flox_uploader import config
    config.load_env()

    from flox_uploader.web.app import create_app
    app = create_app()
    return TestClient(app)


def _make_package_with_source(tmp_path: Path, source_file: Path):
    """Cree un package avec un job source associe (necessaire pour reprepare)."""
    from flox_uploader import config
    from flox_uploader.core import jobs_db
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )

    # Cree le package_dir
    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Test.Pkg.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.PREPARED,
        release_name="Test.Pkg.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
    )
    write_state(pkg, state)
    (pkg / "release_name.txt").write_text("Test.Pkg.2024-TEAM\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}',
        encoding="utf-8",
    )

    # Cree un job source qui pointe sur le fichier (necessaire pour reprepare)
    job = jobs_db.add_job(str(source_file))
    # Lie le job au package en mettant a jour package_dir
    jobs_db.update_job(job.id, status="done", package_dir=str(pkg))
    return pkg, job


# ============================================================
# Backend : /reprepare accepte category_id_hint
# ============================================================

def test_reprepare_accepts_category_id_hint(client, tmp_path, monkeypatch):
    """L'endpoint /api/packages/<name>/reprepare accepte category_id_hint
    et le propage au nouveau job pour que le pipeline force la cat."""
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_source = tmp_path / "source.mkv"
    fake_source.write_bytes(b"")
    pkg, source_job = _make_package_with_source(tmp_path, fake_source)

    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"category_id_hint": 7},  # Anime film
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    # Le nouveau job doit avoir category_id_hint=7
    from flox_uploader.core import jobs_db
    new_job = jobs_db.get_job(data["job_id"])
    assert new_job is not None
    assert new_job.category_id_hint == 7, (
        f"Le nouveau job doit avoir category_id_hint=7, obtenu {new_job.category_id_hint}"
    )


def test_reprepare_without_hint_keeps_zero(client, tmp_path, monkeypatch):
    """Sans hint dans le payload, le nouveau job a category_id_hint=0 (compat v0.4.x)."""
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_source = tmp_path / "source.mkv"
    fake_source.write_bytes(b"")
    pkg, source_job = _make_package_with_source(tmp_path, fake_source)

    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"force_fr": "VFF"},  # autre override, pas de cat hint
    )
    assert resp.status_code == 200
    data = resp.json()
    from flox_uploader.core import jobs_db
    new_job = jobs_db.get_job(data["job_id"])
    assert new_job.category_id_hint == 0  # comportement v0.4.x preserve
    assert new_job.force_fr == "VFF"      # autres overrides toujours respectes


def test_reprepare_invalid_hint_falls_back_to_zero(client, tmp_path, monkeypatch):
    """category_id_hint non-int -> fallback safe a 0 sans plantage."""
    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_source = tmp_path / "source.mkv"
    fake_source.write_bytes(b"")
    pkg, source_job = _make_package_with_source(tmp_path, fake_source)

    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"category_id_hint": "not-an-int"},
    )
    assert resp.status_code == 200
    data = resp.json()
    from flox_uploader.core import jobs_db
    new_job = jobs_db.get_job(data["job_id"])
    assert new_job.category_id_hint == 0


# ============================================================
# Frontend : smoke template
# ============================================================

def test_package_detail_contains_reprepare_category_selector(client, tmp_path):
    """Sprint C.3bis : le selecteur categorie est integre dans la section
    'Re-preparer le package' (plus de modal separee)."""
    fake_source = tmp_path / "source.mkv"
    fake_source.write_bytes(b"")
    pkg, _ = _make_package_with_source(tmp_path, fake_source)

    resp = client.get(f"/packages/{pkg.name}")
    assert resp.status_code == 200
    html = resp.text
    # Section renommee "Re-preparer le package" (au lieu de "Override naming")
    assert "Re-préparer le package" in html
    # Selecteur categorie integre dans la section
    assert 'id="reprepare-category"' in html
    # Le bouton "Re-préparer avec ces options" existe toujours (id inchangee)
    assert 'id="btn-reprepare"' in html
    # Sprint C.3bis : ancien bouton "Changer" du header SUPPRIME
    assert 'id="btn-change-category"' not in html
    # Sprint C.3bis : ancienne modal change-category-modal SUPPRIMEE
    assert 'id="change-category-modal"' not in html


def test_reprepare_section_hidden_for_uploaded_package(client, tmp_path):
    """Sprint C.3bis : pour un package UPLOADED, toute la section
    'Re-preparer le package' est cachee (selecteur cat inclus)."""
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config
    from flox_uploader.core import jobs_db

    fake_source = tmp_path / "uploaded.mkv"
    fake_source.write_bytes(b"")
    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Uploaded.Pkg.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.UPLOADED,
        release_name="Uploaded.Pkg.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        uploaded_torrent_id=12345,
    )
    write_state(pkg, state)
    (pkg / "release_name.txt").write_text("Uploaded.Pkg.2024-TEAM\n")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"media_type": "movie", "tmdb_context": {}}',
        encoding="utf-8",
    )
    job = jobs_db.add_job(str(fake_source))
    jobs_db.update_job(job.id, status="done", package_dir=str(pkg))

    resp = client.get(f"/packages/{pkg.name}")
    assert resp.status_code == 200
    html = resp.text
    # Section "Re-preparer le package" NE DOIT PAS apparaitre pour UPLOADED
    # (cf. template : {% if state == 'prepared' or state == 'failed' %})
    assert 'id="reprepare-category"' not in html
    assert 'id="btn-reprepare"' not in html
    # Anciens marqueurs aussi absents
    assert 'id="btn-change-category"' not in html
    assert 'id="change-category-modal"' not in html


def test_reprepare_uploaded_package_refused(client, tmp_path, monkeypatch):
    """L'endpoint /reprepare refuse 409 pour un package UPLOADED (protection
    existante v0.4.x, on s'assure que category_id_hint ne contourne pas)."""
    from flox_uploader.web import jobs_runner
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config
    from flox_uploader.core import jobs_db
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda job_id: None)

    fake_source = tmp_path / "uploaded2.mkv"
    fake_source.write_bytes(b"")
    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Already.Uploaded.2024-TEAM"
    pkg.mkdir()
    state = PackageStateData(
        state=PackageState.UPLOADED,
        release_name="Already.Uploaded.2024-TEAM",
        tracker_key="gemini",
        created_at="2026-05-23T00:00:00Z",
        updated_at="2026-05-23T00:00:00Z",
        uploaded_torrent_id=999,
    )
    write_state(pkg, state)
    job = jobs_db.add_job(str(fake_source))
    jobs_db.update_job(job.id, status="done", package_dir=str(pkg))

    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"category_id_hint": 12},  # tente de changer pour Livre
    )
    assert resp.status_code == 409, (
        f"Reprepare doit refuser un package UPLOADED meme avec category_id_hint "
        f"(obtenu code {resp.status_code} : {resp.text})"
    )
