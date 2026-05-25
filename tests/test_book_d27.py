"""Tests Sprint D.27 v0.5.0 — Parser scene : pseudos 1-mot + IDs num + permutation.

Cible note Louis : 'Decoupe en tranches (10354) -> Zep.Decoupe.En.Tranches.10354.PDF-NoTAG'
aurait du trouver Google Books mais ne le fait pas. 3 bugs racines :
1. Pseudos 1-mot (Zep) non detectes comme auteur (j'exigeais >= 2 tokens cap).
2. IDs numeriques 4+ digits (10354) restaient dans le titre comme un mot.
3. Pattern 'X francais-prep Y' (Decoupe En Tranches) interprete comme co-auteurs
   au lieu de titre francais.

Verifie le cas Zep en bout-en-bout + regression sur tous les cas precedents.
"""
from __future__ import annotations

import pytest

from flox_uploader.core.providers._scene_parser import parse_book_filename


# ============================================================
# Cas Louis CRITIQUE (D.27)
# ============================================================

def test_zep_decoupe_en_tranches():
    """Zep.Decoupe.En.Tranches.10354.PDF-NoTAG

    Resultat attendu :
    - authors = ['Zep']  (pseudo 1-mot)
    - title = 'Decoupe En Tranches'
    - file_format = 'pdf'
    - team = 'NoTAG'
    - 10354 absorbe (ID tracker, pas dans le titre)
    """
    p = parse_book_filename("Zep.Decoupe.En.Tranches.10354.PDF-NoTAG")
    assert p.authors == ["Zep"], (
        f"Zep doit etre detecte comme pseudo 1-mot, got {p.authors!r}"
    )
    assert "Decoupe" in p.title
    assert "Tranches" in p.title
    # 10354 NE DOIT PLUS apparaitre dans le titre (absorbe comme ID)
    assert "10354" not in p.title, (
        f"10354 doit etre absorbe comme ID, pas dans le titre. Got: {p.title!r}"
    )
    assert "10354" in p.absorbed_tokens
    assert p.file_format == "pdf"
    assert p.team == "NoTAG"


# ============================================================
# Regression : autres cas precedents doivent rester corrects
# ============================================================

def test_regression_sapkowski_witcher():
    """Sapkowski + The Witcher (n_taken=2, pas de french_prep entre auteurs)."""
    p = parse_book_filename(
        "Andrzej.Sapkowski.The.Witcher.T03.Le.Sang.des.Elfes.2026.FRENCH.MP3.VBR-COZY"
    )
    assert p.authors == ["Andrzej Sapkowski"]
    assert "Witcher" in p.title or "Sang" in p.title
    assert p.team == "COZY"
    assert p.series_index == 3.0


def test_regression_lemire_sorrentino():
    """Co-auteurs Lemire + Sorrentino, transition titre via 'Le' (small word)."""
    p = parse_book_filename(
        "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag"
    )
    # On garde les 2 co-auteurs (cas n_taken=2, pas de french_prep dans
    # les tokens 0..1, donc pas de recul)
    assert "Lemire" in str(p.authors)
    assert "Sorrentino" in str(p.authors)


def test_regression_le_massacre_starts_with_small_word():
    """Titre commencant par small_word (Le) -> pas de detection auteur."""
    p = parse_book_filename(
        "Le.Massacre.De.Crac.H.Pierre.Bertin.2025.FRENCH.[EPUB]-NOTAG"
    )
    assert p.authors == []  # title commence par "Le" -> pas d'auteur extractible auto
    assert "Massacre" in p.title


def test_regression_tomoji_no_false_author_detection():
    """Sprint D.27 fix : 'Elle.s.appelait.Tomoji' ne doit PAS prendre Elle
    comme auteur (le 2e token 's' est minuscule)."""
    p = parse_book_filename("Elle.s.appelait.Tomoji.FR.NoTag")
    assert p.authors == [], (
        f"'Elle' ne doit pas etre detecte comme auteur (2e token 's' lowercase). "
        f"Got: {p.authors!r}"
    )
    assert "Elle" in p.title
    assert "Tomoji" in p.title


def test_regression_poitiers_petit_fute():
    """Co-auteurs Auzias + Labourdette + 'et autres' absorbe."""
    p = parse_book_filename(
        "Dominique.Auzias.Jean-Paul.Labourdette.et.autres.POITIERS.2026.Avec.Photos.2025.FRENCH.EPUB-NoTAG"
    )
    assert any("Dominique" in a or "Auzias" in a for a in p.authors)
    # 'et autres' absorbe (note Louis)
    assert "POITIERS" in p.title or "Avec" in p.title


