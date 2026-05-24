"""Protocol commun et dispatcher pour les strategies de score de confiance.

Sprint C.5 v0.5.0 (PLAN-MULTICAT §5.4 Brique 3). Pose l'interface qui unifie
le calcul de score pour toutes les categories Gemini. Pour l'instant, seule
`VideoConfidenceStrategy` (wrap de l'existant) est implementee. Sprints D-H
ajouteront BookConfidenceStrategy, GameConfidenceStrategy, etc.

NOTE Sprint C.5 : ce module est cree mais **n'est pas encore appele par les
callers** (compute_confidence_score reste utilise direct partout). C'est de
l'infrastructure pure pour permettre aux Sprints D-H d'enrichir les profils
non-video sans toucher au caller. Comportement v0.4.x strictement preserve.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ConfidenceStrategy(Protocol):
    """Interface commune a toutes les strategies de score par profil.

    Chaque strategy expose :
    - `name` : libelle court pour les logs ('video', 'book', 'game', ...)
    - `compute(package_dir)` : retourne un `ConfidenceScore` (cf. confidence.py)
    """

    name: str

    def compute(self, package_dir: Path):
        """Calcule le score pour un package. Retourne un ConfidenceScore."""
        ...


def get_confidence_strategy(category_id: int | None) -> ConfidenceStrategy:
    """Retourne la `ConfidenceStrategy` adaptee a la categorie demandee.

    Sprint C.5 : pour toute categorie (video ou non), on retourne actuellement
    `VideoConfidenceStrategy` car les stubs non-video sont des wrappers identiques.
    Sprints D-H specialiseront en remplacant les stubs.

    Le dispatcher utilise `category_profile()` du category_resolver pour
    determiner le profil (donc reste aligne avec le naming et l'UI).

    Args:
        category_id : id Gemini de la categorie (cf. unit3d_mapping.CATEGORY_*).

    Returns:
        Instance de `ConfidenceStrategy`. Garantit de retourner une strategy
        utilisable (jamais None).
    """
    # Import tardif pour eviter le cycle (chaque strategy importe confidence
    # qui pourrait, plus tard, importer le dispatcher).
    from ..category_resolver import category_profile
    profile = category_profile(category_id)

    if profile == "book":
        from .book import BookConfidenceStrategy
        return BookConfidenceStrategy()
    if profile == "game":
        from .game import GameConfidenceStrategy
        return GameConfidenceStrategy()
    if profile == "show":
        from .show import ShowConfidenceStrategy
        return ShowConfidenceStrategy()
    if profile == "sport":
        from .sport import SportConfidenceStrategy
        return SportConfidenceStrategy()
    if profile == "manual":
        from .manual import ManualConfidenceStrategy
        return ManualConfidenceStrategy()

    # Defaut : video (cats 1, 2, 6, 7, 13, 14 + fallback inconnu)
    from .video import VideoConfidenceStrategy
    return VideoConfidenceStrategy()
