"""Tests Phase 3 : signaux de fallback (naming_signals) + scoring nuance.

Verifie que :
- les signaux sont bien emis depuis le pipeline aux bons moments
- les penalites correspondantes sont appliquees au score
- les nouveaux buckets (perfect/ready/good/review/blocked) sont assignes
  correctement selon les seuils
"""
from __future__ import annotations

import json
from pathlib import Path

from flox_uploader.core import naming_signals as ns
from flox_uploader.core.confidence import (
    THRESHOLD_GOOD,
    THRESHOLD_PERFECT,
    THRESHOLD_READY,
    THRESHOLD_REVIEW,
    compute_confidence_score,
)
from flox_uploader.core.debug import Debug
from flox_uploader.core.package_state import (
    PackageState,
    PackageStateData,
    write_state,
)


# ============================================================
# Helpers
# ============================================================

def _make_pkg(tmp_path: Path, debug_data: dict, state_kwargs: dict | None = None) -> Path:
    """Cree un package factice avec _debug/debug.json + package_state.json."""
    pkg = tmp_path / "test_pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "_debug").mkdir(parents=True, exist_ok=True)
    (pkg / "_debug" / "debug.json").write_text(
        json.dumps(debug_data, ensure_ascii=False), encoding="utf-8",
    )
    state_kwargs = dict(state_kwargs or {})
    state = state_kwargs.pop("state", PackageState.PREPARED)
    data = PackageStateData(state=state, release_name="test_release", **state_kwargs)
    write_state(pkg, data)
    return pkg


def _make_full_tmdb_ctx() -> dict:
    """Contexte TMDB complet pour eviter les penalites dures TMDB/IMDB."""
    return {
        "movie_id": 346,
        "title": "Seven Samurai",
        "imdb_id": "tt0047478",
    }


# ============================================================
# Module : naming_signals - emission et lecture
# ============================================================

def test_emit_signal_creates_namespace(tmp_path):
    debug = Debug(tmp_path)
    ns.emit_signal(debug, ns.SIG_LANG_INFERRED_FROM_NFO, True)
    sigs = debug.data.get("naming_signals")
    assert sigs == {ns.SIG_LANG_INFERRED_FROM_NFO: True}


def test_emit_signal_counter_keeps_max(tmp_path):
    """Pour un signal compteur (ex query_shortened), on garde le max si ré-emis."""
    debug = Debug(tmp_path)
    ns.emit_signal(debug, ns.SIG_TMDB_QUERY_SHORTENED, 1)
    ns.emit_signal(debug, ns.SIG_TMDB_QUERY_SHORTENED, 3)
    ns.emit_signal(debug, ns.SIG_TMDB_QUERY_SHORTENED, 2)
    assert debug.data["naming_signals"][ns.SIG_TMDB_QUERY_SHORTENED] == 3


def test_emit_signal_list_merges_unique(tmp_path):
    """Pour un signal liste (ex dropped tokens), on merge sans doublons."""
    debug = Debug(tmp_path)
    ns.emit_signal(debug, ns.SIG_DROPPED_UNKNOWN_TOKENS, ["Criterion"])
    ns.emit_signal(debug, ns.SIG_DROPPED_UNKNOWN_TOKENS, ["Criterion", "Bluray-1080p"])
    assert debug.data["naming_signals"][ns.SIG_DROPPED_UNKNOWN_TOKENS] == [
        "Criterion", "Bluray-1080p",
    ]


# ============================================================
# Module : compute_signal_penalty
# ============================================================

def test_compute_penalty_binary_signal():
    assert ns.compute_signal_penalty(ns.SIG_LANG_INFERRED_FROM_NFO, True) == 3
    assert ns.compute_signal_penalty(ns.SIG_LANG_INFERRED_FROM_NFO, False) == 0


def test_compute_penalty_counter_signal_multiplies():
    """SIG_TMDB_QUERY_SHORTENED : 2 pts par mot droppe."""
    assert ns.compute_signal_penalty(ns.SIG_TMDB_QUERY_SHORTENED, 1) == 2
    assert ns.compute_signal_penalty(ns.SIG_TMDB_QUERY_SHORTENED, 3) == 6


