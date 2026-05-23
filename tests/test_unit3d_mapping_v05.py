"""Tests Sprint A v0.5.0 PR-1 : TYPE_IDs 16-37, banned teams par categorie,
piece sizes torrent conformes au bareme Gemini.

Cf. PLAN-MULTICAT.md §8 (decouvertes critiques) et §9 (Sprint A).
"""
from __future__ import annotations

import pytest

from flox_uploader.core import compliance
from flox_uploader.core.torrent import _recommended_piece_size
from flox_uploader.trackers.gemini import unit3d_mapping as u3d


# ============================================================
# T1 — TYPE_IDs 16-37 conformes au PDF officiel
# ============================================================

@pytest.mark.parametrize("constant_name,expected_id", [
    # Jeux (categorie 3)
    ("TYPE_GAME_WINDOWS", 16),
    ("TYPE_GAME_OTHER", 17),
    ("TYPE_GAME_LINUX", 18),
    ("TYPE_GAME_MACOS", 19),
    ("TYPE_GAME_XBOX", 20),
    ("TYPE_GAME_NINTENDO", 21),
    ("TYPE_GAME_SMARTPHONE", 22),
    ("TYPE_GAME_SONY", 23),
    ("TYPE_GAME_TABLETTE", 24),
    # Livres (categorie 12)
    ("TYPE_BOOK_M4B", 25),
    ("TYPE_BOOK_MP3", 26),
    ("TYPE_BOOK_EBOOK", 27),
    ("TYPE_BOOK_BD", 28),
    ("TYPE_BOOK_COMICS", 29),
    ("TYPE_BOOK_MANGAS", 30),
    ("TYPE_BOOK_MAGAZINE", 31),
    ("TYPE_BOOK_PRESSE", 32),
    ("TYPE_BOOK_AUDIO", 33),
    # Logiciels (categorie 17)
    ("TYPE_SOFTWARE_WINDOWS", 34),
    ("TYPE_SOFTWARE_MACOS", 35),
    ("TYPE_SOFTWARE_LINUX", 36),
    ("TYPE_SOFTWARE_OTHER", 37),
])
def test_type_ids_match_official_pdf(constant_name, expected_id):
    """Verifie que chaque TYPE_ID corresponde a la doc PDF G3MINI TR4CK3R."""
    assert getattr(u3d, constant_name) == expected_id, (
        f"{constant_name} doit valoir {expected_id} (cf. TORRENT_API.txt)"
    )


def test_type_ids_no_collision_with_video_types():
    """Les types non-video (16-37) ne doivent pas chevaucher les types video (1-15)."""
    video_ids = {tid for tid, _ in u3d.TYPE_OPTIONS}
    non_video_ids = {
        tid for tid, _ in
        u3d.GAME_TYPE_OPTIONS + u3d.BOOK_TYPE_OPTIONS + u3d.SOFTWARE_TYPE_OPTIONS
    }
    assert video_ids.isdisjoint(non_video_ids), (
        "Collision detectee entre types video et non-video"
    )


def test_game_type_by_platform_covers_main_consoles():
    """Le mapping plateforme -> type_id couvre les plateformes courantes."""
    assert u3d.GAME_TYPE_BY_PLATFORM["windows"] == u3d.TYPE_GAME_WINDOWS
    assert u3d.GAME_TYPE_BY_PLATFORM["pc"] == u3d.TYPE_GAME_WINDOWS
    assert u3d.GAME_TYPE_BY_PLATFORM["ps5"] == u3d.TYPE_GAME_SONY
    assert u3d.GAME_TYPE_BY_PLATFORM["switch"] == u3d.TYPE_GAME_NINTENDO
    assert u3d.GAME_TYPE_BY_PLATFORM["xbox"] == u3d.TYPE_GAME_XBOX
    assert u3d.GAME_TYPE_BY_PLATFORM["android"] == u3d.TYPE_GAME_SMARTPHONE


