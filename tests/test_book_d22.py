"""Tests Sprint D.22 v0.5.0 — EPUB previews + HTML cleanup + img=250.

Cible notes Louis :
- B1 : Extraction d'images des EPUB illustrés (BDs en EPUB, Petit Futé,
  livres avec photos). Avant : EPUB cover seule, pas de previews.
- N-R5 : Description epub avec '<div><p>...</p></div>' apparait verbatim
  dans la fiche BBCode. Maintenant : nettoyée via strip_html.
- N-UX1 : Previews BBCode taille 250 au lieu de 150 pour mieux voir.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


# ============================================================
# B1 — EPUB previews extraction
# ============================================================

def _make_epub_with_images(path: Path, image_count: int = 5) -> None:
    """Helper : EPUB minimal avec cover + N images embedded."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>""")
        # OPF avec cover declaree
        zf.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Test EPUB Illustré</dc:title>
        <meta name="cover" content="cover-img"/>
    </metadata>
    <manifest>
        <item id="cover-img" href="cover.jpg" media-type="image/jpeg"/>
    </manifest>
</package>""")
        zf.writestr("OEBPS/cover.jpg", b"\xff\xd8\xff\xe0epub_cover_data")
        # Ajoute N images d'illustration
        for i in range(image_count):
            name = f"OEBPS/images/img_{i:03d}.jpg"
            zf.writestr(name, b"\xff\xd8\xff\xe0" + bytes([i % 256]))


def test_extract_epub_cover_and_previews(tmp_path):
    """EPUB illustré : cover + N previews depuis les images embedded."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    epub = tmp_path / "illustrated.epub"
    _make_epub_with_images(epub, image_count=10)
    out = tmp_path / "previews"

    result = extract_cover_and_previews(epub, out, preview_count=4)
    assert result["cover"] is not None
    assert result["cover"].is_file()
    # Maintenant on a des previews (au lieu de [] avant D.22)
    assert len(result["previews"]) > 0, "EPUB illustré doit avoir des previews"
    assert len(result["previews"]) <= 4


def test_extract_epub_text_only_no_previews(tmp_path):
    """EPUB roman texte pur : cover seule, pas de previews (pas d'illustration)."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    epub = tmp_path / "text.epub"
    _make_epub_with_images(epub, image_count=0)  # 0 images embedded
    out = tmp_path / "previews"

    result = extract_cover_and_previews(epub, out, preview_count=4)
    assert result["cover"] is not None
    # 0 previews car aucune image autre que la cover
    assert result["previews"] == []


def test_extract_epub_excludes_cover_from_previews(tmp_path):
    """La cover.jpg n'apparait pas dans les previews (deduplication)."""
    from flox_uploader.core.providers.image_extraction import (
        extract_cover_and_previews,
    )
    epub = tmp_path / "test.epub"
    _make_epub_with_images(epub, image_count=8)
    out = tmp_path / "previews"

    result = extract_cover_and_previews(epub, out, preview_count=4)
    if result["previews"]:
        # Aucune preview ne doit etre identique a la cover
        cover_data = result["cover"].read_bytes()
        for p in result["previews"]:
            assert p.read_bytes() != cover_data, (
                f"Preview {p.name} == cover (deduplication a echoue)"
            )


# ============================================================
# N-R5 — HTML cleanup EPUB description
# ============================================================

def _make_epub_with_html_description(path: Path, description: str) -> None:
    """EPUB avec description HTML dans dc:description."""
    import html as _html
    escaped_desc = _html.escape(description, quote=False)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>""")
        opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Test</dc:title>
        <dc:description>{escaped_desc}</dc:description>
    </metadata>
    <manifest/>
</package>"""
        zf.writestr("OEBPS/content.opf", opf)


def test_epub_description_html_stripped(tmp_path):
    """L'EPUB dc:description contenant du HTML doit etre nettoyé."""
    from flox_uploader.core.providers.epub_metadata import (
        extract_epub_metadata,
    )
    epub = tmp_path / "test.epub"
    # Cas reel Louis N-R5
    polluted = "<div><p>Quand le c... sans l'autre.</p></div>"
    _make_epub_with_html_description(epub, polluted)

    meta = extract_epub_metadata(epub)
    # Le HTML doit etre retire
    assert "<div>" not in meta.description
    assert "<p>" not in meta.description
    assert "</p>" not in meta.description
    assert "</div>" not in meta.description
    # Le contenu doit rester
    assert "Quand le c" in meta.description
    assert "autre" in meta.description


def test_epub_description_already_plain_unchanged(tmp_path):
    """Une description deja en plain text passe inchangee."""
    from flox_uploader.core.providers.epub_metadata import (
        extract_epub_metadata,
    )
    epub = tmp_path / "test.epub"
    _make_epub_with_html_description(epub, "Resume simple sans HTML.")

    meta = extract_epub_metadata(epub)
    assert "Resume simple sans HTML" in meta.description


# ============================================================
# N-UX1 — Previews BBCode [img=250]
# ============================================================

def test_bbcode_uses_img250_for_previews(monkeypatch):
    """Les previews dans le BBCode doivent etre [img=250] (pas 150)."""
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    from flox_uploader.core.bbcode_book import render_book_bbcode
    from flox_uploader.core.providers.book_metadata import BookMetadata
    from flox_uploader.trackers import get_tracker

    tracker = get_tracker("gemini", "https://test.tracker/announce/passkey")
    meta = BookMetadata(
        title="T", authors=["A"], file_format="cbz",
        preview_urls=[
            "https://i.ibb.co/1.jpg",
            "https://i.ibb.co/2.jpg",
        ],
    )
    bbcode = render_book_bbcode(meta, "Rel", tracker)
    # Previews [img=250]
    assert "[img=250]https://i.ibb.co/1.jpg[/img]" in bbcode
    assert "[img=250]https://i.ibb.co/2.jpg[/img]" in bbcode
    # PLUS de [img=150] (regression check : on n'a pas oublie d'en changer)
    assert "[img=150]https://i.ibb.co" not in bbcode
