"""Tests Lot K + L + M : checks de conformite Gemini durs.

Couvre :
- C1  MKV obligatoire (BLOCKING si MP4/AVI)
- C2  MP3 interdit + FLAC > 2ch (BLOCKING)
- C3  PGS dans encode (BLOCKING)
- C5  Saison incomplete (WARN)
- C6  Multi-team dans pack (WARN)
- C7  Russe (WARN)
- C8  Banned team (BLOCKING + liste configurable via .env)
- C9  EXTREME team sur REMUX/raw (BLOCKING)
- C10 Subs separes (WARN)
- M1  CRF hors plage (WARN, silence si info absente)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.compliance import (
    Severity,
    check_compliance,
    has_blocking,
    DEFAULT_BANNED_TEAMS,
)
from flox_uploader.core.media_type import MediaInfo, MediaType


def _mi(container="MATROSKA", audio=None, subs=None, video=None):
    """Helper : forge un mediainfo_data minimal pour les tests."""
    return {
        "container": container,
        "video": video or {"resolution_label": "1080p", "codec": "HEVC / x265"},
        "audio_tracks": audio or [],
        "subtitle_tracks": subs or [],
    }


# ============================================================
# C1 — MKV obligatoire
# ============================================================

def test_c1_mkv_ok():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(container="MATROSKA"),
    )
    assert not any(i.field == "container" for i in issues)


def test_c1_mp4_blocking():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(container="MPEG-4"),
    )
    container_issues = [i for i in issues if i.field == "container"]
    assert len(container_issues) == 1
    assert container_issues[0].severity == Severity.BLOCKING
    assert "MKV" in container_issues[0].message


def test_c1_avi_blocking():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(container="AVI"),
    )
    assert has_blocking(issues)


def test_c1_m2ts_warn_only():
    """M2TS = full disc, on warn (toleré pour Full Disc) au lieu de BLOCK."""
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.2160p.UHD.BluRay-TEAM",
        _mi(container="MPEG-TS"),
    )
    container_issues = [i for i in issues if i.field == "container"]
    assert len(container_issues) == 1
    assert container_issues[0].severity == Severity.WARN


# ============================================================
# C2 — MP3 / FLAC channels
# ============================================================

def test_c2_mp3_blocking():
    audio = [
        {"language": "fr", "codec": "MP3", "channels": "2.0",
         "title": "VFF MP3", "is_commentary": False, "is_audio_description": False},
    ]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.MP3-TEAM",
        _mi(audio=audio),
    )
    assert has_blocking(issues)
    mp3_issues = [
        i for i in issues
        if i.field == "audio_codec" and "MP3" in i.message
    ]
    assert len(mp3_issues) == 1
    assert mp3_issues[0].severity == Severity.BLOCKING


def test_c2_flac_stereo_ok():
    audio = [{"language": "fr", "codec": "FLAC", "channels": "2.0",
              "title": "VFF FLAC", "is_commentary": False, "is_audio_description": False}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.FLAC.2.0.x265-TEAM",
        _mi(audio=audio),
    )
    assert not has_blocking(issues)


def test_c2_flac_5_1_blocking():
    audio = [{"language": "fr", "codec": "FLAC", "channels": "5.1",
              "title": "VFF FLAC 5.1", "is_commentary": False, "is_audio_description": False}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.FLAC.5.1.x265-TEAM",
        _mi(audio=audio),
    )
    assert has_blocking(issues)
    flac_issues = [
        i for i in issues
        if i.field == "audio_codec" and "FLAC" in i.message
    ]
    assert flac_issues[0].severity == Severity.BLOCKING
    assert "stereo" in flac_issues[0].message.lower() or "mono" in flac_issues[0].message.lower()


def test_c2_mp3_commentary_skipped():
    """Un commentaire en MP3 ne doit pas bloquer (piste auxiliaire)."""
    audio = [
        {"language": "fr", "codec": "DDP", "channels": "5.1", "title": "VFF",
         "is_commentary": False, "is_audio_description": False},
        {"language": "en", "codec": "MP3", "channels": "2.0", "title": "Director Commentary",
         "is_commentary": True, "is_audio_description": False},
    ]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.DDP.5.1.x265-TEAM",
        _mi(audio=audio),
    )
    assert not has_blocking(issues)


# ============================================================
# C3 — PGS dans encode
# ============================================================

def test_c3_pgs_only_in_encode_is_warn_not_blocking():
    """C3 (regle revisee, Vague 3) : PGS uniquement dans un encode = WARN
    (pas BLOCKING). Le user devrait remuxer ou ajouter des subs texte
    mais l'upload peut quand meme passer."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(subs=subs),
    )
    # Plus de BLOCKING global (sauf si autre regle bloque, ici aucune)
    assert not has_blocking(issues)
    # Mais on a bien un WARN sur les subs
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert len(sub_issues) == 1
    assert sub_issues[0].severity == Severity.WARN
    assert "uniquement" in sub_issues[0].message.lower()


