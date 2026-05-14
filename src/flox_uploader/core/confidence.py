"""Score de confiance pour un package prepare (0-100).

Le score reflete la probabilite que le package soit pret a etre uploade
sans intervention humaine. Plus le score est bas, plus la review est
necessaire.

Pondération (cf. accord avec Louis 2026-04-29 + extension naming_signals 2026-05-06) :

PENALITES DURES (signaux structurants) :
    Score initial   = 100
    TMDB pas trouve : -25
    imdb_id absent  : -10
    Variante FR ambigue (MULTi sans precision) : -20
    Compliance issue ERROR (NFO <-> release_name) : -15 par issue
    Doublon AMBIGUOUS detecte                  : -20
    Doublon VERY_LIKELY detecte                : -40
    Doublon CERTAIN detecte                    : -100 (ne sera pas uploade)

PENALITES DOUCES (signaux de fallback, cf. naming_signals.py) :
    Chaque signal emis pendant la construction du release_name retire
    1 a 5 points selon sa nature (TMDB raccourci, lang inferee, etc.).
    Capped a 10 points par signal compteur/liste pour eviter de detruire
    le score sur un cas extreme.

Buckets (5 niveaux) :
    Score >= 95 : perfect  (vert vif,   prêt)
    Score 90-94 : ready    (vert,       OK avec un coup d'œil)
    Score 80-89 : good     (jaune doux, quelques fallbacks utilises)
    Score 60-79 : review   (orange,     a verifier avant upload)
    Score <  60 : blocked  (rouge,      override requis)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .naming_signals import (
    SIGNAL_METADATA,
    compute_signal_penalty,
    get_signals,
    render_signal_label,
)
from .package_state import PackageState, read_state


# ============================================================
# CONSTANTES DE PONDERATION (penalites dures)
# ============================================================

PENALTY_TMDB_MISSING = 35          # Lot post-NOTES round 5 : 25 -> 35 (Louis :
                                   # pas de match TMDB = fiche BBCode incomplete,
                                   # vraiment penalisant pour la qualite finale)
PENALTY_IMDB_MISSING = 15          # round 5 : 10 -> 15
PENALTY_LANG_AMBIGUOUS = 20
PENALTY_LANG_NEEDS_CHOICE = 60     # variante FR ambigue + audio FR detecte = override requis
PENALTY_COMPLIANCE_ISSUE = 15
# Compliance "mineur" : warning leger qui merite un signal mais pas un
# malus comme une vraie warning. Cas typique : PGS-only (sans SRT/ASS) —
# Gemini prefere texte mais accepte. Round 5 NOTES Louis : -4.
PENALTY_COMPLIANCE_MINOR = 4

# Penalite ENORME pour les compliance BLOCKING (Lot K) : on force le bucket
# "blocked" en faisant tomber le score en dessous du seuil "review" (60).
# Cas typique : subs PGS dans encode, MKV manquant, team interdite, etc.
# Ces violations sont reellement bloquantes pour l'upload — le score doit
# refleter ca visuellement.
PENALTY_COMPLIANCE_BLOCKING = 50


def shorten_warning_label(label: str) -> str:
    """Lot U.3 : retourne une version courte du label pour l'affichage
    compact (queue). Le panneau "Detail du score" garde le label long
    explicatif ; la queue affiche le short + tooltip=long.

    Approche : pattern matching sur le debut/contenu du label. Centralise
    ici plutot que dispatch dans tous les emetteurs pour rester maintenable
    (1 seul endroit a modifier quand on ajoute un nouveau signal).
    """
    L = label  # alias plus court
    # Compliance BLOCKING (Lot K)
    if "Règle G3MINI bloquante" in L or "[BLOCKED]" in L:
        # Le label complet est tres long ("Règle G3MINI bloquante :
        # subtitles: 3 sous-titre(s) PGS dans un encode — Gemini exige..."),
        # on extrait juste le motif court apres le 1er ':'
        if "PGS dans un encode" in L:
            return "Bloque : PGS dans encode"
        if "container" in L.lower() or "MKV" in L:
            return "Bloque : conteneur non-MKV"
        if "MP3" in L:
            return "Bloque : audio MP3"
        if "FLAC" in L:
            return "Bloque : FLAC multi-canal"
        if "interdite" in L.lower() and "team" in L.lower():
            return "Bloque : team interdite"
        if "EXTREME" in L:
            return "Bloque : EXTREME sur REMUX"
        return "Règle G3MINI bloquante"
    # Doublons
    if "contient déjà ce torrent" in L:
        return "Doublon CERTAIN sur le tracker"
    if "Très probablement un doublon" in L:
        return "Doublon très probable"
    if "Possible doublon" in L:
        return "Possible doublon"
    # TMDB / IMDb
    if "TMDB indisponible momentanément" in L:
        return "TMDB partiel (fiche minimale)"
    if "Pas de correspondance TMDB" in L:
        return "Pas de match TMDB"
    if "Pas d'ID IMDb" in L:
        return "IMDb manquant"
    if "Match TMDB trouvé en français" in L:
        return "Match TMDB en FR"
    if "Titre raccourci" in L:
        return "Titre TMDB raccourci"
    if "Titre français utilisé" in L:
        return "Titre FR utilisé"
    if "Titre anglais utilisé" in L:
        return "Titre EN (non-latin)"
    # Compliance non-bloquant
    if "Conformité charte Gemini" in L:
        return "Divergence NFO/nom"
    if "Conformité (non-bloquant)" in L:
        # Le label long contient le détail apres ":" — on extrait
        msg = L.split(":", 1)[-1].strip() if ":" in L else L
        return msg[:60] + "…" if len(msg) > 60 else msg
    # Categorie
    if "Catégorie devinée par défaut" in L:
        return "Catégorie incertaine"
    # Langue
    if "MULTi sans précision" in L or "MULTi sans precision" in L:
        return "MULTi sans variante FR"
    if "Tag de langue ajouté" in L:
        return "Langue ajoutée auto"
    if "VFF appliquée par défaut" in L:
        return "VFF par défaut"
    if "VFi détecté" in L:
        return "VFi → VFF"
    # MediaInfo
    if "Résolution récupérée depuis MediaInfo" in L:
        return "Résolution depuis MediaInfo"
    # Team
    if "Aucune team détectée" in L:
        return "Team → NoTAG"
    # Tokens
    if "Tokens non reconnus" in L or "Token non reconnu" in L:
        # Souvent court deja, on garde
        return L if len(L) <= 70 else L[:70] + "…"
    # OMDb
    if "OMDb non disponible" in L or "note IMDb / récompenses" in L:
        return "Note IMDb absente"
    # Overrides utilisateur
    if "Variante FR forcée" in L:
        return "Force FR manuel"
    if "TMDB ID forcé" in L:
        return "TMDB ID manuel"
    if "Nom de release saisi" in L:
        return "Release name manuel"
    if "Nom du dossier minimaliste" in L:
        return "Nom dossier minimal"
    if "CRF" in L and "hors plage" in L:
        return "CRF hors plage Gemini"
    if "Sous-titre(s) PGS uniquement" in L:
        return "PGS sans subs texte"
    # Fallback : tronquer si trop long
    return L[:70] + "…" if len(L) > 70 else L
PENALTY_DUP_AMBIGUOUS = 20
PENALTY_DUP_VERY_LIKELY = 40
PENALTY_DUP_CERTAIN = 100

# Seuils de classification visuelle (5 buckets)
THRESHOLD_PARFAIT = 100   # 100 exact -> parfait (★, vert + glow eclatant)
THRESHOLD_PERFECT = 95    # 95-99 -> perfect (✓, vert vif, glow attenue)
THRESHOLD_READY = 90      # 90-94 -> ready   (↑, vert standard)
THRESHOLD_GOOD = 80       # 80-89 -> good    (~,  jaune doux)
THRESHOLD_REVIEW = 60     # 60-79 -> review  (⚠,  orange)
                          # <  60 -> blocked (❌, rouge)


# ============================================================
# RESULTAT
# ============================================================

@dataclass
class ConfidenceScore:
    """Score detaille d'un package."""
    score: int                          # 0-100, clamped
    bucket: str                         # "ready" | "review" | "blocked"
    bucket_emoji: str                   # ✓ ⚠ ❌
    bucket_color: str                   # tailwind class : green | amber | red
    reasons: list[str] = field(default_factory=list)
    # Detail des penalites appliquees
    penalties: list[tuple[str, int]] = field(default_factory=list)


