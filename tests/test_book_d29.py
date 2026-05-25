"""Tests Sprint D.29 v0.5.0 — Guide Petit Fute : titre filename plus informatif.

Cas Louis : 'Guide Poitiers 2026 Petit Futé- Escapades dans la Vienne.epub'
devient 'Dominique.Auzias.Jean-Paul.Labourdette.et.autres.POITIERS.2026.Avec
.Photos.2025.FRENCH.EPUB-Escapades dans la Vienne' au lieu de matcher Google
Books volumeId Nw2eEQAAQBAJ ('Guide Poitiers 2026 Petit Futé Escapades dans
la Vienne').

2 bugs racine :

1. Le scene parser accepte 'Escapades dans la Vienne' comme team (alors qu'un
   team scene n'a JAMAIS d'espaces). Cause : `_is_plausible_team()` ne checke
   pas la presence d'espaces dans le candidat.

2. La metadata EPUB embarquee a un titre tronque (POITIERS 2026) alors que
   le filename a le vrai titre canonique ('Guide Poitiers Petit Fute'). On
   privilegie la metadata EPUB et on rate le match Google Books. Solution :
   passer le titre scene comme candidat alternatif au lookup.
"""
from __future__ import annotations

import pytest


# ============================================================
# Fix 1 : Team avec espaces -> rejet
# ============================================================

class TestTeamWithSpacesRejected:
    """Sprint D.29 : un team scene n'a JAMAIS d'espaces."""

    def test_escapades_not_team(self):
        """Cas Louis Petit Fute : 'Escapades dans la Vienne' n'est PAS un team."""
        from flox_uploader.core.providers._scene_parser import parse_book_filename
        p = parse_book_filename(
            "Guide Poitiers 2026 Petit Fute- Escapades dans la Vienne",
            file_format_hint="epub",
        )
        # La team ne doit PAS contenir d'espaces
        assert " " not in p.team, (
            f"Team avec espaces interdit. Got: {p.team!r}"
        )
        # Si team detectee, c'est forcement un nom valide sans espaces
        if p.team:
            assert all(not c.isspace() for c in p.team)

    def test_team_helper_rejects_spaces(self):
        """Test unitaire direct sur _is_plausible_team."""
        from flox_uploader.core.providers._scene_parser import _is_plausible_team
        # Cas avec espaces : rejetes
        assert _is_plausible_team("Escapades dans la Vienne") is False
        assert _is_plausible_team("Petit Fute") is False
        assert _is_plausible_team("Two Words") is False
        # Cas legitimes : acceptes
        assert _is_plausible_team("NoTAG") is True
        assert _is_plausible_team("COZY") is True
        assert _is_plausible_team("Punisher694") is True
        assert _is_plausible_team("Frosties") is True
        assert _is_plausible_team("PopHD") is True

    def test_team_with_tab_rejected(self):
        """Defensive : tab counts as whitespace."""
        from flox_uploader.core.providers._scene_parser import _is_plausible_team
        assert _is_plausible_team("Foo\tBar") is False

    def test_regression_existing_teams_still_pass(self):
        """Les teams legitimes doivent toujours passer."""
        from flox_uploader.core.providers._scene_parser import _is_plausible_team
        legit = ["NoTAG", "COZY", "Flox", "PopHD", "Punisher694",
                 "Frosties", "mHDgz", "k0RE", "Slay3R"]
        for t in legit:
            assert _is_plausible_team(t) is True, f"{t} should be valid team"


# ============================================================
# Fix 2 : extra_titles dans lookup_google_books
# ============================================================

class _MockResp:
    def __init__(self, json_data):
        self._json = json_data
    def json(self):
        return self._json


