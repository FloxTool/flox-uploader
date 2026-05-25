"""Tests Sprint D.16 v0.5.0 — normalisation queries + multi-strategies lookup.

Verifie :
1. normalize_title_for_query nettoie titre scene (dots, tokens, tome, année).
2. normalize_author_for_query gère 'et autres' et plusieurs auteurs.
3. build_query_variants produit l'ordre attendu (strict -> souple -> court).
4. google_books._query_by_title_author tente les variantes jusqu'au match.
5. bnf._query_bnf_by_title idem.
"""
from __future__ import annotations

import pytest


# ============================================================
# normalize_title_for_query
# ============================================================

def test_normalize_title_scene_with_dots():
    """Cas reel Louis N-Rel-5 : Lemire.Sorrentino.Le.mythe... → titre lisible."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_title_for_query,
    )
    raw = "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag"
    out = normalize_title_for_query(raw)
    # Dots remplacés par espaces, tokens techniques retirés, Tome.1 et 2023 enlevés
    assert "." not in out
    assert "FRENCH" not in out
    assert "PDF" not in out
    assert "NoTag" not in out.split()
    assert "Tome" not in out
    assert "2023" not in out
    # Le contenu signifiant doit rester
    assert "Lemire" in out
    assert "Ossuaire" in out
    assert "passage" in out


def test_normalize_title_integrale_range():
    """Range tomes (T01-T06) doit etre retire."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_title_for_query,
    )
    raw = "Star Wars Rebellion T01-T06 FRENCH EPUB"
    out = normalize_title_for_query(raw)
    assert "T01" not in out
    assert "T06" not in out
    assert "FRENCH" not in out
    assert "EPUB" not in out
    assert "Star Wars Rebellion" in out


def test_normalize_title_keeps_apostrophes():
    """Apostrophes preservees (L'Ile Noire)."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_title_for_query,
    )
    raw = "Tintin T07 - L'Ile Noire (1958)"
    out = normalize_title_for_query(raw)
    assert "L'Ile" in out
    assert "Noire" in out
    assert "T07" not in out
    assert "1958" not in out
    assert "(" not in out
    assert ")" not in out


def test_normalize_title_empty():
    """Vide -> vide, pas de plantage."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_title_for_query,
    )
    assert normalize_title_for_query("") == ""
    assert normalize_title_for_query(None) == ""


# ============================================================
# normalize_author_for_query
# ============================================================

def test_normalize_author_et_autres():
    """Cas reel Louis N-Rel-2 : 'Dominique Auzias et autres' -> 1er auteur."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_author_for_query,
    )
    out = normalize_author_for_query("Dominique Auzias, Jean-Paul Labourdette et autres")
    assert out == "Dominique Auzias"
    assert "autres" not in out
    assert "Labourdette" not in out


def test_normalize_author_dotted_name():
    """J.R.R.Tolkien -> J R R Tolkien."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_author_for_query,
    )
    out = normalize_author_for_query("J.R.R.Tolkien")
    # On accepte plusieurs formes valides
    assert "Tolkien" in out
    assert "." not in out


def test_normalize_author_bracketed():
    """[Tolkien] -> Tolkien."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_author_for_query,
    )
    out = normalize_author_for_query("[Tolkien]")
    assert out == "Tolkien"


def test_normalize_author_multi_comma_keeps_first():
    """Plusieurs auteurs separes par virgule -> garde le 1er."""
    from flox_uploader.core.providers._query_normalize import (
        normalize_author_for_query,
    )
    out = normalize_author_for_query("Alice Dupont, Bob Martin")
    assert out == "Alice Dupont"


# ============================================================
# build_query_variants
# ============================================================

def test_build_variants_with_author():
    """Avec auteur : strict, souple, et éventuellement tronqué/court."""
    from flox_uploader.core.providers._query_normalize import build_query_variants
    variants = build_query_variants(
        "Le Hobbit ou la et retour", author="J.R.R.Tolkien",
    )
    assert len(variants) >= 2
    # 1re variante : strict (avec quotes)
    assert variants[0].use_quotes is True
    # 2e variante : souple (sans quotes)
    assert variants[1].use_quotes is False
    # Toutes ont author non vide
    assert all(v.author for v in variants)


def test_build_variants_long_title_truncates():
    """Titre de plus de 8 mots → variante tronquée produite."""
    from flox_uploader.core.providers._query_normalize import build_query_variants
    long_title = "Un Tres Long Titre Avec Beaucoup De Mots Et Encore Plus De Mots"
    variants = build_query_variants(long_title, author="Auteur Test")
    # Au moins une variante avec un titre plus court
    titles = [v.title for v in variants]
    assert any(len(t.split()) < len(long_title.split()) for t in titles)


def test_build_variants_empty_title():
    """Titre vide -> liste vide."""
    from flox_uploader.core.providers._query_normalize import build_query_variants
    assert build_query_variants("") == []


def test_build_variants_dedup():
    """Si une variante produit la meme query qu'une autre, dedup."""
    from flox_uploader.core.providers._query_normalize import build_query_variants
    # Titre court (<8 mots) -> pas de variante "tronquée" différente
    variants = build_query_variants("Le Hobbit", author="Tolkien")
    seen_keys = set()
    for v in variants:
        k = (v.title.lower(), v.author.lower(), v.use_quotes)
        assert k not in seen_keys, f"Duplicate variant: {v}"
        seen_keys.add(k)


