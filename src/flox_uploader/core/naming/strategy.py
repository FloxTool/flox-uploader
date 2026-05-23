"""Protocol commun et dispatcher pour les strategies de naming par categorie.

Sprint B.2/B.3 v0.5.0 (PLAN-MULTICAT §5.5). Pose l'interface qui unifie le
traitement de toutes les categories Gemini. Pour l'instant, seule la
`VideoNamingStrategy` (= wrap de l'existant) est implementee — les autres
viendront aux Sprints D (Livres), E (Jeux), F (Emission TV), G (Sport), H
(Logiciels / Formations).

Architecture :
- `NamingStrategy` : Protocol qui definit ce que doit savoir faire toute
  strategy (build_release_name, compliance_profile, ...).
- `get_strategy(category_id)` : dispatcher qui retourne la bonne strategy.
- `VideoNamingStrategy` (dans video_strategy.py) : implementation video.

NOTE Sprint B.2/B.3 : ce module est cree mais **n'est pas encore appele par
le pipeline**. La PR B.4 fera le routing dans `pipeline.process_one`. Le
comportement reste donc strictement identique a Sprint B.1.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ...trackers.base import Tracker
    from ..debug import Debug


@runtime_checkable
class NamingStrategy(Protocol):
    """Interface commune a toutes les strategies de naming par categorie.

    `runtime_checkable` permet de faire `isinstance(obj, NamingStrategy)` pour
    valider qu'un objet implemente bien l'interface.

    Chaque strategy doit exposer :
    - `name` : libelle court ("video", "book", "game", ...) pour les logs.
    - `build_release_name(...)` : produit le nom de release final + ctx tracker.
    - `compliance_profile()` : retourne le nom du profil pour check_compliance
      (cf. compliance._profile_for_category). Permet d'aligner naming et
      compliance sur le meme profil.

    Les strategies non-video ajouteront leurs propres methodes specifiques
    (build_extra_payload pour les champs ebook/jeu, build_bbcode_context, etc.)
    sans casser cette interface de base.
    """

    name: str

    def build_release_name(
        self,
        video_path: Path,
        tracker: "Tracker",
        nfo_text: str,
        debug: "Debug",
        *,
        force_fr: str | None = None,
        tmdb_resolver: Any | None = None,
        media_info: Any | None = None,
        mediainfo_data: dict | None = None,
    ) -> tuple[str, dict | None]:
        """Construit le nom de release et retourne (release_name, tmdb_context).

        Signature identique a `release_name.build_release_name` pour permettre
        une substitution sans refactor du caller.
        """
        ...

    def compliance_profile(self) -> str:
        """Retourne le nom du profil compliance ('video', 'book', 'game', 'manual').

        Doit etre aligne avec `compliance._profile_for_category` pour que le
        meme category_id donne le meme profil aux deux modules.
        """
        ...


def get_strategy(category_id: int | None) -> NamingStrategy:
    """Retourne la `NamingStrategy` adaptee a la categorie demandee.

    Sprint B.2/B.3 : seule `VideoNamingStrategy` est implementee. Pour
    n'importe quel category_id (y compris None / inconnu), on retourne cette
    strategy. C'est volontaire :

    - Pour les cats video (1, 2, 6, 7, 10, 13, 14, 15), c'est ce qu'on veut.
    - Pour les cats non-video (3, 12, 17, 18), le pipeline early-return AVANT
      naming (cf. PR-3 Brique 1), donc cette strategy ne sera jamais appelee
      sur du non-video. La Brique 1 die() avec message clair bien avant.

    Sprints D / E / H ajouteront BookNamingStrategy, GameNamingStrategy, etc.,
    et adapteront ce dispatcher pour les router correctement.

    Args:
        category_id : id Gemini de la categorie (cf. unit3d_mapping.CATEGORY_*).

    Returns:
        Instance de `NamingStrategy` (= VideoNamingStrategy aujourd'hui).
    """
    # Import tardif pour eviter cycle (video_strategy importe naming.strategy
    # via le Protocol, mais ce module ne doit pas importer video_strategy
    # au top-level sous peine de cycle si on ajoute d'autres strategies).
    from .video_strategy import VideoNamingStrategy
    return VideoNamingStrategy()
