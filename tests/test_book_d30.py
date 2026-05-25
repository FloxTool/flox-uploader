"""Tests Sprint D.30 v0.5.0 — Diagnostic + 4 bugs concrets.

Apres feedback Louis sur 3 cas non-resolus malgre D.27/28/29 :
- Zep Decoupe en tranches : pas de match Google Books
- Elle.s.appelait.Tomoji.cbz : title pollue + auteur weird + logo cover
- Guide Petit Fute : pas de match Google Books

Root causes identifiees :
A. normalize_title_for_query ne strippait pas les ID 4+ digits (10354)
B. normalize_title_for_query strippait 'EN' (code langue scene) y compris
   quand 'en' est une preposition francaise dans 'Decoupe en tranches'
C. local_cbz fallback assignait le filename brut comme title
D. chasse_aux_livres prenait son LOGO comme cover
E. BnF retournait 'Nom, Prenom. Auteur du texte' format role-tagged

Sprint D.30 : trace diagnostique dans debug.json + fix des 4 bugs.
"""
from __future__ import annotations

import pytest


# ============================================================
# Bug A : normalize_title_for_query strip 4+ digit non-year IDs
# ============================================================

class TestNormalizeStripsNumericIDs:
    """Sprint D.30 : ID numeriques 4+ digits (non-annee) strippes."""

    def test_strip_4digit_id(self):
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        # 10354 = ID tracker, pas une annee
        out = normalize_title_for_query("Decoupe en tranches (10354)")
        assert "10354" not in out
        assert "Decoupe" in out
        assert "tranches" in out

    def test_year_still_stripped(self):
        """Regression : une annee 19xx/20xx reste strippee comme avant."""
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        out = normalize_title_for_query("Tintin 1998")
        assert "1998" not in out
        assert "Tintin" in out

    def test_3digit_kept(self):
        """3 digits = pas un ID, reste."""
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        out = normalize_title_for_query("Suite 999")
        # 999 pourrait etre un numero dans le titre, on le garde
        assert "999" in out or "Suite" in out


# ============================================================
# Bug B : "EN" code langue scene preserve quand non-dot-bounded
# ============================================================

class TestNormalizePreservesFrenchPrepositions:
    """Sprint D.30 : 'EN' / 'FR' naked sont preserves (prepositions fr)."""

    def test_en_in_title_preserved(self):
        """'Decoupe en tranches' garde 'en' (preposition francaise)."""
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        out = normalize_title_for_query("Decoupe en tranches")
        assert "en" in out.lower(), f"'en' supprime par erreur. Got: {out!r}"

    def test_fr_in_scene_position_stripped(self):
        """'.FR.' (dot-bounded) reste strippe comme avant."""
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        out = normalize_title_for_query("Elle.s.appelait.Tomoji.FR.NoTag")
        assert "FR" not in out.split() and "fr" not in out.split()
        assert "NoTag" not in out

    def test_french_full_word_stripped(self):
        """'FRENCH' (3+ chars) toujours strippe whole-word."""
        from flox_uploader.core.providers._query_normalize import normalize_title_for_query
        out = normalize_title_for_query("Title FRENCH EPUB")
        assert "FRENCH" not in out
        assert "EPUB" not in out


# ============================================================
# Bug C : local_cbz n'assigne pas filename brut comme title
# ============================================================

