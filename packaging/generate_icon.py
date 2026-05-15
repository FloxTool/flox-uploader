"""Genere packaging/icon.ico depuis le logo SVG.

A relancer manuellement quand le logo SVG change :

    python packaging/generate_icon.py

L'icon embarque 7 tailles (16, 24, 32, 48, 64, 128, 256) avec downscale
haute qualite depuis un master 256x256 rasterise par resvg.

Dependances :
- resvg-py (renderer SVG pur Rust, pas de cairo, marche sur Win/Mac/Linux)
- Pillow (assemblage .ico multi-tailles)

Pre-requis pour exec :
    pip install resvg-py Pillow

Le .ico produit est commit dans le repo (binaire ~25KB, OK), donc le build
PyInstaller / Inno Setup peut le reference directement sans regenerer.

Sprint 5g PLAN-V1.md.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

try:
    import resvg_py
    from PIL import Image
except ImportError as e:
    print(f"[ERREUR] Dependance manquante : {e}", file=sys.stderr)
    print("Installer : pip install resvg-py Pillow", file=sys.stderr)
    sys.exit(1)


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SVG_PATH = PROJECT_ROOT / "src" / "flox_uploader" / "web" / "static" / "logo.svg"
ICO_PATH = SCRIPT_DIR / "icon.ico"

# Windows attend au moins 16, 32, 48. On rajoute 24/64/128/256 pour Hi-DPI
# (Windows 10/11 sur monitors 4K, raccourcis grande taille, etc.).
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    if not SVG_PATH.is_file():
        print(f"[ERREUR] SVG source introuvable : {SVG_PATH}", file=sys.stderr)
        return 1

    print(f"[INFO] Source SVG : {SVG_PATH}")
    svg_str = SVG_PATH.read_text(encoding="utf-8")

    # Rasterize un master 256x256. Pillow gere ensuite les downscale qualite
    # vers les autres tailles via le format ICO multi-resolution.
    print("[INFO] Rasterisation master 256x256 via resvg_py...")
    png_bytes = resvg_py.svg_to_bytes(svg_string=svg_str, width=256, height=256)
    master = Image.open(BytesIO(bytes(png_bytes)))
    print(f"[INFO] Master : {master.size}, mode {master.mode}")

    print(f"[INFO] Assemblage .ico avec {len(ICO_SIZES)} tailles...")
    master.save(ICO_PATH, format="ICO", sizes=ICO_SIZES)

    size_bytes = ICO_PATH.stat().st_size
    print(f"[OK] .ico genere : {ICO_PATH}")
    print(f"     taille fichier : {size_bytes} bytes ({size_bytes // 1024} KB)")

    # Verification : le header ICO doit dire qu'on a bien N images
    with ICO_PATH.open("rb") as f:
        header = f.read(6)
    import struct
    _reserved, _type, count = struct.unpack("<HHH", header)
    print(f"     images embarquees : {count}")
    if count != len(ICO_SIZES):
        print(
            f"[WARN] Attendu {len(ICO_SIZES)} images, obtenu {count}. "
            "Verifier la version de Pillow.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
