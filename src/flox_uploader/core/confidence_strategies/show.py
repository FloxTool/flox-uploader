"""ShowConfidenceStrategy : score pour les packages Émission TV.

Sprint C.5 v0.5.0 — STUB minimaliste. Sprint F remplacera par une vraie
logique : pénalisation TVmaze rate (-15), présentateur manquant (-10),
chaîne TV inconnue (-10), screenshots ffmpeg absent (-5).
"""
from __future__ import annotations

from pathlib import Path


class ShowConfidenceStrategy:
    name: str = "show"

    def compute(self, package_dir: Path):
        from .video import VideoConfidenceStrategy
        return VideoConfidenceStrategy().compute(package_dir)
