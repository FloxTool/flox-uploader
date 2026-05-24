"""BookConfidenceStrategy : score pour les packages Livre / BD / Manga.

Sprint C.5 v0.5.0 — STUB minimaliste. Pour l'instant, retourne le score video
(= compute_confidence_score) pour ne pas casser le rendu de la queue. Sprint D
remplacera par une vraie logique : pénalisation auteur absent (-20), ISBN
manquant (-15), format ebook inconnu (-10), NFO absent (-10), description
vide (-5), fallback BnF/Google/OpenLibrary (-3 par signal).
"""
from __future__ import annotations

from pathlib import Path


class BookConfidenceStrategy:
    name: str = "book"

    def compute(self, package_dir: Path):
        # Stub : delegue a la strategie video en attendant Sprint D.
        from .video import VideoConfidenceStrategy
        return VideoConfidenceStrategy().compute(package_dir)
