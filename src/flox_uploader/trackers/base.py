"""Interface commune à tous les trackers.

Pour ajouter un nouveau tracker, créer un sous-dossier `trackers/<nom>/` qui
expose une classe héritant de `Tracker` (voir `trackers/gemini/tracker.py`
comme référence) et l'enregistrer dans le registry plus bas.

Sprint 4 PLAN-V1.md : ajout du Protocol `TrackerClient` qui définit
l'interface structurelle attendue d'un client API tracker. Anticipation
v0.5+ : quand on ajoutera un 2e tracker, sa classe client devra respecter
ce protocole (check_duplicate / upload_torrent / download_torrent_from_url).
`GeminiClient` existant respecte déjà ce protocole structurellement, sans
modification — `typing.Protocol` est du duck-typing renforcé par les hints.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


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


# ============================================================
# Sprint 4 PLAN-V1.md — Interface structurelle TrackerClient
# ============================================================
# `Protocol` typing : aucune classe n'a besoin d'hériter explicitement.
# Le typecheck (mypy/pyright) verifie que les methodes existent avec les bons
# noms et signatures haut-niveau. `runtime_checkable` permet aussi un
# isinstance() check si on veut valider au runtime.
#
# Quand on ajoutera un 2e tracker en v0.5+, on crera par exemple
# `trackers/<autre>/api.py:OtherTrackerClient` qui implemente ce protocole.
# Le code applicatif (jobs_runner, upload_orchestrator) parlera a cette
# interface au lieu de `GeminiClient` directement.
#
# Pour la v1 publique on n'a pas besoin d'activer cette indirection : l'app
# UI dit "Gemini" partout, et le code applicatif instancie GeminiClient
# directement. Le Protocol sert juste a DOCUMENTER l'interface attendue.

@runtime_checkable
class TrackerClient(Protocol):
    """Interface attendue d'un client tracker (API operations).

    Toute classe qui expose ces methodes avec ces signatures est consideree
    comme un TrackerClient (duck typing renforce par typing.Protocol).

    `GeminiClient` (dans `core/gemini_api.py`) respecte ce protocole sans
    modification. Pour les futurs trackers, suivre la meme signature.

    Note : les types de retour utilisent `Any` car chaque tracker peut
    avoir ses propres dataclasses (`DupCheckResult`, `UploadResult`...).
    L'application layer doit accepter cette flexibilite ou bien on
    introduira plus tard des types de retour uniformes via dataclasses
    abstraites.
    """

    def check_duplicate(self, **kwargs: Any) -> Any:
        """Verifie l'existence d'un torrent equivalent sur le tracker."""
        ...

    def upload_torrent(self, **kwargs: Any) -> Any:
        """Upload un torrent + ses metadonnees vers le tracker."""
        ...

    def download_torrent_from_url(self, url: str, dest_path: Path) -> Path:
        """Telecharge le .torrent depuis une URL fournie par le tracker.

        Utile post-upload : le tracker renvoie une URL pour recuperer le
        .torrent final (avec passkey injectee), qu'on remplace le local.
        """
        ...
