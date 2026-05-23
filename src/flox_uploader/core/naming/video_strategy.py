"""VideoNamingStrategy : strategie naming pour les categories video.

Sprint B.3 v0.5.0 (PLAN-MULTICAT §5.5). Cette strategy **WRAP** la fonction
historique `release_name.build_release_name` sans dupliquer son code. C'est
volontairement minimal : on garde toute la logique metier video dans
`release_name.py` (1331 lignes apres extraction B.1), on l'expose juste via
l'interface `NamingStrategy` du Sprint B.

Cette strategy est utilisee pour toutes les categories video Gemini :
1 (Films), 2 (Series), 6 (Series Anime), 7 (Films Anime), 10 (Sports),
13 (Films Doc), 14 (Series Doc), 15 (Emission TV).

Plus tard, les Sprints F (ShowNamingStrategy emission TV) et G
(SportNamingStrategy) pourront soit specialiser cette classe, soit avoir
leur propre implementation distincte selon les besoins.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...trackers.base import Tracker
    from ..debug import Debug


class VideoNamingStrategy:
    """Strategy naming pour les categories video (cat 1, 2, 6, 7, 10, 13, 14, 15).

    Implementation = wrap de `release_name.build_release_name`. Aucune
    duplication de code. Comportement strictement identique a l'appel direct
    de la fonction.
    """

    name: str = "video"

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
        """Delegue strictement a `release_name.build_release_name`.

        Import tardif pour eviter le cycle (release_name re-exporte les
        helpers depuis naming/_helpers.py, donc importer release_name
        au top-level de ce module créérait un graphe d'imports circulaire
        au chargement du package naming/).
        """
        from ..release_name import build_release_name as _impl
        return _impl(
            video_path, tracker, nfo_text, debug,
            force_fr=force_fr,
            tmdb_resolver=tmdb_resolver,
            media_info=media_info,
            mediainfo_data=mediainfo_data,
        )

    def compliance_profile(self) -> str:
        """Aligne avec `compliance._profile_for_category` qui retourne 'video'
        pour les cats 1, 2, 6, 7, 10, 13, 14, 15.
        """
        return "video"
