"""Tests Lot O.8 : titre international privilegie pour films non-latins.

Cas reel rapporte par Louis : "Godzilla Minus One" (2023, japonais) etait
transforme en "1.0" parce que l'original_title TMDB est "ゴジラ-1.0" et
l'ascii_fold laissait "-1.0" qui survivait a la validation. On devrait
utiliser title_en="Godzilla Minus One" pour ces films.

Convention scene FR / charte Gemini :
- Films non-latins (ja/ko/zh/ru/ar/...) -> titre international (title_en)
  Ex: "Godzilla.Minus.One" pas "ゴジラ-1.0", "Parasite" pas "기생충"
- Films latins (en/fr/es/de/...) -> original_title (en gardant la casse)
"""
from __future__ import annotations

from flox_uploader.core.tmdb import (
    NON_LATIN_LANGUAGES,
    _title_parts_from_tmdb,
)


# ============================================================
# NON_LATIN_LANGUAGES : couvre les langues attendues
# ============================================================

def test_non_latin_languages_set():
    """Verifie que les langues principales non-latines sont incluses."""
    expected = {"ja", "ko", "zh", "ru", "ar", "hi", "th", "vi", "he", "fa"}
    assert expected.issubset(NON_LATIN_LANGUAGES)


# ============================================================
# Cas reel : Godzilla Minus One
# ============================================================

def test_godzilla_minus_one_uses_international_title():
    """Cas reel : original_title="ゴジラ-1.0", title_en="Godzilla Minus One",
    title_fr="Godzilla Minus One", original_language="ja".
    On DOIT prendre title_en (= "Godzilla.Minus.One"), PAS original_title
    qui produit "1.0" apres ascii_fold."""
    ctx = {
        "movie_id": 940721,
        "title": "Godzilla Minus One",
        "original_title": "ゴジラ-1.0",
        "title_en": "Godzilla Minus One",
        "original_language": "ja",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=["fallback"])
    assert parts == ["Godzilla", "Minus", "One"]
    # PAS [1, 0] (le bug d'avant)
    assert parts != ["1", "0"]


def test_parasite_korean():
    """Parasite (2019) : original "기생충" coreen. On prend title_en."""
    ctx = {
        "movie_id": 496243,
        "title": "Parasite",  # FR title_fr
        "original_title": "기생충",
        "title_en": "Parasite",
        "original_language": "ko",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    assert parts == ["Parasite"]


def test_drive_my_car_japanese():
    """Drive My Car (2021) : original "ドライブ・マイ・カー" jp."""
    ctx = {
        "movie_id": 758323,
        "title": "Drive My Car",
        "original_title": "ドライブ・マイ・カー",
        "title_en": "Drive My Car",
        "original_language": "ja",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    assert parts == ["Drive", "My", "Car"]


def test_russian_film_uses_international():
    """Film russe : title_en doit etre prefere a original_title cyrillique."""
    ctx = {
        "movie_id": 1,
        "title": "Mer des arbres",
        "original_title": "Левиафан",
        "title_en": "Leviathan",
        "original_language": "ru",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    assert parts == ["Leviathan"]


# ============================================================
# Cas latins : on garde l'ordre actuel (original_title prime)
# ============================================================

def test_french_film_keeps_original_title():
    """Film francais : original_title reste prioritaire."""
    ctx = {
        "movie_id": 1083324,
        "title": "En tongs au pied de l'Himalaya",
        "original_title": "En tongs au pied de l'Himalaya",
        "title_en": "",
        "original_language": "fr",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    # apostrophe retiree, accents foldes
    assert parts == ["En", "tongs", "au", "pied", "de", "lHimalaya"]


def test_english_film_keeps_original_title():
    """Film anglais : original_title prime (title_en serait le meme)."""
    ctx = {
        "movie_id": 1,
        "title": "Inception",
        "original_title": "Inception",
        "title_en": "",
        "original_language": "en",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    assert parts == ["Inception"]


def test_spanish_film_keeps_original_title():
    """Espagnol = latin, on garde original."""
    ctx = {
        "movie_id": 1,
        "title": "Le Labyrinthe de Pan",
        "original_title": "El laberinto del fauno",
        "title_en": "Pan's Labyrinth",
        "original_language": "es",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    # On garde l'original espagnol (langue latine)
    assert parts == ["El", "laberinto", "del", "fauno"]


# ============================================================
# Edge cases : non-latin sans title_en (degraded)
# ============================================================

def test_non_latin_without_title_en_uses_title_fr():
    """Film non-latin sans title_en (cas degrade : fetch title_en a echoue) :
    on tombe sur title_fr (fallback) plutot que sur l'original cyrillique."""
    ctx = {
        "movie_id": 1,
        "title": "Le Voleur de bicyclette",
        "original_title": "Велосипед-вор",  # cyrillique
        "title_en": "",  # pas dispo
        "original_language": "ru",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=["fallback"])
    # Sans title_en, le code retombe sur l'ordre normal : original (vide
    # apres ascii_fold) -> title_fr (utilisable). On utilise title_fr.
    assert "Voleur" in parts or "fallback" in parts


def test_chinese_film_with_pinyin():
    """Film chinois : original chinois, title_en international, on prend EN."""
    ctx = {
        "movie_id": 1,
        "title": "Tigre et Dragon",
        "original_title": "卧虎藏龙",
        "title_en": "Crouching Tiger Hidden Dragon",
        "original_language": "zh",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[])
    assert parts == ["Crouching", "Tiger", "Hidden", "Dragon"]


# ============================================================
# Signal SIG_TMDB_TITLE_EN_FALLBACK
# ============================================================

def test_signal_emitted_for_non_latin_using_title_en(tmp_path):
    """Verifie qu'on EMIT bien SIG_TMDB_TITLE_EN_FALLBACK quand on
    bascule sur title_en a cause d'un original non-latin."""
    from flox_uploader.core.debug import Debug

    debug = Debug(tmp_path)
    ctx = {
        "movie_id": 940721,
        "title": "Godzilla Minus One",
        "original_title": "ゴジラ-1.0",
        "title_en": "Godzilla Minus One",
        "original_language": "ja",
    }
    parts = _title_parts_from_tmdb(ctx, fallback_parts=[], debug=debug)
    assert parts == ["Godzilla", "Minus", "One"]
    sigs = debug.data.get("naming_signals") or {}
    assert sigs.get("tmdb_title_en_fallback") is True
