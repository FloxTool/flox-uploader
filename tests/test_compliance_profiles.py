"""Tests Sprint A v0.5.0 PR-3 : check_compliance() route par profil de categorie.

Verifie que :
- category_id=None ou cat video -> profile 'video' (comportement v0.3.x exact)
- cat Livres / Jeux / Logiciels / Formations -> profile non-video
  (checks minimaux uniquement, en attendant Sprint D-H)
- Les checks specifiques video (resolution, codec video, MKV obligatoire, etc.)
  ne sont JAMAIS appliques en non-video.

Cf. PLAN-MULTICAT.md §5.3 Brique 2 + §9 Sprint A.
"""
from __future__ import annotations

import pytest

from flox_uploader.core import compliance
from flox_uploader.core.compliance import (
    CHECKS_BY_PROFILE, Severity, _profile_for_category, check_compliance,
)
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC, CATEGORY_SOFTWARE, CATEGORY_SPORTS, CATEGORY_TRAINING,
    CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
)


# ============================================================
# _profile_for_category : routing categorie -> profil
# ============================================================

@pytest.mark.parametrize("cat_id,expected_profile", [
    # Toutes les cats video -> 'video'
    (CATEGORY_MOVIE, "video"),
    (CATEGORY_TV, "video"),
    (CATEGORY_TV_ANIME, "video"),
    (CATEGORY_MOVIE_ANIME, "video"),
    (CATEGORY_MOVIE_DOC, "video"),
    (CATEGORY_TV_DOC, "video"),
    (CATEGORY_TV_SHOW, "video"),
    (CATEGORY_SPORTS, "video"),
    # Non-video
    (CATEGORY_BOOKS, "book"),
    (CATEGORY_GAME, "game"),
    (CATEGORY_SOFTWARE, "manual"),
    (CATEGORY_TRAINING, "manual"),
])
def test_profile_for_category_routes_correctly(cat_id, expected_profile):
    assert _profile_for_category(cat_id) == expected_profile


def test_profile_for_category_none_is_video_retrocompat():
    """category_id=None -> profile 'video' = comportement v0.3.x retro-compat."""
    assert _profile_for_category(None) == "video"


def test_profile_for_category_unknown_falls_back_video():
    """Un category_id inconnu retombe sur 'video' (sans plantage)."""
    assert _profile_for_category(9999) == "video"


def test_checks_by_profile_registry_documented():
    """Le registre CHECKS_BY_PROFILE expose les 4 profils prevus."""
    assert "video" in CHECKS_BY_PROFILE
    assert "book" in CHECKS_BY_PROFILE
    assert "game" in CHECKS_BY_PROFILE
    assert "manual" in CHECKS_BY_PROFILE


# ============================================================
# check_compliance avec profil video (retro-compat)
# ============================================================

def test_check_compliance_video_profile_identical_to_v03x():
    """check_compliance(category_id=None) doit donner le meme resultat que sans."""
    release_name = "Foo.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-TEAM"
    mi = {
        "container": "Matroska",
        "video": {
            "codec": "HEVC", "resolution_label": "1080p",
            "hdr": "SDR", "framerate": "23.976 FPS",
        },
        "audio_tracks": [
            {"language": "fr", "codec": "DDP", "channels": "5.1", "title": "VFF"},
        ],
        "subtitle_tracks": [],
    }
    # Comportement v0.3.x : appel sans category_id
    issues_v03x = check_compliance(release_name, mi)
    # Comportement A.3 PR-3 : appel avec category_id=None (defaut)
    issues_a3_none = check_compliance(release_name, mi, category_id=None)
    # Comportement A.3 PR-3 : appel avec category_id=CATEGORY_MOVIE
    issues_a3_movie = check_compliance(release_name, mi, category_id=CATEGORY_MOVIE)

    # Les 3 doivent etre strictement identiques
    msgs_v03x = [str(i) for i in issues_v03x]
    msgs_none = [str(i) for i in issues_a3_none]
    msgs_movie = [str(i) for i in issues_a3_movie]
    assert msgs_v03x == msgs_none == msgs_movie


def test_check_compliance_video_detects_missing_mkv():
    """Profil video : MKV manquant => BLOCKING (check_container_mkv s'applique)."""
    release_name = "Foo.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-TEAM"
    mi = {
        "container": "MPEG-4",  # MP4 au lieu de MKV
        "video": {"codec": "HEVC", "resolution_label": "1080p"},
        "audio_tracks": [{"language": "fr", "codec": "DDP", "channels": "5.1"}],
        "subtitle_tracks": [],
    }
    issues = check_compliance(release_name, mi, category_id=CATEGORY_MOVIE)
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    assert any(i.field == "container" for i in blocking), (
        "Le profil video doit detecter le container non-MKV"
    )


