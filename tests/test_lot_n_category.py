"""Tests Lot N : detection enrichie de la categorie Gemini.

Couvre :
- N.1 Sports keywords avec priorite TMDB stricte (le film F1 reste FILM)
- N.3 category_guess_source : libelle humain de la source du guess
- N.4 SIG_CATEGORY_LOW_CONFIDENCE present dans naming_signals
"""
from __future__ import annotations

import pytest

from flox_uploader.core.media_type import MediaType
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_MOVIE,
    CATEGORY_MOVIE_ANIME,
    CATEGORY_MOVIE_DOC,
    CATEGORY_SPORTS,
    CATEGORY_TV,
    CATEGORY_TV_ANIME,
    CATEGORY_TV_DOC,
    SPORTS_KEYWORDS,
    _has_sports_keyword,
    category_guess_source,
    category_id_for,
)


# ============================================================
# N.1 — Le cas critique : film "F1" Brad Pitt (TMDB matche, pas Sports)
# ============================================================

def test_n1_film_f1_with_tmdb_match_is_movie_not_sports():
    """Le film F1 (TMDB id 911430, Brad Pitt 2025) a un keyword 'F1' dans le
    nom mais TMDB matche -> doit rester FILM, pas Sports."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={
            "movie_id": 911430,
            "title": "F1",
            "genres": ["Action", "Drama"],
        },
        release_name="F1.2025.MULTi.VFF.2160p.UHD.BluRay.HEVC.HDR.DTS-HD.MA.7.1-TEAM",
    )
    assert cat == CATEGORY_MOVIE


def test_n1_real_f1_race_no_tmdb_is_sports():
    """Course F1 reelle : TMDB ne matche pas, keyword 'F1' present -> Sports."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context=None,
        release_name="F1.2024.06.Monaco.GP.Race.1080p.WEB-DL.DDP5.1.H.264-TEAM",
    )
    assert cat == CATEGORY_SPORTS


def test_n1_f1_drive_to_survive_is_tv_doc_not_sports():
    """F1.Drive.to.Survive : TMDB matche en TV serie genre Documentary
    -> doit rester SERIE DOCU, pas Sports (priorite TMDB > keyword)."""
    cat = category_id_for(
        MediaType.TV_SEASON,
        tmdb_context={
            "tv_id": 79573,
            "title": "Formula 1: Drive to Survive",
            "genres": ["Documentary"],
        },
        release_name="F1.Drive.to.Survive.S06.MULTi.VFF.1080p.NF.WEB-DL.DDP5.1.x265-TEAM",
    )
    assert cat == CATEGORY_TV_DOC


def test_n1_le_mans_66_film_with_tmdb_is_movie():
    """Ford v Ferrari (Le Mans 66) : TMDB matche -> FILM, pas Sports."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={
            "movie_id": 359724,
            "title": "Le Mans '66",
            "genres": ["Action", "Drama"],
        },
        release_name="Le.Mans.66.2019.MULTi.VFF.1080p.BluRay.x265-TEAM",
    )
    assert cat == CATEGORY_MOVIE


def test_n1_real_le_mans_24h_no_tmdb_is_sports():
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={},
        release_name="24.Heures.du.Mans.2024.Race.1080p.WEB-DL-TEAM",
    )
    assert cat == CATEGORY_SPORTS


# ============================================================
# N.1 — Sports keywords variés
# ============================================================

@pytest.mark.parametrize("release_name,expected_keywords", [
    # Pour chaque release, on liste les keywords ATTENDUS comme presents.
    # _has_sports_keyword retourne le plus long match (priorite specificite),
    # donc on accepte n'importe quel keyword de la liste — ce qui compte
    # c'est que la cat finale soit SPORTS.
    ("UFC.300.2024.Pereira.vs.Hill.1080p.WEB-DL-TEAM", ["UFC"]),
    ("NBA.Finals.2024.Game.5.Celtics.vs.Mavericks-TEAM", ["NBA.Finals", "NBA"]),
    ("NFL.2024.Super.Bowl.LVIII-TEAM", ["Super.Bowl", "NFL"]),
    ("MotoGP.2024.Round.05.Le.Mans.Race-TEAM", ["MotoGP", "Le.Mans"]),
    ("Tour.de.France.2024.Stage.05.HDTV-TEAM", ["Tour.de.France"]),
    ("Wimbledon.2024.Men.Final.Djokovic.vs.Alcaraz-TEAM", ["Wimbledon"]),
    ("Roland.Garros.2024.Final-TEAM", ["Roland.Garros", "Roland-Garros"]),
    ("WWE.SmackDown.2024.05.10.HDTV-TEAM", ["WWE", "SmackDown"]),
    ("FIFA.World.Cup.2026.Final-TEAM", ["FIFA", "World.Cup"]),
])
def test_n1_sports_keyword_detected(release_name, expected_keywords):
    """Sans TMDB, n'importe quel keyword sport pertinent classe en SPORTS."""
    matched = _has_sports_keyword(release_name)
    assert matched in expected_keywords, (
        f"keyword matche '{matched}' pas dans {expected_keywords}"
    )
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context=None,
        release_name=release_name,
    )
    assert cat == CATEGORY_SPORTS