def test_compute_penalty_counter_signal_capped_at_10():
    """Garde-fou : un signal ne peut pas couter > 10 pts a lui seul."""
    # 2 pts * 100 mots = 200 pts mais cap a 10
    assert ns.compute_signal_penalty(ns.SIG_TMDB_QUERY_SHORTENED, 100) == 10


def test_compute_penalty_list_signal_per_item():
    """SIG_DROPPED_UNKNOWN_TOKENS : 1 pt par item."""
    assert ns.compute_signal_penalty(ns.SIG_DROPPED_UNKNOWN_TOKENS, ["a"]) == 1
    assert ns.compute_signal_penalty(ns.SIG_DROPPED_UNKNOWN_TOKENS, ["a", "b", "c"]) == 3


def test_compute_penalty_unknown_signal_zero():
    assert ns.compute_signal_penalty("unknown_signal_xyz", True) == 0


# ============================================================
# Buckets : 5 niveaux
# ============================================================

def test_bucket_perfect_at_100(tmp_path):
    """Lot R-C : Score 100 exact = bucket "parfait" (au-dessus de "perfect" 95-99)."""
    pkg = _make_pkg(tmp_path, {"tmdb_context": _make_full_tmdb_ctx()})
    conf = compute_confidence_score(pkg)
    assert conf.score == 100
    assert conf.bucket == "parfait"
    assert conf.bucket_color == "emerald"


