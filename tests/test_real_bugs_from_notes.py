"""Tests pour les bugs reels remontes dans NOTES.md.

Chaque test cible un cas concret rapporte par l'utilisateur. Le nom du test
reprend le slug du fichier source pour que la trace en CI dise tout de suite
quel cas est casse.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.media_type import MediaType, detect_media_type
from flox_uploader.core.release_name import (
    classify_parts,
    collapse_dots,
    normalize_separators,
    split_compound_specs,
    split_glued_tokens,
)


# ============================================================
# B2 : detection TV pour 1 seul fichier avec S01 sans Eyy
# ============================================================
# Cas : Dune.Prophecy.S01.Multi.VFF.HDR10.DV.2160p.Webrip.X265-Neostark.mkv
# Avant le fix : detect_media_type voyait 1 video, S01 sans Eyy -> MOVIE
# -> pipeline exigeait une annee -> die() "Impossible de detecter l'annee".
# Apres le fix : fallback _extract_season_only -> TV_SEASON, annee non requise.

def test_b2_dune_prophecy_single_file_with_s01_is_tv_season(tmp_path: Path):
    """1 fichier .mkv standalone avec 'S01' dans le nom -> TV_SEASON."""
    f = tmp_path / "Dune.Prophecy.S01.Multi.VFF.HDR10.DV.2160p.Webrip.X265-Neostark.mkv"
    f.write_bytes(b"x")
    info = detect_media_type(f)
    assert info.media_type == MediaType.TV_SEASON
    assert info.season == 1


def test_b2_single_file_with_saison_french_keyword(tmp_path: Path):
    """Variante : 'Saison 02' (FR) doit aussi etre detecte."""
    f = tmp_path / "Foo.Bar.Saison.2.MULTi.1080p.WEBRip.x265-TEAM.mkv"
    f.write_bytes(b"x")
    info = detect_media_type(f)
    assert info.media_type == MediaType.TV_SEASON
    assert info.season == 2


def test_b2_single_file_without_season_pattern_remains_movie(tmp_path: Path):
    """Garde-fou : sans pattern de saison, on reste sur MOVIE."""
    f = tmp_path / "Some.Random.Movie.2024.1080p.BluRay.x265-TEAM.mkv"
    f.write_bytes(b"x")
    info = detect_media_type(f)
    assert info.media_type == MediaType.MOVIE


def test_b2_single_file_with_sxxeyy_still_episode(tmp_path: Path):
    """Garde-fou : SxxEyy explicite reste TV_EPISODE."""
    f = tmp_path / "Show.S03E07.2160p.WEB.x265-TEAM.mkv"
    f.write_bytes(b"x")
    info = detect_media_type(f)
    assert info.media_type == MediaType.TV_EPISODE
    assert info.season == 3
    assert info.episode == 7


def test_b2_folder_name_supplies_season_when_filename_lacks_it(tmp_path: Path):
    """Si le filename n'a pas de pattern mais le folder oui (cas Sonarr renomme),
    on doit quand meme detecter."""
    folder = tmp_path / "Show.S04.MULTi.x265-TEAM"
    folder.mkdir()
    f = folder / "Episode renomme par Sonarr.mkv"
    f.write_bytes(b"x")
    info = detect_media_type(f)
    assert info.media_type == MediaType.TV_SEASON
    assert info.season == 4


# ============================================================
# B3 : split_compound_specs pour les patterns SRC-CHANNELS-CODEC
# ============================================================
# Cas : L'Arracheuse.De.Temps.2021.FRENCH.1080p.WEBDL-5.1-H264.mkv
# Avant : 'WEBDL-5.1-H264' restait UN token -> dropped_unknown_after_year
#         -> release_name produit : 'Larracheuse.De.Temps.2021.VOQ.1080p-NoTAG'
#         (perte de WEB-DL, 5.1, H.264)
# Apres : split en 'WEBDL.5.1.H264' -> tokens individuels classes correctement.

def test_b3_split_compound_src_channels_codec():
    """WEBDL-5.1-H264 doit etre split en 3 tokens."""
    result = split_compound_specs("WEBDL-5.1-H264")
    assert result == "WEBDL.5.1.H264"


def test_b3_split_compound_preserves_web_dl_dash():
    """WEB-DL contient un tiret interne LEGITIME : il doit etre preserve.
    Seuls les tirets ENTRE les groupes spec doivent devenir des points.
    """
    result = split_compound_specs("WEB-DL-7.1-HEVC")
    # WEB-DL conserve son tiret interne, ceux entre groupes spec deviennent points
    assert result == "WEB-DL.7.1.HEVC"


def test_b3_split_compound_src_codec_only():
    """Sans channels au milieu : WEBDL-x264 -> WEBDL.x264."""
    result = split_compound_specs("WEBDL-x264")
    assert result == "WEBDL.x264"


def test_b3_split_compound_src_channels_only():
    """Sans codec a la fin : WEBDL-5.1 -> WEBDL.5.1."""
    result = split_compound_specs("WEBDL-5.1")
    assert result == "WEBDL.5.1"


def test_b3_split_compound_channels_codec():
    """Cas degenere : 5.1-H264 (source manque) -> 5.1.H264."""
    result = split_compound_specs("5.1-H264")
    assert result == "5.1.H264"


def test_b3_split_compound_in_full_release_name():
    """Cas reel : `L'Arracheuse...WEBDL-5.1-H264` passe par les helpers
    de normalisation. Apres split_compound_specs, le `5.1` devient
    deux tokens `5` et `1` (le split par `.` est attendu, ils seront
    recolles par merge_audio_channel_tokens plus tard dans le pipeline).
    Ce qu'on verifie ici : WEBDL et H264 sont separes du compose initial.
    """
    from flox_uploader.core.release_name import merge_audio_channel_tokens

    source = "L'Arracheuse.De.Temps.2021.FRENCH.1080p.WEBDL-5.1-H264"
    cleaned = normalize_separators(source)
    cleaned = split_glued_tokens(cleaned)
    cleaned = split_compound_specs(cleaned)
    parts = [p for p in cleaned.split(".") if p]

    # Apres split, WEBDL et H264 sont des tokens distincts (etaient en bloc)
    assert "WEBDL" in parts
    assert "H264" in parts
    # 5 et 1 sont split par le `.` mais merge_audio_channel_tokens les recolle
    parts = merge_audio_channel_tokens(parts)
    assert "5.1" in parts


def test_b3_no_split_when_no_compound_pattern():
    """Garde-fou : un release name sans pattern compose ne doit pas etre touche."""
    source = "Foo.2024.MULTi.VFF.1080p.BluRay.DTS-HD.7.1.x265-TEAM"
    assert split_compound_specs(source) == source