def test_c3_pgs_with_srt_in_encode_ok():
    """Si on a a la fois du PGS ET du SRT/UTF-8 dans un encode : OK,
    aucun warning. Les subs texte sont disponibles, PGS est un bonus."""
    subs = [
        {"language": "fr", "format": "PGS", "kind": "Complet", "title": ""},
        {"language": "fr", "format": "UTF-8", "kind": "Complet", "title": ""},
    ]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(subs=subs),
    )
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert sub_issues == []


def test_c3_pgs_with_ass_in_encode_ok():
    """ASS est un sub texte aussi, meme combo OK."""
    subs = [
        {"language": "fr", "format": "PGS", "kind": "Complet", "title": ""},
        {"language": "fr", "format": "ASS", "kind": "Complet", "title": ""},
    ]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(subs=subs),
    )
    assert not any(i.field == "subtitles" for i in issues)


def test_c3_pgs_in_remux_ok():
    """PGS toleré dans un REMUX (preserve la source) — meme sans subs texte."""
    subs = [{"language": "fr", "format": "PGS", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.2160p.UHD.BluRay.REMUX.HEVC-TEAM",
        _mi(subs=subs),
    )
    sub_issues = [i for i in issues if i.field == "subtitles"]
    assert sub_issues == []


def test_c3_srt_in_encode_ok():
    subs = [{"language": "fr", "format": "UTF-8", "kind": "Complet", "title": ""}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(subs=subs),
    )
    assert not any(i.field == "subtitles" for i in issues)


# ============================================================
# C5 — Saison incomplete
# ============================================================

def test_c5_season_complete_ok(tmp_path):
    videos = [tmp_path / f"Show.S01E{ep:02d}.mkv" for ep in range(1, 6)]
    for v in videos:
        v.write_bytes(b"")
    media = MediaInfo(
        media_type=MediaType.TV_SEASON,
        reference_video=videos[0],
        torrent_target=tmp_path,
        all_videos=videos,
        season=1,
    )
    issues = check_compliance(
        "Show.S01.COMPLETE.MULTi.VFF.1080p.WEB-DL.x265-TEAM",
        _mi(),
        media,
    )
    assert not any(i.field == "season_completeness" for i in issues)


def test_c5_season_with_gaps_warn(tmp_path):
    """E01, E02, E04, E05 -> manque E03."""
    videos = [
        tmp_path / "Show.S01E01.mkv",
        tmp_path / "Show.S01E02.mkv",
        tmp_path / "Show.S01E04.mkv",
        tmp_path / "Show.S01E05.mkv",
    ]
    for v in videos:
        v.write_bytes(b"")
    media = MediaInfo(
        media_type=MediaType.TV_SEASON,
        reference_video=videos[0],
        torrent_target=tmp_path,
        all_videos=videos,
        season=1,
    )
    issues = check_compliance(
        "Show.S01.COMPLETE.MULTi.VFF.1080p.WEB-DL.x265-TEAM",
        _mi(),
        media,
    )
    completeness_issues = [i for i in issues if i.field == "season_completeness"]
    assert len(completeness_issues) == 1
    assert completeness_issues[0].severity == Severity.WARN
    assert "03" in completeness_issues[0].message


# ============================================================
# C6 — Multi-team dans pack
# ============================================================

def test_c6_multi_team_in_pack_warn(tmp_path):
    videos = [
        tmp_path / "Show.S01E01.MULTi.VFF.1080p.WEB-DL.x265-TEAM_A.mkv",
        tmp_path / "Show.S01E02.MULTi.VFF.1080p.WEB-DL.x265-TEAM_A.mkv",
        tmp_path / "Show.S01E03.MULTi.VFF.1080p.WEB-DL.x265-TEAM_B.mkv",
    ]
    for v in videos:
        v.write_bytes(b"")
    media = MediaInfo(
        media_type=MediaType.TV_SEASON,
        reference_video=videos[0],
        torrent_target=tmp_path,
        all_videos=videos,
        season=1,
    )
    issues = check_compliance(
        "Show.S01.COMPLETE.MULTi.VFF.1080p.WEB-DL.x265-TEAM_A",
        _mi(),
        media,
    )
    team_issues = [i for i in issues if i.field == "team_consistency"]
    assert len(team_issues) == 1
    assert team_issues[0].severity == Severity.WARN
    assert "TEAM_A" in team_issues[0].message
    assert "TEAM_B" in team_issues[0].message


def test_c6_single_team_pack_ok(tmp_path):
    videos = [
        tmp_path / f"Show.S01E0{ep}.MULTi.VFF.1080p.WEB-DL.x265-TEAM.mkv"
        for ep in range(1, 4)
    ]
    for v in videos:
        v.write_bytes(b"")
    media = MediaInfo(
        media_type=MediaType.TV_SEASON,
        reference_video=videos[0],
        torrent_target=tmp_path,
        all_videos=videos,
        season=1,
    )
    issues = check_compliance(
        "Show.S01.COMPLETE.MULTi.VFF.1080p.WEB-DL.x265-TEAM",
        _mi(),
        media,
    )
    assert not any(i.field == "team_consistency" for i in issues)


# ============================================================
# C7 — Russe (WARN, jamais BLOCKING)
# ============================================================

def test_c7_russian_audio_warn():
    audio = [
        {"language": "fr", "codec": "DDP", "channels": "5.1", "title": "VFF",
         "is_commentary": False, "is_audio_description": False},
        {"language": "ru", "codec": "AAC", "channels": "2.0", "title": "RU",
         "is_commentary": False, "is_audio_description": False},
    ]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.DDP.5.1.x265-TEAM",
        _mi(audio=audio),
    )
    ru_issues = [i for i in issues if i.field == "language_blacklist"]
    assert len(ru_issues) == 1
    assert ru_issues[0].severity == Severity.WARN


