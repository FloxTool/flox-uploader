"""Tests Sprint D.26 v0.5.0 — Providers additionnels (chasse-aux-livres + leslibraires.ca).

Cible note Louis N-LS2 : "plus on a d'option plus on recupere d'info.
on continu tant qu'on a pas toute les infos. j'ai mis 2 site de
librairy mais je te laisse trouver quel sont les meilleure site qu'on
peut rajouter."

Verifie :
1. _html_scraper helpers (fetch_html, extract_first, extract_all)
2. chasse_aux_livres parsing (meta tags og:title, og:image, name=author)
3. leslibraires_ca parsing (Schema.org microdata + meta tags)
4. Integration dans book_lookup orchestrator
5. Defensive : pas de plantage sur HTML invalide / reseau down / ISBN absent
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ============================================================
# _html_scraper helpers
# ============================================================

def test_extract_first_basic():
    from flox_uploader.core.providers._html_scraper import extract_first
    html = '<h1>Le Hobbit</h1>'
    assert extract_first(html, r"<h1>(.*?)</h1>") == "Le Hobbit"


def test_extract_first_strips_inline_tags():
    from flox_uploader.core.providers._html_scraper import extract_first
    html = '<h1>Le <em>Hobbit</em></h1>'
    assert extract_first(html, r"<h1>(.*?)</h1>") == "Le Hobbit"


def test_extract_first_decodes_entities():
    from flox_uploader.core.providers._html_scraper import extract_first
    html = '<meta name="author" content="Tolkien &amp; Co"/>'
    assert extract_first(
        html, r'<meta\s+name="author"\s+content="([^"]+)"',
    ) == "Tolkien & Co"


def test_extract_first_returns_empty_on_no_match():
    from flox_uploader.core.providers._html_scraper import extract_first
    assert extract_first("<p>foo</p>", r"<h1>(.*?)</h1>") == ""


def test_extract_all():
    from flox_uploader.core.providers._html_scraper import extract_all
    html = '<span itemprop="author">A</span> <span itemprop="author">B</span>'
    out = extract_all(html, r'<[^>]+itemprop="author"[^>]*>([^<]+)</[^>]+>')
    assert out == ["A", "B"]


# ============================================================
# chasse_aux_livres
# ============================================================

class _MockResp:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


def test_chasse_parses_meta_tags(tmp_path):
    """HTML chasse-aux-livres parse correctement meta tags."""
    from flox_uploader.core.providers.chasse_aux_livres import (
        lookup_chasse_aux_livres,
    )
    fake_html = '''<html>
    <head>
        <meta property="og:title" content="Le Seigneur des Anneaux | chasse-aux-livres"/>
        <meta name="author" content="J.R.R. Tolkien"/>
        <meta property="og:image" content="https://chasse.example/cover.jpg"/>
    </head>
    <body><h1>Le Seigneur des Anneaux</h1></body>
    </html>'''

    def fake_http(url, **kwargs):
        return _MockResp(text=fake_html)

    meta = lookup_chasse_aux_livres(
        isbn="9782266154116", cache_file=None, http_get=fake_http,
    )
    assert meta is not None
    assert meta.title == "Le Seigneur des Anneaux"
    assert "J.R.R. Tolkien" in meta.authors
    assert meta.cover_url == "https://chasse.example/cover.jpg"
    assert meta.isbn_13 == "9782266154116"
    assert "chasse_aux_livres" in meta.sources


def test_chasse_multiple_authors(tmp_path):
    """Plusieurs auteurs separes par virgule -> liste."""
    from flox_uploader.core.providers.chasse_aux_livres import (
        lookup_chasse_aux_livres,
    )
    fake_html = '<meta name="author" content="Alice Dupont, Bob Martin"/>'

    def fake_http(url, **kwargs):
        return _MockResp(text=fake_html)

    meta = lookup_chasse_aux_livres(
        isbn="9782266154116", cache_file=None, http_get=fake_http,
    )
    # On a tente une recherche mais pas trouve title -> meta=None
    # Donc on rajoute aussi un title pour que le parse retourne meta
    fake_html2 = (
        '<meta property="og:title" content="Test"/>'
        '<meta name="author" content="Alice Dupont, Bob Martin"/>'
    )

    def fake_http2(url, **kwargs):
        return _MockResp(text=fake_html2)

    meta = lookup_chasse_aux_livres(
        isbn="9782266154116", cache_file=None, http_get=fake_http2,
    )
    assert meta is not None
    assert "Alice Dupont" in meta.authors
    assert "Bob Martin" in meta.authors


def test_chasse_no_isbn_returns_none():
    from flox_uploader.core.providers.chasse_aux_livres import (
        lookup_chasse_aux_livres,
    )
    assert lookup_chasse_aux_livres(isbn="", cache_file=None) is None


def test_chasse_empty_html_returns_none():
    """Reseau OK mais HTML vide -> None (pas de cache MISS pour potentiel reessai)."""
    from flox_uploader.core.providers.chasse_aux_livres import (
        lookup_chasse_aux_livres,
    )

    def fake_http(url, **kwargs):
        return _MockResp(text="")

    assert lookup_chasse_aux_livres(
        isbn="9782266154116", cache_file=None, http_get=fake_http,
    ) is None


def test_chasse_cache_miss_persisted(tmp_path):
    """Si page parsee retourne None, on cache MISS pour eviter retry."""
    from flox_uploader.core.providers.chasse_aux_livres import (
        lookup_chasse_aux_livres,
    )

    def fake_http(url, **kwargs):
        # Page existe mais vide de contenu utile
        return _MockResp(text="<html><body>Pas trouve</body></html>")

    cache = tmp_path / ".chasse_aux_livres_cache.json"
    result = lookup_chasse_aux_livres(
        isbn="9782266154116", cache_file=cache, http_get=fake_http,
    )
    assert result is None
    # Cache MISS persisté
    assert cache.is_file()
    import json as _json
    data = _json.loads(cache.read_text(encoding="utf-8"))
    assert "9782266154116" in data


# ============================================================
# leslibraires_ca
# ============================================================

def test_leslibraires_parses_schema_org(tmp_path):
    """HTML leslibraires.ca utilise Schema.org microdata."""
    from flox_uploader.core.providers.leslibraires_ca import (
        lookup_leslibraires_ca,
    )
    fake_html = '''<html>
    <head>
        <meta property="og:title" content="La Trilogie des Vents T3 - Les Libraires"/>
        <meta property="og:image" content="https://leslibraires.example/cov.jpg"/>
    </head>
    <body>
        <span itemprop="name">La Trilogie des Vents T3</span>
        <span itemprop="author">Mercedes Lackey</span>
        <span itemprop="publisher">Bragelonne</span>
    </body>
    </html>'''

    def fake_http(url, **kwargs):
        return _MockResp(text=fake_html)

    meta = lookup_leslibraires_ca(
        isbn="9782811204808", cache_file=None, http_get=fake_http,
    )
    assert meta is not None
    assert meta.title == "La Trilogie des Vents T3"
    assert "Mercedes Lackey" in meta.authors
    assert meta.publisher == "Bragelonne"
    assert meta.cover_url == "https://leslibraires.example/cov.jpg"
    assert "leslibraires_ca" in meta.sources


def test_leslibraires_no_isbn_returns_none():
    from flox_uploader.core.providers.leslibraires_ca import (
        lookup_leslibraires_ca,
    )
    assert lookup_leslibraires_ca(isbn="", cache_file=None) is None


def test_leslibraires_html_no_match_returns_none():
    """HTML sans title ni author -> None."""
    from flox_uploader.core.providers.leslibraires_ca import (
        lookup_leslibraires_ca,
    )

    def fake_http(url, **kwargs):
        return _MockResp(text="<html><body>404</body></html>")

    assert lookup_leslibraires_ca(
        isbn="9782811204808", cache_file=None, http_get=fake_http,
    ) is None


# ============================================================
# Integration book_lookup orchestrator
# ============================================================

def test_book_lookup_includes_new_providers_in_default_order():
    """providers_order par defaut contient chasse_aux_livres + leslibraires_ca."""
    from flox_uploader.core.providers.book_lookup import lookup_book_metadata
    from flox_uploader.core.providers.book_metadata import BookMetadata
    import inspect

    sig = inspect.signature(lookup_book_metadata)
    default_order = sig.parameters["providers_order"].default
    assert "chasse_aux_livres" in default_order
    assert "leslibraires_ca" in default_order


def test_book_lookup_chains_after_other_providers(tmp_path):
    """Si BnF/Google/OpenLib retournent vide, chasse-aux-livres prend le relais."""
    from flox_uploader.core.providers.book_lookup import lookup_book_metadata
    from flox_uploader.core.providers.book_metadata import BookMetadata

    # Mock HTTP : tous les providers reseau retournent vide SAUF chasse
    call_log = []

    def fake_http(url, params=None, **kwargs):
        call_log.append(url)
        # BnF SRU + Google Books + OpenLibrary : reponse vide
        if "bnf.fr" in url:
            class R: text = '<?xml version="1.0"?><a><numberOfRecords>0</numberOfRecords></a>'
            return R()
        if "googleapis.com" in url:
            class R:
                def json(self): return {"items": []}
            return R()
        if "openlibrary.org" in url:
            class R:
                def json(self): return {}
            return R()
        # chasse-aux-livres trouve
        if "chasse-aux-livres" in url:
            class R:
                ok = True
                text = '''<meta property="og:title" content="Found Title"/>
                       <meta name="author" content="Trouvé"/>'''
            return R()
        # leslibraires fallback (mais on s'attend a stop avant)
        class R:
            ok = True
            text = ""
        return R()

    base = BookMetadata(isbn_13="9782266154116")
    enriched = lookup_book_metadata(
        base, cache_dir=tmp_path, http_get=fake_http,
    )
    # chasse_aux_livres doit avoir ete consulte
    assert any("chasse-aux-livres" in u for u in call_log)
    # Title trouve via chasse
    assert enriched.title == "Found Title"
