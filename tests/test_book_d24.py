"""Tests Sprint D.24 v0.5.0 — Cover backup depuis fichier cover.* du dossier source.

Cible note Louis N-LS1 : "Decoupe en tranches (10354) dans ce release
on a un fichier 'cover' on peut l'utiliser en backup et l'heberger sur IMGBB."

Verifie que _find_folder_cover detecte les fichiers cover.jpg / couverture.jpg
/ front.png / folder.jpg etc. dans le dossier source du livre, et les
prefere a la cover extraite du fichier ebook.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ============================================================
# _find_folder_cover
# ============================================================

def test_find_folder_cover_jpg_next_to_file(tmp_path):
    """Fichier book.pdf avec cover.jpg dans le meme dossier."""
    from flox_uploader.pipeline import _find_folder_cover

    source_dir = tmp_path / "Decoupe en tranches"
    source_dir.mkdir()
    pdf = source_dir / "Decoupe.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    cover = source_dir / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0jpeg_data")

    output_dir = tmp_path / "out"
    result = _find_folder_cover(pdf, output_dir)
    assert result is not None
    assert result.is_file()
    assert result.read_bytes() == b"\xff\xd8\xff\xe0jpeg_data"


def test_find_folder_cover_couverture(tmp_path):
    """couverture.png est aussi reconnu."""
    from flox_uploader.pipeline import _find_folder_cover

    src = tmp_path / "src"
    src.mkdir()
    epub = src / "book.epub"
    epub.write_bytes(b"PK fake epub")
    cover = src / "couverture.png"
    cover.write_bytes(b"\x89PNGfake")

    output_dir = tmp_path / "out"
    result = _find_folder_cover(epub, output_dir)
    assert result is not None
    assert result.read_bytes() == b"\x89PNGfake"


def test_find_folder_cover_folder_input(tmp_path):
    """Si on passe un dossier (pas un fichier), on cherche dedans."""
    from flox_uploader.pipeline import _find_folder_cover

    src = tmp_path / "LARGO_WINCH"
    src.mkdir()
    (src / "front.jpg").write_bytes(b"\xff\xd8\xff jpeg")
    # Quelques autres fichiers (pour s'assurer qu'on prend juste cover)
    (src / "book.epub").write_bytes(b"epub")
    (src / "readme.txt").write_text("txt")

    output_dir = tmp_path / "out"
    result = _find_folder_cover(src, output_dir)
    assert result is not None
    assert result.read_bytes() == b"\xff\xd8\xff jpeg"


def test_find_folder_cover_none_returns_none(tmp_path):
    """Pas de fichier cover.* -> None."""
    from flox_uploader.pipeline import _find_folder_cover

    src = tmp_path / "src"
    src.mkdir()
    (src / "book.pdf").write_bytes(b"pdf")
    # PAS de cover

    output_dir = tmp_path / "out"
    assert _find_folder_cover(src / "book.pdf", output_dir) is None


def test_find_folder_cover_ignores_random_image(tmp_path):
    """Une image random (sample.jpg) ne doit PAS etre prise comme cover."""
    from flox_uploader.pipeline import _find_folder_cover

    src = tmp_path / "src"
    src.mkdir()
    (src / "book.pdf").write_bytes(b"pdf")
    (src / "sample.jpg").write_bytes(b"random image")
    (src / "screenshot.png").write_bytes(b"random screenshot")

    output_dir = tmp_path / "out"
    # Ni sample.jpg ni screenshot.png ne matchent _COVER_BACKUP_STEMS
    assert _find_folder_cover(src / "book.pdf", output_dir) is None


def test_find_folder_cover_case_insensitive(tmp_path):
    """COVER.JPG / Cover.JPG / coVeR.jpg : tous reconnus."""
    from flox_uploader.pipeline import _find_folder_cover

    # On utilise un index pour les dossiers car Windows est case-insensitive
    for idx, variant in enumerate(["COVER.JPG", "Cover.Jpg", "Couv.png", "FRONT.webp"]):
        src = tmp_path / f"variant_{idx}"
        src.mkdir()
        (src / "book.pdf").write_bytes(b"pdf")
        (src / variant).write_bytes(b"image_data")

        output_dir = tmp_path / f"out_{idx}"
        result = _find_folder_cover(src / "book.pdf", output_dir)
        assert result is not None, f"variant {variant} non reconnue"


def test_find_folder_cover_copies_not_links(tmp_path):
    """La cover est COPIEE, pas hard-linkee, pour eviter ref vers source disparue."""
    from flox_uploader.pipeline import _find_folder_cover

    src = tmp_path / "src"
    src.mkdir()
    (src / "book.epub").write_bytes(b"epub")
    cover_src = src / "cover.jpg"
    cover_src.write_bytes(b"original")

    output_dir = tmp_path / "out"
    result = _find_folder_cover(src / "book.epub", output_dir)
    assert result is not None

    # Modifier l'original ne doit PAS affecter la copie
    cover_src.write_bytes(b"modified")
    assert result.read_bytes() == b"original"
