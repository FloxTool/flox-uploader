"""Interface commune à tous les trackers.

Pour ajouter un nouveau tracker, créer un sous-dossier `trackers/<nom>/` qui
expose une classe héritant de `Tracker` (voir `trackers/gemini/tracker.py`
comme référence) et l'enregistrer dans le registry plus bas.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Tracker:
    """Configuration et règles d'un tracker.

    Chaque tracker fournit :
    - un identifiant (`key`) utilisé en CLI / configuration
    - un nom affichable (`display_name`)
    - une URL d'announce (lue depuis l'environnement)
    - un set de règles de normalisation du release name (`rules`)
    - le nom à inscrire dans le champ `source` du fichier .torrent (`torrent_source`)
    - la team par défaut quand le nom source n'en contient pas (`default_team`)

    Le template BBCode (`template.bbcode`) vit à côté de `rules.json` dans le
    dossier du tracker. Il est chargé à la volée par le renderer.
    """

    key: str
    display_name: str
    announce_url: str
    rules: dict
    torrent_source: str
    default_team: str = "NoTAG"
    private: bool = True
    require_precise_multi_language: bool = field(init=False)

    def __post_init__(self):
        self.require_precise_multi_language = bool(
            self.rules.get("require_precise_multi_language", True)
        )


def load_tracker_rules(tracker_dir: Path) -> dict:
    """Charge `rules.json` depuis un dossier de tracker."""
    rules_file = tracker_dir / "rules.json"
    if not rules_file.exists():
        raise FileNotFoundError(f"Fichier de règles introuvable : {rules_file}")
    with rules_file.open("r", encoding="utf-8") as f:
        return json.load(f)
