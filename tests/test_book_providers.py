"""Tests Sprint D.2 v0.5.0 : providers BnF, Google Books, OpenLibrary + orchestrateur.

Pas d'appel HTTP reel : on injecte un `http_get` mock qui retourne des
reponses pre-construites (XML BnF, JSON Google/OpenLibrary). Verifie le
parsing, le cache atomique, la degradation gracieuse en cas d'erreur.

Cf. PLAN-MULTICAT.md §7.4 + §9 Sprint D.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flox_uploader.core.providers._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, normalize_isbn, save_cache,
)
from flox_uploader.core.providers.book_lookup import lookup_book_metadata
from flox_uploader.core.providers.book_metadata import (
    BookMetadata, book_from_dict, book_to_dict,
)
from flox_uploader.core.providers.bnf import lookup_bnf
from flox_uploader.core.providers.google_books import lookup_google_books
from flox_uploader.core.providers.openlibrary import lookup_openlibrary


def _mock_response(text: str = "", json_data=None) -> MagicMock:
    """Construit un mock requests.Response."""
    resp = MagicMock()
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


# ============================================================
# _cache helpers
# ============================================================

def test_normalize_isbn_strips_dashes_and_spaces():
    assert normalize_isbn("978-2-267-02704-4") == "9782267027044"
    assert normalize_isbn("978 2267 02704 4") == "9782267027044"
    assert normalize_isbn("urn:isbn:9782267027044") == "9782267027044"
    assert normalize_isbn("ISBN-13:9782267027044") == "9782267027044"
    assert normalize_isbn("0747532699") == "0747532699"
    assert normalize_isbn("074753269X") == "074753269X"  # check digit X


def test_normalize_isbn_rejects_invalid():
    assert normalize_isbn("") == ""
    assert normalize_isbn("123") == ""
    assert normalize_isbn("not-an-isbn") == ""
    assert normalize_isbn("978226702704A") == ""  # lettre dans le corps


def test_cache_save_and_load_roundtrip(tmp_path):
    cache_file = tmp_path / "test_cache.json"
    save_cache(cache_file, {"9782267027044": {"title": "Test"}})
    loaded = load_cache(cache_file)
    assert loaded == {"9782267027044": {"title": "Test"}}


def test_cache_load_missing_returns_empty(tmp_path):
    assert load_cache(tmp_path / "ghost.json") == {}


def test_cache_load_corrupt_returns_empty(tmp_path):
    cache_file = tmp_path / "corrupt.json"
    cache_file.write_text("{ this is not valid json", encoding="utf-8")
    assert load_cache(cache_file) == {}


def test_cache_miss_marker_roundtrip():
    """is_miss reconnait le marker fait par make_miss."""
    marker = make_miss()
    assert is_miss(marker)
    assert not is_miss({"title": "found"})
    assert not is_miss(None)


# ============================================================
# BookMetadata serialisation
# ============================================================

def test_book_to_dict_and_back_roundtrip():
    """to_dict + from_dict redonne un BookMetadata equivalent."""
    original = BookMetadata(
        title="Le Hobbit",
        authors=["J.R.R. Tolkien"],
        isbn_13="9782266154116",
        publisher="Pocket",
        publication_year=2004,
        language="fr",
        page_count=384,
        series="Le Hobbit",
        series_index=1.0,
        description="Bilbo part a l'aventure.",
        cover_url="https://example.com/cover.jpg",
        genres=["Fantasy"],
        sources=["local_epub", "bnf"],
    )
    d = book_to_dict(original)
    # JSON-serializable
    json.dumps(d)
    rebuilt = book_from_dict(d)
    assert rebuilt.title == original.title
    assert rebuilt.authors == original.authors
    assert rebuilt.isbn_13 == original.isbn_13
    assert rebuilt.publication_year == original.publication_year
    assert rebuilt.series == original.series
    assert rebuilt.series_index == original.series_index
    assert rebuilt.sources == original.sources


def test_book_from_dict_tolerant_to_missing_keys():
    """from_dict ne plante pas sur un dict partiel."""
    meta = book_from_dict({"title": "Solo"})
    assert meta.title == "Solo"
    assert meta.authors == []
    assert meta.publication_year == 0


def test_book_from_dict_tolerant_to_non_dict():
    """from_dict({}) ou from_dict(None) retourne BookMetadata vide."""
    assert book_from_dict({}).title == ""
    assert book_from_dict(None).title == ""  # type: ignore[arg-type]


# ============================================================
# BnF provider
# ============================================================

_BNF_RESPONSE_TOLKIEN = """<?xml version="1.0" encoding="UTF-8"?>
<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">
    <srw:numberOfRecords>1</srw:numberOfRecords>
    <srw:records>
        <srw:record>
            <srw:recordSchema>dublincore</srw:recordSchema>
            <srw:recordData>
                <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
                           xmlns:dc="http://purl.org/dc/elements/1.1/">
                    <dc:title>Le Seigneur des anneaux</dc:title>
                    <dc:creator>Tolkien, John Ronald Reuel (1892-1973)</dc:creator>
                    <dc:publisher>Paris : Christian Bourgois , 2002</dc:publisher>
                    <dc:date>2002</dc:date>
                    <dc:language>fre</dc:language>
                    <dc:identifier scheme="ISBN">9782267027044</dc:identifier>
                    <dc:description>Le grand classique de la fantasy.</dc:description>
                    <dc:subject>Fantasy</dc:subject>
                    <dc:subject>Roman anglais</dc:subject>
                </oai_dc:dc>
            </srw:recordData>
        </srw:record>
    </srw:records>
