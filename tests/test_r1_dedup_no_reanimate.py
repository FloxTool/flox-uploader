"""R1 (audit AUDIT_2026-07-19) : le dedup-check post-prepare ne doit JAMAIS
reanimer un package en etat terminal (FAILED, ABORTED_DUPLICATE, UPLOADED).

Bug d'origine : un package mis en FAILED par la compliance (ex. team bannie
Slay3R) etait repasse en PREPARED une seconde plus tard par _try_dedup_check,
le rendant uploadable. Le corpus contenait 29 packages Slay3R dans ce cas.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.package_state import (
    PackageState,
    init_state,
    read_state,
    transition,
)
from flox_uploader.web.jobs_runner import _try_dedup_check


def _make_package(tmp_path, state: PackageState):
    pkg = tmp_path / "Foo.2024.MULTi.VFF.1080p.WEB-DL.DD5.1.x265-Slay3R"
    pkg.mkdir()
    init_state(pkg, release_name=pkg.name, tracker_key="gemini")
    # Respecte la machine a etats (PREPARED -> VALIDATED -> UPLOADED).
    _PATH = {
        PackageState.PREPARED: [],
        PackageState.FAILED: [PackageState.FAILED],
        PackageState.ABORTED_DUPLICATE: [PackageState.ABORTED_DUPLICATE],
        PackageState.UPLOADED: [PackageState.VALIDATED, PackageState.UPLOADED],
    }
    for step in _PATH[state]:
        transition(pkg, step, note="setup test")
    return pkg


def test_dedup_check_does_not_reanimate_failed(tmp_path, monkeypatch):
    """Un package FAILED reste FAILED apres _try_dedup_check."""
    # Meme si les cles tracker sont presentes, le skip terminal doit primer.
    monkeypatch.setenv("TRACKER_API_URL", "https://example.org/api")
    monkeypatch.setenv("TRACKER_API_KEY", "dummy")
    pkg = _make_package(tmp_path, PackageState.FAILED)

    _try_dedup_check(pkg)

    assert read_state(pkg).state == PackageState.FAILED


def test_dedup_check_does_not_reanimate_aborted_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_API_URL", "https://example.org/api")
    monkeypatch.setenv("TRACKER_API_KEY", "dummy")
    pkg = _make_package(tmp_path, PackageState.ABORTED_DUPLICATE)

    _try_dedup_check(pkg)

    assert read_state(pkg).state == PackageState.ABORTED_DUPLICATE


def test_dedup_check_does_not_reanimate_uploaded(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_API_URL", "https://example.org/api")
    monkeypatch.setenv("TRACKER_API_KEY", "dummy")
    pkg = _make_package(tmp_path, PackageState.UPLOADED)

    _try_dedup_check(pkg)

    assert read_state(pkg).state == PackageState.UPLOADED