# ============================================================
# CACHE EN MEMOIRE (in-process)
# ============================================================
# Le score depend uniquement de debug.json + package_state.json. On stocke
# le resultat avec leur mtime composite comme cle de validite. La queue
# polle /api/queue/snapshot toutes les 2s et appelle compute_confidence_score
# pour chaque package -> sans cache, c'etait 2 fopen+parse par package par
# poll. Avec 200 packages et un poll 2s : 400 lectures/2s == 200/s.

_score_cache: dict[Path, tuple[float, "ConfidenceScore"]] = {}


def _cache_signature(package_dir: Path) -> float:
    """Signature de validite du cache : max(mtime debug.json, mtime state.json).

    Si l'un des deux fichiers est modifie, la signature change -> recompute.
    Si les deux sont absents, on retourne 0 (compute sera trivial).
    """
    debug_file = package_dir / "_debug" / "debug.json"
    state_file = package_dir / "package_state.json"
    try:
        m1 = debug_file.stat().st_mtime if debug_file.is_file() else 0.0
    except OSError:
        m1 = 0.0
    try:
        m2 = state_file.stat().st_mtime if state_file.is_file() else 0.0
    except OSError:
        m2 = 0.0
    return max(m1, m2)


def invalidate_score_cache(package_dir: Path | None = None) -> None:
    """Invalide une entree du cache (ou tout le cache si package_dir=None).
    Utile quand on sait qu'un fichier vient de changer hors de notre vue.
    """
    if package_dir is None:
        _score_cache.clear()
    else:
        _score_cache.pop(package_dir, None)


