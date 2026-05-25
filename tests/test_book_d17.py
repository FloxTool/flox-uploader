"""Tests Sprint D.17 v0.5.0 — fallback ISBN→title quand lookup ISBN echoue.

Cible note Louis N-Rel-3 : 'le package a un ISBN 9782305108117 mais sur
google book j'ai 9782305108124'. Notre extraction prend l'ISBN ebook ou
print du fichier source ; si cet ISBN n'est PAS indexe par BnF/Google
Books (reedition annuelle, ISBN print vs ebook divergent), notre lookup
retournait None silencieusement au lieu de basculer sur title+author.

Verifie :
1. google_books : si ISBN match → retourne le match (no fallback)
2. google_books : si ISBN ne match pas (no items) mais title fourni →
   fallback automatique sur title+author
3. google_books : si ISBN cache=MISS mais title fourni → idem
4. bnf : meme comportement
"""
from __future__ import annotations

import pytest


class _MockResp:
    """Réponse HTTP mockée pour tests."""
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text
    def json(self):
        return self._payload


# ============================================================
# google_books fallback ISBN -> title
# ============================================================

def test_google_books_fallback_isbn_miss_to_title(tmp_path):
    """ISBN ne match pas en ligne → fallback automatique sur title+author."""
    from flox_uploader.core.providers.google_books import lookup_google_books

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("q", "")
        call_log.append(q)
        if "isbn:" in q:
            # ISBN lookup : 0 items
            return _MockResp({"items": []})
        # title lookup : match
        return _MockResp({
            "items": [{
                "id": "FALLBACK_OK",
                "volumeInfo": {
                    "title": "Match Title",
                    "authors": ["A"],
                },
            }],
        })

    meta = lookup_google_books(
        isbn="9782305108117",
        title="Guide Poitiers",
        author="Auzias",
        cache_file=None,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.google_books_id == "FALLBACK_OK"
    # On doit avoir au moins 2 calls : ISBN puis title
    assert len(call_log) >= 2
    assert any("isbn:" in q for q in call_log)
    assert any("intitle" in q for q in call_log)


def test_google_books_isbn_match_no_fallback(tmp_path):
    """Si ISBN match, on ne tente PAS le fallback title."""
    from flox_uploader.core.providers.google_books import lookup_google_books

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("q", "")
        call_log.append(q)
        if "isbn:" in q:
            return _MockResp({
                "items": [{
                    "id": "ISBN_MATCH",
                    "volumeInfo": {"title": "T", "authors": ["A"]},
                }],
            })
        return _MockResp({"items": []})

    meta = lookup_google_books(
        isbn="9782266154116",
        title="T",
        author="A",
        cache_file=None,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.google_books_id == "ISBN_MATCH"
    # 1 seul call (pas de fallback car ISBN a match)
    assert len(call_log) == 1


def test_google_books_isbn_miss_no_title_no_fallback(tmp_path):
    """ISBN miss + pas de title → retourne None (pas de fallback possible)."""
    from flox_uploader.core.providers.google_books import lookup_google_books

    def fake_http(url, params=None, **kwargs):
        return _MockResp({"items": []})

    meta = lookup_google_books(
        isbn="9782305108117",
        title="",
        author="",
        cache_file=None,
        http_get=fake_http,
    )
    assert meta is None


def test_google_books_cache_miss_fallback_to_title(tmp_path):
    """Si l'ISBN est cache MISS, on tente quand meme le fallback title."""
    from flox_uploader.core.providers.google_books import lookup_google_books

    # Pré-remplir le cache avec un MISS pour cet ISBN
    # (_MISS_MARKER = "__NOT_FOUND__" cote core/providers/_cache.py)
    cache_file = tmp_path / ".google_books_cache.json"
    cache_file.write_text(
        '{"9782305108117": "__NOT_FOUND__"}',
        encoding="utf-8",
    )

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("q", "")
        call_log.append(q)
        return _MockResp({
            "items": [{
                "id": "TITLE_FALLBACK",
                "volumeInfo": {"title": "T", "authors": ["A"]},
            }],
        })

    meta = lookup_google_books(
        isbn="9782305108117",
        title="Guide Poitiers",
        author="Auzias",
        cache_file=cache_file,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.google_books_id == "TITLE_FALLBACK"
    # 1 call (pas l'ISBN car cache MISS, juste le title fallback)
    assert len(call_log) == 1
    assert "intitle" in call_log[0]


# ============================================================
# bnf fallback ISBN -> title
# ============================================================

def _bnf_empty_xml() -> str:
    return '''<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
    <numberOfRecords>0</numberOfRecords>
</searchRetrieveResponse>'''


def _bnf_match_xml(title: str = "Match BnF") -> str:
    return f'''<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
    <numberOfRecords>1</numberOfRecords>
    <records><record><recordData>
        <oai_dc:dc xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/">
            <dc:title>{title}</dc:title>
            <dc:creator>Auteur</dc:creator>
        </oai_dc:dc>
    </recordData></record></records>
</searchRetrieveResponse>'''


def test_bnf_fallback_isbn_miss_to_title(tmp_path):
    """BnF : ISBN ne match pas → fallback title automatique."""
    from flox_uploader.core.providers.bnf import lookup_bnf

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("query", "")
        call_log.append(q)
        if "isbn" in q.lower():
            return _MockResp(text=_bnf_empty_xml())
        # title query
        return _MockResp(text=_bnf_match_xml("Guide Poitiers BnF"))

    meta = lookup_bnf(
        isbn="9782305108117",
        title="Guide Poitiers",
        author="Auzias",
        cache_file=None,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.title == "Guide Poitiers BnF"
    # Au moins 2 calls
    assert len(call_log) >= 2
    assert any("isbn" in q.lower() for q in call_log)
    assert any("bib.title" in q.lower() for q in call_log)


def test_bnf_isbn_match_no_fallback(tmp_path):
    """BnF : ISBN match -> pas de fallback title."""
    from flox_uploader.core.providers.bnf import lookup_bnf

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("query", "")
        call_log.append(q)
        return _MockResp(text=_bnf_match_xml("ISBN Match BnF"))

    meta = lookup_bnf(
        isbn="9782266154116",
        title="X",
        author="Y",
        cache_file=None,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.title == "ISBN Match BnF"
    assert len(call_log) == 1


def test_bnf_cache_miss_fallback_to_title(tmp_path):
    """BnF : ISBN cache MISS -> fallback title."""
    from flox_uploader.core.providers.bnf import lookup_bnf

    cache_file = tmp_path / ".bnf_cache.json"
    cache_file.write_text(
        '{"9782305108117": "__NOT_FOUND__"}',
        encoding="utf-8",
    )

    call_log = []
    def fake_http(url, params=None, **kwargs):
        q = (params or {}).get("query", "")
        call_log.append(q)
        return _MockResp(text=_bnf_match_xml("Cache miss fallback"))

    meta = lookup_bnf(
        isbn="9782305108117",
        title="Guide",
        author="Auzias",
        cache_file=cache_file,
        http_get=fake_http,
    )
    assert meta is not None
    assert meta.title == "Cache miss fallback"
    # 1 seul call : le title fallback (l'ISBN est cache MISS, on skip)
    assert len(call_log) == 1
    assert "bib.title" in call_log[0].lower()