class TestGoogleBooksExtraTitles:
    """Sprint D.29 : Google Books accepte des titres alternatifs."""

    def test_extra_titles_param_accepted(self):
        """Signature accepte extra_titles sans plantage."""
        from flox_uploader.core.providers.google_books import lookup_google_books

        # Tout retourne vide -> None
        def fake_http(url, params=None, **kwargs):
            return _MockResp({"items": []})

        result = lookup_google_books(
            title="POITIERS 2026",
            author="Auzias",
            extra_titles=["Guide Poitiers Petit Fute"],
            http_get=fake_http,
        )
        assert result is None  # rien trouve, pas de plantage

    def test_extra_title_triggers_additional_query(self):
        """Si primary title rate, extra_title doit etre tente."""
        from flox_uploader.core.providers.google_books import lookup_google_books

        call_queries = []

        def fake_http(url, params=None, **kwargs):
            call_queries.append(params.get("q", ""))
            # Le 1er query (titre primary) retourne vide
            # Le 2e (extra_title) retourne un match
            if "Guide" in params.get("q", ""):
                return _MockResp({
                    "items": [{
                        "id": "Nw2eEQAAQBAJ",
                        "volumeInfo": {
                            "title": "Guide Poitiers 2026 Petit Fute Escapades",
                            "authors": ["Dominique Auzias"],
                            "language": "fr",
                        },
                    }]
                })
            return _MockResp({"items": []})

        result = lookup_google_books(
            title="POITIERS avec photos",
            author="Dominique Auzias",
            extra_titles=["Guide Poitiers Petit Fute"],
            http_get=fake_http,
        )
        assert result is not None
        assert result.google_books_id == "Nw2eEQAAQBAJ"
        assert "Guide Poitiers" in result.title
        # On a bien lance des queries pour les 2 titres
        all_q = " ".join(call_queries)
        assert "Guide" in all_q

    def test_extra_title_duplicate_skipped(self):
        """Si extra_title == title (apres normalisation), on ne le rejoue pas."""
        from flox_uploader.core.providers.google_books import lookup_google_books

        call_count = [0]

        def fake_http(url, params=None, **kwargs):
            call_count[0] += 1
            return _MockResp({"items": []})

        lookup_google_books(
            title="Guide Poitiers",
            author="Auzias",
            extra_titles=["Guide Poitiers"],  # meme titre
            http_get=fake_http,
        )
        # Pas de queries dupliquees pour le meme titre
        # Le compte exact depend de build_query_variants mais en tout cas
        # on n'a pas doubl le nombre de queries
        # (avant dedupe, 2 variantes par titre = 4 queries ; apres dedupe = 2)
        assert call_count[0] <= 3  # 2 variantes + tolerance edge


# ============================================================
# Integration : BookNamingStrategy passe scene_title en extra
# ============================================================

class TestBookStrategyPassesSceneTitle:
    """Sprint D.29 : la strategie livre passe scene_parsed.title comme extra."""

    def test_book_lookup_metadata_accepts_extra_titles(self):
        """lookup_book_metadata accepte extra_titles."""
        from flox_uploader.core.providers.book_lookup import lookup_book_metadata
        from flox_uploader.core.providers.book_metadata import BookMetadata

        def fake_http(url, params=None, **kwargs):
            class R:
                def json(self): return {"items": []}
                text = '<?xml version="1.0"?><a><numberOfRecords>0</numberOfRecords></a>'
                ok = True
            return R()

        base = BookMetadata(title="POITIERS 2026", authors=["Auzias"])
        # Ne doit pas planter
        result = lookup_book_metadata(
            base,
            extra_titles=["Guide Poitiers Petit Fute"],
            http_get=fake_http,
        )
        assert result is base  # mute in-place, retourne le meme

    def test_book_lookup_metadata_default_extra_titles_none(self):
        """extra_titles=None par defaut, signature backward-compat."""
        from flox_uploader.core.providers.book_lookup import lookup_book_metadata
        from flox_uploader.core.providers.book_metadata import BookMetadata
        import inspect

        sig = inspect.signature(lookup_book_metadata)
        assert "extra_titles" in sig.parameters
        assert sig.parameters["extra_titles"].default is None


# ============================================================
# Integration end-to-end (parse + scene title extraction)
# ============================================================

def test_petit_fute_filename_parses_proper_title():
    """Le filename Petit Fute parse correctement le titre via scene parser."""
    from flox_uploader.core.providers._scene_parser import parse_book_filename
    p = parse_book_filename(
        "Guide Poitiers 2026 Petit Fute- Escapades dans la Vienne",
        file_format_hint="epub",
    )
    # Le titre doit contenir au moins 'Guide' et 'Poitiers'
    assert "Guide" in p.title or "guide" in p.title.lower()
    assert "Poitiers" in p.title or "poitiers" in p.title.lower()
    # 'Escapades dans la Vienne' ne doit PAS etre la team
    assert p.team != "Escapades dans la Vienne"
    assert "dans" not in p.team.lower() if p.team else True