</srw:searchRetrieveResponse>
"""

_BNF_RESPONSE_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">
    <srw:numberOfRecords>0</srw:numberOfRecords>
</srw:searchRetrieveResponse>
"""


def test_bnf_parses_tolkien_record(tmp_path):
    """Parsing d'un record BnF avec titre + auteur + ISBN + date + langue."""
    http = MagicMock(return_value=_mock_response(text=_BNF_RESPONSE_TOLKIEN))
    meta = lookup_bnf(isbn="9782267027044", http_get=http)
    assert meta is not None
    assert meta.title == "Le Seigneur des anneaux"
    # "Tolkien, John Ronald Reuel" doit etre inverse en "John Ronald Reuel Tolkien"
    assert meta.authors == ["John Ronald Reuel Tolkien"]
    # Editeur nettoye : "Paris : Christian Bourgois , 2002" -> "Christian Bourgois"
    assert "Christian Bourgois" in meta.publisher
    assert meta.publication_year == 2002
    assert meta.language == "fr"  # "fre" -> "fr"
    assert meta.isbn_13 == "9782267027044"
    assert "Fantasy" in meta.genres
    assert "bnf" in meta.sources


def test_bnf_returns_none_on_empty_response(tmp_path):
    """numberOfRecords=0 -> None."""
    http = MagicMock(return_value=_mock_response(text=_BNF_RESPONSE_EMPTY))
    meta = lookup_bnf(isbn="9999999999999", http_get=http)
    assert meta is None


def test_bnf_returns_none_on_http_error():
    """Erreur HTTP -> None sans plantage."""
    http = MagicMock(side_effect=RuntimeError("network down"))
    meta = lookup_bnf(isbn="9782267027044", http_get=http)
    assert meta is None


def test_bnf_caches_results(tmp_path):
    """Apres un lookup reussi, le cache est ecrit. Le 2eme appel hit le cache."""
    http = MagicMock(return_value=_mock_response(text=_BNF_RESPONSE_TOLKIEN))
    cache_file = tmp_path / ".bnf_cache.json"
    # 1er lookup : appelle HTTP
    meta1 = lookup_bnf(isbn="9782267027044", cache_file=cache_file, http_get=http)
    assert meta1 is not None
    assert http.call_count == 1
    # 2eme lookup : cache hit, pas d'appel HTTP supplementaire
    meta2 = lookup_bnf(isbn="9782267027044", cache_file=cache_file, http_get=http)
    assert meta2 is not None
    assert meta2.title == meta1.title
    assert http.call_count == 1  # toujours 1, pas 2


