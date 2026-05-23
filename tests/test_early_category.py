"""Tests Sprint A v0.5.0 PR-2 : early_category_guess().

Verifie la fonction qui devine la categorie Gemini d'un fichier d'entree
juste a partir du path + d'un hint user optionnel. Pure fonction, aucun
side-effect, aucun appel reseau, aucune dependance MediaInfo.

Cf. PLAN-MULTICAT.md §5.1 (Etape 0).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.early_category import (
    _first_file_extension,
    early_category_guess,
)
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_SOFTWARE,
    CATEGORY_TV, CATEGORY_TV_SHOW,
)


# ============================================================
# Priorite 1 : hint user prioritaire
# ============================================================

def test_hint_user_wins_over_extension(tmp_path):
    """Si l'user choisit une categorie explicitement, on ne devine pas."""
    fake_video = tmp_path / "movie.mkv"
    fake_video.write_bytes(b"")
    # L'extension dirait "video", mais l'user dit "livre" -> on respecte.
    assert early_category_guess(fake_video, category_hint=CATEGORY_BOOKS) == CATEGORY_BOOKS


def test_hint_user_zero_or_negative_is_ignored(tmp_path):
    """category_hint = 0 ou negatif est traite comme 'pas de hint'."""
    fake_video = tmp_path / "movie.mkv"
    fake_video.write_bytes(b"")
    # 0 = pas de hint -> on retombe sur la detection par extension
    assert early_category_guess(fake_video, category_hint=0) == CATEGORY_MOVIE
    assert early_category_guess(fake_video, category_hint=-1) == CATEGORY_MOVIE


def test_hint_user_unknown_id_passthrough(tmp_path):
    """Un hint id 'invalide' (cat inexistante) passe quand meme.

    On ne valide pas la cat ici — c'est la responsabilite de l'UI Inbox de
    proposer uniquement des cats valides. La fonction reste passthrough.
    """
    fake = tmp_path / "movie.mkv"
    fake.write_bytes(b"")
    assert early_category_guess(fake, category_hint=9999) == 9999


# ============================================================
# Priorite 2 : detection par extension
# ============================================================

@pytest.mark.parametrize("filename,expected_cat", [
    # Video -> CATEGORY_MOVIE par defaut (TMDB raffinera en cat 2/6/7/13/14/15)
    ("Movie.2024.mkv", CATEGORY_MOVIE),
    ("Show.S01E01.mp4", CATEGORY_MOVIE),
    ("Sport.avi", CATEGORY_MOVIE),
    ("Video.ts", CATEGORY_MOVIE),
    ("Concert.m2ts", CATEGORY_MOVIE),
    ("Capture.mov", CATEGORY_MOVIE),
    ("BluRay.iso", CATEGORY_MOVIE),  # ambiguite assumee -> video par defaut

    # Livres / Ebooks
    ("Tolkien.epub", CATEGORY_BOOKS),
    ("Document.pdf", CATEGORY_BOOKS),
    ("Book.mobi", CATEGORY_BOOKS),
    ("Kindle.azw3", CATEGORY_BOOKS),
    ("OldEbook.djvu", CATEGORY_BOOKS),
    ("Comic.cbz", CATEGORY_BOOKS),
    ("Manga.cbr", CATEGORY_BOOKS),
    ("Audiobook.m4b", CATEGORY_BOOKS),

    # Logiciels
    ("Setup.exe", CATEGORY_SOFTWARE),
    ("Installer.msi", CATEGORY_SOFTWARE),
    ("MacApp.dmg", CATEGORY_SOFTWARE),
    ("Package.pkg", CATEGORY_SOFTWARE),
    ("Software.deb", CATEGORY_SOFTWARE),
    ("Linux.appimage", CATEGORY_SOFTWARE),
])
def test_extension_maps_to_correct_category(tmp_path, filename, expected_cat):
    fake = tmp_path / filename
    fake.write_bytes(b"")
    assert early_category_guess(fake) == expected_cat


def test_case_insensitive_extension(tmp_path):
    """L'extension doit etre matchee insensible a la casse."""
    upper = tmp_path / "Book.EPUB"
    upper.write_bytes(b"")
    assert early_category_guess(upper) == CATEGORY_BOOKS


# ============================================================
# Priorite 3 : fallback retro-compatible
# ============================================================

