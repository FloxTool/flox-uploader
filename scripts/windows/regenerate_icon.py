"""Régénère scripts/windows/flox_icon.ico depuis le logo SVG officiel.

Sprint D.45 v0.5.0 - le logo de référence est `src/flox_uploader/web/static/logo.svg`
(le « F » Flox indigo, celui de la sidebar de l'app). On l'utilise comme source
unique de vérité pour éviter la divergence avec d'anciens PNG.

Usage :
    .venv/Scripts/python.exe scripts/windows/regenerate_icon.py

Pré-requis : Pillow + PyMuPDF (déjà dans pyproject.toml).
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image


# Source de vérité unique : le SVG officiel de la sidebar web.
ROOT = Path(__file__).resolve().parents[2]
SVG_SOURCE = ROOT / "src" / "flox_uploader" / "web" / "static" / "logo.svg"
ICO_TARGET = Path(__file__).parent / "flox_icon.ico"


def main() -> int:
    if not SVG_SOURCE.is_file():
        raise SystemExit(f"SVG source introuvable : {SVG_SOURCE}")

    # Rendre le SVG en PNG haute résolution via PyMuPDF
    doc = fitz.open(str(SVG_SOURCE))
    page = doc.load_page(0)
    rect = page.rect
    target_size = 1024
    zoom = target_size / max(rect.width, rect.height)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
    png_bytes = pix.tobytes("png")
    doc.close()

    # Pad to square (les ICO doivent être carrés)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    w, h = img.size
    size = max(w, h)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(img, ((size - w) // 2, (size - h) // 2))

    # Multi-résolution Windows standard
    square.save(
        ICO_TARGET,
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icone regeneree : {ICO_TARGET}")
    print(f"  Source : {SVG_SOURCE.name}")
    print(f"  Resolutions : 16/32/48/64/128/256 px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