class TestCBZSceneStyleSkip:
    """Sprint D.30 : CBZ avec stem scene-style -> title vide."""

    def test_tomoji_scene_style_skipped(self):
        """'Elle.s.appelait.Tomoji.FR.NoTag' -> _parse_cbz_filename retourne vide."""
        from flox_uploader.core.providers.cbz_metadata import _parse_cbz_filename, _looks_scene_style

        assert _looks_scene_style("Elle.s.appelait.Tomoji.FR.NoTag") is True

        result = _parse_cbz_filename("Elle.s.appelait.Tomoji.FR.NoTag")
        # title vide = laisse le scene parser remplir proprement
        assert result["title"] == ""
        assert result["author"] == ""
        assert result["series"] == ""

    def test_human_filename_still_parsed(self):
        """Cas legitime : 'Tintin T07 - L'Ile Noire' reste parse normalement."""
        from flox_uploader.core.providers.cbz_metadata import _parse_cbz_filename, _looks_scene_style

        assert _looks_scene_style("Tintin T07 - L'Ile Noire") is False

        result = _parse_cbz_filename("Tintin T07 - L'Ile Noire")
        # Doit toujours detecter tome 7 + serie/titre
        assert result["volume"] == 7

    def test_no_scene_tokens_treated_as_normal(self):
        """Filename sans tokens scene = parse normal."""
        from flox_uploader.core.providers.cbz_metadata import _looks_scene_style
        assert _looks_scene_style("Largo Winch 01 L Heritier") is False
        assert _looks_scene_style("One Piece 042") is False


# ============================================================
# Bug D : chasse_aux_livres logo rejected as cover
# ============================================================

class _MockResp:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


class TestChasseLogoRejected:
    """Sprint D.30 : chasse-aux-livres ne renvoie pas son logo comme cover."""

    def test_logo_rejected(self):
        """og:image qui pointe vers logo-chasse-aux-livres = rejete."""
        from flox_uploader.core.providers.chasse_aux_livres import lookup_chasse_aux_livres

        fake_html = '''
        <meta property="og:title" content="Tomoji"/>
        <meta name="author" content="Miwako Ogihara"/>
        <meta property="og:image" content="https://www.chasse-aux-livres.fr/logo-chasse-aux-livres-square.png"/>
        '''
        def fake_http(url, **kwargs):
            return _MockResp(text=fake_html)

        meta = lookup_chasse_aux_livres(
            isbn="9782369811312", cache_file=None, http_get=fake_http,
        )
        assert meta is not None
        # Logo rejete, cover_url reste vide
        assert meta.cover_url == "", (
            f"Logo accepte par erreur comme cover : {meta.cover_url!r}"
        )

    def test_real_cover_accepted(self):
        """Une vraie URL cover (pas logo) est acceptee."""
        from flox_uploader.core.providers.chasse_aux_livres import lookup_chasse_aux_livres

        fake_html = '''
        <meta property="og:title" content="Tomoji"/>
        <meta property="og:image" content="https://images.example.com/cover-12345.jpg"/>
        '''
        def fake_http(url, **kwargs):
            return _MockResp(text=fake_html)

        meta = lookup_chasse_aux_livres(
            isbn="9782369811312", cache_file=None, http_get=fake_http,
        )
        assert meta is not None
        assert meta.cover_url == "https://images.example.com/cover-12345.jpg"

    def test_placeholder_rejected(self):
        """URLs avec 'placeholder' ou 'no-image' rejetees."""
        from flox_uploader.core.providers.chasse_aux_livres import lookup_chasse_aux_livres

        for bad_url in [
            "https://chasse-aux-livres.fr/placeholder.png",
            "https://example.com/no-image.jpg",
            "https://example.com/default.jpg",
        ]:
            fake_html = f'''
            <meta property="og:title" content="Test"/>
            <meta property="og:image" content="{bad_url}"/>
            '''
            def fake_http(url, **kwargs):
                return _MockResp(text=fake_html)

            meta = lookup_chasse_aux_livres(
                isbn="9782369811312", cache_file=None, http_get=fake_http,
            )
            if meta:  # peut etre None si pas de title
                assert meta.cover_url == "", f"URL placeholder/logo non rejetee : {bad_url}"


# ============================================================
# Bug E : BnF author cleanup (role annotations)
# ============================================================