def test_unknown_extension_falls_back_to_movie(tmp_path):
    """Une extension inconnue retombe sur CATEGORY_MOVIE (comportement v0.3.x)."""
    fake = tmp_path / "weird.xyz"
    fake.write_bytes(b"")
    assert early_category_guess(fake) == CATEGORY_MOVIE


def test_no_extension_falls_back_to_movie(tmp_path):
    """Un fichier sans extension retombe sur CATEGORY_MOVIE."""
    fake = tmp_path / "fichier_sans_ext"
    fake.write_bytes(b"")
    assert early_category_guess(fake) == CATEGORY_MOVIE


def test_nonexistent_path_falls_back_to_movie(tmp_path):
    """Un path inexistant ne plante pas, fallback CATEGORY_MOVIE.

    Important : `early_category_guess` doit etre robuste — il est appele AVANT
    toute validation, et la suite du pipeline va gerer le path inexistant
    proprement via detect_media_type.
    """
    fake = tmp_path / "n_existe_pas.mkv"
    # On ne cree pas le fichier.
    # Note : meme si le fichier n'existe pas, l'extension est connue -> on
    # retourne CATEGORY_MOVIE par .mkv. C'est OK.
    assert early_category_guess(fake) == CATEGORY_MOVIE


def test_nonexistent_path_unknown_ext_falls_back_to_movie(tmp_path):
    """Path inexistant + extension inconnue = fallback robuste."""
    fake = tmp_path / "ghost.xyz"
    assert early_category_guess(fake) == CATEGORY_MOVIE


# ============================================================
# Detection dans un dossier (premier fichier non-cache)
# ============================================================

def test_directory_uses_first_alphabetical_file(tmp_path):
    """Un dossier d'entree => on inspecte le premier fichier (ordre alpha)."""
    folder = tmp_path / "MyShow.S01"
    folder.mkdir()
    (folder / "MyShow.S01E01.mkv").write_bytes(b"")
    (folder / "MyShow.S01E02.mkv").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_MOVIE


def test_directory_with_books_detected(tmp_path):
    """Un dossier qui contient un .epub est detecte comme livre."""
    folder = tmp_path / "TolkienComplete"
    folder.mkdir()
    (folder / "01-Hobbit.epub").write_bytes(b"")
    (folder / "02-Lord-of-the-Rings.epub").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS


def test_directory_skips_hidden_files(tmp_path):
    """Les fichiers caches (commencant par .) sont ignores pour l'inspection."""
    folder = tmp_path / "Album"
    folder.mkdir()
    (folder / ".DS_Store").write_bytes(b"")     # cache, doit etre ignore
    (folder / "Book.epub").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS


def test_empty_directory_falls_back_to_movie(tmp_path):
    """Un dossier vide => fallback CATEGORY_MOVIE (le pipeline plantera plus tard)."""
    folder = tmp_path / "Empty"
    folder.mkdir()
    assert early_category_guess(folder) == CATEGORY_MOVIE


# ============================================================
# Sprint A.4 : scan dossier intelligent (ignore satellites)
# ============================================================
# Cas reel rapporte par Louis (test PR-3) : un dossier ebook contient
# souvent cover.jpg + le .pdf (ou autres satellites Calibre .opf, .nfo).
# Avant le fix, l'algo prenait .jpg en premier (ordre alpha avant .pdf),
# fallback movie, puis plantait avec un message generique.

def test_directory_with_cover_and_book_detects_book(tmp_path):
    """Dossier ebook typique : cover.jpg + .pdf -> on detecte LIVRE."""
    folder = tmp_path / "Decoupe en tranches (10354)"
    folder.mkdir()
    (folder / "Cover.jpg").write_bytes(b"")
    (folder / "Decoupe en tranches - Zep.pdf").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS, (
        "Le .jpg satellite ne doit pas masquer le .pdf qui definit la categorie"
    )


def test_directory_with_calibre_metadata_detects_book(tmp_path):
    """Calibre genere souvent metadata.opf + cover.jpg + le .epub."""
    folder = tmp_path / "Tolkien - Hobbit"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(b"")
    (folder / "metadata.opf").write_bytes(b"")
    (folder / "Tolkien_Hobbit.epub").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS


def test_directory_with_only_satellites_falls_back_to_movie(tmp_path):
    """Dossier ne contenant que des satellites -> fallback CATEGORY_MOVIE."""
    folder = tmp_path / "OnlyCovers"
    folder.mkdir()
    (folder / "cover1.jpg").write_bytes(b"")
    (folder / "cover2.png").write_bytes(b"")
    (folder / "info.nfo").write_bytes(b"")
    # Pas de fichier de contenu reel -> on tombe sur le fallback
    assert early_category_guess(folder) == CATEGORY_MOVIE


