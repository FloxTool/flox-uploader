"""Tests Phase 3a : interface web.

Couvre les routes principales et l'API JSON. On utilise TestClient FastAPI
qui ne demarre pas de serveur reel.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# fastapi est optional ; les tests sont skipped si pas installe
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from flox_uploader.web.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Cree une app FastAPI avec un workspace propre et un browse_root sandbox.

    Set les variables critiques pour que `is_setup_complete()` retourne True
    et que le middleware /setup-redirect ne bloque pas les routes testees.
    Les tests qui veulent tester explicitement le wizard utilisent la fixture
    `client_unconfigured` (qui ne set pas ces vars).
    """
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    # Variables critiques requises par le middleware first-run.
    # Valeurs bidons : les tests qui appellent l'API tracker mockent les requetes.
    monkeypatch.setenv("TRACKER_API_URL", "https://gemini-tracker.test/api")
    monkeypatch.setenv("TRACKER_API_KEY", "test-tracker-key")
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://gemini-tracker.test/announce/test-passkey")
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb-key")
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)
    return TestClient(create_app())


@pytest.fixture
def client_unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Variante de `client` ou la config est volontairement incomplete : le
    middleware doit rediriger vers /setup. Utilise pour tester le wizard.

    IMPORTANT (fix bug post-merge Lots K-S) : on doit aussi neutraliser le
    `.env` legacy de PROJECT_ROOT que `config.load_env()` charge automatiquement
    en mode dev (cf. config.env_file()). Sans ce patch, les tests "unconfigured"
    echouent quand le user a un vrai .env a la racine du repo (cas de Louis).
    On force `_is_dev_install` a retourner False pendant le test pour que
    `env_file()` cible `data_dir/.env` (qui n'existe pas dans tmp_path).
    """
    from flox_uploader import config as _cfg
    # Force env_file() vers un chemin tmp_path inexistant -> load_env() ne
    # charge rien et ne migre rien. Sinon le `.env` legacy a la racine du
    # repo (PROJECT_ROOT/.env) est lu en mode dev, ou copié vers data_dir
    # via _migrate_legacy_env_if_needed() en mode non-dev — les deux
    # repolluent os.environ avec les vraies cles du user (cas Louis).
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
    monkeypatch.setenv("FLOX_UPLOADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BROWSE_ROOT", str(tmp_path / "browse"))
    # Volontairement : on retire les vars critiques au cas ou elles seraient
    # heritees du shell/CI.
    for k in ("TRACKER_API_URL", "TRACKER_API_KEY", "TRACKER_ANNOUNCE", "TMDB_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "browse").mkdir()
    (tmp_path / "data" / "upload_packages").mkdir(parents=True)
    return TestClient(create_app())


# ============================================================
# Routes pages
# ============================================================

def test_root_redirects_to_inbox(client: TestClient):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/inbox"


def test_inbox_renders_html(client: TestClient):
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Inbox" in resp.text
    assert "Flox Uploader" in resp.text


def test_queue_renders_html_empty(client: TestClient):
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert "Aucun package" in resp.text


# ============================================================
# Sprint 6 — /api/update-info
# ============================================================

def test_api_update_info_no_cache_returns_unavailable(client: TestClient):
    """Sans cache disque (premier run), l'endpoint renvoie une UpdateInfo
    vide avec available=False — jamais d'erreur, jamais de blocage."""
    resp = client.get("/api/update-info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["current"]  # __version__ courant
    assert data["latest"] == ""
    assert data["release_url"] == ""


def test_api_update_info_with_cached_newer_version(
    client: TestClient, tmp_path: Path, monkeypatch
):
    """Si le cache disque contient une version > current, l'endpoint
    retourne available=True avec release_url."""
    import time as _t
    from flox_uploader.core import update_check as uc

    monkeypatch.setattr(uc, "__version__", "0.3.5")
    # Le data_dir de la fixture client pointe deja vers tmp_path/data,
    # donc _save_cache va ecrire au bon endroit.
    uc._save_cache({
        "checked_at_epoch": _t.time(),
        "checked_at_iso": "2026-05-15T10:00:00+00:00",
        "latest": "v0.4.0",
        "release_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
        "release_notes": "notes",
    })
    resp = client.get("/api/update-info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["latest"] == "v0.4.0"
    assert "github.com/FloxTool" in data["release_url"]


def test_update_banner_rendered_when_update_available(
    client: TestClient, monkeypatch
):
    """Si l'update est dispo, le banner est present dans le HTML rendu sur
    une page non-setup. data-latest attribute permet au JS de gerer le
    dismiss per-version via localStorage."""
    import time as _t
    from flox_uploader.core import update_check as uc

    monkeypatch.setattr(uc, "__version__", "0.3.5")
    uc._save_cache({
        "checked_at_epoch": _t.time(),
        "latest": "v0.4.0",
        "release_url": "https://github.com/FloxTool/flox-uploader/releases/tag/v0.4.0",
        "release_notes": "",
    })
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert 'id="update-banner"' in resp.text
    assert 'data-latest="v0.4.0"' in resp.text
    assert "Nouvelle version disponible" in resp.text


def test_update_banner_absent_when_no_update(client: TestClient):
    """Sans cache (ou cache avec version egale), pas de banner dans le HTML."""
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert 'id="update-banner"' not in resp.text


def test_update_banner_absent_on_setup_page(
    client_unconfigured: TestClient, monkeypatch
):
    """Sur /setup, le banner update est masque meme si une update est dispo
    (decision PLAN-V1 §1.6 : ne pas perturber l'onboarding)."""
    import time as _t
    from flox_uploader.core import update_check as uc

    monkeypatch.setattr(uc, "__version__", "0.3.5")
    uc._save_cache({
        "checked_at_epoch": _t.time(),
        "latest": "v0.4.0",
        "release_url": "https://example.com",
        "release_notes": "",
    })
    resp = client_unconfigured.get("/setup")
    assert resp.status_code == 200
    assert 'id="update-banner"' not in resp.text


# ============================================================
# Sprint 8 — Crash report helper
# ============================================================

def test_api_diagnostic_returns_structured_payload(client: TestClient):
    """/api/diagnostic retourne un JSON avec tous les champs attendus
    et aucun secret."""
    resp = client.get("/api/diagnostic")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "version", "python_version", "os", "os_release",
        "mediainfo_available", "mediainfo_version", "setup_complete",
    }
    assert data["version"]  # __version__ courant
    assert data["python_version"]  # ex "3.12.4"
    assert data["os"] in {"Windows", "macOS", "Linux", "Autre"}
    # Pas de secrets dans le payload
    body = resp.text
    assert "TRACKER_API_KEY" not in body
    assert "passkey" not in body.lower()


def test_diagnostic_injected_in_base_html(client: TestClient):
    """Le diagnostic est inject e en JS global window.APP_DIAGNOSTIC sur
    toutes les pages, accessible immediatement sans round-trip API."""
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert "window.APP_DIAGNOSTIC" in resp.text
    # On verifie qu'au moins les cles clefs sont serialisees
    assert '"version"' in resp.text
    assert '"python_version"' in resp.text
    assert '"os"' in resp.text


def test_guide_page_contains_signaler_un_bug_section(client: TestClient):
    """La page Guide affiche la section 'Signaler un bug' avec le bouton
    qui declenche tu.openBugReport()."""
    resp = client.get("/guide")
    assert resp.status_code == 200
    assert "Signaler un bug" in resp.text
    assert 'id="guide-report-bug"' in resp.text
    assert "tu.openBugReport" in resp.text


def test_toast_helper_includes_bug_report_logic(client: TestClient):
    """base.html contient les helpers tu.buildBugReport et tu.openBugReport
    pour que les toasts danger puissent les utiliser."""
    resp = client.get("/inbox")
    assert resp.status_code == 200
    assert "tu.buildBugReport" in resp.text
    assert "tu.openBugReport" in resp.text
    # Le bouton "Copier rapport" est rendu dans le toast danger
    assert "toast-copy-report" in resp.text
    # URL de pre-remplissage GitHub (assemble en JS via URLSearchParams)
    assert "'bug.yml'" in resp.text
    assert "issues/new" in resp.text


def test_inbox_browses_subdirectory(client: TestClient, tmp_path: Path):
    """Naviguer dans un sous-dossier doit le lister sans erreur."""
    sub = tmp_path / "browse" / "MyMovies"
    sub.mkdir()
    (sub / "Foo.2024.1080p.mkv").write_bytes(b"fake")
    resp = client.get(f"/inbox?path={sub}")
    assert resp.status_code == 200
    assert "Foo.2024.1080p.mkv" in resp.text


def test_inbox_hides_companions_by_default(client: TestClient, tmp_path: Path):
    """NOTES Sprint 8 hotfix : revolu round 7. Par defaut on n'affiche que
    les dossiers + videos. Les companions (NFO, posters, sous-titres) ne sont
    plus visibles tant que la checkbox "Afficher tout" n'est pas cochee."""
    sub = tmp_path / "browse" / "Mixed"
    sub.mkdir()
    (sub / "movie.mkv").write_bytes(b"x")
    (sub / "thumbnail.jpg").write_bytes(b"x")     # poster -> cache (showall=off)
    (sub / "readme.nfo").write_text("nfo")        # NFO -> cache
    (sub / "subs.srt").write_text("subs")         # sous-titres -> cache
    (sub / "script.exe").write_bytes(b"exe")      # hors perimetre -> cache
    (sub / "log.log").write_text("log")           # hors perimetre -> cache
    resp = client.get(f"/inbox?path={sub}")
    assert resp.status_code == 200
    # Seul le fichier video apparait
    assert "movie.mkv" in resp.text
    assert "thumbnail.jpg" not in resp.text
    assert "readme.nfo" not in resp.text
    assert "subs.srt" not in resp.text
    assert "script.exe" not in resp.text
    assert "log.log" not in resp.text


def test_inbox_shows_everything_with_show_all(client: TestClient, tmp_path: Path):
    """Avec ?show_all=1 (checkbox "Afficher tout" cochee), on voit TOUT :
    videos + companions + fichiers exotiques (.exe, .log, etc.)."""
    sub = tmp_path / "browse" / "Mixed2"
    sub.mkdir()
    (sub / "movie.mkv").write_bytes(b"x")
    (sub / "thumbnail.jpg").write_bytes(b"x")
    (sub / "readme.nfo").write_text("nfo")
    (sub / "subs.srt").write_text("subs")
    (sub / "script.exe").write_bytes(b"exe")
    resp = client.get(f"/inbox?path={sub}&show_all=1")
    assert resp.status_code == 200
    # Avec show_all : tout est visible
    assert "movie.mkv" in resp.text
    assert "thumbnail.jpg" in resp.text
    assert "readme.nfo" in resp.text
    assert "subs.srt" in resp.text
    assert "script.exe" in resp.text


# ============================================================
# Routes API JSON
# ============================================================

def test_api_files_lists_directory(client: TestClient, tmp_path: Path):
    sub = tmp_path / "browse" / "Films"
    sub.mkdir()
    (sub / "A.mkv").write_bytes(b"x" * 1000)
    (sub / "B").mkdir()
    resp = client.get(f"/api/files?path={sub}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_path"] == str(sub)
    names = {e["name"] for e in data["entries"]}
    assert "A.mkv" in names
    assert "B" in names
    # B en premier (dossier d'abord), puis A.mkv
    entries_ordered = [e["name"] for e in data["entries"]]
    assert entries_ordered.index("B") < entries_ordered.index("A.mkv")


def test_api_files_404_on_missing_path(client: TestClient):
    resp = client.get("/api/files?path=/nonexistent/path")
    assert resp.status_code == 404


def test_api_packages_returns_empty_list_initially(client: TestClient):
    resp = client.get("/api/packages")
    assert resp.status_code == 200
    assert resp.json() == {"packages": []}


def test_api_packages_lists_existing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Cree un faux package_state.json et verifie qu'il apparait."""
    from flox_uploader.core.package_state import PackageState, init_state, transition

    pkg = tmp_path / "data" / "upload_packages" / "Foo.2024.1080p.x265-TEAM"
    pkg.mkdir()
    init_state(pkg, "Foo.2024.1080p.x265-TEAM", "gemini")
    # prepared -> validated -> uploaded (transitions autorisees)
    transition(pkg, PackageState.VALIDATED, infohash="abc")
    transition(pkg, PackageState.UPLOADED, uploaded_torrent_id=42, uploaded_torrent_url="https://example/42")

    resp = client.get("/api/packages")
    assert resp.status_code == 200
    pkgs = resp.json()["packages"]
    assert len(pkgs) == 1
    assert pkgs[0]["release_name"] == "Foo.2024.1080p.x265-TEAM"
    assert pkgs[0]["state"] == "uploaded"
    assert pkgs[0]["uploaded_torrent_id"] == 42


def test_api_queue_add_validates_paths(client: TestClient):
    """Les paths inexistants doivent etre rejetes."""
    resp = client.post(
        "/api/queue/add",
        json={"paths": ["/nonexistent/foo.mkv"]},
    )
    assert resp.status_code == 400


def test_api_queue_add_accepts_existing_path(client: TestClient, tmp_path: Path):
    """Les paths qui existent sont acceptes (Phase 3a : on accuse juste reception)."""
    f = tmp_path / "browse" / "real.mkv"
    f.write_bytes(b"x")
    resp = client.post("/api/queue/add", json={"paths": [str(f)]})
    resp = client.post("/api/queue/add", json={"paths": [str(f)]})
    assert resp.status_code == 200
    assert resp.json()["added"] == 1


def test_api_docs_available(client: TestClient):
    resp = client.get("/api/docs")
    assert resp.status_code == 200


# ============================================================
# Phase 3b.3 : page detail + reprepare + options
# ============================================================

def _make_prepared_package(tmp_path: Path, name: str = "Foo.2024.1080p.x265-TEAM") -> Path:
    """Cree un package prepared minimal pour les tests Phase 3b.3.

    Inclut un faux fichier `.torrent` (contenu bidon) pour passer la
    precondition de l'endpoint /api/packages/<name>/upload qui verifie
    sa presence (cf. fix B1 dans AUDIT.md).
    """
    from flox_uploader.core.package_state import init_state

    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    (pkg / "release_name.txt").write_text(name, encoding="utf-8")
    (pkg / f"{name}.nfo").write_text("Generic Title\nDate.....: 2024", encoding="utf-8")
    # Faux .torrent : contenu bidon, suffit pour le check is_file().
    (pkg / f"{name}.torrent").write_bytes(b"d8:announce0:e")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        '{"tmdb_context":{"movie_id":12345,"imdb_id":"tt9999"},"media_type":"movie","torrent_size":1234567890}',
        encoding="utf-8",
    )
    return pkg


def test_package_detail_page_renders(client: TestClient, tmp_path: Path):
    """La page detail doit afficher le release_name, le score, le NFO."""
    pkg = _make_prepared_package(tmp_path)
    resp = client.get(f"/packages/{pkg.name}")
    assert resp.status_code == 200
    assert pkg.name in resp.text
    assert "12345" in resp.text          # TMDB ID
    assert "tt9999" in resp.text         # IMDB ID
    assert "Nom de release" in resp.text  # section visible (renommee depuis release_name.txt)
    # Apres F1 NOTES.md round 2 : 2 cartes distinctes "Override naming" et "Options pour l'upload"
    assert "Override naming" in resp.text       # carte 1 visible (state=prepared)
    assert "Options pour l'upload" in resp.text  # carte 2 visible


def test_package_detail_404_on_unknown(client: TestClient):
    resp = client.get("/packages/Nonexistent.Package")
    assert resp.status_code == 404


def test_package_detail_400_on_path_traversal(client: TestClient):
    resp = client.get("/packages/..%2F..%2Fetc%2Fpasswd")
    # FastAPI normalize peut donner 404 ou 400 selon la version, on accepte les deux
    assert resp.status_code in (400, 404)


def test_package_options_save(client: TestClient, tmp_path: Path):
    """POST /api/packages/<name>/options doit persister personal_release et anonymous."""
    from flox_uploader.core.package_state import read_state

    pkg = _make_prepared_package(tmp_path, "OptionsTest")
    resp = client.post(
        f"/api/packages/{pkg.name}/options",
        json={"personal_release": True, "anonymous": False, "manual_tmdb_id": 999},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    state = read_state(pkg)
    assert state is not None
    assert state.personal_release is True
    assert state.anonymous is False
    assert state.manual_tmdb_id == 999


def test_package_options_404_on_unknown(client: TestClient):
    resp = client.post(
        "/api/packages/Nonexistent.Package/options",
        json={"personal_release": True},
    )
    assert resp.status_code == 404


def test_package_reprepare_422_when_no_source_job(client: TestClient, tmp_path: Path):
    """Re-prepare doit echouer 422 si pas de job source (package legacy)."""
    pkg = _make_prepared_package(tmp_path, "Legacy.Package")
    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"force_fr": "VFF"},
    )
    assert resp.status_code == 422