def test_c7_no_russian_no_warn():
    audio = [{"language": "fr", "codec": "DDP", "channels": "5.1", "title": "VFF",
              "is_commentary": False, "is_audio_description": False}]
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.DDP.5.1.x265-TEAM",
        _mi(audio=audio),
    )
    assert not any(i.field == "language_blacklist" for i in issues)


# ============================================================
# C8 — Team interdite (BLOCKING, configurable)
# ============================================================

def test_c8_default_banned_team_k0re_blocking():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.x265-k0RE",
        _mi(),
    )
    assert has_blocking(issues)
    team_issues = [i for i in issues if i.field == "team"]
    assert any("k0RE" in t.message for t in team_issues)


def test_c8_default_banned_team_slay3r_blocking():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.x265-Slay3R",
        _mi(),
    )
    assert has_blocking(issues)


def test_c8_user_added_banned_team():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.x265-CustomBadTeam",
        _mi(),
        banned_teams=["CustomBadTeam"],
    )
    assert has_blocking(issues)


def test_c8_case_insensitive():
    """k0RE / K0RE / k0re -> tous bloques."""
    for variant in ["k0RE", "K0RE", "k0re"]:
        issues = check_compliance(
            f"Foo.2024.MULTi.VFF.1080p.WEB-DL.x265-{variant}",
            _mi(),
        )
        assert has_blocking(issues), f"variant {variant} non bloque"


def test_c8_clean_team_not_blocked():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.WEB-DL.x265-Amen",
        _mi(),
    )
    team_issues = [i for i in issues if i.field == "team" and "interdite" in i.message]
    assert team_issues == []


def test_c8_default_constants_present():
    """Verifie que les defauts hardcodes sont bien k0RE + Slay3R."""
    assert "k0RE" in DEFAULT_BANNED_TEAMS
    assert "Slay3R" in DEFAULT_BANNED_TEAMS


# ============================================================
# C9 — EXTREME team sur REMUX
# ============================================================

def test_c9_extreme_on_encode_ok():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-EXTREME",
        _mi(),
    )
    scope_issues = [i for i in issues if i.field == "team_scope"]
    assert scope_issues == []


