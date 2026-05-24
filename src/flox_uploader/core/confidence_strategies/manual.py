"""ManualConfidenceStrategy : score pour Logiciel / Formation (profil manuel).

Sprint C.5 v0.5.0 — STUB minimaliste. Sprint H remplacera par une vraie
logique : pénalisation champs obligatoires manquants (nom, éditeur, version),
URL site officiel absente (-5), pas d'auto-enrich GitHub/YouTube (-3).
"""
from __future__ import annotations

from pathlib import Path


class ManualConfidenceStrategy:
    name: str = "manual"

    def compute(self, package_dir: Path):
        from .video import VideoConfidenceStrategy
        return VideoConfidenceStrategy().compute(package_dir)