def test_bnf_caches_misses(tmp_path):
    """Les 'pas trouve' sont aussi cachees pour eviter de re-fetch."""
    http = MagicMock(return_value=_mock_response(text=_BNF_RESPONSE_EMPTY))
    cache_file = tmp_path / ".bnf_cache.json"
    # 1er lookup : 0 record -> None + cache write avec marker miss
    meta1 = lookup_bnf(isbn="9999999999999", cache_file=cache_file, http_get=http)
    assert meta1 is None
    assert http.call_count == 1
    # 2eme lookup : hit le miss marker, pas de HTTP
    meta2 = lookup_bnf(isbn="9999999999999", cache_file=cache_file, http_get=http)
    assert meta2 is None
    assert http.call_count == 1


def test_bnf_clean_author_name_inversion():
    """'Nom, Prenom (dates)' -> 'Prenom Nom'."""
    from flox_uploader.core.providers.bnf import _clean_author_name
    assert _clean_author_name("Tolkien, John Ronald Reuel (1892-1973)") == "John Ronald Reuel Tolkien"
    assert _clean_author_name("Hugo, Victor") == "Victor Hugo"
    # Si pas de virgule, on garde tel quel
    assert _clean_author_name("Single Name") == "Single Name"


# ============================================================
# Google Books provider
# ============================================================

_GOOGLE_RESPONSE_HOBBIT = {
    "items": [
        {
            "id": "abc123",
            "volumeInfo": {
                "title": "Le Hobbit",
                "subtitle": "ou la, et retour",
                "authors": ["J.R.R. Tolkien"],
                "publisher": "Pocket Jeunesse",
                "publishedDate": "2004-09-30",
                "description": "Bilbo Sacquet part a l'aventure...",
                "industryIdentifiers": [
                    {"type": "ISBN_13", "identifier": "9782266154116"},
                    {"type": "ISBN_10", "identifier": "2266154117"},
                ],
                "pageCount": 384,
                "language": "fr",
                "categories": ["Juvenile Fiction / Fantasy & Magic"],
                "imageLinks": {
                    "thumbnail": "http://books.google.com/books/content?id=abc&zoom=1",
                    "smallThumbnail": "http://books.google.com/books/content?id=abc&zoom=5",
                },
            },
        }
    ]
}


def test_google_books_parses_hobbit(tmp_path):
    """Parsing complet d'un volume Google Books."""
    http = MagicMock(return_value=_mock_response(json_data=_GOOGLE_RESPONSE_HOBBIT))
    meta = lookup_google_books(isbn="9782266154116", http_get=http)
    assert meta is not None
    assert meta.title == "Le Hobbit"
    assert meta.subtitle == "ou la, et retour"
    assert meta.authors == ["J.R.R. Tolkien"]
    assert meta.publisher == "Pocket Jeunesse"
    assert meta.publication_year == 2004
    assert meta.isbn_13 == "9782266154116"
    assert meta.isbn_10 == "2266154117"
    assert meta.page_count == 384
    assert meta.language == "fr"
    assert "Fantasy" in meta.genres[0] or "Juvenile" in meta.genres[0]
    # URL forcee en HTTPS (Google sert HTTP par defaut)
    assert meta.cover_url.startswith("https://")
    assert "google_books" in meta.sources


def test_google_books_returns_none_on_empty_items():
    """items: [] -> None."""
    http = MagicMock(return_value=_mock_response(json_data={"items": []}))
    meta = lookup_google_books(isbn="9999999999999", http_get=http)
    assert meta is None


def test_google_books_returns_none_on_no_items_key():
    """Reponse sans cle 'items' (pas trouve) -> None."""
    http = MagicMock(return_value=_mock_response(json_data={"totalItems": 0}))
    meta = lookup_google_books(isbn="9999999999999", http_get=http)
    assert meta is None


def test_google_books_returns_none_on_http_error():
    http = MagicMock(side_effect=ConnectionError("connection refused"))
    meta = lookup_google_books(isbn="9782266154116", http_get=http)
    assert meta is None


