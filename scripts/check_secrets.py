#!/usr/bin/env python3
"""Scan de secrets — garde-fou pre-commit (R2, audit 2026-07-19).

Empeche qu'une cle API / passkey en clair reparte dans un commit (cas reel :
la cle imgbb committee dans NOTES.md sur le repo public FloxTool).

Usage :
    python scripts/check_secrets.py                 # scanne les fichiers stages
    python scripts/check_secrets.py fichier1 ...    # scanne des fichiers precis
    python scripts/check_secrets.py --all           # scanne tous les fichiers suivis

Sortie : code 0 si rien, 1 si un secret probable est detecte (avec fichier:ligne).
Sans dependance externe (stdlib uniquement), fonctionne sous Windows.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Extensions ou un secret en clair est un vrai risque (docs/config/data).
# On NE scanne PAS le code Python : les 32-hex y sont massivement des
# infohashes / md5 de test (faux positifs garantis).
_TEXT_EXTS = {".md", ".txt", ".json", ".env", ".ini", ".cfg", ".yaml", ".yml", ".toml"}

# Fichiers/paths a ignorer (exemples, gabarits, ce script lui-meme).
_SKIP_SUBSTR = (
    ".env.example", "check_secrets.py", "_extracted/", "gemini/",
    "package-lock", "poetry.lock",
)

# Marqueurs qui prouvent qu'une valeur est un PLACEHOLDER, pas un vrai secret.
_ALLOW_MARKERS = (
    "…", "...", "<", ">", "••", "xxxx", "XXXX", "example", "exemple",
    "redact", "your_", "YOUR_", "changeme", "placeholder",
)

# --- Motifs de detection ---
# A. 32 caracteres hex isoles (cle TMDB v3, cle imgbb) dans un fichier texte.
_RE_HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
# B. Passkey dans une URL announce.
_RE_ANNOUNCE = re.compile(r"announce/[0-9A-Za-z]{16,}", re.IGNORECASE)
# C. Affectation KEY = <valeur qui ressemble a un secret>. Le nom de cle peut
#    avoir un prefixe (IMGBB_API_KEY, TRACKER_API_KEY) -> on tolere [A-Za-z0-9_]*
#    devant le mot-cle.
_RE_ASSIGN = re.compile(
    r"(?i)([A-Za-z0-9_]*(?:api[_-]?key|apikey|passkey|secret|token|client[_-]?id))"
    r"\s*[=:]\s*['\"]?([A-Za-z0-9._\-]{16,})"
)


def _looks_placeholder(line: str, value: str) -> bool:
    hay = line + " " + value
    return any(m in hay for m in _ALLOW_MARKERS)


def _scan_text(rel: str, text: str) -> list[str]:
    hits: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _RE_ANNOUNCE.search(line) and not _looks_placeholder(line, line):
            hits.append(f"{rel}:{i}: passkey probable dans une URL announce")
            continue
        m = _RE_ASSIGN.search(line)
        if m and not _looks_placeholder(line, m.group(2)):
            hits.append(f"{rel}:{i}: valeur secrete affectee a '{m.group(1)}'")
            continue
        # 32-hex : on ne flag QUE le cas "cle seule sur sa ligne" (exactement
        # la forme du leak imgbb committe). Un 32-hex noye dans une URL/phrase
        # est presque toujours un exemple (delete_url imgbb, infohash de
        # changelog) -> pas un secret a nous.
        stripped = line.strip()
        if _RE_HEX32.fullmatch(stripped) and not _looks_placeholder(line, stripped):
            hits.append(f"{rel}:{i}: cle 32-hex isolee (cle API ?) : {stripped[:6]}…")
    return hits


def _staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True,
    )
    return [f for f in out.stdout.splitlines() if f.strip()]


def _all_tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    return [f for f in out.stdout.splitlines() if f.strip()]


def main(argv: list[str]) -> int:
    if "--all" in argv:
        files = _all_tracked_files()
    elif len(argv) > 1:
        files = argv[1:]
    else:
        files = _staged_files()

    all_hits: list[str] = []
    for f in files:
        rel = f.replace("\\", "/")
        if any(s in rel for s in _SKIP_SUBSTR):
            continue
        p = Path(f)
        if p.suffix.lower() not in _TEXT_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue
        all_hits.extend(_scan_text(rel, text))

    if all_hits:
        print("SECRET PROBABLE DETECTE — commit bloque :", file=sys.stderr)
        for h in all_hits:
            print("  " + h, file=sys.stderr)
        print(
            "\nRetire le secret (utilise .env / la page Config), ou si c'est un "
            "faux positif ajoute un marqueur placeholder (<...>, …, example).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
