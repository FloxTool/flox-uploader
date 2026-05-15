"""Telecharge le MediaInfo CLI Windows pour bundling PyInstaller.

Lance ce script AVANT `pyinstaller flox_uploader.spec` pour avoir
`packaging/vendor/mediainfo/MediaInfo.exe` + DLLs prets a etre embarques.

Usage :
    python packaging/fetch_mediainfo_windows.py

Le script :
1. Telecharge le ZIP officiel de MediaInfo CLI Windows depuis mediaarea.net
2. Extrait dans `packaging/vendor/mediainfo/`
3. Verifie que MediaInfo.exe existe

Pourquoi pas une dependance pip ? Parce que `pymediainfo` (pip) est un
WRAPPER Python qui CHARGE la lib MediaInfo.dll system-wide. Sur une machine
sans MediaInfo installé, ça plante. On embarque le binaire pour etre
totalement autonome.

Version pinned : on cible une version stable plutot que "latest" pour
reproductibilite des builds.

Sprint 5 PLAN-V1.md.
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

# Version pinnée : on prend la 24.06 (stable, releases predictables).
# Quand il faudra bumper, verifier sur https://mediaarea.net/MediaInfo/Download/Windows
# que la nouvelle version a le meme schema de packaging "CLI ZIP 64-bit".
MEDIAINFO_VERSION = "24.06"
MEDIAINFO_URL = (
    f"https://mediaarea.net/download/binary/mediainfo/"
    f"{MEDIAINFO_VERSION}/MediaInfo_CLI_{MEDIAINFO_VERSION}_Windows_x64.zip"
)

SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR / "vendor" / "mediainfo"


def fetch_and_extract() -> None:
    print(f"[INFO] Telechargement MediaInfo CLI {MEDIAINFO_VERSION}...")
    print(f"       URL : {MEDIAINFO_URL}")

    try:
        with urllib.request.urlopen(MEDIAINFO_URL, timeout=60) as resp:
            data = resp.read()
    except Exception as e:
        print(f"[ERREUR] Telechargement echoue : {e}", file=sys.stderr)
        print("        Verifie ta connexion ou bumpe MEDIAINFO_VERSION.", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Extraction vers {VENDOR_DIR}...")
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            # On extrait tout (MediaInfo.exe + DLLs + readme)
            # En CLI ZIP, tout est a la racine du ZIP — pas de sous-dossier
            target = VENDOR_DIR / Path(member).name
            if member.endswith("/"):
                continue
            with zf.open(member) as src:
                target.write_bytes(src.read())

    exe = VENDOR_DIR / "MediaInfo.exe"
    if not exe.is_file():
        print(
            f"[ERREUR] MediaInfo.exe absent apres extraction. "
            f"Contenu de {VENDOR_DIR} : {[p.name for p in VENDOR_DIR.iterdir()]}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[OK] MediaInfo.exe pret : {exe}")
    print(f"     Fichiers : {sorted(p.name for p in VENDOR_DIR.iterdir())}")


if __name__ == "__main__":
    fetch_and_extract()