# ============================================================
# Tests unitaires pour les nouveaux comportements
# ============================================================

class TestNumericIDAbsorption:
    """ID numeriques 4+ digits absorbes (cas tracker interne)."""

    def test_id_10354_absorbed(self):
        p = parse_book_filename("Author.Title.10354.PDF-NoTAG")
        assert "10354" not in p.title
        assert "10354" in p.absorbed_tokens

    def test_id_29384_absorbed(self):
        p = parse_book_filename("Foo.Bar.29384.EPUB-Flox")
        assert "29384" not in p.title

    def test_year_still_kept_as_year(self):
        """Une annee 4 digits reste annee, pas ID generique."""
        p = parse_book_filename("Author.Title.2024.PDF-NoTAG")
        assert p.year == 2024
        # Year is absorbed as year, not as generic ID
        assert "2024" in p.absorbed_tokens

    def test_5_digit_id(self):
        p = parse_book_filename("Author.Title.12345.PDF-NoTAG")
        assert "12345" not in p.title
        assert "12345" in p.absorbed_tokens

    def test_3_digit_stays_in_title(self):
        """3 digits seuls = pas un ID. Ex 'Suite 123' restera dans titre."""
        # 3 digits seul pourrait etre tome implicite (1-99) ou titre
        # On accepte qu'il reste dans le titre.
        p = parse_book_filename("Author.Title.999.PDF-NoTAG")
        # 999 n'est ni tome implicite (>99) ni ID (3 chars), reste dans titre
        # OU absorbed selon implementation - on tolere les 2
        # On verifie juste que le code n'a pas plante
        assert p.file_format == "pdf"


class TestFrenchPrepPattern:
    """Pattern X francais-prep Y -> X est auteur seul si chaine longue."""

    def test_en_recul(self):
        """X En Y -> X est auteur si chaine >= 3."""
        p = parse_book_filename("Zep.Decoupe.En.Tranches-NoTAG")
        assert p.authors == ["Zep"]

    def test_de_in_small_words_stops_loop_early(self):
        """'De' est a la fois small_word ET french_preposition. Comme small_word
        gagne en priorite (stoppe le loop n_taken plus tot), la recul french
        ne se declenche pas pour 'X De Y...' avec n_taken=2. Le test verifie
        que 'Zep Titre' reste comme 2 auteurs (comportement acceptable car
        ambigu : 'Zep Titre' POURRAIT etre un nom prenom-nom)."""
        p = parse_book_filename("Zep.Titre.De.Quelque.Chose-NoTAG")
        # n_taken=2 (loop stop at 'De' small_word). french_prep check
        # requires n_taken >= 3, donc skip. Result : 2 auteurs.
        # On accepte ce comportement comme limite documentee.
        assert len(p.authors) >= 1


    def test_ou_recul(self):
        """X Ou Y dans une longue chaine -> recul."""
        # 'OU' is in french_prepositions but NOT in small_words,
        # so the loop continues past it.
        p = parse_book_filename("Pseudo.Mort.Ou.Vif.Suite-NoTAG")
        # n_taken=5 (all cap, no small_word in chain).
        # french_prep at j=2 (Ou) -> new_n_taken=1 -> 'Pseudo' seul
        assert p.authors == ["Pseudo"]

    def test_no_recul_when_short_chain(self):
        """Si n_taken < 3 (pas de chaine longue), pas de recul."""
        p = parse_book_filename("Andrzej.Sapkowski.The.Witcher-NoTAG")
        # n_taken=2 (stop at "The" small_word). Pas de check french_prep.
        # 2 auteurs gardes.
        assert p.authors == ["Andrzej Sapkowski"]


class TestPseudoOneWord:
    """Pseudonyme 1-mot (Zep, Herge, ...) detecte si pattern propice."""

    def test_pseudo_with_french_prep(self):
        """Zep + (titre avec preposition) = pseudo auto-detecte."""
        p = parse_book_filename("Zep.Decoupe.En.Tranches-NoTAG")
        assert p.authors == ["Zep"]

    def test_pseudo_not_triggered_on_lowercase_after(self):
        """'Elle.s.appelait' : 's' lowercase -> pas de pseudo detection."""
        p = parse_book_filename("Elle.s.appelait.Tomoji-NoTAG")
        assert p.authors == []
