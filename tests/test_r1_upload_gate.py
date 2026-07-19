"""R1 (audit AUDIT_2026-07-19) : garde-fous a l'upload.

1. get_blocking_compliance_messages relit les violations BLOQUANTES persistees.
2. upload_package refuse un package non conforme (defense en profondeur).
3. resolve_torrent_path trouve un .torrent au nom raccourci (fix D.46 pour la
   route web : plus de faux 409 "doublon CERTAIN" sur les 52 packages du corpus).
"""
from __future__ import annotations

import json

from flox_uploader.core.package_state import (
    PackageState,
    init_state,
    read_state,
    transition,
)
from flox_uploader.core.upload_orchestrator import (
    UploadConfig,
    get_blocking_compliance_messages,
    resolve_torrent_path,
    upload_package,
)


def _write_debug(pkg, blocking):
    dbg = pkg / "_debug"
    dbg.mkdir(exist_ok=True)
    (dbg / "debug.json").write_text(
        json.dumps({"blocking_compliance_messages": blocking}),
        encoding="utf-8",
    )


def test_get_blocking_compliance_messages_reads_debug(tmp_path):
    pkg = tmp_path / "Foo-Slay3R"
    pkg.mkdir()
    _write_debug(pkg, ["Team 'Slay3R' interdite par le tracker G3MINI."])
    msgs = get_blocking_compliance_messages(pkg)
    assert msgs == ["Team 'Slay3R' interdite par le tracker G3MINI."]


def test_get_blocking_compliance_messages_empty_when_none(tmp_path):
    pkg = tmp_path / "Foo-NoTAG"
    pkg.mkdir()
    _write_debug(pkg, [])
    assert get_blocking_compliance_messages(pkg) == []


def test_upload_package_refuses_blocking(tmp_path):
    """Un package avec compliance bloquante ne part pas, meme en dry_run."""
    pkg = tmp_path / "Bad.2024.MULTi.VFF.1080p.WEB.x264-Slay3R"
    pkg.mkdir()
    (pkg / "release_name.txt").write_text(pkg.name, encoding="utf-8")
    init_state(pkg, pkg.name, "gemini")
    _write_debug(pkg, ["Team 'Slay3R' interdite par le tracker G3MINI."])

    cfg = UploadConfig(
        api_url="https://example.org/api", api_key="dummy",
        dry_run=True, force_upload=False, force_existing_id=None,
    )
    outcome = upload_package(pkg, cfg)
    assert outcome.final_state == PackageState.FAILED
    assert "conforme" in outcome.message.lower() or "charte" in outcome.message.lower()
    assert read_state(pkg).state == PackageState.FAILED


def test_resolve_torrent_path_exact(tmp_path):
    pkg = tmp_path / "Movie.2024.MULTi.VFF.1080p.BluRay.x265-TEAM"
    pkg.mkdir()
    (pkg / f"{pkg.name}.torrent").write_bytes(b"d0:e")
    found = resolve_torrent_path(pkg, pkg.name)
    assert found is not None and found.name == f"{pkg.name}.torrent"


def test_resolve_torrent_path_shortened_single(tmp_path):
    """Fix D.46 : nom raccourci Windows MAX_PATH -> resolu via le fallback."""
    pkg = tmp_path / "Back.To.The.Future.Part.III.1990.MULTi.VFF.2160p.x265-QTZ"
    pkg.mkdir()
    # Nom physique raccourci (differe du release_name complet).
    (pkg / "Back.To.The.Future.Part.III.199MULTFF.torrent").write_bytes(b"d0:e")
    found = resolve_torrent_path(pkg, pkg.name)
    assert found is not None
    assert found.suffix == ".torrent"


def test_resolve_torrent_path_none_when_missing(tmp_path):
    pkg = tmp_path / "Empty.2024.MULTi.VFF.1080p.x265-TEAM"
    pkg.mkdir()
    assert resolve_torrent_path(pkg, pkg.name) is None


def test_resolve_torrent_path_none_when_ambiguous(tmp_path):
    pkg = tmp_path / "Ambig.2024.MULTi.VFF.1080p.x265-TEAM"
    pkg.mkdir()
    (pkg / "a.torrent").write_bytes(b"d0:e")
    (pkg / "b.torrent").write_bytes(b"d0:e")
    assert resolve_torrent_path(pkg, pkg.name) is None
