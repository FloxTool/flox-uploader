"""Registry des trackers supportés.

L'ajout d'un nouveau tracker = importer son loader ici et l'ajouter au dict.
"""
from __future__ import annotations

from .base import Tracker
from .gemini import load_gemini_tracker

# Registry: clé CLI -> fonction qui retourne une instance Tracker prête à l'emploi.
# La fonction prend l'announce URL en argument (lue depuis l'env) et charge
# rules.json + system_prompt.txt depuis le sous-dossier du tracker.
TRACKER_LOADERS = {
    "gemini": load_gemini_tracker,
}


def get_tracker(key: str, announce_url: str) -> Tracker:
    """Retourne une instance Tracker configurée. Lève KeyError si inconnu."""
    if key not in TRACKER_LOADERS:
        available = ", ".join(sorted(TRACKER_LOADERS))
        raise KeyError(
            f"Tracker '{key}' inconnu. Disponibles : {available}"
        )
    return TRACKER_LOADERS[key](announce_url)


def list_trackers() -> list[str]:
    return sorted(TRACKER_LOADERS.keys())
