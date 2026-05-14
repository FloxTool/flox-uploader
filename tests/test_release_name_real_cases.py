"""Tests sur les cas reels remontes par l'utilisateur.

Chaque test cible une categorie de bug rencontree en production. Les
fonctions internes (split_team, _normalize_token_case, _title_parts_from_tmdb)
sont testees en isolation pour pouvoir valider sans setup TMDB+MediaInfo+NFO.

Si une regression casse un de ces tests, le naming est cassé pour le cas reel
correspondant -> on saura immediatement quoi reverter.
"""
from __future__ import annotations

from flox_uploader.core.release_name import (
    _normalize_token_case,
    split_team,
)
from flox_uploader.core.tmdb import _title_parts_from_tmdb


# ============================================================
# Cat A : preserver la casse de la team
# ============================================================

def test_cat_a_team_punisher694_keeps_case():
    """Cas 5 : -Punisher694 doit rester 'Punisher694', pas 'PUNISHER694'."""
    base, team = split_team(
        "Le.Chateau.Ambulant.2004.MULTi.1080p.BluRay.AC35.1.x265-Punisher694",
        "NOTAG",
    )
    assert team == "Punisher694"


def test_cat_a_team_pophd_keeps_case():
    """Cas 7 : -PopHD doit rester 'PopHD', pas 'POPHD'."""
    base, team = split_team(
        "Cidade.De.Deus.2002.MULTi.1080p.BluRay.AC3.x264-PopHD",
        "NOTAG",
    )
    assert team == "PopHD"


def test_cat_a_team_amen_keeps_case():
    """Cas 8 : -Amen doit rester 'Amen', pas 'AMEN'."""
    base, team = split_team(
        "Kpop.Demon.Hunters.2025.MULTi.1080p.AD.DV.HDR.WEB.E-AC3.5.1.x265-Amen",
        "NOTAG",
    )
    assert team == "Amen"


def test_cat_a_team_frosties_keeps_case():
    """Cas 9 : -Frosties doit rester 'Frosties', pas 'FROSTIES'."""
    base, team = split_team(
        "Im.Thinking.Of.Ending.Things.2020.MULTi.1080p.WEBRip.x265-Frosties",
        "NOTAG",
    )
    assert team == "Frosties"


def test_cat_a_team_ulysse_keeps_case():
    """Cas 10/12 : -Ulysse doit rester 'Ulysse', pas 'ULYSSE'."""
    base, team = split_team(
        "The.Father.2020.MULTi.1080p.BluRay.x264-Ulysse",
        "NOTAG",
    )
    assert team == "Ulysse"


# ============================================================
# Cat B : team avec tirets internes (mHDgz-Dread-Team)
# ============================================================

def test_cat_b_team_with_internal_dashes():
    """Cas 6 : -mHDgz-Dread-Team doit etre capture en entier."""
    base, team = split_team(
        "La.Vita.E.Bella.1997.MULTi.VFF.1080p.x264-mHDgz-Dread-Team",
        "NOTAG",
    )
    assert team == "mHDgz-Dread-Team"


def test_cat_b_team_mhdgz_simple_dash():
    """Sept Samourais : '...AAC-mHDgz' (un seul tiret colle, format scene
    avec espaces dans le base) doit donner 'mHDgz', pas 'MHDGZ' (regression
    Cat A) ni autre chose."""
    base, team = split_team(
        "Les Septs Samourai 1954 1080p VoStFR Criterion X264 AAC-mHDgz",
        "NOTAG",
    )
    assert team == "mHDgz"


# ============================================================
# Cat C : team derriere un point final (.mHDgz)
# ============================================================

def test_cat_c_team_after_dot():
    """Cas 3 : '...AC3.mHDgz' doit reconnaitre 'mHDgz' comme team."""
    base, team = split_team(
        "Les.Visiteurs.Ii.1998.VOF.1080p.AC3.x264.mHDgz",
        "NOTAG",
    )
    assert team == "mHDgz"


def test_cat_c_team_after_dot_doesnt_grab_codec():
    """Le fallback ne doit PAS prendre 'x264' comme team."""
    base, team = split_team(
        "Foo.2024.MULTi.1080p.BluRay.x264",
        "NOTAG",
    )
    # x264 est dans _NEVER_TEAM -> defaut
    assert team == "NOTAG"


def test_cat_c_team_after_dot_doesnt_grab_resolution():
    """Le fallback ne doit pas prendre '1080p' comme team."""
    base, team = split_team(
        "Foo.2024.1080p",
        "NOTAG",
    )
    assert team == "NOTAG"


# ============================================================
# Cat D : strip "(titre alternatif)" final
# ============================================================

def test_cat_d_strip_paren_then_team():
    """Cas 4 : '...PopHD (The King's Speech)' -> team = PopHD."""
    base, team = split_team(
        "The.Kings.Speech.2010.MULTi.VF2.1080p.BluRay-PopHD (The King's Speech)",
        "NOTAG",
    )
    assert team == "PopHD"


