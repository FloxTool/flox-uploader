"""Tests Sprint D.11 v0.5.0 — Conformite naming Gemini + Date + placeholders + taille torrent.

Verifie :
1. Panneau warning 'Format de release Gemini incomplet' affiche pour livres
   incomplets (Auteur/Titre/Date/Langue/Format manquants).
2. Pas de warning pour un livre complet.
3. Champ Annee dans Re-preparer livre present.
4. Placeholders 'exemple: ...' presents dans les inputs livre.
5. Taille torrent calculee depuis le .torrent pour les packages livre.
6. Backend chain : jobs_db persiste manual_book_year.
7. Re-prepare propage manual_book_year vers le pipeline.
"""
from __future__ import annotations

import json
import zipfile
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


def _make_book_pkg(pkg_root: Path, name: str, book_meta: dict) -> Path:
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    pkg = pkg_root / name
    pkg.mkdir(parents=True, exist_ok=True)
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name=name,
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
        manual_category_id=12,
    ))
    (pkg / "release_name.txt").write_text(name + "\n")
    (pkg / "presentation.txt").write_text("[b]Test[/b]", encoding="utf-8")
    debug = pkg / "_debug"
    debug.mkdir()
    (debug / "debug.json").write_text(json.dumps({
        "media_type": "movie",
        "tmdb_context": {},
        "book_metadata": book_meta,
    }), encoding="utf-8")
    return pkg


# ============================================================
# Panneau Conformite naming Gemini
# ============================================================

def test_warning_gemini_format_incomplete(client, tmp_path):
    """Livre sans auteur/titre/date/langue/format -> warning dur."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Incomplete.Gemini-Flox", book_meta={
        # AUCUN des 5 champs obligatoires
        "isbn_13": "9782266154116",  # juste l'ISBN
        "description": "",
        "cover_url": "",
    })

    resp = client.get("/packages/Incomplete.Gemini-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Format de release Gemini incomplet" in html
    # Doit lister les champs manquants
    assert "Auteur" in html
    assert "Titre" in html
    assert "Date" in html
    assert "Langue" in html
    assert "Format" in html
    # Mentionne le format Gemini officiel
    assert "Auteur.Titre.Date.Langue.Format" in html


def test_warning_gemini_format_complete_no_warning(client, tmp_path):
    """Livre avec tous les champs -> pas de warning Gemini."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Complete.Gemini-Flox", book_meta={
        "title": "Le Hobbit",
        "authors": ["Tolkien"],
        "publication_year": 1937,
        "language": "fr",
        "file_format": "epub",
        "isbn_13": "9782266154116",
        "description": "Resume",
        "cover_url": "x",
    })

    resp = client.get("/packages/Complete.Gemini-Flox")
    assert resp.status_code == 200
    assert "Format de release Gemini incomplet" not in resp.text