def test_bucket_ready_at_92(tmp_path):
    """8 pts de penalite -> score 92 -> bucket ready."""
    debug_data = {
        "tmdb_context": _make_full_tmdb_ctx(),
        "naming_signals": {
            ns.SIG_TMDB_LANG_FALLBACK: True,        # -3
            ns.SIG_TMDB_TITLE_EN_FALLBACK: True,    # -2
            ns.SIG_RESOLUTION_INFERRED: True,       # -2
            ns.SIG_FOLDER_NAME_MINIMAL_FALLBACK: True,  # -1
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    assert conf.score == 92
    assert conf.bucket == "ready"
    assert conf.bucket_color == "green"


def test_bucket_good_at_85(tmp_path):
    """15 pts de penalite douce -> score 85 -> bucket good."""
    debug_data = {
        "tmdb_context": _make_full_tmdb_ctx(),
        "naming_signals": {
            ns.SIG_TMDB_QUERY_SHORTENED: 2,         # -4
            ns.SIG_TMDB_LANG_FALLBACK: True,        # -3
            ns.SIG_LANG_INFERRED_FROM_NFO: True,    # -3
            ns.SIG_LANG_DEFAULT_VFF_USED: True,     # -2
            ns.SIG_TEAM_DEFAULT_USED: True,         # -2
            ns.SIG_RESOLUTION_INFERRED: True,       # -2
            # Total : -16 -> 84
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    assert THRESHOLD_GOOD <= conf.score < THRESHOLD_READY
    assert conf.bucket == "good"
    assert conf.bucket_color == "yellow"


def test_bucket_review_when_no_tmdb_match(tmp_path):
    """R5 (audit AUDIT_2026-07-19) : sans match TMDB, seul -35 s'applique
    (l'IMDb absent n'est plus re-compte). 100-35 = 65 -> review (verifier),
    plus « blocked » : un nom bien forme avec juste un TMDB rate est
    reviewable, pas a overrider."""
    pkg = _make_pkg(tmp_path, {})  # pas de tmdb_context
    conf = compute_confidence_score(pkg)
    assert conf.score == 65
    assert conf.bucket == "review"


def test_bucket_blocked_dup_certain(tmp_path):
    """Doublon CERTAIN court-circuite tout : score 0 + bucket blocked."""
    pkg = _make_pkg(
        tmp_path,
        {"tmdb_context": _make_full_tmdb_ctx()},
        state_kwargs={
            "state": PackageState.ABORTED_DUPLICATE,
            "existing_torrent_id": 12345,
        },
    )
    conf = compute_confidence_score(pkg)
    assert conf.score == 0
    assert conf.bucket == "blocked"
    assert conf.bucket_color == "red"


# ============================================================
# Cas reels (reference les debug.json du user)
# ============================================================

def test_real_case_time_machine_perfect_after_fix(tmp_path):
    """Time Machine 2002 : tous les signaux OK + lang inferee MULTi.VFF.
    Resultat attendu : score 100 ou ~97 (1 signal lang_inferred = -3)."""
    debug_data = {
        "tmdb_context": {
            "movie_id": 2135,
            "title": "La Machine à explorer le temps",
            "imdb_id": "tt0268695",
        },
        "naming_signals": {
            # Auto-enrichissement langue depuis NFO (FR + EN -> MULTi.VFF)
            ns.SIG_LANG_INFERRED_FROM_NFO: True,    # -3
            # 'Bluray-1080p' droppe car non separe -> token jete apres annee
            ns.SIG_DROPPED_UNKNOWN_TOKENS: ["Bluray-1080p"],  # -1
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    assert conf.score == 96  # 100 - 3 - 1
    # 96 est >= 95 donc bucket = perfect (pas "ready" qui commence a 90 mais
    # plafonne a 94). Le seul fait d'avoir inferе la langue + drop 1 token
    # ne casse pas le bucket "parfait".
    assert conf.bucket == "perfect"


def test_real_case_seven_samurai_with_override(tmp_path):
    """Sept Samourais avec override TMDB ID 346 : matching direct, pas de
    fallback de query. Mais 'Criterion' est droppe."""
    debug_data = {
        "tmdb_context": {
            "movie_id": 346,
            "title": "Les Sept Samouraïs",
            "imdb_id": "tt0047478",
        },
        "naming_signals": {
            ns.SIG_DROPPED_UNKNOWN_TOKENS: ["Criterion"],  # -1
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    assert conf.score == 99  # 100 - 1
    assert conf.bucket == "perfect"


def test_real_case_no_tmdb_match_reviews(tmp_path):
    """Sept Samourais sans override : TMDB rien (-35). R5 : plus de -15 IMDb
    (double comptage). 100-35 = 65 -> review (a verifier)."""
    pkg = _make_pkg(tmp_path, {})
    conf = compute_confidence_score(pkg)
    assert conf.score == 65
    assert conf.bucket == "review"


# ============================================================
# Penalites mixtes (douces + dures)
# ============================================================

def test_mixed_soft_and_hard_penalties_accumulate(tmp_path):
    """Verifie que les penalites soft s'ajoutent aux penalites hard."""
    debug_data = {
        # R5 : pas de tmdb_context -> -35 (TMDB seul, plus de -15 IMDb)
        "naming_signals": {
            ns.SIG_LANG_INFERRED_FROM_NFO: True,    # -3
            ns.SIG_RESOLUTION_INFERRED: True,       # -2
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    # 100 - 35 - 3 - 2 = 60
    assert conf.score == 60
    # Le label soft est present dans les reasons. On cherche un mot stable
    # des nouveaux libellés user-friendly : "automatiquement" (cf. SIG_LANG_INFERRED_FROM_NFO)
    # et "MediaInfo" (cf. SIG_RESOLUTION_INFERRED).
    soft_labels = [
        r for r, _ in conf.penalties
        if "automatiquement" in r.lower() or "mediainfo" in r.lower()
    ]
    assert len(soft_labels) >= 1


def test_render_signal_label_for_counter():
    """Le label d'un compteur inclut le {n}."""
    label = ns.render_signal_label(ns.SIG_TMDB_QUERY_SHORTENED, 3)
    assert "3" in label
    # Mot stable du libelle user-friendly : "raccourci"
    assert "raccourci" in label.lower()


def test_render_signal_label_for_list_joins_items():
    """Le label d'une liste joint les items."""
    label = ns.render_signal_label(
        ns.SIG_DROPPED_UNKNOWN_TOKENS, ["Criterion", "Bluray-1080p"],
    )
    assert "Criterion" in label
    assert "Bluray-1080p" in label


# ============================================================
# Lot E (NOTES.md) : nouveaux signaux trust-badge
# ============================================================

def test_user_force_fr_signal_label_contains_variant():
    """SIG_USER_FORCE_FR_USED : la valeur (variante choisie) apparait dans le label."""
    label = ns.render_signal_label(ns.SIG_USER_FORCE_FR_USED, "VFQ")
    assert "VFQ" in label
    assert "manuellement" in label.lower() or "force" in label.lower()


def test_user_manual_tmdb_id_signal_label_contains_id():
    label = ns.render_signal_label(ns.SIG_USER_MANUAL_TMDB_ID, 12345)
    assert "12345" in label


def test_user_manual_release_name_signal_in_metadata():
    """Signal binaire : penalite -3, label fixe."""
    assert ns.SIG_USER_MANUAL_RELEASE_NAME in ns.SIGNAL_METADATA
    penalty, _label = ns.SIGNAL_METADATA[ns.SIG_USER_MANUAL_RELEASE_NAME]
    assert penalty == 3


def test_omdb_data_missing_signal_in_metadata():
    """Signal binaire OMDb : penalite legere -1."""
    assert ns.SIG_OMDB_DATA_MISSING in ns.SIGNAL_METADATA
    penalty, _label = ns.SIGNAL_METADATA[ns.SIG_OMDB_DATA_MISSING]
    assert penalty == 1


def test_compliance_warns_is_deprecated_no_penalty():
    """SIG_COMPLIANCE_WARNS est DEPRECATED depuis NOTES round 6 (double-comptage
    avec confidence.py qui traite deja les WARN via is_warn_minor). Le signal
    reste dans LIST_SIGNALS pour compat retro, mais sa penalite est 0."""
    assert ns.SIG_COMPLIANCE_WARNS in ns.LIST_SIGNALS
    # Tous les cas retournent 0 (penality = 0 dans SIGNAL_METADATA)
    assert ns.compute_signal_penalty(ns.SIG_COMPLIANCE_WARNS, ["foo"]) == 0
    assert ns.compute_signal_penalty(ns.SIG_COMPLIANCE_WARNS, ["a", "b", "c"]) == 0
    assert ns.compute_signal_penalty(ns.SIG_COMPLIANCE_WARNS, ["x"] * 50) == 0


def test_compliance_warns_label_includes_each_warn_message():
    """Le label rendu par render_signal_label contient un libelle par WARN
    concret (utilise dans le panneau 'Detail du score'). Un release avec
    'codec absent' + 'HDR absent' affiche les 2 messages."""
    label = ns.render_signal_label(
        ns.SIG_COMPLIANCE_WARNS,
        ["Codec audio absent du nom (DDP detecte)", "Tag HDR absent du nom (HDR10 detecte)"],
    )
    assert "Codec audio absent" in label
    assert "Tag HDR absent" in label
    assert "Conformité" in label


def test_lot_e_signals_are_emittable_and_scored(tmp_path):
    """Test bout-en-bout : on cree un debug.json avec les nouveaux signaux,
    on verifie que compute_confidence_score les compte dans les penalties.

    NOTES round 6 : SIG_COMPLIANCE_WARNS est passe a penalite 0 (deprecated,
    double-comptage avec compliance_issues). Le signal est encore present
    dans le naming_signals mais ne contribue plus au score."""
    debug_data = {
        "tmdb_context": {"movie_id": 1, "imdb_id": "tt1"},
        "lang": ["VFF"],
        "naming_signals": {
            ns.SIG_USER_FORCE_FR_USED: "VFF",          # -2
            ns.SIG_USER_MANUAL_TMDB_ID: 999,           # -2
            ns.SIG_OMDB_DATA_MISSING: True,            # -1
            ns.SIG_COMPLIANCE_WARNS: ["Codec audio absent", "HDR absent"],  # -0 (deprecated)
        },
    }
    pkg = _make_pkg(tmp_path, debug_data)
    conf = compute_confidence_score(pkg)
    # 100 - 2 - 2 - 1 - 0 = 95 (bucket "perfect")
    assert conf.score == 95
    assert conf.bucket == "perfect"
    # Les 3 signaux non-deprecates apparaissent dans les penalties
    labels = [r for r, _ in conf.penalties]
    assert any("VFF" in r for r in labels)
    assert any("999" in r for r in labels)
    assert any("OMDb" in r for r in labels)
    # NOTES round 6 : SIG_COMPLIANCE_WARNS deprecate, ne genere plus
    # d'entree dans penalties (penalty=0 -> skippe par confidence.py).
    assert not any("Codec audio absent" in r for r in labels)
    assert not any("HDR absent" in r for r in labels)