def test_cat_d_strip_paren_already_handled_format():
    """Format complexe : '...x265-Frosties (titre alternatif)'."""
    base, team = split_team(
        "Im.Thinking.Of.Ending.Things.2020.MULTi.1080p.WEBRip.x265-Frosties (Im Thinking Of Ending Things)",
        "NOTAG",
    )
    assert team == "Frosties"


# ============================================================
# Cat F : 2CH/6CH/8CH en MAJUSCULES
# ============================================================

def test_cat_f_2ch_uppercase():
    """Cas 2 : '2ch' / '2CH' / '2Ch' doivent tous donner '2CH'."""
    assert _normalize_token_case("2CH") == "2CH"
    assert _normalize_token_case("2ch") == "2CH"
    assert _normalize_token_case("2Ch") == "2CH"


def test_cat_f_6ch_8ch_uppercase():
    assert _normalize_token_case("6ch") == "6CH"
    assert _normalize_token_case("8CH") == "8CH"


# ============================================================
# Cat G : chiffres romains preserves
# ============================================================

def test_cat_g_roman_ii_preserved():
    """Cas 3 : 'II' doit rester 'II', pas 'Ii'."""
    assert _normalize_token_case("II") == "II"
    assert _normalize_token_case("ii") == "II"
    assert _normalize_token_case("Ii") == "II"


def test_cat_g_roman_iii_iv_preserved():
    assert _normalize_token_case("III") == "III"
    assert _normalize_token_case("iv") == "IV"
    assert _normalize_token_case("VIII") == "VIII"


# ============================================================
# Cat I : titre EN pour films etrangers (CJK/cyrilliques)
# ============================================================

def test_cat_i_japanese_falls_back_to_title_en():
    """Cas 5 : original_title en jp -> ascii_fold -> vide -> fallback title_en
    -> 'Howl's Moving Castle'."""
    ctx = {
        "original_title": "ハウルの動く城",
        "title_en": "Howl's Moving Castle",
        "title": "Le Château ambulant",
        "original_language": "ja",
    }
    parts = _title_parts_from_tmdb(ctx, ["Le", "Chateau", "Ambulant"])
    # Doit utiliser title_en ('s strip apostrophe)
    assert parts == ["Howls", "Moving", "Castle"]


def test_cat_i_korean_falls_back_to_title_en():
    """Coreen : title_en doit etre prefere quand original est non-latin."""
    ctx = {
        "original_title": "기생충",  # Parasite en KR
        "title_en": "Parasite",
        "title": "Parasite",
        "original_language": "ko",
    }
    parts = _title_parts_from_tmdb(ctx, ["Parasite"])
    assert parts == ["Parasite"]


def test_cat_i_latin_original_keeps_priority():
    """Pour les films en alphabet latin, original_title reste prioritaire."""
    ctx = {
        "original_title": "La Vita è Bella",  # IT
        "title_en": "Life Is Beautiful",
        "title": "La Vie est belle",
        "original_language": "it",
    }
    parts = _title_parts_from_tmdb(ctx, ["La", "Vie", "Est", "Belle"])
    # ascii_fold de "La Vita è Bella" -> "La Vita e Bella"
    assert parts == ["La", "Vita", "e", "Bella"]


def test_cat_i_no_title_en_falls_back_to_title_fr():
    """Si pas de title_en (vieux cache TMDB sans fetch en-US), fallback title FR."""
    ctx = {
        "original_title": "ハウル",  # non-latin pur
        "title": "Le Château",
        "original_language": "ja",
    }
    parts = _title_parts_from_tmdb(ctx, ["Foo"])
    assert parts == ["Le", "Chateau"]


# ============================================================
# Cat H : auto-enrichissement MULTi.VFF depuis NFO
# ============================================================

def test_cat_h_multi_vff_from_audio_tracks_fr_plus_en():
    """Cas 11 : NFO indique 1 piste FR + 1 piste EN -> doit inferer MULTi.VFF
    (pas juste VFF). Le bug etait que le code lisait 'nfo_audio_titles'
    (clef inexistante) au lieu de 'audio_titles'."""
    from flox_uploader.core.nfo import infer_french_variant_from_nfo

    nfo_text = """
General
Title : Some Movie

Audio
Language : French
Title : AC-3 5.1 (VFI)

Audio
Language : English
Title : AC-3 5.1
"""
    inferred = infer_french_variant_from_nfo(nfo_text)
    # Le NFO doit donner 2 pistes audio + french_audio_count=1
    assert inferred["french_audio_count"] == 1
    assert len(inferred["audio_titles"]) == 2

    # Et le calcul non_fr_count doit donner 1 (FR + non-FR -> MULTi)
    fr_count = inferred["french_audio_count"]
    non_fr_count = max(0, len(inferred["audio_titles"]) - fr_count)
    assert non_fr_count == 1
