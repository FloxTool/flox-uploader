"""R3 (audit AUDIT_2026-07-19) : le payload d'un livre envoie un type_id LIVRE
(25-33), pas le type_id VIDEO par defaut (BDRip=3).

Bug : build_upload_payload appelait type_id_for (heuristique video, defaut
BDRip=3) meme pour un livre -> categorie 12 + type 3 = combinaison invalide
cote tracker (rejet). Le cas nominal « l'user ne touche a rien » etait casse.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flox_uploader.core.media_type import MediaType
from flox_uploader.core.package_state import (
    PackageState,
    PackageStateData,
    write_state,
)
from flox_uploader.core.upload_orchestrator import (
    PackageBundle,
    UploadConfig,
    build_upload_payload,
)
from flox_uploader.trackers.gemini import unit3d_mapping as m


def _book_bundle(tmp_path: Path, release_name: str, book_metadata: dict) -> PackageBundle:
    pkg = tmp_path / "book_pkg"
    pkg.mkdir()
    (pkg / "release.torrent").write_bytes(b"d0:e")
    dbg = pkg / "_debug"
    dbg.mkdir()
    (dbg / "debug.json").write_text(
        json.dumps({"book_metadata": book_metadata, "media_type": "book"}),
        encoding="utf-8",
    )
    # Le pipeline livre persiste manual_category_id=12 (mais jamais type_id).
    write_state(
        pkg,
        PackageStateData(
            state=PackageState.PREPARED,
            release_name=release_name,
            manual_category_id=m.CATEGORY_BOOKS,
        ),
    )
    return PackageBundle(
        release_name=release_name,
        package_dir=pkg,
        torrent_path=pkg / "release.torrent",
        nfo_path=None,
        description="desc",
        mediainfo="",
        infohash="abc",
        size_bytes=10 ** 7,
        tmdb_id=0,
        imdb_id=0,
        tvdb_id=0,
        media_type=MediaType.MOVIE,  # peu importe : la categorie manuelle prime
        season_number=0,
        episode_number=0,
        tmdb_genres=[],
    )


_CFG = UploadConfig(api_url="http://x", api_key="k", dry_run=True)
_BOOK_TYPES = {
    m.TYPE_BOOK_M4B, m.TYPE_BOOK_MP3, m.TYPE_BOOK_EBOOK, m.TYPE_BOOK_BD,
    m.TYPE_BOOK_COMICS, m.TYPE_BOOK_MANGAS, m.TYPE_BOOK_MAGAZINE,
    m.TYPE_BOOK_PRESSE, m.TYPE_BOOK_AUDIO,
}


def test_epub_gets_ebook_type(tmp_path):
    b = _book_bundle(tmp_path, "Auteur.Titre.2024.FRENCH.EPUB-NoTAG",
                     {"file_format": "epub"})
    p = build_upload_payload(b, _CFG)
    assert p.category_id == m.CATEGORY_BOOKS
    assert p.type_id == m.TYPE_BOOK_EBOOK
    assert p.type_id in _BOOK_TYPES
    assert p.type_id != m.TYPE_BDRIP  # jamais le defaut video


def test_mp3_audiobook_gets_audio_type(tmp_path):
    b = _book_bundle(tmp_path, "Auteur.Titre.2024.FRENCH.MP3-NoTAG",
                     {"file_format": "mp3"})
    p = build_upload_payload(b, _CFG)
    assert p.type_id in _BOOK_TYPES
    assert p.type_id != m.TYPE_BDRIP


def test_book_unknown_format_falls_back_to_ebook(tmp_path):
    b = _book_bundle(tmp_path, "Auteur.Titre.2024.FRENCH.XYZ-NoTAG",
                     {"file_format": "xyz"})
    p = build_upload_payload(b, _CFG)
    assert p.type_id == m.TYPE_BOOK_EBOOK  # fallback, jamais BDRip


def test_book_manual_type_id_respected(tmp_path):
    """Si l'user force un type_id, on le respecte (pas d'ecrasement)."""
    b = _book_bundle(tmp_path, "Auteur.Titre.2024.FRENCH.CBZ-NoTAG",
                     {"file_format": "cbz"})
    write_state(
        b.package_dir,
        PackageStateData(
            state=PackageState.PREPARED,
            release_name=b.release_name,
            manual_category_id=m.CATEGORY_BOOKS,
            manual_type_id=m.TYPE_BOOK_COMICS,
        ),
    )
    p = build_upload_payload(b, _CFG)
    assert p.type_id == m.TYPE_BOOK_COMICS