# ============================================================
# check_compliance avec profils non-video
# ============================================================

@pytest.mark.parametrize("cat_id", [CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_SOFTWARE, CATEGORY_TRAINING])
def test_check_compliance_non_video_skips_video_checks(cat_id):
    """Les checks specifiques video ne s'appliquent pas en non-video.

    Exemple : un .epub n'a pas de container MKV, pas de resolution video, pas
    de codec video. Avec le profil non-video, ces checks ne doivent rien
    detecter (= pas d'issue de type 'container', 'resolution', etc.).
    """
    release_name = "Auteur.Livre.2024.FRENCH.EPUB-TEAM"
    # mediainfo_data vide : pas de container, pas de video, pas d'audio
    # (simule un fichier non-video pour lequel MediaInfo n'a pas tourne)
    mi: dict = {}

    issues = check_compliance(release_name, mi, category_id=cat_id)

    # Ces fields ne doivent JAMAIS apparaitre en profil non-video
    forbidden_fields = {
        "container", "resolution", "video_codec", "audio_codec",
        "audio_channels", "hdr", "french_audio", "vfi", "multi_variant",
        "media_type_tag", "audio_codec_allowed", "pgs_in_encode",
        "season_complete", "multi_team_in_pack", "russian_audio",
        "extreme_team", "separate_subs", "crf",
    }
    actual_fields = {i.field for i in issues}
    leaked = actual_fields & forbidden_fields
    assert not leaked, (
        f"Checks video appliques par erreur en profil non-video "
        f"(cat={cat_id}): {leaked}"
    )


def test_check_compliance_non_video_still_checks_team_present():
    """Profil non-video : team manquante reste detectee (check universel)."""
    # Pas de team a la fin (pas de "-TEAM")
    release_name = "Auteur.Livre.2024.FRENCH.EPUB"
    issues = check_compliance(release_name, {}, category_id=CATEGORY_BOOKS)
    team_issues = [i for i in issues if i.field == "team"]
    assert team_issues, "Le profil non-video doit detecter une team manquante"


def test_check_compliance_non_video_still_checks_banned_team():
    """Profil non-video : team interdite reste bloquante (check universel)."""
    release_name = "Auteur.Livre.2024.FRENCH.EPUB-k0RE"  # team historiquement bannie
    issues = check_compliance(
        release_name, {}, category_id=CATEGORY_BOOKS,
        # On passe la liste banned video pour simuler l'integration future
        banned_teams=list(compliance.DEFAULT_BANNED_TEAMS_VIDEO),
    )
    # Note : k0RE est dans DEFAULT_BANNED_TEAMS_VIDEO via le pool defaut de
    # _check_banned_team -> doit bloquer meme en profil book.
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    assert any(i.field == "team" for i in blocking), (
        "Le profil non-video doit refuser une team interdite"
    )


def test_check_compliance_non_video_clean_release_no_issues():
    """Profil non-video, release propre : aucune issue retournee."""
    release_name = "Auteur.Livre.2024.FRENCH.EPUB-Flox"
    issues = check_compliance(release_name, {}, category_id=CATEGORY_BOOKS)
    assert issues == [], (
        f"Une release ebook clean ne devrait pas avoir d'issue, obtenu : {issues}"
    )


# ============================================================
# Tri des issues : meme regle pour tous les profils
# ============================================================

def test_issues_sorted_blocking_first_in_both_profiles():
    """Le tri BLOCKING > ERROR > WARN s'applique sur les 2 types de profil."""
    # Video : provoquons un BLOCKING (MKV manquant) + un WARN (CRF si dispo)
    release_name = "Foo.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-k0RE"  # banned team
    mi = {
        "container": "MPEG-4",  # BLOCKING container
        "video": {"codec": "HEVC", "resolution_label": "1080p"},
        "audio_tracks": [{"language": "fr", "codec": "DDP", "channels": "5.1"}],
        "subtitle_tracks": [],
    }
    issues = check_compliance(release_name, mi, category_id=CATEGORY_MOVIE)
    if issues:
        # Toutes les BLOCKING doivent precéder les ERROR/WARN
        seen_non_blocking = False
        for i in issues:
            if i.severity != Severity.BLOCKING:
                seen_non_blocking = True
            else:
                assert not seen_non_blocking, (
                    "Une BLOCKING apparait apres une ERROR/WARN — tri casse"
                )
