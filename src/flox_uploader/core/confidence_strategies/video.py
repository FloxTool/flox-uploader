"""VideoConfidenceStrategy : strategie de score pour les categories video.

Sprint C.5 v0.5.0. Wrap strictement `compute_confidence_score` de
confidence.py (= comportement v0.4.x preserve). Utilise pour Films, Series,
Anime, Docs, Sport, Emission TV (toutes les categories qui passent par le
pipeline video).
"""
from __future__ import annotations

from pathlib import Path


class VideoConfidenceStrategy:
    """Strategy de score pour les categories video (1, 2, 6, 7, 10, 13, 14, 15).

    Implementation = wrap de `compute_confidence_score`. Aucune duplication.
    """

    name: str = "video"

    def compute(self, package_dir: Path):
        """Delegue strictement a `confidence.compute_confidence_score`.

        Import tardif pour eviter le cycle (confidence importera plus tard ce
        Protocol pour valider via isinstance dans les tests).
        """
        from ..confidence import compute_confidence_score
        return compute_confidence_score(package_dir)