# ============================================================
# CALCUL
# ============================================================

def compute_confidence_score(package_dir: Path) -> ConfidenceScore:
    """Calcule le score de confiance d'un package.

    Lit `package_state.json` + `_debug/debug.json` du package. Tous les
    signaux qui manquent / sont ambigus reduisent le score.

    Hierarchie : si DOUBLON CERTAIN -> on n'affiche QUE ce warning (les autres
    deviennent du bruit). Si MULTi force a choisir -> on masque le warning
    compliance qui en decoule mecaniquement.

    Resultat memoise par `package_dir` avec invalidation par mtime composite
    de debug.json et package_state.json (cf. _cache_signature).
    """
    sig = _cache_signature(package_dir)
    cached = _score_cache.get(package_dir)
    if cached and cached[0] == sig:
        return cached[1]

    debug = _read_debug(package_dir)
    state_data = read_state(package_dir)

    # === 1. Doublon CERTAIN cote tracker : court-circuit complet ===
    is_dup_certain = False
    dup_id = None
    if state_data and state_data.state == PackageState.ABORTED_DUPLICATE:
        is_dup_certain = True
        dup_id = state_data.existing_torrent_id
    elif state_data:
        dc = (state_data.dedup_confidence or "").strip().lower()
        if dc == "certain":
            is_dup_certain = True
            dup_id = state_data.existing_torrent_id

    if is_dup_certain:
        # Score = 0, un seul label, on n'ajoute aucun autre warning.
        # Le label reste concis ; le lien "Voir le doublon" est ajoute cote
        # template (queue.html / package_detail.html) en utilisant l'ID
        # disponible dans state_data.existing_torrent_id.
        label = "Le tracker contient déjà ce torrent. L'upload sera refusé."
        result = ConfidenceScore(
            score=0,
            bucket="blocked",
            bucket_emoji="✗",
            bucket_color="red",
            reasons=[label],
            penalties=[(label, PENALTY_DUP_CERTAIN)],
        )
        _score_cache[package_dir] = (sig, result)
        return result

    score = 100
    penalties: list[tuple[str, int]] = []

    # 2. TMDB
    tmdb_ctx = debug.get("tmdb_context") or {}
    tmdb_id = (
        tmdb_ctx.get("movie_id")
        or tmdb_ctx.get("tv_id")
        or tmdb_ctx.get("tmdb_id")
        or 0
    )
    if not tmdb_id:
        score -= PENALTY_TMDB_MISSING
        penalties.append((
            "Pas de correspondance TMDB. La fiche BBCode sera incomplète "
            "(pas de poster, casting, synopsis). Vérifie le titre dans le "
            "nom du fichier source ou force un TMDB ID manuel.",
            PENALTY_TMDB_MISSING,
        ))

    # 3. IMDB
    imdb_id = tmdb_ctx.get("imdb_id") or ""
    if not imdb_id:
        score -= PENALTY_IMDB_MISSING
        penalties.append((
            "Pas d'ID IMDb associé sur TMDB. La note IMDb / récompenses "
            "ne pourront pas être affichées sur la fiche.",
            PENALTY_IMDB_MISSING,
        ))

    # 4. Langue ambigue
    # Source forte : flag lang_needs_choice ecrit par release_name quand le
    # pipeline a force "MULTi" pour eviter de mourir, mais le user doit choisir.
    needs_choice = bool(debug.get("lang_needs_choice"))
    if needs_choice:
        score -= PENALTY_LANG_NEEDS_CHOICE
        penalties.append((
            "Le release est tagué MULTi sans préciser la variante FR "
            "(VFF / VFQ / VFB / VF2). La charte Gemini exige cette "
            "précision : choisis-la dans 'Forcer la variante FR' "
            "ci-dessus puis re-prépare le package.",
            PENALTY_LANG_NEEDS_CHOICE,
        ))
    else:
        # Source faible : lang contient "MULTi" sans precision -> -20
        lang = debug.get("lang") or []
        if isinstance(lang, list):
            for l in lang:
                if isinstance(l, str) and l.upper().strip() == "MULTI":
                    score -= PENALTY_LANG_AMBIGUOUS
                    penalties.append((
                        "Tag 'MULTi' sans variante précise — vérifie que "
                        "le release est bien un MULTi-doublage avant upload.",
                        PENALTY_LANG_AMBIGUOUS,
                    ))
                    break

    # 5. Compliance issues : on les detaille un par un (pas un compteur).
    # On reconnait DEUX niveaux :
    # - [BLOCKED] : Lot K — violation dure (PGS dans encode, MKV manquant,
    #   team interdite, etc.). Penalite massive (50 pts) qui force le bucket
    #   "blocked" pour rester coherent avec l'etat FAILED du package.
    # - [!!ERROR] / "ERROR" : divergence visible (codec annonce vs detecte)
    #   mais non bloquante. Penalite moderee (15 pts).
    # SAUF si needs_choice est actif (les compliance issues en sont la
    # consequence mecanique d'un meme bug, ne pas double-compter).
    issues = debug.get("compliance_issues") or []
    if isinstance(issues, list) and not needs_choice:
        for issue in issues:
            if not isinstance(issue, str):
                continue
            issue_upper = issue.upper()
            is_blocking = "[BLOCKED]" in issue_upper or "BLOCKING" in issue_upper
            is_error = "ERROR" in issue_upper and not is_blocking
            # WARN level : non bloquant, non error. Maintenant traite generiquement
            # (NOTES round 6) :
            # - "PGS UNIQUEMENT" -> -4 (preference mineure Gemini specifique)
            # - autres WARN -> -1 generique (codec absent, hdr absent, etc.)
            is_warn = (
                not is_blocking and not is_error
                and ("[ WARN ]" in issue_upper or "[WARN]" in issue_upper
                     or issue_upper.startswith("WARN:") or issue_upper.startswith("SEVERITY.WARN"))
            )
            if is_warn:
                is_warn_pgs_only = "PGS UNIQUEMENT" in issue_upper
                # Strip prefixes pour avoir un label propre
                label_warn = issue.strip()
                for prefix in ("[ WARN ]", "[WARN]", "Severity.WARN:", "WARN:"):
                    if label_warn.upper().startswith(prefix.upper()):
                        label_warn = label_warn[len(prefix):].strip()
                        break
                # Strip field prefix (ex: "subtitles: ..." -> "...")
                if ":" in label_warn:
                    first, rest = label_warn.split(":", 1)
                    if len(first) < 30:
                        label_warn = rest.strip()
                if len(label_warn) > 200:
                    label_warn = label_warn[:200] + "..."
                if is_warn_pgs_only:
                    score -= PENALTY_COMPLIANCE_MINOR
                    penalties.append((
                        f"Preference Gemini (mineur) : {label_warn}",
                        PENALTY_COMPLIANCE_MINOR,
                    ))
                else:
                    # WARN generique : -1 (pas grave, juste un signal)
                    score -= 1
                    penalties.append((
                        f"Conformite (non-bloquant) : {label_warn}",
                        1,
                    ))
                continue
            if not (is_blocking or is_error):
                continue
            # Resume de l'issue : on tronque les longues, on enleve les marqueurs
            label = issue.strip()
            for prefix in (
                "[BLOCKED]", "Severity.BLOCKING:", "BLOCKING:",
                "[!! ERROR]", "[!!ERROR]", "Severity.ERROR:",
                "ERROR:", "Severity.ERROR -",
            ):
                if label.upper().startswith(prefix.upper()):
                    label = label[len(prefix):].strip()
                    break
            # Strip aussi le prefixe "field:" (ex: "subtitles: 3 sub PGS...")
            # pour rester lisible
            if ":" in label and len(label.split(":", 1)[0]) < 30:
                # heuristique : si le 1er segment avant ':' est court (< 30c),
                # c'est probablement un nom de champ, on le retire
                pass  # on garde le contexte pour le user
            if len(label) > 220:
                label = label[:220] + "..."
            if is_blocking:
                score -= PENALTY_COMPLIANCE_BLOCKING
                penalties.append((
                    f"Règle G3MINI bloquante : {label}",
                    PENALTY_COMPLIANCE_BLOCKING,
                ))
            else:
                score -= PENALTY_COMPLIANCE_ISSUE
                penalties.append((
                    f"Conformité charte Gemini — divergence entre le NFO et "
                    f"le nom de release : {label}",
                    PENALTY_COMPLIANCE_ISSUE,
                ))

    # 6. Doublon non-certain (very_likely / ambiguous)
    if state_data:
        dc = (state_data.dedup_confidence or "").strip().lower()
        if dc == "very_likely":
            score -= PENALTY_DUP_VERY_LIKELY
            penalties.append((
                "Très probablement un doublon. Vérifier avant l'upload "
                "pour ne pas se prendre un refus du tracker.",
                PENALTY_DUP_VERY_LIKELY,
            ))
        elif dc == "ambiguous":
            score -= PENALTY_DUP_AMBIGUOUS
            penalties.append((
                "Possible doublon (taille proche d'un torrent existant sur le tracker).",
                PENALTY_DUP_AMBIGUOUS,
        ))

    # 7. Penalites DOUCES : signaux de fallback emis pendant la construction
    # du release_name (cf. naming_signals.py). Chaque signal retire 1 a 5 pts
    # pour signaler une approximation sans tomber dans la classe "review".
    naming_signals = get_signals(debug)
    for signal_key, signal_value in naming_signals.items():
        if signal_key not in SIGNAL_METADATA:
            continue
        penalty = compute_signal_penalty(signal_key, signal_value)
        if penalty <= 0:
            continue
        label = render_signal_label(signal_key, signal_value)
        score -= penalty
        penalties.append((label, penalty))

    # Clamp 0-100
    score = max(0, min(100, score))

    # Bucket : 5 niveaux pour donner une vraie granularite. Symboles choisis
    # pour un glance immediat :
    # - perfect (≥95)  : ✓ emerald + glow CSS = signal le plus fort
    # - ready   (90-94): ↑ green   = montee, OK avec un coup d'oeil
    # - good    (80-89): ~ yellow  = ondulation, quelques fallbacks
    # - review  (60-79): ⚠ amber   = a verifier
    # - blocked (<60)  : ✗ red     = override requis
    # Lot R-C : nouveau bucket "parfait" (100 exact) avec son propre glow
    # plus eclatant. 95-99 reste "perfect" mais glow attenue.
    if score >= THRESHOLD_PARFAIT:
        bucket, emoji, color = "parfait", "★", "emerald"
    elif score >= THRESHOLD_PERFECT:
        bucket, emoji, color = "perfect", "✓", "emerald"
    elif score >= THRESHOLD_READY:
        bucket, emoji, color = "ready", "↑", "green"
    elif score >= THRESHOLD_GOOD:
        bucket, emoji, color = "good", "~", "yellow"
    elif score >= THRESHOLD_REVIEW:
        bucket, emoji, color = "review", "⚠", "amber"
    else:
        bucket, emoji, color = "blocked", "✗", "red"

    reasons = [label for label, _ in penalties]

    result = ConfidenceScore(
        score=score,
        bucket=bucket,
        bucket_emoji=emoji,
        bucket_color=color,
        reasons=reasons,
        penalties=penalties,
    )
    _score_cache[package_dir] = (sig, result)
    return result


def _read_debug(package_dir: Path) -> dict:
    """Lit _debug/debug.json (cree par process_one). Vide si absent."""
    debug_file = package_dir / "_debug" / "debug.json"
    if not debug_file.is_file():
        return {}
    try:
        return json.loads(debug_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
