"""Re-score a package without re-running the prepare pipeline.

NOTES round 8 P5.8 — "Re-score in place".

Use case : un package a ete prepare il y a longtemps avec des regles de
scoring (ou de compliance) qui depuis ont ete fixees. Le user ne veut
PAS regenerer le .torrent (changerait l'infohash, risquerait de devoir
re-uploader cote tracker), mais veut juste rafraichir le score affiche
dans l'UI pour qu'il reflete les regles actuelles.

Mecanique :
 1. Lit `_debug/debug.json` du package (contient mediainfo_data, release_name,
    naming_signals, tmdb_context — tout ce qu'il faut pour scorer).
 2. Re-execute `check_compliance(release_name, mediainfo_data, ...)` avec les
    regles actuelles. Le resultat remplace `compliance_issues` dans debug.json.
 3. Re-ecrit aussi `blocking_compliance_messages` (denormalisation cache) pour
    rester coherent.
 4. Invalide le cache de scoring pour ce package (mtime de debug.json change
    de toute facon, donc l'invalidation auto fonctionnerait aussi — mais on
    force pour eviter toute race avec le poll de la queue).
 5. Recalcule le score et le retourne, avec le score precedent pour comparaison.

Ce qu'on ne touche PAS, deliberement :
  - Le .torrent file (=> infohash preserve)
  - package_state.json (etat machine intact, y compris UPLOADED)
  - Les fichiers NFO / release_name.txt / presentation.bbcode
  - TMDB context / dedup confidence (deja en cache, pas de re-fetch)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RescoreResult:
    """Diff entre l'ancien et le nouveau score apres rescore."""
    old_score: int
    new_score: int
    old_bucket: str
    new_bucket: str
    old_issues: list[str]
    new_issues: list[str]
    removed_issues: list[str]   # issues qui sont parties (etaient bloquantes, ne le sont plus)
    added_issues: list[str]     # issues nouvelles (rare : code plus strict aujourd'hui)

    @property
    def changed(self) -> bool:
        return self.old_score != self.new_score or self.old_issues != self.new_issues


def rescore_package(package_dir: Path) -> RescoreResult:
    """Re-execute le compliance check + recalcule le score, sans toucher
    au .torrent ni au state.

    Lance une exception si :
      - le package n'a pas de debug.json (jamais prepare)
      - debug.json ne contient pas mediainfo_data ou release_name (corrompu)

    Sinon, mutate debug.json en place et retourne un RescoreResult.
    """
    from .compliance import Severity, check_compliance
    from .confidence import compute_confidence_score, invalidate_score_cache

    debug_path = package_dir / "_debug" / "debug.json"
    if not debug_path.is_file():
        raise FileNotFoundError(
            f"Aucun _debug/debug.json dans {package_dir.name}. "
            "Le package n'a pas ete prepare avec la version actuelle "
            "du pipeline (ou debug.json a ete supprime manuellement)."
        )

    try:
        debug_data: dict = json.loads(debug_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise ValueError(f"debug.json corrompu : {e}") from e

    mediainfo_data = debug_data.get("mediainfo_data")
    release_name = (debug_data.get("release_name") or "").strip()
    if not mediainfo_data or not release_name:
        raise ValueError(
            "debug.json est present mais incomplet : il manque mediainfo_data "
            "ou release_name. Ce package devrait etre re-prepare proprement "
            "(via 'Re-preparer avec ces options')."
        )

    # 1. Capture l'ancien score (utilise debug.json AVANT mutation)
    old_score_obj = compute_confidence_score(package_dir)
    old_issues = list(debug_data.get("compliance_issues") or [])

    # 2. Re-run check_compliance. On passe media_info=None et torrent_target=None
    # car ces deux args ne sont pas serialisables dans debug.json :
    # - media_info.all_videos / .torrent_target : utilises pour les checks
    #   season_complete + multi_team_in_pack + separate_subs. Pour un film
    #   single-file (cas usuel), ces checks sont no-ops.
    # - Pour les seasons multi-fichiers, on perd potentiellement le check
    #   season_complete, mais ce check passe ou non independamment des
    #   regles de scoring : c'etait pareil au moment du prepare initial.
    # banned_teams : on lit la config actuelle (peut avoir change).
    banned_teams: list[str] = []
    try:
        from .. import config as _cfg
        banned_teams = _cfg.banned_teams_list()
    except Exception:
        pass  # config absente / mal-formee : on continue sans

    new_issues_objs = check_compliance(
        release_name,
        mediainfo_data,
        media_info=None,
        torrent_target=None,
        banned_teams=banned_teams,
    )
    new_issues = [str(i) for i in new_issues_objs]
    blocking_msgs = [
        i.message for i in new_issues_objs if i.severity == Severity.BLOCKING
    ]

    # 3. Persiste les changements dans debug.json.
    debug_data["compliance_issues"] = new_issues
    if blocking_msgs:
        debug_data["blocking_compliance_messages"] = blocking_msgs
    else:
        # Plus aucun BLOCKING -> on retire la cle (sinon affichage incoherent).
        debug_data.pop("blocking_compliance_messages", None)

    debug_path.write_text(
        json.dumps(debug_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # 4. Invalide le cache de scoring (le mtime aurait suffi, mais on force
    # pour eviter toute race avec un poll de queue en cours).
    invalidate_score_cache(package_dir)

    # 5. Recalcule le score frais
    new_score_obj = compute_confidence_score(package_dir)

    old_set = set(old_issues)
    new_set = set(new_issues)
    removed = [i for i in old_issues if i not in new_set]
    added = [i for i in new_issues if i not in old_set]

    return RescoreResult(
        old_score=int(old_score_obj.score),
        new_score=int(new_score_obj.score),
        old_bucket=str(old_score_obj.bucket),
        new_bucket=str(new_score_obj.bucket),
        old_issues=old_issues,
        new_issues=new_issues,
        removed_issues=removed,
        added_issues=added,
    )
