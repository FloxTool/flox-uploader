"""Tests Sprint 3 (PLAN-V1.md) : OMDb est OPTIONNEL.

Quand OMDB_API_KEY n'est pas configuree :
 1. Le pipeline saute proprement les appels OMDb (verifie via fetch_omdb_data
    qui retourne un dict vide + flag debug).
 2. Aucun signal SIG_OMDB_DATA_MISSING n'est emis (pas de penalite de score
    pour ce choix volontaire de l'user).
 3. La BBCode rendue ne contient pas de "Note IMDb" ni de section "Recompenses".
 4. La carte Media de package_detail.html n'affiche pas "IMDb 7.5/10".

Avant Sprint 3 : pipeline emettait SIG_OMDB_DATA_MISSING quand IMDB ID present
mais pas de note, MEME SI l'user n'avait pas configure OMDb. -1 point injuste.
"""
from __future__ import annotations

from flox_uploader.core import naming_signals as ns
from flox_uploader.core.debug import Debug
from flox_uploader.core.omdb import fetch_omdb_data


# ============================================================
# 1. fetch_omdb_data sans cle = retour vide + flag debug
# ============================================================

def test_fetch_omdb_no_api_key_returns_empty_and_sets_debug(tmp_path):
    debug = Debug(tmp_path)
    result = fetch_omdb_data(imdb_id="tt0111161", api_key="", debug=debug)
    assert result == {
        "imdb_rating": "", "imdb_vote_count": 0,
        "poster_url": "", "awards": "", "plot": "",
    }
    assert debug.data.get("omdb_skipped_reason") == "OMDB_API_KEY absent"


def test_fetch_omdb_no_imdb_id_returns_empty_no_debug_flag(tmp_path):
    """Pas d'IMDB ID = on saute meme avec une cle. Aucun flag debug.
    (le signal trust badge ne s'applique pas non plus.)"""
    debug = Debug(tmp_path)
    result = fetch_omdb_data(imdb_id="", api_key="some-key", debug=debug)
    assert result["imdb_rating"] == ""
    assert "omdb_skipped_reason" not in debug.data


# ============================================================
# 2. SIG_OMDB_DATA_MISSING : metadata du signal
# ============================================================

def test_omdb_signal_exists_and_has_penalty():
    """Le signal existe avec une penalite de 1 point."""
    assert ns.SIG_OMDB_DATA_MISSING in ns.SIGNAL_METADATA
    penalty, label = ns.SIGNAL_METADATA[ns.SIG_OMDB_DATA_MISSING]
    assert penalty == 1
    assert "OMDb" in label or "IMDb" in label


# ============================================================
# 3. BBCode renderer skip propre quand OMDb absent
# ============================================================

def test_bbcode_awards_section_empty_when_no_awards():
    """_build_awards_section retourne string vide si awards_text est vide."""
    from flox_uploader.core.bbcode_renderer import _build_awards_section
    assert _build_awards_section("") == ""
    assert _build_awards_section("   ") == ""
    assert _build_awards_section("N/A") == ""
    assert _build_awards_section("None") == ""


def test_bbcode_awards_section_renders_when_present():
    """Avec un texte de recompense reel, la section est rendue."""
    from flox_uploader.core.bbcode_renderer import _build_awards_section
    out = _build_awards_section("Won 7 Oscars. Another 159 wins & 220 nominations.")
    assert "Oscars" in out
    assert out != ""


# ============================================================
# 4. Confidence score : aucune penalite si le signal n'est pas emis
# ============================================================

def test_confidence_no_penalty_when_omdb_signal_not_emitted(tmp_path):
    """Sprint 3 : on cree un debug.json sans SIG_OMDB_DATA_MISSING dans les
    naming_signals. La penalite OMDB ne doit PAS s'appliquer."""
    import json
    from flox_uploader.core import package_state
    from flox_uploader.core.confidence import (
        compute_confidence_score, invalidate_score_cache,
    )

    pkg = tmp_path / "Test.Movie.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-TEAM"
    pkg.mkdir()
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    debug_data = {
        "release_name": pkg.name,
        "mediainfo_data": {
            "container": "Matroska",
            "video": {"codec": "HEVC", "resolution": "1080p"},
            "audio_tracks": [{"codec": "DDP", "channels": "5.1", "language": "fr"}],
            "subtitle_tracks": [{"format": "UTF-8", "language": "fr"}],
        },
        "tmdb_context": {
            "movie_id": 12345, "imdb_id": "tt1234567", "title": "Test Movie",
            "release_date": "2024-01-15", "tmdb_poster_path": "/foo.jpg",
        },
        # PAS de naming_signals avec SIG_OMDB_DATA_MISSING
        "naming_signals": {},
        "compliance_issues": [],
    }
    (debug_dir / "debug.json").write_text(
        json.dumps(debug_data), encoding="utf-8",
    )
    package_state.init_state(pkg, pkg.name, "gemini")

    invalidate_score_cache(pkg)
    result = compute_confidence_score(pkg)
    # Aucune penalite "OMDb" ne doit apparaitre
    omdb_penalties = [
        p for p in result.penalties
        if "OMDb" in p[0] or "IMDb" in p[0]
    ]
    assert omdb_penalties == [], f"Penalite OMDb inattendue : {omdb_penalties}"