def test_package_reprepare_creates_new_job(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Si un job source existe, reprepare cree un nouveau job avec le force_fr override."""
    from flox_uploader.core import jobs_db

    # Mock submit_prepare_job pour ne pas vraiment lancer le pipeline
    submitted: list[int] = []
    monkeypatch.setattr(
        "flox_uploader.web.jobs_runner.submit_prepare_job",
        lambda jid: submitted.append(jid),
    )

    pkg = _make_prepared_package(tmp_path, "ReprepareTest")
    # Cree un fichier source + job source qui pointe vers le package
    src_file = tmp_path / "browse" / "source.mkv"
    src_file.write_bytes(b"x")
    src_job = jobs_db.add_job(str(src_file), force_fr="VOF")
    jobs_db.update_job(src_job.id, status="done", package_dir=str(pkg))

    resp = client.post(
        f"/api/packages/{pkg.name}/reprepare",
        json={"force_fr": "VFF"},
    )
    assert resp.status_code == 200
    new_job_id = resp.json()["job_id"]
    assert new_job_id in submitted
    new_job = jobs_db.get_job(new_job_id)
    assert new_job is not None
    assert new_job.file_path == str(src_file)
    assert new_job.force_fr == "VFF"


def test_queue_links_to_package_detail(client: TestClient, tmp_path: Path):
    """La queue doit avoir un lien vers /packages/<name> pour chaque package."""
    pkg = _make_prepared_package(tmp_path, "LinkTest")
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert f'/packages/{pkg.name}' in resp.text


def test_package_delete_requires_confirm_name(client: TestClient, tmp_path: Path):
    """DELETE /api/packages/<name> sans confirm_name correct -> 400."""
    pkg = _make_prepared_package(tmp_path, "DeleteTest")
    resp = client.request(
        "DELETE",
        f"/api/packages/{pkg.name}",
        json={"confirm_name": "wrong"},
    )
    assert resp.status_code == 400
    assert pkg.is_dir()  # toujours present


def test_package_delete_works(client: TestClient, tmp_path: Path):
    """DELETE avec bon confirm_name -> 200, le dossier est supprime."""
    pkg = _make_prepared_package(tmp_path, "DeleteOk")
    resp = client.request(
        "DELETE",
        f"/api/packages/{pkg.name}",
        json={"confirm_name": pkg.name},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == pkg.name
    assert not pkg.exists()


def test_package_delete_refuses_uploaded(client: TestClient, tmp_path: Path):
    """DELETE refuse 409 sur un package en etat uploaded."""
    from flox_uploader.core.package_state import PackageState, transition

    pkg = _make_prepared_package(tmp_path, "UploadedPkg")
    transition(pkg, PackageState.VALIDATED, infohash="abc")
    transition(pkg, PackageState.UPLOADED, uploaded_torrent_id=42)
    resp = client.request(
        "DELETE",
        f"/api/packages/{pkg.name}",
        json={"confirm_name": pkg.name},
    )
    assert resp.status_code == 409
    assert pkg.is_dir()


# ============================================================
# Phase 3b.4 : upload (single + batch)
# ============================================================

def test_package_upload_409_when_already_uploaded(client: TestClient, tmp_path: Path):
    """POST /api/packages/<name>/upload refuse 409 si state == uploaded."""
    from flox_uploader.core.package_state import PackageState, transition

    pkg = _make_prepared_package(tmp_path, "AlreadyUploaded")
    transition(pkg, PackageState.VALIDATED, infohash="abc")
    transition(pkg, PackageState.UPLOADED, uploaded_torrent_id=1)
    resp = client.post(f"/api/packages/{pkg.name}/upload", json={"dry_run": True})
    assert resp.status_code == 409


def test_package_upload_dry_run_submits_job(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """POST avec dry_run=True doit appeler submit_upload_job avec les bons params."""
    submitted = []
    monkeypatch.setattr(
        "flox_uploader.web.jobs_runner.submit_upload_job",
        lambda target, dry_run=False, force_upload=False, force_existing_id=None, anonymous=False:
            submitted.append({
                "target": str(target),
                "dry_run": dry_run,
                "force_upload": force_upload,
                "anonymous": anonymous,
            }),
    )
    pkg = _make_prepared_package(tmp_path, "DryRunTest")
    resp = client.post(f"/api/packages/{pkg.name}/upload", json={"dry_run": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert len(submitted) == 1
    assert submitted[0]["dry_run"] is True
    assert submitted[0]["target"] == str(pkg)


def test_package_upload_409_when_torrent_missing(
    client: TestClient, tmp_path: Path,
):
    """B1 : si le .torrent n'existe pas (cas pre-check anticipe ABORTED_DUPLICATE
    qui a skip create_torrent), l'endpoint /upload retourne 409 avec un message
    structure pointant vers la solution (re-preparer)."""
    pkg = _make_prepared_package(tmp_path, "Missing.Torrent.Pkg")
    # On retire le .torrent pour simuler le cas reel
    (pkg / "Missing.Torrent.Pkg.torrent").unlink()

    resp = client.post(f"/api/packages/{pkg.name}/upload", json={"dry_run": True})
    assert resp.status_code == 409
    body = resp.json()
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "torrent_missing"
    assert detail["package"] == pkg.name
    assert "Re-prepare" in detail["message"] or "re-prepare" in detail["message"].lower()


def test_presentation_save_writes_user_file(client: TestClient, tmp_path: Path):
    """F4 : POST /api/packages/<name>/presentation ecrit presentation_user.txt."""
    pkg = _make_prepared_package(tmp_path, "PresEditTest")
    # Simuler une presentation regenerated existante
    (pkg / "presentation.txt").write_text("[b]Original[/b]", encoding="utf-8")

    new_text = "[b]Edité par l'user[/b]\n[i]Plus de detail[/i]"
    resp = client.post(
        f"/api/packages/{pkg.name}/presentation",
        json={"text": new_text},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overridden"] is True
    # Le fichier user existe
    assert (pkg / "presentation_user.txt").read_text(encoding="utf-8") == new_text
    # Le fichier original n'a pas ete touche
    assert (pkg / "presentation.txt").read_text(encoding="utf-8") == "[b]Original[/b]"


def test_presentation_reset_deletes_user_file(client: TestClient, tmp_path: Path):
    """F4 : DELETE /api/packages/<name>/presentation supprime le user-edit."""
    pkg = _make_prepared_package(tmp_path, "PresResetTest")
    (pkg / "presentation.txt").write_text("[b]Original[/b]", encoding="utf-8")
    (pkg / "presentation_user.txt").write_text("[b]Edité[/b]", encoding="utf-8")

    resp = client.delete(f"/api/packages/{pkg.name}/presentation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overridden"] is False
    assert not (pkg / "presentation_user.txt").exists()
    # L'original est intact
    assert (pkg / "presentation.txt").read_text(encoding="utf-8") == "[b]Original[/b]"


def test_presentation_reset_idempotent_when_no_user_file(client: TestClient, tmp_path: Path):
    """F4 : DELETE accepte un noop quand aucun user-edit n'existe."""
    pkg = _make_prepared_package(tmp_path, "PresResetEmpty")
    resp = client.delete(f"/api/packages/{pkg.name}/presentation")
    assert resp.status_code == 200


