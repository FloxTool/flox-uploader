"""BookConfidenceStrategy : score pour les packages Livre / BD / Manga.

Sprint D.5 v0.5.0 — vraie implementation avec penalites specifiques livres :
- auteur absent          : -20 (= naming partiel, fiche tracker incomplete)
- ISBN absent            : -15 (= pas de lookup fiable possible)
- description vide       : -5 (= fiche tracker pauvre)
- pas de couverture      : -3
- aucun provider en ligne consulte (sources = ['local_epub'] seul) : -3
- package en FAILED      : -100 (bloque l'upload)
- compliance bloquante   : -25 (format invalide ou archive interdite)

Buckets : reutilise les seuils communs THRESHOLD_PARFAIT/PERFECT/READY/GOOD/REVIEW
de confidence.py. La granularite reste identique pour ne pas perturber l'UI Queue.
"""
from __future__ import annotations

import json
from pathlib import Path


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
        if debug_path.is_file():
            try:
                debug_data = json.loads(debug_path.read_text(encoding="utf-8"))
                book_meta = debug_data.get("book_metadata") or {}
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