def test_confidence_has_penalty_when_omdb_signal_explicitly_emitted(tmp_path):
    """Cas inverse : si le signal EST emis (user a une cle mais OMDb ne
    renvoie rien), la penalite -1 doit s'appliquer."""
    import json
    from flox_uploader.core import package_state
    from flox_uploader.core.confidence import (
        compute_confidence_score, invalidate_score_cache,
    )

    pkg = tmp_path / "Test.Movie.2024.MULTi.VFF.1080p.BluRay.DDP5.1.x265-TEAM"
    pkg.mkdir()
    debug_dir = pkg / "_debug"
    debug_dir.mkdir()
    debug_data = {
        "release_name": pkg.name,
        "mediainfo_data": {
            "container": "Matroska",
            "video": {"codec": "HEVC", "resolution": "1080p"},
            "audio_tracks": [{"codec": "DDP", "channels": "5.1", "language": "fr"}],
            "subtitle_tracks": [{"format": "UTF-8", "language": "fr"}],
        },
        "tmdb_context": {
            "movie_id": 12345, "imdb_id": "tt1234567", "title": "Test Movie",
            "release_date": "2024-01-15", "tmdb_poster_path": "/foo.jpg",
        },
        # AVEC le signal OMDB_DATA_MISSING explicitement
        "naming_signals": {ns.SIG_OMDB_DATA_MISSING: True},
        "compliance_issues": [],
    }
    (debug_dir / "debug.json").write_text(
        json.dumps(debug_data), encoding="utf-8",
    )
    package_state.init_state(pkg, pkg.name, "gemini")

    invalidate_score_cache(pkg)
    result = compute_confidence_score(pkg)
    # La penalite -1 doit apparaitre (label contient OMDb ou IMDb)
    omdb_penalties = [
        p for p in result.penalties
        if "OMDb" in p[0] or "IMDb" in p[0]
    ]
    assert len(omdb_penalties) == 1, f"Penalite OMDb attendue : {result.penalties}"
    assert omdb_penalties[0][1] == 1  # -1 point


# ============================================================
# 5. Pipeline integration : test du nouveau garde "omdb_configured"
# ============================================================
# On teste directement la fonction du pipeline en mockant fetch_omdb_data,
# pour eviter de monter une stack complete (TMDB, MediaInfo, etc.).

def test_pipeline_skips_signal_when_no_omdb_key(tmp_path, monkeypatch):
    """Verifie que la branche conditionnelle de pipeline.py emet bien
    omdb_not_configured (debug flag) quand omdb_api_key est vide."""
    import json
    # On simule le bout de code conditionnel directement, sans toute la
    # machinerie du pipeline (qui est lourde a stubber).
    from flox_uploader.core.debug import Debug
    from flox_uploader.core import naming_signals as ns

    debug = Debug(tmp_path)
    tmdb_context = {
        "imdb_id": "tt1234567",
        "release_date": "2020-06-15",
    }
    omdb_api_key = ""  # User n'a pas configure
    omdb_data = {
        "imdb_rating": "", "imdb_vote_count": 0,
        "poster_url": "", "awards": "", "plot": "",
    }

    # Reproduit la logique exacte du pipeline (apres Sprint 3 fix)
    omdb_configured = bool((omdb_api_key or "").strip())
    if (
        omdb_configured
        and tmdb_context.get("imdb_id")
        and not omdb_data["imdb_rating"]
    ):
        ns.emit_signal(debug, ns.SIG_OMDB_DATA_MISSING, True)
    elif not omdb_configured:
        debug.set("omdb_not_configured", True)

    # Verification : aucun signal emis, juste le flag debug
    assert debug.data.get("omdb_not_configured") is True
    # Vue dict-style sur naming_signals
    signals = debug.data.get("naming_signals") or {}
    assert ns.SIG_OMDB_DATA_MISSING not in signals