def test_google_books_caches(tmp_path):
    http = MagicMock(return_value=_mock_response(json_data=_GOOGLE_RESPONSE_HOBBIT))
    cache_file = tmp_path / ".google_books_cache.json"
    meta1 = lookup_google_books(isbn="9782266154116", cache_file=cache_file, http_get=http)
    meta2 = lookup_google_books(isbn="9782266154116", cache_file=cache_file, http_get=http)
    assert meta1 is not None and meta2 is not None
    assert http.call_count == 1  # cache hit au 2eme


# ============================================================
# OpenLibrary provider
# ============================================================

_OPENLIB_RESPONSE_TOLKIEN = {
    "ISBN:9782267027044": {
        "title": "Le Seigneur des Anneaux",
        "authors": [{"name": "John Ronald Reuel Tolkien"}],
        "publishers": [{"name": "Christian Bourgois"}],
        "publish_date": "2002",
        "number_of_pages": 1280,
        "identifiers": {"isbn_13": ["9782267027044"]},
        "subjects": [{"name": "Fantasy"}, "Adventure"],
        "languages": [{"key": "/languages/fre"}],
        "cover": {
            "large": "https://covers.openlibrary.org/b/id/12345-L.jpg",
            "medium": "https://covers.openlibrary.org/b/id/12345-M.jpg",
        },
    }
}


def test_openlibrary_parses_tolkien(tmp_path):
    http = MagicMock(return_value=_mock_response(json_data=_OPENLIB_RESPONSE_TOLKIEN))
    meta = lookup_openlibrary(isbn="9782267027044", http_get=http)
    assert meta is not None
    assert meta.title == "Le Seigneur des Anneaux"
    assert meta.authors == ["John Ronald Reuel Tolkien"]
    assert meta.publisher == "Christian Bourgois"
    assert meta.publication_year == 2002
    assert meta.page_count == 1280
    assert meta.isbn_13 == "9782267027044"
    assert meta.language == "fr"  # "/languages/fre" -> "fr"
    assert "Fantasy" in meta.genres
    assert "Adventure" in meta.genres
    assert meta.cover_url.startswith("https://")
    assert "openlibrary" in meta.sources


def test_openlibrary_returns_none_on_empty():
    """Reponse vide (bibkey absente) -> None."""
    http = MagicMock(return_value=_mock_response(json_data={}))
    meta = lookup_openlibrary(isbn="9999999999999", http_get=http)
    assert meta is None


def test_openlibrary_returns_none_on_no_isbn():
    """Pas d'ISBN -> on ne fait meme pas l'appel."""
    http = MagicMock()
    meta = lookup_openlibrary(isbn="", http_get=http)
    assert meta is None
    assert http.call_count == 0


# ============================================================
# Orchestrateur lookup_book_metadata()
# ============================================================

def test_orchestrator_returns_base_when_no_isbn_no_title():
    """Sans ISBN ni titre/auteur, on ne peut rien chercher -> retour direct."""
    base = BookMetadata()  # vide
    result = lookup_book_metadata(base)
    assert result is base  # in-place
    assert result.sources == []  # aucun provider appele


def test_orchestrator_calls_all_3_providers_in_order(tmp_path):
    """Si on a un ISBN, les 3 providers sont appeles dans l'ordre."""
    calls = []

    def fake_http(url, params=None, **kwargs):
        # Repere quel provider est appele d'apres l'URL
        if "bnf.fr" in url:
            calls.append("bnf")
            return _mock_response(text=_BNF_RESPONSE_TOLKIEN)
        if "googleapis.com/books" in url:
            calls.append("google")
            return _mock_response(json_data=_GOOGLE_RESPONSE_HOBBIT)
        if "openlibrary.org" in url:
            calls.append("openlib")
            return _mock_response(json_data=_OPENLIB_RESPONSE_TOLKIEN)
        raise ValueError(f"Unexpected URL: {url}")

    base = BookMetadata(isbn_13="9782267027044", title="Le Seigneur des Anneaux",
                        authors=["J.R.R. Tolkien"])
    result = lookup_book_metadata(base, cache_dir=tmp_path, http_get=fake_http)
    # Les 3 providers ont ete appeles
    assert "bnf" in calls
    assert "google" in calls
    assert "openlib" in calls
    # Sources tracees dans le meta
    assert "bnf" in result.sources
    assert "google_books" in result.sources
    assert "openlibrary" in result.sources


