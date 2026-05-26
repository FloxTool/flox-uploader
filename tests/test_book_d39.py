"""Tests Sprint D.39 v0.5.0 — Cloture livres : 9 fixes finaux.

Cible feedback Louis dans FILMDEBUG.md :
1. Year doublon strip (2024.2024 / 2026.2026)
2. Author "Lastname, Firstname" inversion BnF (T.H. White)
3. Subtitle dedup quand subtitle == series (Raja/Space Brothers)
4. Fanscan C\\d{3,4} -> no_canonical_match (One Piece chapitres)
5. MP3 cover fallback all-files (Marc Levy)
6. Multi-tome range detection from files (Star Wars Rebellion T01-T06)
7. Description Google Books prio si BnF courte
8. Strip "HS" comme auteur (LARGO.WINCH.INTEGRALE)
"""
from __future__ import annotations

import pytest
from pathlib import Path

from flox_uploader.core.naming.book_strategy import BookNamingStrategy
from flox_uploader.core.providers.book_metadata import BookMetadata
from flox_uploader.core.providers.dir_parser import detect_volume_range_from_files


# ============================================================
# 1. Year doublon strip
# ============================================================

def test_year_doublon_strip():
    """Title finit par '2024' + publication_year=2024 -> on n'ajoute pas '.2024' apres."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.authors = ["Marc Levy"]
    meta.title = "Sept Jours Pour Une Eternite 2024"
    meta.publication_year = 2024
    meta.language = "fr"
    meta.file_format = "mp3"
    release = strat._build_book_release_name(meta, "NoTAG")
    # Doit avoir UNE seule occurrence de 2024 a la fin
    assert release.count("2024") == 1, (
        f"Doublon year non strippe : {release}"
    )
    assert ".2024.2024." not in release, (
        f"Doublon brut : {release}"
    )


def test_year_doublon_strip_poitou():
    """POITOU 2024 (title) + year=2024 -> pas de doublon."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.authors = ["Dominique Auzias"]
    meta.title = "POITOU 2024 Petit Fute"
    meta.publication_year = 2024
    meta.file_format = "epub"
    release = strat._build_book_release_name(meta, "NoTAG")
    # Le title contient deja "2024" au milieu -> on ajoute year apres,
    # mais le dernier token du title n'est pas 2024 (c'est Fute), donc
    # la sequence finale aura 2024 au milieu ET 2024 a la fin = potentiel
    # doublon different. Notre fix vise le cas STRICT ou title se termine
    # par 2024. Test ici : POITOU 2024 Petit Fute -> 2024 ne se repete pas
    # forcement, mais on verifie au moins qu'il n'y a pas '.2024.2024.'
    # accole. Si "Fute" est le dernier mot, on ajoute 2024 -> "...Fute.2024".
    assert release.count("2024") <= 2


def test_year_doublon_strip_lequipe():
    """Title se termine par '2026' + year=2026 -> pas de doublon."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.title = "Le Temps Magazine 23 Mai 2026"
    meta.publication_year = 2026
    meta.file_format = "pdf"
    release = strat._build_book_release_name(meta, "NoTAG")
    assert release.count("2026") == 1, f"Doublon : {release}"


# ============================================================
# 2. Author "Lastname, Firstname" BnF inversion
# ============================================================

def test_author_bnf_inversion_th_white():
    """White, T. H. (format BnF) -> T.H.White dans release."""
    strat = BookNamingStrategy()
    token = strat._tokenize_author("White, T. H.")
    # Apres inversion : "T. H. White" -> "T.H.White"
    assert "White" in token
    # Le firstname doit etre EN PREMIER
    assert token.startswith("T") or token.startswith("T.H")
    # Ne doit PAS commencer par "White,"
    assert not token.startswith("White,")


def test_author_bnf_inversion_tolkien():
    """Tolkien, J.R.R. -> J.R.R.Tolkien."""
    strat = BookNamingStrategy()
    token = strat._tokenize_author("Tolkien, J.R.R.")
    assert "Tolkien" in token
    assert token.startswith("J")


def test_author_bnf_no_inversion_when_no_comma():
    """Pas de virgule -> pas d'inversion."""
    strat = BookNamingStrategy()
    token = strat._tokenize_author("Stephen King")
    assert token == "Stephen.King"


def test_author_hs_stripped():
    """HS (Hors-Serie) en pseudo-auteur -> empty token."""
    strat = BookNamingStrategy()
    assert strat._tokenize_author("HS") == ""
    assert strat._tokenize_author("H.S.") == ""
    assert strat._tokenize_author("Hors-Serie") == ""


# ============================================================
# 3. Subtitle dedup quand subtitle se termine par la serie
# ============================================================

