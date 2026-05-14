"""Tests NOTES round 8 P5.8 : endpoint POST /api/packages/{name}/rescore.

Le rescore re-execute check_compliance sur le mediainfo_data cache dans
debug.json, sans toucher au .torrent. Cas d'usage typique : un package
upload il y a longtemps avec un score 50 (bug PGS bloquant depuis fixe) ->
click pour rafraichir le score sans risque pour l'infohash deja sur le tracker.
"""
from __future__ import annotations

import json
from pathlib import Path


def _make_client(tmp_path, monkeypatch):
    from flox_uploader import config as _cfg
    monkeypatch.setattr(_cfg, "env_file", lambda: tmp_path / "no_such.env")
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


def _make_pkg_with_debug(tmp_path, name, release_name, mediainfo_data,
                         compliance_issues=None, blocking_messages=None,
                         state="uploaded"):
    """Cree un package avec state.json + debug.json. Permet de simuler un
    package "ancien" avec un compliance_issues errone qu'on va rescore."""
    from flox_uploader.core.package_state import (
        init_state, transition, PackageState,
    )
    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    if state == "uploaded":
        transition(pkg, PackageState.VALIDATED, note="setup")
        transition(pkg, PackageState.UPLOADED, note="setup", uploaded_torrent_id=42)
    elif state == "aborted-duplicate":
        transition(pkg, PackageState.ABORTED_DUPLICATE, note="setup",
                   existing_torrent_id=1, existing_torrent_url="http://x/1")
    elif state == "validated":
        transition(pkg, PackageState.VALIDATED, note="setup")
    # else: PREPARED (default from init_state)

    # debug.json
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    debug = {
        "release_name": release_name,
        "mediainfo_data": mediainfo_data,
        "compliance_issues": compliance_issues or [],
    }
    if blocking_messages:
        debug["blocking_compliance_messages"] = blocking_messages
    (debug_dir / "debug.json").write_text(
        json.dumps(debug, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return pkg


def _mi_with_pgs_and_text():
    """Mars.Express-like : 3 text subs (UTF-8) + 3 PGS subs. Nouvelle regle
    compliance : PGS tolere si subs texte presents -> 0 issue."""
    return {
        "container": "Matroska",
        "video": {"codec": "HEVC", "resolution": "2160p"},
        "audio_tracks": [
            {"codec": "DDP", "channels": "5.1", "language": "fr", "title": "VOF"},
        ],
        "subtitle_tracks": [
            {"format": "UTF-8", "language": "fr", "kind": "Complet", "title": "FR SRT"},
            {"format": "UTF-8", "language": "fr", "kind": "SDH", "title": "FR SDH SRT"},
            {"format": "UTF-8", "language": "en", "kind": "Complet", "title": "EN SRT"},
            {"format": "PGS",   "language": "fr", "kind": "SDH",     "title": "FR SDH PGS"},
            {"format": "PGS",   "language": "en", "kind": "Complet", "title": "EN PGS"},
            {"format": "PGS",   "language": "en", "kind": "SDH",     "title": "EN SDH PGS"},
        ],
    }


# ============================================================
# Cas principal : le scenario Mars.Express
# Package upload avec un ancien compliance_issues "[BLOCKED] PGS dans encode",
# rescore aujourd'hui doit retirer ce blocking et faire remonter le score.
# ============================================================

def test_rescore_clears_stale_pgs_blocking_for_uploaded_package(tmp_path, monkeypatch):
    """Reproduit le cas Mars.Express : score 50 (cause par PGS blocking),
    rescore aujourd'hui -> +50 (PGS+texte = OK, le blocking saute)."""
    client = _make_client(tmp_path, monkeypatch)
    # Le release name inclut audio codec + channels pour eviter les WARN
    # audio_codec/audio_channels qui pollueraient le test.
    name = "Mars.Express.2023.VOF.2160p.DV.HDR.BluRay.DDP5.1.x265-QTZ"
    pkg = _make_pkg_with_debug(
        tmp_path, name,
        release_name=name,
        mediainfo_data=_mi_with_pgs_and_text(),
        # Ancien blocking errone : la regle PGS-in-encode etait trop stricte
        compliance_issues=[
            "[BLOCKED] subtitles: 3 sous-titre(s) PGS dans un encode — "
            "Gemini exige des SRT/ASS (PGS toleré uniquement en REMUX)."
        ],
        blocking_messages=["3 sous-titre(s) PGS dans un encode"],
        state="uploaded",
    )

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    # Le score doit augmenter significativement : blocking PGS retire (50 pts).
    # On ne hard-code pas la valeur exacte car d'autres penalites peuvent
    # exister (tmdb absent dans le fixture etc.) ; on verifie surtout :
    # 1. delta proche de +50 (le blocking PGS pesait 50 pts)
    # 2. les compliance_issues sont passees a [] (le blocking saute)
    delta = data["new_score"] - data["old_score"]
    assert delta >= 40, f"Score n'a pas suffisamment augmente : {data['old_score']} -> {data['new_score']}"
    assert data["changed"] is True
    assert data["removed_issues_count"] == 1
    assert data["added_issues_count"] == 0
    assert data["new_issues_count"] == 0

    # debug.json doit avoir ete mute en place
    debug = json.loads((pkg / "_debug" / "debug.json").read_text(encoding="utf-8"))
    assert debug["compliance_issues"] == []
    assert "blocking_compliance_messages" not in debug


def test_rescore_preserves_torrent_file(tmp_path, monkeypatch):
    """Garantie cle : le rescore NE TOUCHE PAS au .torrent. L'infohash
    doit etre preserve pour ne pas casser un upload deja seedable."""
    import hashlib
    client = _make_client(tmp_path, monkeypatch)
    name = "Mars.Express.2023.VOF.2160p.BluRay.x265-QTZ"
    pkg = _make_pkg_with_debug(
        tmp_path, name,
        release_name=name,
        mediainfo_data=_mi_with_pgs_and_text(),
        compliance_issues=["[BLOCKED] subtitles: PGS dans encode"],
        state="uploaded",
    )
    # Pose un .torrent fictif
    torrent = pkg / f"{name}.torrent"
    torrent.write_bytes(b"d8:announce30:https://test.local/announce/xe")
    sha_before = hashlib.sha256(torrent.read_bytes()).hexdigest()
    mtime_before = torrent.stat().st_mtime

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 200, r.text

    # Le .torrent doit etre BIT-POUR-BIT identique
    sha_after = hashlib.sha256(torrent.read_bytes()).hexdigest()
    assert sha_after == sha_before, "Le .torrent a ete modifie par rescore !"
    # Le mtime aussi : on n'a meme pas touche au fichier
    assert torrent.stat().st_mtime == mtime_before


def test_rescore_works_on_uploaded_state(tmp_path, monkeypatch):
    """Cas d'usage principal : on doit pouvoir rescore meme un package
    UPLOADED (contrairement a re-prepare qui refuse ce cas)."""
    client = _make_client(tmp_path, monkeypatch)
    name = "Foo.2023.VOF.1080p.BluRay.x265-TEAM"
    _make_pkg_with_debug(
        tmp_path, name,
        release_name=name,
        mediainfo_data=_mi_with_pgs_and_text(),
        state="uploaded",
    )
    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 200


def test_rescore_works_on_aborted_duplicate_state(tmp_path, monkeypatch):
    """Le rescore doit fonctionner meme pour un package ABORTED_DUPLICATE :
    le user peut vouloir refresh les warnings affiches avant de force_upload."""
    client = _make_client(tmp_path, monkeypatch)
    name = "Foo.2023.VOF.1080p.BluRay.x265-TEAM"
    _make_pkg_with_debug(
        tmp_path, name,
        release_name=name,
        mediainfo_data=_mi_with_pgs_and_text(),
        state="aborted-duplicate",
    )
    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 200


def test_rescore_unchanged_when_no_rule_difference(tmp_path, monkeypatch):
    """Si les compliance_issues sont deja a jour, rescore renvoie
    changed=False (pas de toast de regression bizarre)."""
    client = _make_client(tmp_path, monkeypatch)
    # Release name complet (incl. audio codec) pour ne pas declencher de
    # WARN audio_codec/audio_channels qui creeraient une diff non desiree.
    name = "Clean.2023.VOF.1080p.BluRay.DDP5.1.x265-TEAM"
    pkg = _make_pkg_with_debug(
        tmp_path, name,
        release_name=name,
        mediainfo_data=_mi_with_pgs_and_text(),
        compliance_issues=[],  # deja propre
        state="uploaded",
    )
    # Determine quelles seraient les issues d'aujourd'hui — on les pre-injecte
    # comme "ancien etat" pour garantir l'invariance. C'est un cas "deja a
    # jour" : un package qui a deja le compliance_issues a jour ne doit pas
    # voir son score changer.
    from flox_uploader.core.compliance import check_compliance
    current_issues = [str(i) for i in check_compliance(name, _mi_with_pgs_and_text())]
    # Ecrit ces issues dans debug.json comme s'ils etaient deja la
    debug_path = pkg / "_debug" / "debug.json"
    d = json.loads(debug_path.read_text(encoding="utf-8"))
    d["compliance_issues"] = current_issues
    debug_path.write_text(json.dumps(d), encoding="utf-8")

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 200
    data = r.json()
    assert data["changed"] is False
    assert data["old_score"] == data["new_score"]


def test_rescore_missing_package_returns_404(tmp_path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post("/api/packages/NoSuchPkg/rescore")
    assert r.status_code == 404


def test_rescore_missing_debug_json_returns_422(tmp_path, monkeypatch):
    """Si le package n'a pas de _debug/debug.json (legacy / efface),
    le rescore renvoie 422 plutot que de planter."""
    from flox_uploader.core.package_state import init_state
    client = _make_client(tmp_path, monkeypatch)
    name = "Legacy.2020.VFF.1080p.WEB-DL.x264-OLD"
    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    # Pas de debug.json -> doit etre 422

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 422
    assert "debug.json" in r.text.lower()


def test_rescore_corrupted_debug_returns_422(tmp_path, monkeypatch):
    """Si debug.json existe mais est corrompu / incomplet -> 422 clean,
    pas un 500."""
    from flox_uploader.core.package_state import init_state
    client = _make_client(tmp_path, monkeypatch)
    name = "Corrupt.2023.VOF.1080p.BluRay.x265-TEAM"
    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text("{not valid json", encoding="utf-8")

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 422


def test_rescore_incomplete_debug_returns_422(tmp_path, monkeypatch):
    """debug.json valide mais sans mediainfo_data -> 422 explicite."""
    from flox_uploader.core.package_state import init_state
    client = _make_client(tmp_path, monkeypatch)
    name = "NoMI.2023.VOF.1080p.BluRay.x265-TEAM"
    pkg = tmp_path / "data" / "upload_packages" / name
    pkg.mkdir(parents=True)
    init_state(pkg, name, "gemini")
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    (debug_dir / "debug.json").write_text(
        json.dumps({"release_name": name}),
        encoding="utf-8",
    )

    r = client.post(f"/api/packages/{name}/rescore")
    assert r.status_code == 422
    assert "mediainfo_data" in r.text.lower() or "incomplet" in r.text.lower()