def test_orchestrator_skips_openlibrary_without_isbn():
    """OpenLibrary requiert ISBN -> skip si pas d'ISBN."""
    calls = []

    def fake_http(url, params=None, **kwargs):
        if "openlibrary.org" in url:
            calls.append("openlib")
        if "bnf.fr" in url:
            return _mock_response(text=_BNF_RESPONSE_EMPTY)
        if "googleapis.com" in url:
            return _mock_response(json_data={"items": []})
        raise ValueError(f"unexpected: {url}")

    # Pas d'ISBN, juste title + author -> BnF et Google peuvent essayer, openlib skip
    base = BookMetadata(title="Titre", authors=["Auteur"])
    lookup_book_metadata(base, http_get=fake_http)
    assert calls == []  # openlib n'a JAMAIS ete appele


def test_orchestrator_continues_when_one_provider_fails(tmp_path):
    """Si BnF plante, on continue avec Google + OpenLib."""
    def fake_http(url, params=None, **kwargs):
        if "bnf.fr" in url:
            raise ConnectionError("BnF down")
        if "googleapis.com" in url:
            return _mock_response(json_data=_GOOGLE_RESPONSE_HOBBIT)
        if "openlibrary.org" in url:
            return _mock_response(json_data=_OPENLIB_RESPONSE_TOLKIEN)
        raise ValueError(url)

    base = BookMetadata(isbn_13="9782267027044")
    result = lookup_book_metadata(base, cache_dir=tmp_path, http_get=fake_http)
    # BnF rate, mais Google + OpenLib ont enrichi
    assert "bnf" not in result.sources
    assert "google_books" in result.sources
    assert "openlibrary" in result.sources


def test_orchestrator_preserves_local_extraction(tmp_path):
    """L'extraction locale (base) n'est PAS ecrasee par les providers en ligne."""
    def fake_http(url, params=None, **kwargs):
        if "googleapis.com" in url:
            # Google renvoie un titre different
            data = json.loads(json.dumps(_GOOGLE_RESPONSE_HOBBIT))
            data["items"][0]["volumeInfo"]["title"] = "Titre Different Google"
            data["items"][0]["volumeInfo"]["authors"] = ["Auteur Different Google"]
            return _mock_response(json_data=data)
        if "bnf.fr" in url:
            return _mock_response(text=_BNF_RESPONSE_EMPTY)
        if "openlibrary.org" in url:
            return _mock_response(json_data={})
        raise ValueError(url)

    base = BookMetadata(
        title="Titre Local",
        authors=["Auteur Local"],
        isbn_13="9782266154116",
    )
    lookup_book_metadata(base, cache_dir=tmp_path, http_get=fake_http)
    # Le titre/auteur local NE doivent PAS etre ecrases
    assert base.title == "Titre Local"
    assert base.authors == ["Auteur Local"]
    # Mais d'autres champs peuvent etre completes (publisher, year, description...)
    assert base.publisher == "Pocket Jeunesse"
    assert base.publication_year == 2004


def test_orchestrator_completes_empty_fields(tmp_path):
    """Les providers en ligne COMPLETENT les champs vides du base."""
    def fake_http(url, params=None, **kwargs):
        if "bnf.fr" in url:
            return _mock_response(text=_BNF_RESPONSE_TOLKIEN)
        if "googleapis.com" in url:
            return _mock_response(json_data={"items": []})
        if "openlibrary.org" in url:
            return _mock_response(json_data={})
        raise ValueError(url)

    base = BookMetadata(isbn_13="9782267027044")  # juste l'ISBN, le reste vide
    lookup_book_metadata(base, cache_dir=tmp_path, http_get=fake_http)
    # BnF a complete tous les champs
    assert base.title == "Le Seigneur des anneaux"
    assert base.authors == ["John Ronald Reuel Tolkien"]
    assert base.publication_year == 2002