def test_warning_gemini_only_some_fields_missing(client, tmp_path):
    """Seule la langue manque -> warning ciblé."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "OnlyLang.Missing-Flox", book_meta={
        "title": "Titre",
        "authors": ["Author"],
        "publication_year": 2024,
        "language": "",  # manquant
        "file_format": "epub",
        "isbn_13": "9782266154116",
        "description": "R",
        "cover_url": "x",
    })

    resp = client.get("/packages/OnlyLang.Missing-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert "Format de release Gemini incomplet" in html
    assert "Langue" in html


# ============================================================
# Champ Annee + placeholders dans Re-preparer
# ============================================================

def test_repreparer_has_year_field(client, tmp_path):
    """La section Re-preparer livre contient un input manual_book_year."""
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Test.Year.Field-Flox", book_meta={
        "title": "T", "authors": ["A"], "publication_year": 1999,
        "language": "fr", "file_format": "epub",
    })

    resp = client.get("/packages/Test.Year.Field-Flox")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="manual_book_year"' in html
    # Doit etre prerempli avec 1999
    assert 'value="1999"' in html


def test_repreparer_has_example_placeholders(client, tmp_path):
    """Sprint D.11 + D.40 : placeholders sur les inputs livre.

    Sprint D.40 (feedback Louis) : on a allege les placeholders en retirant
    le prefixe 'exemple : ' pour des inputs plus propres. On teste donc
    juste la presence des exemples canoniques.
    """
    from flox_uploader import config
    pkg_root = config.packages_dir()
    _make_book_pkg(pkg_root, "Test.Placeholders-Flox", book_meta={
        "title": "", "authors": [], "file_format": "epub",
    })

    resp = client.get("/packages/Test.Placeholders-Flox")
    assert resp.status_code == 200
    html = resp.text
    # Exemples canoniques presents dans placeholders ou aide.
    assert "9782266154116" in html
    assert "J.R.R. Tolkien" in html
    assert "Le Seigneur des Anneaux" in html
    assert "1999" in html


# ============================================================
# Taille torrent depuis le .torrent pour les livres
# ============================================================

def test_size_from_torrent_for_book(client, tmp_path):
    """Sprint D.11 : un livre sans mediainfo_data doit avoir size_pretty
    rempli depuis la lecture du .torrent."""
    from flox_uploader import config
    pkg_root = config.packages_dir()

    # Crée un EPUB factice puis un .torrent qui le wrap
    source = tmp_path / "source.epub"
    source.write_bytes(b"x" * 1024 * 50)  # 50 KB

    pkg = _make_book_pkg(pkg_root, "Test.Size.Torrent-Flox", book_meta={
        "title": "T", "authors": ["A"], "publication_year": 2024,
        "language": "fr", "file_format": "epub",
    })

    # Genere un vrai .torrent dans le package
    from torf import Torrent
    t = Torrent(
        path=source,
        trackers=["https://test.tracker/announce/x"],
    )
    t.generate()
    torrent_path = pkg / "Test.Size.Torrent-Flox.torrent"
    t.write(str(torrent_path))

    resp = client.get("/packages/Test.Size.Torrent-Flox")
    assert resp.status_code == 200
    html = resp.text
    # On doit voir une taille (Ko ou Mo). 50 KB -> "50 Ko"
    assert "Ko" in html or "Mo" in html
    # Le placeholder '—' qui signifie "vide" ne doit pas etre dans la
    # ligne Taille de la carte Fichier (Sprint D.10).
    # Note : '—' peut apparaitre ailleurs (durée, container), on cherche
    # le contexte 'Taille [—]'
    import re
    assert not re.search(r'Taille[^a-z]{1,30}—', html)


# ============================================================
# Backend chain : jobs_db + reprepare
# ============================================================

def test_jobs_db_persists_manual_book_year(tmp_path, monkeypatch):
    """jobs_db.add_job accepte manual_book_year et le persiste."""
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    from flox_uploader import config
    config.load_env()

    from flox_uploader.core import jobs_db
    job = jobs_db.add_job("C:/test/book.pdf", manual_book_year=1999)
    assert job.manual_book_year == 1999

    reloaded = jobs_db.get_job(job.id)
    assert reloaded.manual_book_year == 1999


def test_reprepare_propagates_manual_book_year(client, tmp_path, monkeypatch):
    """POST /reprepare avec manual_book_year -> job cree avec ce field."""
    from flox_uploader.core import jobs_db
    from flox_uploader.core.package_state import (
        PackageState, PackageStateData, write_state,
    )
    from flox_uploader import config

    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    initial_job = jobs_db.add_job(str(source))

    pkg_root = config.packages_dir()
    pkg_root.mkdir(parents=True, exist_ok=True)
    pkg = pkg_root / "Year.Test-Flox"
    pkg.mkdir()
    write_state(pkg, PackageStateData(
        state=PackageState.PREPARED,
        release_name="Year.Test-Flox",
        tracker_key="gemini",
        created_at="2026-05-24T00:00:00Z",
        updated_at="2026-05-24T00:00:00Z",
    ))
    jobs_db.update_job(
        initial_job.id, package_dir=str(pkg),
        release_name="Year.Test-Flox", status="done",
    )

    from flox_uploader.web import jobs_runner
    monkeypatch.setattr(jobs_runner, "submit_prepare_job", lambda jid: None)

    resp = client.post(
        "/api/packages/Year.Test-Flox/reprepare",
        json={
            "manual_book_year": 1999,
            "category_id_hint": 12,
        },
    )
    assert resp.status_code == 200, resp.text
    new_job_id = resp.json()["job_id"]
    new_job = jobs_db.get_job(new_job_id)
    assert new_job.manual_book_year == 1999