def test_n1_no_keyword_no_tmdb_defaults_to_movie():
    """Pas de TMDB, pas de keyword sport -> defaut FILM."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context=None,
        release_name="Some.Random.Movie.2024.MULTi.VFF.1080p.BluRay-TEAM",
    )
    assert cat == CATEGORY_MOVIE


def test_n1_no_keyword_no_tmdb_tv_defaults_to_series():
    cat = category_id_for(
        MediaType.TV_SEASON,
        tmdb_context=None,
        release_name="Random.Show.S01.MULTi.VFF.1080p.WEB-DL-TEAM",
    )
    assert cat == CATEGORY_TV


# ============================================================
# N.1 — Boundary tokens (le keyword doit etre un token isole)
# ============================================================

def test_n1_keyword_in_middle_of_word_not_matched():
    """Le keyword doit etre un token isole, pas un substring de mot."""
    # 'F1' est dans 'CONFINEMENT' au milieu : ne doit PAS matcher
    assert _has_sports_keyword("CONFINEMENT.2020.MULTi.VFF.1080p-TEAM") == ""


def test_n1_keyword_with_dot_separator_matches():
    """Cas reel : 'F1' entoure de '.' matche."""
    assert _has_sports_keyword("F1.2024.Monaco-TEAM") == "F1"


def test_n1_keyword_at_start_matches():
    assert _has_sports_keyword("UFC.300-TEAM") == "UFC"


def test_n1_keyword_at_end_matches():
    assert _has_sports_keyword("2024.Wimbledon") == "Wimbledon"


# ============================================================
# N.1 — Animation / Documentaire restent prioritaires
# ============================================================

def test_n1_animation_genre_overrides_sports_keyword():
    """Cas tordu : un anime appele 'F1' (peu probable mais defensif).
    Animation prime -> ANIME FILM."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"movie_id": 999, "genres": ["Animation"]},
        release_name="F1.Anime.2024-TEAM",
    )
    assert cat == CATEGORY_MOVIE_ANIME


def test_n1_documentary_genre_overrides_sports_keyword():
    """Documentaire sport (ex: F1: Drive to Survive movie cut) reste DOC."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"movie_id": 999, "genres": ["Documentary", "Sport"]},
        release_name="UFC.Documentary.2024-TEAM",
    )
    assert cat == CATEGORY_MOVIE_DOC


# ============================================================
# N.1 — Compat retroactive : appel sans release_name
# ============================================================

def test_n1_backward_compat_no_release_name():
    """Anciens appels sans `release_name` continuent de fonctionner."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"genres": ["Animation"]},
    )
    assert cat == CATEGORY_MOVIE_ANIME


def test_n1_existing_anime_test_still_passes():
    """Compat avec test_unit3d_mapping : Animation TMDB sans release_name."""
    cat = category_id_for(
        MediaType.MOVIE,
        tmdb_context={"genres": ["Animation", "Family"]},
    )
    assert cat == CATEGORY_MOVIE_ANIME


# ============================================================
# N.3 — category_guess_source (source du guess pour UI)
# ============================================================

def test_n3_source_animation_genre():
    src = category_guess_source(
        MediaType.MOVIE,
        tmdb_context={"movie_id": 1, "genres": ["Animation", "Comedy"]},
    )
    assert "Animation" in src


def test_n3_source_documentary_genre():
    src = category_guess_source(
        MediaType.MOVIE,
        tmdb_context={"genres": ["Documentaire"]},
    )
    assert "Documentaire" in src


def test_n3_source_tmdb_other_genres():
    src = category_guess_source(
        MediaType.MOVIE,
        tmdb_context={"movie_id": 911430, "genres": ["Action", "Drama"]},
    )
    assert "Action" in src or "Drama" in src
    assert "TMDB" in src


def test_n3_source_sports_keyword():
    src = category_guess_source(
        MediaType.MOVIE,
        tmdb_context=None,
        release_name="UFC.300.2024-TEAM",
    )
    assert "UFC" in src
    assert "sport" in src.lower()


def test_n3_source_default_movie():
    src = category_guess_source(
        MediaType.MOVIE,
        tmdb_context=None,
        release_name="Random.Movie.2024-TEAM",
    )
    assert "Films" in src or "default" in src.lower() or "défaut" in src.lower() or "Defaut" in src


def test_n3_source_default_series():
    src = category_guess_source(
        MediaType.TV_SEASON,
        tmdb_context=None,
        release_name="Random.S01-TEAM",
    )
    # Le label par defaut TV peut contenir "Series" ou un fallback langue
    assert "Series" in src or "TV" in src or "Defaut" in src or "default" in src.lower()


# ============================================================
# N.4 — SIG_CATEGORY_LOW_CONFIDENCE constants exists
# ============================================================

def test_n4_signal_constant_exists():
    from flox_uploader.core.naming_signals import (
        SIG_CATEGORY_LOW_CONFIDENCE,
        SIGNAL_METADATA,
    )
    assert SIG_CATEGORY_LOW_CONFIDENCE in SIGNAL_METADATA
    penalty, label = SIGNAL_METADATA[SIG_CATEGORY_LOW_CONFIDENCE]
    assert penalty == 1
    assert "Catégorie" in label


def test_n4_sports_keywords_immutable():
    """Liste hardcodee, on s'assure qu'elle a au moins 30 entrees."""
    assert len(SPORTS_KEYWORDS) >= 30
    assert "UFC" in SPORTS_KEYWORDS
    assert "F1" in SPORTS_KEYWORDS
    assert "Tour.de.France" in SPORTS_KEYWORDS
