#!/usr/bin/env python3
"""Regenere le bloc chiffre de docs/STATUS.md (R6, audit 2026-07-19).

La doc ne peut structurellement plus mentir sur ces chiffres : ils sont
calcules depuis le repo (version pyproject, tag git, nombre de tests
collectes, nombre de routes, taille du corpus dev) et injectes entre les
marqueurs <!-- AUTO:START --> / <!-- AUTO:END --> de docs/STATUS.md.

Usage :
    python scripts/status_snapshot.py            # met a jour docs/STATUS.md
    python scripts/status_snapshot.py --check    # exit 1 si le bloc est perime

Sans dependance externe (stdlib), fonctionne sous Windows.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "STATUS.md"
_MARK_START = "<!-- AUTO:START -->"
_MARK_END = "<!-- AUTO:END -->"


def _version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    return m.group(1) if m else "?"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _last_tag() -> str:
    return _git("describe", "--tags", "--abbrev=0") or "(aucun tag)"


def _test_count() -> int:
    """Nombre de tests collectes (pytest --collect-only)."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
    except Exception:
        return -1
    total = 0
    for line in out.stdout.splitlines():
        m = re.match(r"^tests/.*: (\d+)$", line.strip())
        if m:
            total += int(m.group(1))
    return total


def _route_count() -> int:
    app = ROOT / "src" / "flox_uploader" / "web" / "app.py"
    if not app.is_file():
        return -1
    text = app.read_text(encoding="utf-8")
    return len(re.findall(r"@app\.(get|post|delete|put|patch)\(", text))


def _corpus_count() -> int:
    pkgs = ROOT / "data" / "upload_packages"
    if not pkgs.is_dir():
        return 0
    return sum(1 for p in pkgs.iterdir() if (p / "package_state.json").is_file())


def _build_block() -> str:
    return "\n".join([
        _MARK_START,
        f"- **Version** : {_version()}",
        f"- **Dernier tag git** : {_last_tag()}",
        f"- **Tests collectés** : {_test_count()}",
        f"- **Routes API (`web/app.py`)** : {_route_count()}",
        f"- **Packages corpus dev** : {_corpus_count()}",
        _MARK_END,
    ])


def _apply(check: bool) -> int:
    block = _build_block()
    if STATUS.is_file():
        content = STATUS.read_text(encoding="utf-8")
        if _MARK_START in content and _MARK_END in content:
            new = re.sub(
                re.escape(_MARK_START) + r".*?" + re.escape(_MARK_END),
                block, content, flags=re.DOTALL,
            )
        else:
            new = content.rstrip() + "\n\n" + block + "\n"
    else:
        new = "# STATUS — état courant (auto)\n\n" + block + "\n"

    if check:
        current = STATUS.read_text(encoding="utf-8") if STATUS.is_file() else ""
        if current != new:
            print("docs/STATUS.md est perime — relance : python scripts/status_snapshot.py",
                  file=sys.stderr)
            return 1
        return 0

    tmp = STATUS.with_suffix(".md.tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(STATUS)
    print(f"docs/STATUS.md mis a jour.\n{block}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_apply(check="--check" in sys.argv))