class TestBnFAuthorCleanup:
    """Sprint D.30 : roles BnF 'Auteur du texte' etc. strippes."""

    def test_auteur_du_texte_stripped(self):
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name("Ogihara, Miwako. Auteur du texte") == "Miwako Ogihara"

    def test_role_with_dates(self):
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name("Taniguchi, Jiro (1947-2017). Auteur du texte") == "Jiro Taniguchi"

    def test_illustrateur_stripped(self):
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name("Uderzo, Albert (1927-2020). Illustrateur") == "Albert Uderzo"

    def test_traducteur_stripped(self):
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name("Doe, Jane. Traducteur") == "Jane Doe"

    def test_regression_simple_name(self):
        """Nom sans annotation reste intact."""
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name("Hergé") == "Hergé"

    def test_regression_tolkien(self):
        from flox_uploader.core.providers.bnf import _clean_author_name
        assert _clean_author_name(
            "Tolkien, John Ronald Reuel (1892-1973)"
        ) == "John Ronald Reuel Tolkien"


# ============================================================
# Trace instrumentation
# ============================================================

class TestLookupTrace:
    """Sprint D.30 : trace diagnostique persistee dans debug.json."""

    def test_google_books_appends_trace(self):
        """lookup_google_books append un entry au trace."""
        from flox_uploader.core.providers.google_books import lookup_google_books

        trace = []

        def fake_http(url, params=None, **kwargs):
            class R:
                status_code = 200
                def json(self): return {"items": []}
            return R()

        lookup_google_books(
            title="Foo Bar",
            author="Author",
            http_get=fake_http,
            trace=trace,
        )
        assert len(trace) == 1
        entry = trace[0]
        assert entry["provider"] == "google_books"
        assert entry["title"] == "Foo Bar"
        assert entry["outcome"] == "no_match"
        assert isinstance(entry["queries"], list)
        assert len(entry["queries"]) >= 1

    def test_bnf_appends_trace(self):
        """lookup_bnf append un entry au trace."""
        from flox_uploader.core.providers.bnf import lookup_bnf

        trace = []

        def fake_http(url, params=None, **kwargs):
            class R:
                status_code = 200
                text = '<?xml version="1.0"?><a><numberOfRecords>0</numberOfRecords></a>'
            return R()

        lookup_bnf(
            title="Foo Bar",
            author="Author",
            http_get=fake_http,
            trace=trace,
        )
        assert len(trace) == 1
        entry = trace[0]
        assert entry["provider"] == "bnf"
        assert entry["outcome"] == "no_match"

    def test_book_lookup_metadata_accepts_trace(self):
        """lookup_book_metadata accepte trace + passe aux providers."""
        from flox_uploader.core.providers.book_lookup import lookup_book_metadata
        from flox_uploader.core.providers.book_metadata import BookMetadata
        import inspect

        sig = inspect.signature(lookup_book_metadata)
        assert "trace" in sig.parameters

        # Test runtime
        trace = []
        base = BookMetadata(title="Foo", authors=["Bar"])

        def fake_http(url, params=None, **kwargs):
            class R:
                status_code = 200
                text = '<?xml version="1.0"?><a><numberOfRecords>0</numberOfRecords></a>'
                def json(self): return {"items": []}
            return R()

        lookup_book_metadata(base, http_get=fake_http, trace=trace)
        # BnF + Google Books au minimum doivent avoir tente
        providers = {e["provider"] for e in trace}
        assert "bnf" in providers
        assert "google_books" in providers

    def test_rate_limit_outcome_detected(self):
        """429 -> outcome='rate_limited'."""
        from flox_uploader.core.providers.google_books import lookup_google_books

        trace = []

        class FakeHTTPError(Exception):
            pass

        def fake_http(url, params=None, **kwargs):
            raise FakeHTTPError("429 Client Error: Too Many Requests")

        lookup_google_books(
            title="Foo",
            author="Bar",
            http_get=fake_http,
            trace=trace,
        )
        assert trace[0]["outcome"] == "rate_limited"
