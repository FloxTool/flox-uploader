"""GameConfidenceStrategy : score pour les packages Jeu vidéo.

Sprint C.5 v0.5.0 — STUB minimaliste. Sprint E remplacera par une vraie
logique : pénalisation titre absent (-20), plateforme manquante (-15), IGDB
ID absent (-10), version manquante (-5), fallback Steam Store (-3).
"""
from __future__ import annotations

from pathlib import Path


class GameConfidenceStrategy:
    name: str = "game"

    def compute(self, package_dir: Path):
        from .video import VideoConfidenceStrategy
        return VideoConfidenceStrategy().compute(package_dir)