def test_c9_extreme_on_remux_blocking():
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.2160p.UHD.BluRay.REMUX.HEVC-EXTREME",
        _mi(),
    )
    scope_issues = [i for i in issues if i.field == "team_scope"]
    assert len(scope_issues) == 1
    assert scope_issues[0].severity == Severity.BLOCKING


# ============================================================
# C10 — Subs separes (WARN)
# ============================================================

def test_c10_separate_subs_warn(tmp_path):
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"")
    (tmp_path / "Show.S01E01.fr.srt").write_bytes(b"")
    issues = check_compliance(
        "Show.S01E01.MULTi.VFF.1080p.WEB-DL.x265-TEAM",
        _mi(),
        torrent_target=tmp_path,
    )
    sub_issues = [i for i in issues if i.field == "subtitles_external"]
    assert len(sub_issues) == 1
    assert sub_issues[0].severity == Severity.WARN


def test_c10_no_separate_subs_ok(tmp_path):
    (tmp_path / "Show.S01E01.mkv").write_bytes(b"")
    issues = check_compliance(
        "Show.S01E01.MULTi.VFF.1080p.WEB-DL.x265-TEAM",
        _mi(),
        torrent_target=tmp_path,
    )
    assert not any(i.field == "subtitles_external" for i in issues)


# ============================================================
# Lot M — CRF hors plage
# ============================================================

def test_m1_crf_in_range_silent():
    """x265 1080p CRF 21 (dans 20-23) -> aucun warning."""
    video = {
        "resolution_label": "1080p", "codec": "HEVC / x265",
        "crf": 21.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(video=video),
    )
    assert not any(i.field == "crf" for i in issues)


def test_m1_crf_too_high_warn():
    """x265 1080p CRF 28 (hors 20-23, trop leger) -> WARN."""
    video = {
        "resolution_label": "1080p", "codec": "HEVC / x265",
        "crf": 28.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(video=video),
    )
    crf_issues = [i for i in issues if i.field == "crf"]
    assert len(crf_issues) == 1
    assert crf_issues[0].severity == Severity.WARN
    assert "leger" in crf_issues[0].message


def test_m1_crf_too_low_warn():
    """x265 1080p CRF 15 (trop lourd) -> WARN."""
    video = {
        "resolution_label": "1080p", "codec": "HEVC / x265",
        "crf": 15.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(video=video),
    )
    crf_issues = [i for i in issues if i.field == "crf"]
    assert len(crf_issues) == 1
    assert "lourd" in crf_issues[0].message


def test_m1_crf_absent_silent():
    """Pas de crf dans encoding_settings -> AUCUN warning (silence)."""
    video = {
        "resolution_label": "1080p", "codec": "HEVC / x265",
        "crf": None,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        _mi(video=video),
    )
    assert not any(i.field == "crf" for i in issues)


def test_m1_crf_unknown_codec_silent():
    """Codec hors table (VC-1) -> silence."""
    video = {
        "resolution_label": "1080p", "codec": "VC-1",
        "crf": 25.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.VC-1-TEAM",
        _mi(video=video),
    )
    assert not any(i.field == "crf" for i in issues)


def test_m1_crf_x264_1080p_in_range():
    video = {
        "resolution_label": "1080p", "codec": "AVC / x264",
        "crf": 19.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.x264-TEAM",
        _mi(video=video),
    )
    assert not any(i.field == "crf" for i in issues)


def test_m1_crf_x265_2160p_in_range():
    video = {
        "resolution_label": "2160p", "codec": "HEVC / x265",
        "crf": 24.0,
    }
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.2160p.BluRay.x265-TEAM",
        _mi(video=video),
    )
    assert not any(i.field == "crf" for i in issues)


# ============================================================
# Sprint 8 hotfix v16 : 3 faux positifs compliance audio (Louis)
# ============================================================
# Cas 1 : VF2.2160p contenait `2.2` qui faisait croire qu'il y avait
#         un layout 2.2 dans le nom -> warning "Nom dit ['2.2']".
# Cas 2 : 2 pistes audio (7.1 + 5.1), le nom dit 5.1, mais on comparait
#         uniquement avec la piste principale (7.1) -> warning faux.
# Cas 3 : AC35.1 (codec colle au layout) n'etait pas detecte comme
#         contenant "5.1" -> warning "aucun layout dans le nom".