# ============================================================
# google_books multi-strategies (integration mock)
# ============================================================

class _MockResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


def test_google_books_tries_multiple_variants():
    """Si la 1re variante retourne vide, on essaye la suivante."""
    from flox_uploader.core.providers.google_books import _query_by_title_author

    call_count = {"n": 0}
    def fake_http(url, params=None, **kwargs):
        call_count["n"] += 1
        # Première tentative (strict) : 0 résultat
        # Deuxième tentative (souple) : 1 résultat
        if call_count["n"] == 1:
            return _MockResp({"items": []})
        return _MockResp({
            "items": [{
                "id": "MOCK_ID_42",
                "volumeInfo": {
                    "title": "Le Hobbit",
                    "authors": ["J.R.R. Tolkien"],
                },
            }],
        })

    meta = _query_by_title_author(
        "Le Hobbit ou la et retour", "Tolkien",
        api_key="", http=fake_http,
    )
    assert meta is not None
    assert meta.google_books_id == "MOCK_ID_42"
    assert call_count["n"] >= 2  # Au moins 2 tentatives


def test_google_books_returns_none_if_all_variants_fail():
    """Si toutes les variantes retournent vide -> None."""
    from flox_uploader.core.providers.google_books import _query_by_title_author

    def fake_http(url, params=None, **kwargs):
        return _MockResp({"items": []})

    meta = _query_by_title_author(
        "Inconnu Absolu Sans Match", "Personne",
        api_key="", http=fake_http,
    )
    assert meta is None


def test_google_books_stops_at_first_match():
    """Si la 1re variante matche, on n'essaye pas les suivantes."""
    from flox_uploader.core.providers.google_books import _query_by_title_author

    call_count = {"n": 0}
    def fake_http(url, params=None, **kwargs):
        call_count["n"] += 1
        return _MockResp({
            "items": [{
                "id": "FIRST_MATCH",
                "volumeInfo": {"title": "T", "authors": ["A"]},
            }],
        })

    meta = _query_by_title_author(
        "Le Hobbit", "Tolkien",
        api_key="", http=fake_http,
    )
    assert meta is not None
    assert call_count["n"] == 1  # 1 seul appel HTTP


# ============================================================
# bnf multi-strategies
# ============================================================

def test_bnf_tries_multiple_variants():
    """BnF essaye plusieurs variantes si la 1re ne matche pas."""
    from flox_uploader.core.providers.bnf import _query_bnf_by_title

    call_count = {"n": 0}
    def fake_http(url, params=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 1re tentative : 0 records
            class R:
                text = '<?xml version="1.0"?><sru:searchRetrieveResponse xmlns:sru="http://www.loc.gov/zing/srw/"><sru:numberOfRecords>0</sru:numberOfRecords></sru:searchRetrieveResponse>'
            return R()
        # 2e tentative : match
        class R2:
            text = '''<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
    <numberOfRecords>1</numberOfRecords>
    <records><record><recordData>
        <oai_dc:dc xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
            <dc:title>Match Trouvé</dc:title>
            <dc:creator>Auteur</dc:creator>
        </oai_dc:dc>
    </recordData></record></records>
</searchRetrieveResponse>'''
        return R2()

    meta = _query_bnf_by_title(
        "Long Titre Compliqué Avec Plein De Mots",
        "Auteur Test",
        http=fake_http,
    )
    assert meta is not None
    assert meta.title == "Match Trouvé"
    assert call_count["n"] >= 2
