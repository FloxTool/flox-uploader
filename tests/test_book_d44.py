"""Tests Sprint D.44 v0.5.0 — Space Brothers T33 fixes.

Cible feedback Louis : 3 incoherences sur Space Brothers T33.cbz :
1. Title local affiche '2021' au lieu de 'Space Brothers T33'
2. Lien Google Books pointe vers la mauvaise fiche (T28 au lieu de T33)
3. Si on cherche 'Space.Brothers.T33' sur Google manuellement, on trouve le bon
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================
# Fix 1 : sanitize_book_title clear les titres suspects
# ============================================================

class TestSanitizeClearSuspect:
    """sanitize_book_title doit retourner '' (pas '2021') quand le residu
    est juste une annee / chapitre / nombre seul."""

    def test_year_only_cleared(self):
        from flox_uploader.core.providers._query_normalize import sanitize_book_title
        assert sanitize_book_title("2021") == ""
        assert sanitize_book_title("2024") == ""
        assert sanitize_book_title("1999") == ""

    def test_year_with_lang_cleared(self):
        """Cas Louis Space Brothers : '2021.FR' -> strip FR -> '2021' -> clear."""
        from flox_uploader.core.providers._query_normalize import sanitize_book_title
        # ".FR" stripped par _SCENE_TRAILING_TOKENS_RE, puis "2021" detect comme suspect
        assert sanitize_book_title("2021.FR") == ""

    def test_chapter_only_cleared(self):
        from flox_uploader.core.providers._query_normalize import sanitize_book_title
        assert sanitize_book_title("C1180") == ""
        assert sanitize_book_title("C 1180") == ""

    def test_number_only_cleared(self):
        from flox_uploader.core.providers._query_normalize import sanitize_book_title
        assert sanitize_book_title("12345") == ""
        assert sanitize_book_title("7") == ""

    def test_valid_title_preserved(self):
        from flox_uploader.core.providers._query_normalize import sanitize_book_title
        assert sanitize_book_title("Le Seigneur des Anneaux") == "Le Seigneur des Anneaux"
        # Year dans un title valide (pas suspect)
        assert sanitize_book_title("POITIERS 2024") == "POITIERS 2024"


# ============================================================
# Fix 2 : Google Books ranking penalise titles suspects
# ============================================================

class TestGoogleBooksScoringSuspect:
    """_title_suspect_penalty + _parse_best_item prefere les titles meaningful."""

    def test_suspect_penalty_year_only(self):
        from flox_uploader.core.providers.google_books import _title_suspect_penalty
        assert _title_suspect_penalty("2021") == 200
        assert _title_suspect_penalty("1999") == 200

    def test_suspect_penalty_chapter(self):
        from flox_uploader.core.providers.google_books import _title_suspect_penalty
        assert _title_suspect_penalty("C1180") == 200

    def test_suspect_penalty_number(self):
        from flox_uploader.core.providers.google_books import _title_suspect_penalty
        assert _title_suspect_penalty("42") == 200

    def test_suspect_penalty_normal_title(self):
        from flox_uploader.core.providers.google_books import _title_suspect_penalty
        assert _title_suspect_penalty("Space Brothers T33") == 0
        assert _title_suspect_penalty("Le Seigneur des Anneaux") == 0

    def test_suspect_penalty_very_short(self):
        from flox_uploader.core.providers.google_books import _title_suspect_penalty
        assert _title_suspect_penalty("ab") == 100

    def test_parse_best_item_prefers_meaningful_over_suspect(self):
        """Cas Louis Space Brothers T33 : 2 candidates Google Books avec le
        meme ISBN, on doit preferer celle au title 'Space Brothers T33'
        (meaningful) plutot que celle au title '2021' (suspect).
        """
        from flox_uploader.core.providers.google_books import _parse_best_item

        data = {
            "items": [
                # Candidate 1 : title suspect (year seul) — celui qui sortait avant
                {
                    "id": "ZXe9ygEACAAJ",
                    "volumeInfo": {
                        "title": "2021",
                        "authors": ["Chūya Koyama"],
                        "publishedDate": "2021",
                        "industryIdentifiers": [
                            {"type": "ISBN_13", "identifier": "9782811644796"},
                        ],
                    },
                },
                # Candidate 2 : title meaningful (= le bon)
                {
                    "id": "elEXEAAAQBAJ",
                    "volumeInfo": {
                        "title": "Space Brothers T33",
                        "authors": ["Chūya Koyama"],
                        "publishedDate": "2021",
                        "industryIdentifiers": [
                            {"type": "ISBN_13", "identifier": "9782811644796"},
                        ],
                    },
                },
            ]
        }
        result = _parse_best_item(data)
        assert result is not None
        assert result.google_books_id == "elEXEAAAQBAJ"
        assert "Space Brothers" in result.title


# ============================================================
# Fix 3 : BnF volume mismatch reject
# ============================================================

class TestBnfVolumeRejection:
    """lookup_bnf rejette les matches au volume mismatch."""

    def _bnf_match_xml(self, title: str = "Match BnF") -> str:
        # Format BnF identique aux tests existants (test_book_d17.py)
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

    def test_bnf_rejects_wrong_volume(self):
        """Cas Louis Space Brothers T33 : BnF retourne 'Space brothers. 28'
        (T28) alors qu'on cherchait T33 -> reject + return None."""
        from flox_uploader.core.providers.bnf import lookup_bnf

        def fake_http(url, params=None, **kw):
            mock_resp = MagicMock()
            mock_resp.text = self._bnf_match_xml("Space brothers. 28")
            mock_resp.status_code = 200
            return mock_resp

        # Avec target_volume=33, le match T28 doit etre rejette
        result = lookup_bnf(
            title="Space Brothers",
            http_get=fake_http,
            target_volume=33.0,
        )
        # Doit retourner None car volume mismatch
        assert result is None

    def test_bnf_accepts_matching_volume(self):
        """Si BnF retourne T33 et on cherche T33 -> accepte."""
        from flox_uploader.core.providers.bnf import lookup_bnf

        def fake_http(url, params=None, **kw):
            mock_resp = MagicMock()
            mock_resp.text = self._bnf_match_xml("Space brothers. 33")
            mock_resp.status_code = 200
            return mock_resp

        result = lookup_bnf(
            title="Space Brothers",
            http_get=fake_http,
            target_volume=33.0,
        )
        assert result is not None
        assert "33" in result.title

    def test_bnf_no_target_volume_keeps_legacy(self):
        """Sans target_volume, le comportement reste celui d'avant (match T28 accepte)."""
        from flox_uploader.core.providers.bnf import lookup_bnf

        def fake_http(url, params=None, **kw):
            mock_resp = MagicMock()
            mock_resp.text = self._bnf_match_xml("Space brothers. 28")
            mock_resp.status_code = 200
            return mock_resp

        # Sans target_volume, on accepte T28 (legacy behavior)
        result = lookup_bnf(
            title="Space Brothers",
            http_get=fake_http,
            # pas de target_volume
        )
        assert result is not None
        assert "28" in result.title