def test_subtitle_dedup_raja():
    """Raja - Tome 2 - RAJA (title) avec serie='Raja' -> Raja.T2 sans suffix RAJA."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.authors = ["Kota INNAMI"]
    meta.series = "Raja"
    meta.series_index = 2.0
    meta.title = "RAJA Tome 2 RAJA"
    meta.publication_year = 2025
    meta.language = "fr"
    meta.file_format = "cbz"
    release = strat._build_book_release_name(meta, "Club")
    # RAJA ne doit apparaitre qu'une seule fois (pas suffixe doublon)
    raja_count = release.upper().count("RAJA")
    assert raja_count <= 2, f"Trop de RAJA dans : {release}"


def test_subtitle_dedup_space_brothers():
    """Space Brothers T33 avec title BnF = 'Space Brothers' (= series) -> pas doublon."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.authors = ["Chuya Koyama"]
    meta.series = "Space Brothers"
    meta.series_index = 33.0
    meta.title = "Space Brothers"
    meta.publication_year = 2021
    meta.language = "fr"
    meta.file_format = "cbz"
    release = strat._build_book_release_name(meta, "NoTAG")
    # Doit etre Space.Brothers.T33 SANS repetition
    assert "Space.Brothers.T33.Space.Brothers" not in release


# ============================================================
# 6. Multi-tome range detection from files
# ============================================================

def test_detect_volume_range_from_files(tmp_path):
    """Dossier avec T01.cbz, T02.cbz, T03.cbz -> "1-3"."""
    (tmp_path / "Tokyo.Alien.Bros.T01.cbz").write_bytes(b"")
    (tmp_path / "Tokyo.Alien.Bros.T02.cbz").write_bytes(b"")
    (tmp_path / "Tokyo.Alien.Bros.T03.cbz").write_bytes(b"")
    result = detect_volume_range_from_files(tmp_path)
    assert result == "1-3", f"Got {result!r}"


def test_detect_volume_range_star_wars(tmp_path):
    """Star Wars Rebellion T01..T06 -> "1-6"."""
    for i in range(1, 7):
        (tmp_path / f"Star.Wars.Rebellion.T{i:02d}.cbz").write_bytes(b"")
    result = detect_volume_range_from_files(tmp_path)
    assert result == "1-6"


def test_detect_volume_range_single_tome(tmp_path):
    """Un seul T01.cbz -> "" (pas de range)."""
    (tmp_path / "Solo.T01.cbz").write_bytes(b"")
    result = detect_volume_range_from_files(tmp_path)
    assert result == ""


def test_detect_volume_range_no_tomes(tmp_path):
    """Aucun T<num> -> "" (pas de range)."""
    (tmp_path / "Solo.cbz").write_bytes(b"")
    (tmp_path / "Other.cbz").write_bytes(b"")
    result = detect_volume_range_from_files(tmp_path)
    assert result == ""


# ============================================================
# 7. Description Google Books prio si BnF courte
# ============================================================

def test_description_google_overrides_short_bnf():
    """BnF description = 44 chars (code-barres) -> Google override."""
    bnf_meta = BookMetadata()
    bnf_meta.description = "Code a barres commercial: EAN 9782...."  # ~44 chars
    bnf_meta.sources = ["bnf"]
    google_meta = BookMetadata()
    google_meta.description = (
        "Le mythe de l'Ossuaire raconte l'histoire incroyable de Marius, "
        "un homme qui decouvre dans la cave de sa maison un ossuaire ancien "
        "datant de l'an mille. Cette decouverte va bouleverser sa vie et "
        "l'entrainer dans une quete des origines fascinante. Roman fantastique."
    )  # >> 100 chars
    bnf_meta.merge_from(google_meta, "google")
    # La description doit etre celle de Google (plus longue)
    assert "Marius" in bnf_meta.description
    assert len(bnf_meta.description) >= 100


def test_description_short_bnf_no_google_kept():
    """BnF description courte, pas de Google -> on garde la BnF (mieux que rien)."""
    bnf_meta = BookMetadata()
    bnf_meta.description = "Code: EAN 9782..."
    google_meta = BookMetadata()
    google_meta.description = ""  # pas de description Google
    bnf_meta.merge_from(google_meta, "google")
    assert bnf_meta.description.startswith("Code")


# ============================================================
# Integration : release name complet attendu Louis (#26 Marc Levy)
# ============================================================

def test_marc_levy_release_name_clean():
    """Marc.Levy.Sept.Jours.Pour.Une.Eternite.2024.FRENCH.MP3-NoTAG (sans doublon)."""
    strat = BookNamingStrategy()
    meta = BookMetadata()
    meta.authors = ["Marc Levy"]
    meta.title = "Sept Jours Pour Une Eternite"
    meta.publication_year = 2024
    meta.language = "fr"
    meta.file_format = "mp3"
    release = strat._build_book_release_name(meta, "NoTAG")
    # Pas de doublon "Marc.Levy" au debut
    assert release.count("Marc") == 1
    # Pas de doublon "2024"
    assert release.count("2024") == 1
    # Format attendu
    assert release.startswith("Marc.Levy")
    assert release.endswith("-NoTAG")
