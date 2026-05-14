"""Test NOTES round 7 : copie auto du .torrent final vers TORRENT_FINAL_DIR."""
from __future__ import annotations

from pathlib import Path

from flox_uploader.core.upload_orchestrator import _copy_to_torrent_final_dir


def test_copy_when_env_set(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src" / "x.torrent"
    src.parent.mkdir()
    src.write_bytes(b"fake torrent bytes")
    dst_dir = tmp_path / "watched"
    monkeypatch.setenv("TORRENT_FINAL_DIR", str(dst_dir))

    _copy_to_torrent_final_dir(src)

    copied = dst_dir / "x.torrent"
    assert copied.exists()
    assert copied.read_bytes() == b"fake torrent bytes"
    out = capsys.readouterr().out
    assert "copie aussi vers" in out


def test_no_op_when_env_empty(tmp_path, monkeypatch):
    src = tmp_path / "x.torrent"
    src.write_bytes(b"x")
    monkeypatch.delenv("TORRENT_FINAL_DIR", raising=False)
    # Ne doit rien faire (pas de plantage)
    _copy_to_torrent_final_dir(src)


def test_rejects_relative_path(tmp_path, monkeypatch, capsys):
    src = tmp_path / "x.torrent"
    src.write_bytes(b"x")
    monkeypatch.setenv("TORRENT_FINAL_DIR", "relative/path")
    _copy_to_torrent_final_dir(src)
    out = capsys.readouterr().out
    assert "absolu" in out.lower()


def test_creates_target_dir_if_missing(tmp_path, monkeypatch):
    src = tmp_path / "x.torrent"
    src.write_bytes(b"x")
    target = tmp_path / "deep" / "nested" / "dir"
    monkeypatch.setenv("TORRENT_FINAL_DIR", str(target))
    _copy_to_torrent_final_dir(src)
    assert (target / "x.torrent").exists()