def test_directory_with_video_and_satellites_detects_video(tmp_path):
    """Dossier release scene : poster.jpg + .nfo + .mkv -> VIDEO."""
    folder = tmp_path / "Movie.2024.1080p.BluRay.x265-TEAM"
    folder.mkdir()
    (folder / "poster.jpg").write_bytes(b"")
    (folder / "release.nfo").write_bytes(b"")
    (folder / "movie.mkv").write_bytes(b"")
    (folder / "subs.srt").write_bytes(b"")  # sous-titre externe satellite
    assert early_category_guess(folder) == CATEGORY_MOVIE


def test_directory_with_nested_book(tmp_path):
    """Dossier avec sous-dossier contenant l'ebook -> scan recursif."""
    folder = tmp_path / "Collection"
    sub = folder / "Tome1"
    sub.mkdir(parents=True)
    (sub / "cover.jpg").write_bytes(b"")
    (sub / "tome1.epub").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS


def test_directory_with_software_installer_and_readme(tmp_path):
    """Dossier logiciel typique : readme.txt + .exe -> LOGICIEL."""
    folder = tmp_path / "MySoft v1.0"
    folder.mkdir()
    (folder / "readme.txt").write_bytes(b"")  # satellite
    (folder / "Setup.exe").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_SOFTWARE


def test_directory_known_extension_wins_over_unknown(tmp_path):
    """Si dossier contient .epub + .xyz inconnu : on retient .epub (connu)."""
    folder = tmp_path / "Mixed"
    folder.mkdir()
    (folder / "aaa_weird.xyz").write_bytes(b"")    # inconnu, ordre alpha avant
    (folder / "real_content.epub").write_bytes(b"")
    assert early_category_guess(folder) == CATEGORY_BOOKS, (
        "Une extension connue dans le mapping doit gagner sur une inconnue, "
        "meme si l'inconnue vient avant en ordre alpha"
    )


# ============================================================
# Helper _first_file_extension
# ============================================================

def test_first_file_extension_on_file(tmp_path):
    f = tmp_path / "test.MKV"
    f.write_bytes(b"")
    assert _first_file_extension(f) == ".mkv"  # lowercase normalise


def test_first_file_extension_on_directory(tmp_path):
    """Sprint A.4 : scan intelligent ignore les satellites et privilegie les
    extensions connues. .txt est satellite (info/readme) -> ignore.
    .mkv est extension connue -> retourne .mkv meme si pas en ordre alpha.
    """
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.txt").write_bytes(b"")   # satellite, ignore
    (folder / "b.mkv").write_bytes(b"")   # extension connue, retournee
    assert _first_file_extension(folder) == ".mkv"


def test_first_file_extension_on_dir_only_unknown_extensions(tmp_path):
    """Si aucune extension connue, on retourne la premiere non-satellite (ordre alpha)."""
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.aaa").write_bytes(b"")   # non-satellite, non-connue
    (folder / "b.bbb").write_bytes(b"")
    assert _first_file_extension(folder) == ".aaa"


def test_first_file_extension_empty_dir(tmp_path):
    folder = tmp_path / "vide"
    folder.mkdir()
    assert _first_file_extension(folder) == ""


def test_first_file_extension_nonexistent(tmp_path):
    """Un path inexistant ne leve pas, retourne ''."""
    assert _first_file_extension(tmp_path / "ghost") == ""


# ============================================================
# Smoke : la fonction est appelable sans plantage
# ============================================================

def test_returns_valid_gemini_category_id(tmp_path):
    """Toute sortie doit etre un category_id Gemini connu (cf. unit3d_mapping)."""
    from flox_uploader.trackers.gemini.unit3d_mapping import CATEGORY_OPTIONS
    valid_ids = {cid for cid, _ in CATEGORY_OPTIONS}
    # On teste qq cas et on s'assure que le retour est dans le set des cats valides
    samples = [
        tmp_path / "x.mkv",
        tmp_path / "x.epub",
        tmp_path / "x.exe",
        tmp_path / "x.unknown_ext",
    ]
    for s in samples:
        s.write_bytes(b"")
        assert early_category_guess(s) in valid_ids