def test_book_type_by_format_defaults():
    """Les extensions ebook courantes sont mappees correctement."""
    assert u3d.BOOK_TYPE_BY_FORMAT["epub"] == u3d.TYPE_BOOK_EBOOK
    assert u3d.BOOK_TYPE_BY_FORMAT["pdf"] == u3d.TYPE_BOOK_EBOOK
    assert u3d.BOOK_TYPE_BY_FORMAT["mobi"] == u3d.TYPE_BOOK_EBOOK
    assert u3d.BOOK_TYPE_BY_FORMAT["azw3"] == u3d.TYPE_BOOK_EBOOK
    assert u3d.BOOK_TYPE_BY_FORMAT["cbr"] == u3d.TYPE_BOOK_BD
    assert u3d.BOOK_TYPE_BY_FORMAT["m4b"] == u3d.TYPE_BOOK_M4B


def test_software_type_by_platform_defaults():
    """Le mapping plateforme -> type_id logiciel."""
    assert u3d.SOFTWARE_TYPE_BY_PLATFORM["windows"] == u3d.TYPE_SOFTWARE_WINDOWS
    assert u3d.SOFTWARE_TYPE_BY_PLATFORM["macos"] == u3d.TYPE_SOFTWARE_MACOS
    assert u3d.SOFTWARE_TYPE_BY_PLATFORM["linux"] == u3d.TYPE_SOFTWARE_LINUX


def test_type_label_resolves_all_known_ids():
    """type_label() retrouve un libelle pour tous les TYPE_IDs declares."""
    # Echantillon couvrant video + non-video
    samples = [
        (u3d.TYPE_FULL_DISC, "Full Disc"),
        (u3d.TYPE_REMUX, "Remux"),
        (u3d.TYPE_WEB, "WEB"),
        (u3d.TYPE_GAME_WINDOWS, "Windows"),
        (u3d.TYPE_GAME_SONY, "Sony"),
        (u3d.TYPE_BOOK_EBOOK, "Livre"),
        (u3d.TYPE_BOOK_BD, "BD"),
        (u3d.TYPE_SOFTWARE_LINUX, "Linux"),
    ]
    for type_id, expected_keyword in samples:
        label = u3d.type_label(type_id)
        assert expected_keyword.lower() in label.lower(), (
            f"type_label({type_id}) = '{label}' ne contient pas '{expected_keyword}'"
        )


def test_type_label_unknown_returns_marker():
    """Un type_id inconnu retourne le format '? (id=N)'."""
    assert u3d.type_label(999) == "? (id=999)"


# ============================================================
# T2 — Banned teams par categorie
# ============================================================

def test_default_banned_teams_video_contains_historical():
    """La liste video contient toujours k0RE et Slay3R (charte historique)."""
    assert "k0RE" in compliance.DEFAULT_BANNED_TEAMS_VIDEO
    assert "Slay3R" in compliance.DEFAULT_BANNED_TEAMS_VIDEO


def test_default_banned_teams_alias_retro_compat():
    """L'alias historique pointe sur la liste video (compat v0.3.x)."""
    assert compliance.DEFAULT_BANNED_TEAMS is compliance.DEFAULT_BANNED_TEAMS_VIDEO
    assert "k0RE" in compliance.DEFAULT_BANNED_TEAMS


def test_default_banned_teams_games_apps_from_pdf():
    """La liste jeux/apps reprend les teams du PDF officiel."""
    games_apps = compliance.DEFAULT_BANNED_TEAMS_GAMES_APPS
    for team in ("Fenixx", "KMS.Tools.Portable", "MAXAGENT", "Seyter", "Vansik"):
        assert team in games_apps, f"{team} attendu dans DEFAULT_BANNED_TEAMS_GAMES_APPS"


def test_banned_teams_for_category_video():
    """Categories video -> liste video."""
    for cat in (
        u3d.CATEGORY_MOVIE, u3d.CATEGORY_TV, u3d.CATEGORY_TV_ANIME,
        u3d.CATEGORY_MOVIE_ANIME, u3d.CATEGORY_SPORTS, u3d.CATEGORY_MOVIE_DOC,
        u3d.CATEGORY_TV_DOC, u3d.CATEGORY_TV_SHOW,
    ):
        assert compliance.banned_teams_for_category(cat) == compliance.DEFAULT_BANNED_TEAMS_VIDEO


