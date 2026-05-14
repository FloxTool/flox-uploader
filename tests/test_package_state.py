"""Tests du module core/package_state.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.package_state import (
    PackageState,
    PackageStateData,
    init_state,
    read_state,
    state_path,
    transition,
    write_state,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    p = tmp_path / "Foo.2024.1080p.BluRay.x265-TEAM"
    p.mkdir()
    return p


# ============================================================
# Init et lecture
# ============================================================

def test_read_state_returns_none_when_no_file(package_dir: Path):
    assert read_state(package_dir) is None


def test_init_state_creates_prepared_state(package_dir: Path):
    data = init_state(package_dir, "Foo.2024", "gemini")
    assert data.state == PackageState.PREPARED
    assert data.release_name == "Foo.2024"
    assert data.tracker_key == "gemini"
    assert data.created_at != ""
    assert data.updated_at != ""
    assert state_path(package_dir).exists()
    assert len(data.history) == 1
    assert data.history[0]["to"] == "prepared"


def test_init_state_idempotent_when_already_advanced(package_dir: Path):
    """Un package deja UPLOADED ne doit pas etre reinitialise."""
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.VALIDATED, note="dedup ok")
    transition(
        package_dir, PackageState.UPLOADED,
        uploaded_torrent_id=42,
        uploaded_torrent_url="https://example.org/t/42",
    )

    # Re-init : on doit recuperer l'etat UPLOADED, pas un PREPARED tout neuf
    data = init_state(package_dir, "Foo", "gemini")
    assert data.state == PackageState.UPLOADED
    assert data.uploaded_torrent_id == 42


def test_init_state_after_failure_resets_to_prepared(package_dir: Path):
    """Un package en FAILED peut etre re-init pour retry depuis le debut."""
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.FAILED, note="erreur reseau", last_error="timeout")

    data = init_state(package_dir, "Foo", "gemini")
    # Retour propre a PREPARED, mais on conserve l'historique.
    assert data.state == PackageState.PREPARED
    assert any(h["to"] == "failed" for h in data.history)


# ============================================================
# Transitions
# ============================================================

def test_transition_prepared_to_validated(package_dir: Path):
    init_state(package_dir, "Foo", "gemini")
    data = transition(
        package_dir, PackageState.VALIDATED,
        note="dedup OK",
        infohash="abc123",
    )
    assert data.state == PackageState.VALIDATED
    assert data.infohash == "abc123"


def test_transition_validated_to_uploaded(package_dir: Path):
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.VALIDATED, infohash="abc")
    data = transition(
        package_dir, PackageState.UPLOADED,
        uploaded_torrent_id=99,
        uploaded_torrent_url="https://example.org/t/99",
        uploaded_at="2026-04-28T12:00:00Z",
    )
    assert data.state == PackageState.UPLOADED
    assert data.uploaded_torrent_id == 99


def test_transition_prepared_to_aborted_duplicate(package_dir: Path):
    init_state(package_dir, "Foo", "gemini")
    data = transition(
        package_dir, PackageState.ABORTED_DUPLICATE,
        note="doublon detecte par infohash",
        existing_torrent_id=7,
        existing_torrent_url="https://example.org/t/7",
    )
    assert data.state == PackageState.ABORTED_DUPLICATE
    assert data.existing_torrent_id == 7


def test_transition_uploaded_is_terminal(package_dir: Path):
    """Un package UPLOADED ne peut pas redescendre vers PREPARED ou VALIDATED."""
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.VALIDATED)
    transition(package_dir, PackageState.UPLOADED, uploaded_torrent_id=1)

    with pytest.raises(ValueError, match="interdite"):
        transition(package_dir, PackageState.PREPARED)
    with pytest.raises(ValueError, match="interdite"):
        transition(package_dir, PackageState.VALIDATED)


def test_transition_uploaded_to_uploaded_is_idempotent(package_dir: Path):
    """Re-ecrire UPLOADED -> UPLOADED ne casse pas (re-write metadata)."""
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.VALIDATED)
    transition(package_dir, PackageState.UPLOADED, uploaded_torrent_id=1)

    # Doit passer sans lever
    data = transition(package_dir, PackageState.UPLOADED, uploaded_torrent_id=1)
    assert data.state == PackageState.UPLOADED


def test_transition_aborted_to_validated_for_force_upload(package_dir: Path):
    """Sur force-upload, on doit pouvoir repasser de ABORTED_DUPLICATE a VALIDATED."""
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.ABORTED_DUPLICATE, existing_torrent_id=42)
    data = transition(
        package_dir, PackageState.VALIDATED, note="force-upload bypass dedup",
    )
    assert data.state == PackageState.VALIDATED


def test_transition_without_init_raises(package_dir: Path):
    with pytest.raises(ValueError, match="aucun state initial"):
        transition(package_dir, PackageState.VALIDATED)


def test_transition_unknown_field_raises(package_dir: Path):
    init_state(package_dir, "Foo", "gemini")
    with pytest.raises(AttributeError):
        transition(package_dir, PackageState.VALIDATED, nonexistent_field=42)


# ============================================================
# Serialisation
# ============================================================

def test_state_roundtrip_via_json(package_dir: Path):
    """Ce qu'on ecrit, on peut le relire et obtenir le meme objet."""
    init_state(package_dir, "Foo", "gemini")
    transition(
        package_dir, PackageState.VALIDATED,
        infohash="deadbeef" * 5,
        note="ok",
    )

    # Le fichier sur disque doit etre du JSON parseable
    raw = state_path(package_dir).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["state"] == "validated"
    assert parsed["infohash"] == "deadbeef" * 5

    # Et la lecture re-construit bien le dataclass
    reread = read_state(package_dir)
    assert reread is not None
    assert reread.state == PackageState.VALIDATED
    assert reread.infohash == "deadbeef" * 5


def test_corrupted_state_file_returns_none(package_dir: Path):
    state_path(package_dir).write_text("{ this is not json", encoding="utf-8")
    assert read_state(package_dir) is None


def test_history_grows_with_transitions(package_dir: Path):
    init_state(package_dir, "Foo", "gemini")
    transition(package_dir, PackageState.VALIDATED, note="dedup ok")
    transition(package_dir, PackageState.UPLOADED, uploaded_torrent_id=1)

    data = read_state(package_dir)
    assert data is not None
    # init + 2 transitions = 3 entries
    assert len(data.history) == 3
    states_in_history = [h["to"] for h in data.history]
    assert states_in_history == ["prepared", "validated", "uploaded"]


def test_recover_creates_corrupted_backup(package_dir: Path):
    """Quand un JSON tronque est repare, l'original doit etre sauvegarde
    en `.corrupted-<timestamp>` avant overwrite (cf. AUDIT.md section 6.6)."""
    # Ecrit un JSON tronque mais avec quelques cles recuperables
    truncated = '{"state": "prepared", "release_name": "Foo", "tracker_key":'
    state_path(package_dir).write_text(truncated, encoding="utf-8")

    recovered = read_state(package_dir)
    assert recovered is not None
    assert recovered.release_name == "Foo"
    # Backup .corrupted-* doit exister
    backups = list(package_dir.glob("package_state.json.corrupted-*"))
    assert len(backups) == 1, f"Attendu 1 backup, trouve {backups}"
    # Et son contenu = le JSON tronque original
    assert backups[0].read_text(encoding="utf-8") == truncated
