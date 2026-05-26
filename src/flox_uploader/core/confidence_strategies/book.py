"""BookConfidenceStrategy : score pour les packages Livre / BD / Manga.

Sprint D.5 v0.5.0 — vraie implementation avec penalites specifiques livres :
- auteur absent          : -20 (= naming partiel, fiche tracker incomplete)
- ISBN absent            : -15 (= pas de lookup fiable possible)
- description vide       : -5 (= fiche tracker pauvre)
- pas de couverture      : -3
- aucun provider en ligne consulte (sources = ['local_epub'] seul) : -3
- package en FAILED      : -100 (bloque l'upload)
- compliance bloquante   : -25 (format invalide ou archive interdite)

Sprint D.43 v0.5.0 (feedback Louis) — penalites "match faible" :
- title local suspect (< 4 chars / juste une annee / juste 'C\\d+')   : -15
- title local tres different du title canonique trouve (similarity<0.5) : -10
- volume scene index != volume canonique trouve (mauvais tome)         : -15
- year scene != year canonique (mauvaise edition / annee)              : -3
- imgbb rate-limit (fiche incomplete, re-prepare suggere)              : -5

Buckets : reutilise les seuils communs THRESHOLD_PARFAIT/PERFECT/READY/GOOD/REVIEW
de confidence.py. La granularite reste identique pour ne pas perturber l'UI Queue.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def _normalize_title_for_compare(s: str) -> str:
    """Normalise un titre pour comparaison fuzzy : minuscule, sans
    ponctuation, sans tokens techniques (Tome.X, T01, ...), sans annee."""
    if not s:
        return ""
    out = s.lower().strip()
    # Apostrophes, ponctuation -> espace
    out = re.sub(r"[.,;:!?\(\)\[\]\{\}'’\"\-_]+", " ", out)
    # Strip Tome.X / Tx / Vol.X (token-bounded)
    out = re.sub(r"\bt(?:ome)?\.?\s*\d{1,3}\b", "", out)
    out = re.sub(r"\bvol\.?\s*\d{1,3}\b", "", out)
    # Strip annee 19xx/20xx
    out = re.sub(r"\b(?:19|20)\d{2}\b", "", out)
    # Compact whitespace
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _titles_similarity(a: str, b: str) -> float:
    """Retourne similarity ratio [0..1] entre 2 titres normalises.

    1.0 = identiques. < 0.5 = tres differents (probable mauvais match).
    """
    na = _normalize_title_for_compare(a)
    nb = _normalize_title_for_compare(b)
    if not na or not nb:
        return 1.0  # incomparable -> on penalise pas
    return SequenceMatcher(None, na, nb).ratio()


_SUSPICIOUS_TITLE_PATTERNS = [
    # Year seul (cas Space Brothers "2021")
    re.compile(r"^\s*(?:19|20)\d{2}\s*$"),
    # Chapter id seul (cas One Piece "C1180")
    re.compile(r"^\s*c\s*\d{2,4}\s*$", re.IGNORECASE),
    # ID numerique brut
    re.compile(r"^\s*\d{1,5}\s*$"),
]


def _is_suspicious_title(title: str, file_format: str = "") -> str:
    """Retourne un libelle si le title local est suspect, sinon "".

    Cas detectes :
    - Title vide ou < 4 chars (sauf format video qui ne nous concerne pas)
    - Title = juste une annee ('2021')
    - Title = pattern chapitre ('C1180')
    - Title = juste un nombre brut
    """
    t = (title or "").strip()
    if not t:
        return "Titre local absent"
    if len(t) < 4:
        return f"Titre local très court ({len(t)} chars : '{t}')"
    for pat in _SUSPICIOUS_TITLE_PATTERNS:
        if pat.match(t):
            return f"Titre local suspect : '{t}' ressemble à une année / ID / chapitre"
    return ""


class BookConfidenceStrategy:
    name: str = "book"

    def compute(self, package_dir: Path):
        """Calcule le score d'un package livre."""
        from ..confidence import (
            ConfidenceScore, THRESHOLD_PARFAIT, THRESHOLD_PERFECT,
            THRESHOLD_READY, THRESHOLD_GOOD, THRESHOLD_REVIEW,
        )
        from ..package_state import read_state, PackageState

        penalties: list[tuple[str, int]] = []

        # Lecture state
        state = read_state(package_dir)
        if state is None:
            return ConfidenceScore(
                score=0, bucket="blocked", bucket_emoji="✗",
                bucket_color="red",
                reasons=["State manquant"],
                penalties=[("State manquant", 100)],
            )

        # 1. State FAILED : court-circuit a 0
        if state.state == PackageState.FAILED:
            return ConfidenceScore(
                score=0, bucket="blocked", bucket_emoji="✗",
                bucket_color="red",
                reasons=["Package en echec (compliance ou erreur pipeline)"],
                penalties=[("Package FAILED", 100)],
            )

        # 2. Lecture debug.json pour les metadonnees livre
        debug_path = package_dir / "_debug" / "debug.json"
        book_meta: dict = {}
        scene_parsed: dict = {}
        if debug_path.is_file():
            try:
                debug_data = json.loads(debug_path.read_text(encoding="utf-8"))
                book_meta = debug_data.get("book_metadata") or {}
                scene_parsed = debug_data.get("scene_parsed") or {}
                compliance_issues = debug_data.get("compliance_issues") or []
            except (OSError, json.JSONDecodeError):
                compliance_issues = []
        else:
            compliance_issues = []

        # 3. Compliance bloquante depuis debug.compliance_issues
        blocking_count = sum(
            1 for s in compliance_issues if "[BLOCKED]" in s
        )
        if blocking_count > 0:
            penalties.append(
                (f"Compliance ebook bloquante ({blocking_count})", 25),
            )

        # 4. Auteur absent (champ obligatoire format Gemini)
        if not (book_meta.get("authors") or []):
            penalties.append((
                "Auteur manquant — format Gemini incomplet (Auteur.Titre.Date.Langue.Format)",
                20,
            ))

        # 4bis. Titre absent (champ obligatoire format Gemini)
        if not (book_meta.get("title") or "").strip():
            penalties.append((
                "Titre manquant — format Gemini incomplet",
                15,
            ))

        # 4ter. Date absente (champ obligatoire format Gemini)
        if not (book_meta.get("publication_year") or 0):
            penalties.append((
                "Date de publication manquante — format Gemini incomplet",
                5,
            ))

        # 4quater. Langue absente (champ obligatoire format Gemini)
        if not (book_meta.get("language") or "").strip():
            penalties.append((
                "Langue manquante — format Gemini incomplet",
                5,
            ))

        # 4quinquies. Format absent (champ obligatoire format Gemini)
        if not (book_meta.get("file_format") or "").strip():
            penalties.append((
                "Format fichier manquant — format Gemini incomplet",
                3,
            ))

        # 5. ISBN absent (13 ou 10) — important pour le lookup
        if not book_meta.get("isbn_13") and not book_meta.get("isbn_10"):
            penalties.append((
                "ISBN manquant — pas de lookup fiable BnF/Google/OpenLib",
                15,
            ))

        # 6. Description vide
        if not (book_meta.get("description") or "").strip():
            penalties.append(("Résumé vide — fiche tracker pauvre", 5))

        # 7. Pas de couverture
        if not (book_meta.get("cover_url") or "").strip():
            penalties.append(("Couverture absente — fiche tracker sans image", 3))

        # 8. Aucun provider en ligne consulte
        sources = book_meta.get("sources") or []
        online_sources = [
            s for s in sources
            if s not in ("local_epub", "local_pdf", "local_cbz", "local_cbr")
        ]
        if not online_sources and book_meta:
            penalties.append((
                "Pas de lookup en ligne (BnF/Google Books/OpenLibrary)",
                3,
            ))

        # 9. Sprint D.37 : flag no_canonical_match -> grosse penalite.
        # Indique que ni BnF ni Google ni ISBN n'ont matche -> on ne peut
        # PAS garantir la fiche est correcte. Le release_name est construit
        # depuis la metadata locale (potentiellement pourrie).
        if book_meta.get("no_canonical_match"):
            penalties.append((
                "⚠️ Aucune correspondance fiable trouvée (BnF/Google Books/ISBN tous KO) — "
                "le release_name est basé sur la metadata locale uniquement, à valider manuellement",
                30,
            ))

        # ============================================================
        # Sprint D.43 v0.5.0 (feedback Louis) : penalites "match faible"
        # ============================================================
        # Le score doit refleter la DIFFICULTE du match. Si on a galere
        # pour trouver une correspondance (title local pourri, volume
        # mismatch, title meta tres different), c'est probablement pas
        # le bon livre -> score plus bas.
        #
        # On ne penalise PAS si no_canonical_match est deja set (deja
        # -30 au-dessus, eviter le double-comptage).
        # On ne penalise PAS non plus si scene_parsed est absent (packages
        # legacy ou tests unitaires sans pipeline complet).
        if not book_meta.get("no_canonical_match") and scene_parsed:

            # A. Title local suspect (cas Space Brothers T33 / One Piece C1180)
            scene_title = scene_parsed.get("title") or ""
            file_format = book_meta.get("file_format", "")
            suspect_msg = _is_suspicious_title(scene_title, file_format) if scene_title else ""
            if suspect_msg:
                penalties.append((
                    f"Match peu fiable : {suspect_msg} — la recherche s'est "
                    f"appuyée sur très peu d'information",
                    15,
                ))

            # B. Title final tres different du title scene (similarity < 0.5)
            # Cas typique : on cherche "Spartacus Blood and Sand 01" et on
            # tombe sur un livre McFarland random sur Spartacus general.
            # On exige aussi qu'on ait un match canonique (au moins 1 ID
            # externe), sinon le mismatch est sans interet.
            meta_title = book_meta.get("title") or ""
            has_external_match = bool(
                book_meta.get("google_books_id")
                or book_meta.get("bnf_ark")
                or book_meta.get("isbn_13")
            )
            if (scene_title and meta_title and not suspect_msg
                    and has_external_match):
                sim = _titles_similarity(scene_title, meta_title)
                if sim < 0.5:
                    penalties.append((
                        f"Titre canonique très différent du titre source "
                        f"(similarité {sim:.0%} : '{scene_title}' vs '{meta_title}') "
                        f"— probable mauvaise correspondance, à vérifier",
                        10,
                    ))

            # C. Volume mismatch (cas critique mangas : on demande T33, on
            # match une fiche sans T33 dans le titre).
            scene_vol = float(scene_parsed.get("series_index") or 0)
            meta_vol = float(book_meta.get("series_index") or 0)
            if scene_vol > 0 and meta_vol > 0 and abs(scene_vol - meta_vol) >= 0.5:
                penalties.append((
                    f"Tome demandé T{int(scene_vol)} ≠ tome canonique T{int(meta_vol)} "
                    f"— probable mauvais tome dans la correspondance",
                    15,
                ))
            elif (scene_vol > 0 and meta_vol == 0 and meta_title
                    and has_external_match):
                # On a un tome dans le filename mais aucun tome dans la fiche
                # canonique : on a probablement matche la SERIE generique au
                # lieu du tome specifique (cas Space Brothers T30 -> fiche
                # generique 'Space Brothers').
                # On verifie aussi que le title canonique ne contient pas
                # T<num> dans son texte (sinon false positive).
                if not re.search(rf"\bt\.?\s*0*{int(scene_vol)}\b",
                                 meta_title, re.IGNORECASE):
                    penalties.append((
                        f"Tome T{int(scene_vol)} demandé mais la fiche "
                        f"canonique est générique (série sans numéro) — "
                        f"probable match imprécis",
                        8,
                    ))

            # D. Year mismatch (signal faible : la fiche canonique peut etre
            # une reedition recente d'un livre ancien -> tolerance > 5 ans).
            scene_year = int(scene_parsed.get("year") or 0)
            meta_year = int(book_meta.get("publication_year") or 0)
            if (scene_year > 0 and meta_year > 0
                    and abs(scene_year - meta_year) > 5
                    and has_external_match):
                penalties.append((
                    f"Année canonique {meta_year} ≠ année source {scene_year} "
                    f"(écart > 5 ans — peut-être une autre édition)",
                    3,
                ))

        # E. imgbb rate-limit : fiche incomplete, re-prepare suggere
        if book_meta.get("imgbb_rate_limited"):
            failed = book_meta.get("imgbb_failed_images") or []
            n = len(failed) or 1
            penalties.append((
                f"imgbb rate-limit : {n} image{'s' if n > 1 else ''} "
                f"non uploadée{'s' if n > 1 else ''} — re-prépare dans ~1h",
                5,
            ))

        # Score final
        score = max(0, 100 - sum(p for _, p in penalties))

        # Bucket (reutilise les seuils video pour coherence UI)
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

        return ConfidenceScore(
            score=score,
            bucket=bucket,
            bucket_emoji=emoji,
            bucket_color=color,
            reasons=[label for label, _ in penalties],
            penalties=penalties,
        )