def test_banned_teams_for_category_games_apps():
    """Jeux (3) et Logiciels (17) -> liste games_apps."""
    assert compliance.banned_teams_for_category(u3d.CATEGORY_GAME) == compliance.DEFAULT_BANNED_TEAMS_GAMES_APPS
    assert compliance.banned_teams_for_category(u3d.CATEGORY_SOFTWARE) == compliance.DEFAULT_BANNED_TEAMS_GAMES_APPS


def test_banned_teams_for_category_books_and_training_empty():
    """Livres (12) et Formations (18) n'ont pas de liste officielle."""
    assert compliance.banned_teams_for_category(u3d.CATEGORY_BOOKS) == ()
    assert compliance.banned_teams_for_category(u3d.CATEGORY_TRAINING) == ()


def test_banned_teams_for_category_none_defaults_to_video():
    """Compat : None retourne la liste video (defaut historique)."""
    assert compliance.banned_teams_for_category(None) == compliance.DEFAULT_BANNED_TEAMS_VIDEO


def test_banned_teams_for_category_unknown_id_empty():
    """Un category_id inconnu n'inflige pas de defaut arbitraire."""
    assert compliance.banned_teams_for_category(9999) == ()


# ============================================================
# T3 — Piece sizes torrent conformes au bareme Gemini §8.3
# ============================================================

@pytest.mark.parametrize("total_bytes,expected_piece_size,label", [
    # < 500 Mo -> 256 KB
    (100 * 1024 * 1024, 256 * 1024, "100 MB"),
    (499 * 1024 * 1024, 256 * 1024, "499 MB (limite basse)"),
    # > 500 Mo et < 1 Go -> 512 KB
    (500 * 1024 * 1024, 512 * 1024, "500 MB"),
    (800 * 1024 * 1024, 512 * 1024, "800 MB"),
    # > 1 Go et < 2 Go -> 1 MB
    (1024 * 1024 * 1024, 1024 * 1024, "1 GB"),
    (1500 * 1024 * 1024, 1024 * 1024, "1.5 GB"),
    # > 2 Go et < 4 Go -> 2 MB
    (2 * 1024 * 1024 * 1024, 2 * 1024 * 1024, "2 GB"),
    (3 * 1024 * 1024 * 1024, 2 * 1024 * 1024, "3 GB"),
    # > 4 Go et < 8 Go -> 4 MB
    (4 * 1024 * 1024 * 1024, 4 * 1024 * 1024, "4 GB"),
    (6 * 1024 * 1024 * 1024, 4 * 1024 * 1024, "6 GB"),
    # > 8 Go et < 20 Go -> 8 MB
    (8 * 1024 * 1024 * 1024, 8 * 1024 * 1024, "8 GB"),
    (15 * 1024 * 1024 * 1024, 8 * 1024 * 1024, "15 GB"),
    # > 20 Go -> 16 MB (cap compat clients)
    (20 * 1024 * 1024 * 1024, 16 * 1024 * 1024, "20 GB"),
    (50 * 1024 * 1024 * 1024, 16 * 1024 * 1024, "50 GB"),
])
def test_recommended_piece_size_matches_gemini_table(
    total_bytes, expected_piece_size, label,
):
    """Verifie le bareme officiel Gemini RÈGLES D'UPLOAD page 5."""
    actual = _recommended_piece_size(total_bytes)
    assert actual == expected_piece_size, (
        f"{label} ({total_bytes} bytes) attend piece_size={expected_piece_size}, "
        f"obtenu {actual}"
    )


def test_recommended_piece_size_always_power_of_two():
    """Le format .torrent exige une puissance de 2 pour piece_size."""
    for total in (
        1 * 1024 * 1024,                     # 1 MB
        500 * 1024 * 1024,                   # 500 MB
        5 * 1024 * 1024 * 1024,              # 5 GB
        100 * 1024 * 1024 * 1024,            # 100 GB
    ):
        ps = _recommended_piece_size(total)
        # Power of 2 <=> ps & (ps-1) == 0
        assert ps > 0 and (ps & (ps - 1)) == 0, (
            f"piece_size={ps} pour total={total} n'est pas une puissance de 2"
        )
