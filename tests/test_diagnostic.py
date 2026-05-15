"""Tests Sprint 8 PLAN-V1 — collecte du diagnostic pour rapport de bug.

Couvre :
- _detect_os_label : mapping platform.system() vers les labels du dropdown bug.yml
- _detect_mediainfo : detection presence + version
- collect_diagnostic : structure du Diagnostic, valeurs coherentes
- build_markdown_report : format Markdown, troncature longs messages, absence de secrets
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from flox_uploader.core import diagnostic as diag


# ============================================================================
# _detect_os_label
# ============================================================================

@pytest.mark.parametrize(
    "platform_system,expected",
    [
        ("Windows", "Windows"),
        ("Darwin", "macOS"),
        ("Linux", "Linux"),
        ("FreeBSD", "Autre"),
        ("", "Autre"),
    ],
)
def test_detect_os_label(platform_system, expected):
    with patch.object(diag.platform, "system", return_value=platform_system):
        assert diag._detect_os_label() == expected


# ============================================================================
# _detect_mediainfo
# ============================================================================

def test_detect_mediainfo_when_binary_missing():
    """`shutil.which` renvoie None -> available=False, version=''."""
    with patch.object(diag.shutil, "which", return_value=None):
        ok, version = diag._detect_mediainfo()
        assert ok is False
        assert version == ""


def test_detect_mediainfo_when_present():
    """Binaire trouve + subprocess retourne version -> available=True."""
    with patch.object(diag.shutil, "which", return_value="/usr/bin/mediainfo"):
        with patch.object(diag.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "MediaInfoLib - v24.06\n"
            mock_run.return_value.stderr = ""
            ok, version = diag._detect_mediainfo()
            assert ok is True
            assert "MediaInfo" in version
            assert "24.06" in version


def test_detect_mediainfo_when_subprocess_fails():
    """Binaire trouve mais --Version retourne non-zero -> available=False."""
    with patch.object(diag.shutil, "which", return_value="/usr/bin/mediainfo"):
        with patch.object(diag.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "error"
            ok, version = diag._detect_mediainfo()
            assert ok is False
            assert version == ""


def test_detect_mediainfo_when_timeout():
    """Timeout subprocess -> available=False, jamais d'exception."""
    with patch.object(diag.shutil, "which", return_value="/usr/bin/mediainfo"):
        with patch.object(
            diag.subprocess, "run",
            side_effect=diag.subprocess.TimeoutExpired("mediainfo", 3),
        ):
            ok, version = diag._detect_mediainfo()
            assert ok is False
            assert version == ""


def test_detect_mediainfo_version_capped_at_80_chars():
    """Une 1ere ligne de version tres longue est tronquee a 80 chars."""
    long_line = "MediaInfoLib " + "x" * 200
    with patch.object(diag.shutil, "which", return_value="/usr/bin/mediainfo"):
        with patch.object(diag.subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = long_line
            mock_run.return_value.stderr = ""
            ok, version = diag._detect_mediainfo()
            assert ok is True
            assert len(version) <= 80


# ============================================================================
# collect_diagnostic
# ============================================================================

def test_collect_diagnostic_structure():
    """Le Diagnostic contient tous les champs attendus, types coherents."""
    d = diag.collect_diagnostic()
    assert isinstance(d.version, str) and d.version
    assert isinstance(d.python_version, str) and d.python_version
    assert d.os in {"Windows", "macOS", "Linux", "Autre"}
    assert isinstance(d.os_release, str)
    assert isinstance(d.mediainfo_available, bool)
    assert isinstance(d.mediainfo_version, str)
    assert isinstance(d.setup_complete, bool)


def test_collect_diagnostic_to_dict_serializable():
    """Le dict est JSON-serializable (utilise par Jinja tojson)."""
    import json
    d = diag.collect_diagnostic()
    serialized = json.dumps(d.to_dict())
    assert json.loads(serialized) == d.to_dict()


def test_collect_diagnostic_keys():
    """Les cles du dict matchent exactement le contrat JS (window.APP_DIAGNOSTIC)."""
    d = diag.collect_diagnostic()
    assert set(d.to_dict().keys()) == {
        "version", "python_version", "os", "os_release",
        "mediainfo_available", "mediainfo_version", "setup_complete",
    }


# ============================================================================
# build_markdown_report
# ============================================================================

def _fake_diagnostic(**overrides) -> diag.Diagnostic:
    base = dict(
        version="0.3.7",
        python_version="3.12.4",
        os="Windows",
        os_release="11",
        mediainfo_available=True,
        mediainfo_version="MediaInfoLib - v24.06",
        setup_complete=True,
    )
    base.update(overrides)
    return diag.Diagnostic(**base)


def test_markdown_report_minimal():
    d = _fake_diagnostic()
    report = diag.build_markdown_report(d)
    assert "## Diagnostic" in report
    assert "0.3.7" in report
    assert "3.12.4" in report
    assert "Windows" in report
    assert "11" in report
    assert "MediaInfoLib - v24.06" in report
    # Pas de section "Contexte" ni "Message" si pas fournis
    assert "## Contexte" not in report
    assert "## Message" not in report


def test_markdown_report_with_page_and_error():
    d = _fake_diagnostic()
    report = diag.build_markdown_report(
        d,
        page_url="/queue",
        error_message="Upload failed: timeout after 30s",
    )
    assert "## Contexte" in report
    assert "/queue" in report
    assert "## Message d'erreur" in report
    assert "timeout after 30s" in report
    # Code block pour l'erreur
    assert "```" in report


def test_markdown_report_truncates_long_error():
    """Un message d'erreur de 5000 chars est tronque a 2000 + suffixe."""
    long_msg = "A" * 5000
    d = _fake_diagnostic()
    report = diag.build_markdown_report(d, error_message=long_msg)
    assert "tronque" in report
    # La portion brute du message dans le rapport ne depasse pas 2050 chars
    # (2000 + le suffixe "... (tronque...)")
    # On compte les 'A' uniquement
    n_a = report.count("A")
    assert n_a == 2000


def test_markdown_report_when_mediainfo_missing():
    d = _fake_diagnostic(mediainfo_available=False, mediainfo_version="")
    report = diag.build_markdown_report(d)
    assert "non detecte" in report.lower()
    assert "PATH" in report  # explique la cause


def test_markdown_report_contains_no_secrets():
    """Sanity check : aucune mention de secrets connus dans le rapport."""
    d = _fake_diagnostic()
    report = diag.build_markdown_report(
        d,
        page_url="/packages/foo",
        error_message="some error",
    )
    forbidden = [
        "TRACKER_API_KEY",
        "TMDB_API_KEY",
        "OMDB_API_KEY",
        "passkey",
        "PASSKEY",
        "/announce/",
    ]
    for needle in forbidden:
        assert needle not in report, f"Secret leak suspect : '{needle}' dans le rapport"