def test_presentation_save_400_on_missing_text(client: TestClient, tmp_path: Path):
    pkg = _make_prepared_package(tmp_path, "PresBadTest")
    resp = client.post(f"/api/packages/{pkg.name}/presentation", json={})
    assert resp.status_code == 400


def test_package_upload_status_idle_initially(client: TestClient, tmp_path: Path):
    """GET upload-status retourne 'idle' si aucun upload n'a ete lance."""
    pkg = _make_prepared_package(tmp_path, "StatusTest")
    resp = client.get(f"/api/packages/{pkg.name}/upload-status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_queue_upload_batch_validates_packages(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """POST upload-batch lance les packages prepared, skip les autres."""
    from flox_uploader.core.package_state import PackageState, transition

    submitted = []
    monkeypatch.setattr(
        "flox_uploader.web.jobs_runner.submit_upload_job",
        lambda target, dry_run=False, force_upload=False, force_existing_id=None, anonymous=False:
            submitted.append(str(target)),
    )

    pkg_ok = _make_prepared_package(tmp_path, "BatchOk")
    pkg_uploaded = _make_prepared_package(tmp_path, "BatchAlreadyUp")
    transition(pkg_uploaded, PackageState.VALIDATED, infohash="abc")
    transition(pkg_uploaded, PackageState.UPLOADED, uploaded_torrent_id=1)

    resp = client.post(
        "/api/queue/upload-batch",
        json={"package_names": [pkg_ok.name, pkg_uploaded.name, "Nonexistent"], "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert pkg_ok.name in body["accepted"]
    assert len(body["skipped"]) == 2
    assert len(submitted) == 1


def test_queue_upload_batch_400_on_empty(client: TestClient):
    resp = client.post("/api/queue/upload-batch", json={"package_names": []})
    assert resp.status_code == 400


# ============================================================
# Phase 3b.5 : SSE log streaming
# ============================================================

def test_job_stream_404_on_unknown(client: TestClient):
    resp = client.get("/api/jobs/99999/stream")
    assert resp.status_code == 404


def test_upload_stream_404_when_no_upload(client: TestClient, tmp_path: Path):
    """SSE upload stream : 404 si aucun upload n'a ete lance pour ce package."""
    pkg = _make_prepared_package(tmp_path, "NoUpload")
    resp = client.get(f"/api/uploads/{pkg.name}/stream")
    assert resp.status_code == 404


def test_job_stream_returns_sse_when_done(
    client: TestClient, tmp_path: Path,
):
    """SSE stream sur un job 'done' lit le fichier log existant et termine."""
    from flox_uploader.core import jobs_db

    src_file = tmp_path / "browse" / "src.mkv"
    src_file.write_bytes(b"x")
    job = jobs_db.add_job(str(src_file))
    # Cree un log file avec quelques lignes
    log_path = Path(job.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("[INFO] ligne 1\n[OK] ligne 2\n", encoding="utf-8")
    jobs_db.update_job(job.id, status="done")
    # Stream synchrone (le job est deja 'done', le stream doit terminer vite)
    with client.stream("GET", f"/api/jobs/{job.id}/stream") as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "ligne 1" in body
    assert "ligne 2" in body
    assert "event: end" in body


# ============================================================
# Phase 3c : Config UI
# ============================================================

def test_config_page_renders(client: TestClient):
    """GET /config affiche le form de configuration."""
    resp = client.get("/config")
    assert resp.status_code == 200
    assert "Configuration" in resp.text
    assert "TRACKER_API_URL" in resp.text
    assert "TMDB_API_KEY" in resp.text


def test_config_api_get_masks_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """GET /api/config doit retourner une serie de puces de meme longueur
    que le vrai secret (Sprint 8 hotfix : avant on retournait '***' fixe).
    Les valeurs non secretes restent en clair."""
    secret = "secret-real-key"
    monkeypatch.setenv("TRACKER_API_KEY", secret)
    monkeypatch.setenv("TRACKER_API_URL", "https://example.com/api")
    resp = client.get("/api/config")
    assert resp.status_code == 200
    values = resp.json()["values"]
    # Le masque est compose uniquement de puces et a la meme longueur que
    # le secret reel — donne un retour visuel coherent dans l'UI.
    masked = values["TRACKER_API_KEY"]
    assert len(masked) == len(secret)
    assert set(masked) == {"●"}
    # Les non-secrets restent en clair.
    assert values["TRACKER_API_URL"] == "https://example.com/api"


def test_config_api_save_writes_env(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """POST /api/config ecrit dans le .env et applique a os.environ."""
    # Pointe le .env vers un fichier dans tmp_path
    env_file = tmp_path / ".env"
    monkeypatch.setattr(
        "flox_uploader.config.env_file", lambda: env_file,
    )
    resp = client.post(
        "/api/config",
        json={"values": {
            "TRACKER_API_URL": "https://test.tracker.com/api",
            "TMDB_API_KEY": "abc123",
            # NOTES round 7 : APPEND_FR_TITLE_TO_RELEASE_NAME retire de l'UI,
            # remplace par un autre champ valide (TORRENT_FINAL_DIR nouveau).
            "TORRENT_FINAL_DIR": r"C:\watched",
        }},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "TRACKER_API_URL" in data["updated_keys"]
    # Verifier le .env
    content = env_file.read_text(encoding="utf-8")
    assert "TRACKER_API_URL=https://test.tracker.com/api" in content
    assert "TMDB_API_KEY=abc123" in content
    assert "TORRENT_FINAL_DIR=" in content
    # Verifier os.environ a ete maj
    assert os.environ.get("TRACKER_API_URL") == "https://test.tracker.com/api"


def test_config_api_save_keeps_secret_when_placeholder(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Si le user laisse *** comme valeur d'un secret, l'existant est conserve."""
    monkeypatch.setattr(
        "flox_uploader.config.env_file", lambda: tmp_path / ".env",
    )
    monkeypatch.setenv("TMDB_API_KEY", "real-key-keep-me")
    resp = client.post(
        "/api/config",
        json={"values": {
            "TMDB_API_KEY": "***",  # placeholder = ne pas changer
            "TRACKER_API_URL": "https://updated.com/api",
        }},
    )
    assert resp.status_code == 200
    assert "TMDB_API_KEY" not in resp.json()["updated_keys"]
    assert os.environ.get("TMDB_API_KEY") == "real-key-keep-me"


def test_config_api_save_rejects_unknown_key(client: TestClient):
    resp = client.post(
        "/api/config",
        json={"values": {"NOT_IN_SCHEMA": "foo"}},
    )
    assert resp.status_code == 400


def test_config_api_save_rejects_invalid_url(client: TestClient):
    resp = client.post(
        "/api/config",
        json={"values": {"TRACKER_API_URL": "no-protocol"}},
    )
    assert resp.status_code == 400


def test_config_reveal_returns_real_value(client: TestClient):
    """L'endpoint /api/config/reveal retourne la VRAIE valeur d'un secret
    (pour que le bouton oeil de la page /config puisse l'afficher)."""
    resp = client.get("/api/config/reveal?key=TRACKER_API_KEY")
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "TRACKER_API_KEY"
    assert body["value"] == "test-tracker-key"  # cf. fixture client


def test_config_reveal_404_unknown_key(client: TestClient):
    resp = client.get("/api/config/reveal?key=NOT_A_REAL_KEY")
    assert resp.status_code == 404


def test_config_reveal_400_on_non_secret(client: TestClient):
    """Refuse de reveler les cles non-secret (ex: TRACKER_API_URL est en clair)."""
    resp = client.get("/api/config/reveal?key=TRACKER_API_URL")
    assert resp.status_code == 400


# Need os import for the env tests above
import os  # noqa: E402


# ============================================================
# Wizard first-run (/setup)
# ============================================================

def test_unconfigured_redirects_to_setup(client_unconfigured: TestClient):
    """Sur config incomplete, GET / -> 303 vers /setup."""
    resp = client_unconfigured.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/setup"


def test_unconfigured_redirects_inbox_to_setup(client_unconfigured: TestClient):
    """Sur config incomplete, /inbox aussi redirige vers /setup."""
    resp = client_unconfigured.get("/inbox", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/setup"


def test_unconfigured_api_returns_503(client_unconfigured: TestClient):
    """Sur config incomplete, les /api/* renvoient 503 setup_required (pas un redirect HTML)."""
    resp = client_unconfigured.get("/api/packages")
    assert resp.status_code == 503
    body = resp.json()
    assert body["setup_required"] is True
    assert "TRACKER_API_KEY" in body["missing"]


def test_setup_page_renders(client_unconfigured: TestClient):
    """La page /setup elle-meme reste accessible meme sans config."""
    resp = client_unconfigured.get("/setup")
    assert resp.status_code == 200
    # Round 6 (refonte Sprint 1) : titre H1 = "Bienvenue" + page <title>
    # contient "Première configuration".
    assert "Bienvenue" in resp.text or "Première configuration" in resp.text


def test_setup_save_writes_env_and_unlocks(client_unconfigured: TestClient, monkeypatch: pytest.MonkeyPatch):
    """POST /api/setup/save persiste les valeurs ; ensuite /api/packages repond 200."""
    payload = {
        "values": {
            "TRACKER_API_URL": "https://gemini-tracker.test/api",
            "TRACKER_API_KEY": "filled-key",
            "TRACKER_ANNOUNCE": "https://gemini-tracker.test/announce/pk",
            "TMDB_API_KEY": "filled-tmdb",
        },
    }
    resp = client_unconfigured.post("/api/setup/save", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["setup_complete"] is True
    # apply_updates a mute os.environ -> /api/packages doit maintenant repondre 200
    resp2 = client_unconfigured.get("/api/packages")
    assert resp2.status_code == 200


def test_setup_test_tmdb_400_on_empty(client_unconfigured: TestClient):
    resp = client_unconfigured.post("/api/setup/test-tmdb", json={"api_key": ""})
    assert resp.status_code == 400


def test_setup_test_tracker_400_on_empty(client_unconfigured: TestClient):
    resp = client_unconfigured.post("/api/setup/test-tracker", json={})
    assert resp.status_code == 400


def test_unconfigured_with_skip_cookie_can_browse_inbox(client_unconfigured: TestClient):
    """Q2 NOTES.md : avec le cookie tu_setup_skip=1, /inbox doit etre accessible
    meme si setup incomplet (banner persistant suffit, plus de redirect)."""
    resp = client_unconfigured.get(
        "/inbox",
        cookies={"tu_setup_skip": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Configuration incomplète" in resp.text


def test_unconfigured_with_skip_cookie_blocks_queue_add(client_unconfigured: TestClient):
    """Q2 NOTES.md : le cookie skip n'autorise PAS les actions blocking
    (add-to-queue, upload). Le 503 setup_required reste."""
    resp = client_unconfigured.post(
        "/api/queue/add",
        json={"paths": ["/some/path"]},
        cookies={"tu_setup_skip": "1"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["setup_required"] is True


def test_static_bypass_setup_middleware(client_unconfigured: TestClient):
    """Les /static/* ne doivent PAS rediriger vers /setup (sinon les CSS du
    wizard lui-meme cassent)."""
    # Static dir n'existe peut-etre pas en test, mais le middleware ne doit
    # pas intercepter (sinon on aurait 303, pas 404).
    resp = client_unconfigured.get("/static/missing.css", follow_redirects=False)
    assert resp.status_code in (404, 200)
    assert resp.status_code != 303


# ============================================================
# Path traversal sanity check (cf. AUDIT.md section 5.1)
# ============================================================

def test_api_files_rejects_empty_path(client: TestClient):
    """Path empty est rejete par _safe_resolve_path en 400 (Path("") = cwd, surprise effect)."""
    resp = client.get("/api/files?path=")
    assert resp.status_code == 400


def test_api_files_rejects_null_byte(client: TestClient):
    """Path avec null-byte rejete proprement (technique d'evasion classique)."""
    resp = client.get("/api/files?path=/tmp/foo%00bar")
    assert resp.status_code == 400


def test_api_files_rejects_dot_only(client: TestClient):
    resp = client.get("/api/files?path=.")
    assert resp.status_code == 400


def test_inbox_rejects_dotdot_only(client: TestClient):
    resp = client.get("/inbox?path=..")
    assert resp.status_code == 400


def test_queue_add_rejects_null_byte(client: TestClient, tmp_path: Path):
    """Tentative d'ajout d'un path avec null-byte rejetee."""
    resp = client.post(
        "/api/queue/add",
        json={"paths": [str(tmp_path / "foo\x00bar")]},
    )
    assert resp.status_code == 400


# ============================================================
# Log scrubbing (cf. AUDIT.md section 5.2)
# ============================================================

def test_log_scrubber_masks_known_secrets():
    """Le SecretScrubber masque les API keys connues dans une string."""
    from flox_uploader.core.log_scrubber import SecretScrubber
    os.environ["TRACKER_API_KEY"] = "supersecret-tracker-key-1234"
    os.environ["TMDB_API_KEY"] = "tmdb-key-abcdef-99887766"
    try:
        scrubber = SecretScrubber()
        text = "Calling https://api.example.com/foo?token=supersecret-tracker-key-1234 and tmdb=tmdb-key-abcdef-99887766"
        out = scrubber.scrub(text)
        assert "supersecret-tracker-key-1234" not in out
        assert "tmdb-key-abcdef-99887766" not in out
        assert "<redacted:TRACKER_API_KEY>" in out
        assert "<redacted:TMDB_API_KEY>" in out
    finally:
        for k in ("TRACKER_API_KEY", "TMDB_API_KEY"):
            os.environ.pop(k, None)


def test_log_scrubber_extracts_passkey_from_announce():
    """Le scrubber masque la passkey extraite de TRACKER_ANNOUNCE."""
    from flox_uploader.core.log_scrubber import SecretScrubber
    os.environ["TRACKER_ANNOUNCE"] = "https://gemini-tracker.org/announce/abcdef0123456789abcdef0123456789"
    try:
        scrubber = SecretScrubber()
        text = "Found announce abcdef0123456789abcdef0123456789 in URL"
        out = scrubber.scrub(text)
        assert "abcdef0123456789abcdef0123456789" not in out
        assert "<redacted:passkey>" in out
    finally:
        os.environ.pop("TRACKER_ANNOUNCE", None)


def test_log_scrubber_empty_when_no_secrets():
    """Sans secrets en env, le scrubber est falsy et ne fait rien."""
    from flox_uploader.core.log_scrubber import SecretScrubber
    for k in ("TRACKER_API_KEY", "TMDB_API_KEY", "OMDB_API_KEY", "TRACKER_ANNOUNCE"):
        os.environ.pop(k, None)
    scrubber = SecretScrubber()
    assert not bool(scrubber)
    assert scrubber.scrub("hello world") == "hello world"
