"""SportConfidenceStrategy : score pour les packages Sport.

Sprint C.5 v0.5.0 — STUB minimaliste. Sprint G remplacera par une vraie
logique : pénalisation ligue non identifiée (-15), TheSportsDB rate (-10),
date manquante (-5), logo statique absent (-3).
"""
from __future__ import annotations

from pathlib import Path


class SportConfidenceStrategy:
    name: str = "sport"

    def compute(self, package_dir: Path):
        from .video import VideoConfidenceStrategy
        return VideoConfidenceStrategy().compute(package_dir)