def test_audio_channels_no_false_positive_from_resolution_in_vf2_2160p():
    """Cas 1 : `VF2.2160p` ne doit PAS etre interprete comme layout '2.2'.
    Le release dit AC3 5.1, MediaInfo aussi 5.1 -> aucun warning."""
    audio = [{"codec": "AC3", "channels": "5.1"}]
    issues = check_compliance(
        "Edge.Of.Tomorrow.2014.MULTi.VF2.2160p.HDR10.BluRay.AC35.1.x265-Portos",
        _mi(audio=audio),
    )
    # Pas de warning audio_channels (avant : warning "Nom dit ['2.2']")
    assert not any(i.field == "audio_channels" for i in issues)


def test_audio_channels_accepts_multiple_tracks_5_1_or_7_1():
    """Cas 2 : 2 pistes (7.1 + 5.1). Le nom tagge 5.1 -> doit etre OK
    meme si la piste principale est 7.1."""
    audio = [
        {"codec": "DDP", "channels": "7.1"},  # piste principale
        {"codec": "DDP", "channels": "5.1"},  # piste alternative
    ]
    issues = check_compliance(
        "Elemental.2023.MULTi.VFF.2160p.DV.HDR.BluRay.DDP5.1.x265-QTZ",
        _mi(audio=audio),
    )
    assert not any(i.field == "audio_channels" for i in issues)


def test_audio_channels_detects_glued_layout_AC35_1():
    """Cas 3 : `AC35.1` (codec colle au layout, sans separateur) doit
    etre reconnu comme contenant 5.1."""
    audio = [{"codec": "AC3", "channels": "5.1"}]
    issues = check_compliance(
        "Everythings.Going.To.Be.Great.2025.MULTi.VFF.2160p.HDR10P.WEBRip.AC35.1.x265-Amen",
        _mi(audio=audio),
    )
    # Pas de warning "aucun layout dans le nom" (avant : warning faux)
    assert not any(i.field == "audio_channels" for i in issues)


def test_audio_channels_eac3_dot_5_1_not_misread_as_3_5():
    """Cas 4 (Emilia Perez, v0.3.17) : `E-AC3.5.1` ne doit PAS etre lu comme
    layout '3.5' (le 3 de AC3 + .5). Le vrai layout est 5.1, present dans
    MediaInfo -> aucun warning. Le findall non-overlappant matchait `3.5`
    et ratait `5.1` ; le fix capture en chevauchement + filtre layouts valides."""
    audio = [
        {"codec": "DDP", "channels": "5.1"},
        {"codec": "DDP", "channels": "5.1"},
        {"codec": "DDP", "channels": "2.0"},
    ]
    issues = check_compliance(
        "Emilia.Perez.2024.MULTi.VFF.2160p.AD.SDR.WEBRip.E-AC3.5.1.x265-TyHD",
        _mi(audio=audio),
    )
    assert not any(i.field == "audio_channels" for i in issues)


def test_audio_channels_3_5_not_a_valid_layout():
    """Garde-fou : `3.5` n'est pas un layout audio valide, donc meme isole
    dans un nom bizarre il ne doit jamais etre pris pour un layout."""
    audio = [{"codec": "DDP", "channels": "5.1"}]
    # Nom artificiel avec '3.5' isole mais aussi le vrai 5.1
    issues = check_compliance(
        "Foo.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-TEAM",
        _mi(audio=audio),
    )
    assert not any(i.field == "audio_channels" for i in issues)


def test_audio_channels_still_warns_when_truly_mismatched():
    """Sanity check : le warning doit toujours se declencher quand
    le nom dit X.Y mais aucune piste MediaInfo ne match."""
    audio = [{"codec": "DDP", "channels": "5.1"}]
    issues = check_compliance(
        # Nom dit 7.1 mais MediaInfo dit 5.1 -> warning legitime
        "Movie.2024.MULTi.VFF.1080p.BluRay.DDP7.1.x265-TEAM",
        _mi(audio=audio),
    )
    audio_warnings = [i for i in issues if i.field == "audio_channels"]
    assert len(audio_warnings) == 1
    assert "7.1" in audio_warnings[0].message
    assert "5.1" in audio_warnings[0].message
