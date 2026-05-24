"""Resolution de la categorie effective d'un package.

Sprint C.2 v0.5.0 — pour afficher le bon badge couleur dans la Queue / Page
detail / History, on a besoin de connaitre la categorie *finale* qui sera
envoyee au tracker. Cette categorie peut venir de 3 sources :

1. **Override explicite** : l'user a coche manuellement une cat (modal Inbox
   Sprint C.1 sous-cat video forcee, ou page detail override). Persiste dans
   `state.manual_category_id` (> 0 si override actif).

2. **Auto-detection TMDB+keywords** : pour les video sans override, la cat
   precise est calculee dynamiquement par `category_id_for(media_type,
   tmdb_context, release_name)` qui lit debug.json.

3. **Fallback** : si rien n'est connu (pas de state, pas de debug), on
   retombe sur CATEGORY_MOVIE (= comportement historique v0.3.x).

Cette resolution est pure-lecture, sans side-effect.
"""
from __future__ import annotations

import json
from pathlib import Path

from .media_type import MediaType
from .package_state import read_state
from ..trackers.gemini.unit3d_mapping import (
    CATEGORY_MOVIE, category_id_for,
)


def resolve_effective_category(package_dir: Path) -> int:
    """Retourne le category_id Gemini *effectif* d'un package.

    Ordre de priorité (le premier qui matche gagne) :

    1. `state.manual_category_id > 0` : override explicite de l'user (modal
       Inbox sous-cat video forcée, ou page detail override). Sprint C.1bis
       fix : ce champ est aussi peuple par le hint user envoye dans la modal
       Inbox quand il est non-zero.

    2. Auto-detection TMDB+keywords via `category_id_for()` : on lit
       debug.json pour recuperer media_type + tmdb_context + release_name,
       puis on applique la logique de classification existante (cf. Lot N).

    3. Fallback CATEGORY_MOVIE (cat 1) : si pas de state, pas de debug,
       ou erreur lecture. C'est le comportement v0.3.x preserve.

    Args:
        package_dir : path du dossier package (sous data/upload_packages/<name>).

    Returns:
        category_id Gemini (int dans CATEGORY_OPTIONS). Garantit de retourner
        une valeur valide, jamais None.
    """
    # 1. Override explicite via state.manual_category_id
    state = read_state(package_dir)
    if state is not None and state.manual_category_id > 0:
        return int(state.manual_category_id)

    # 2. Auto-detection via debug.json + category_id_for
    debug_path = package_dir / "_debug" / "debug.json"
    if not debug_path.is_file():
        return CATEGORY_MOVIE

    try:
        raw = debug_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        # Debug corrompu ou inaccessible -> fallback safe
        return CATEGORY_MOVIE

    if not isinstance(data, dict):
        return CATEGORY_MOVIE

    # Extraction du media_type (MOVIE / TV_EPISODE / TV_SEASON / TV_INTEGRALE)
    media_type_str = (data.get("media_type") or "movie").strip().lower()
    try:
        media_type = MediaType(media_type_str)
    except ValueError:
        media_type = MediaType.MOVIE

    tmdb_context = data.get("tmdb_context") or {}
    if not isinstance(tmdb_context, dict):
        tmdb_context = {}

    # Release name : depuis le state si dispo, sinon depuis le dossier
    release_name = ""
    if state is not None:
        release_name = state.release_name or ""
    if not release_name:
        release_name = package_dir.name

    return category_id_for(
        media_type,
        tmdb_context=tmdb_context,
        release_name=release_name,
    )


def category_profile(category_id: int | None) -> str:
    """Retourne le nom du profil UI pour une category_id.

    Sprint C.4 v0.5.0 — utilise par les templates pour inclure le bon
    `_detail_<profile>.html` selon la categorie effective. Aligne avec
    `compliance._profile_for_category` pour eviter toute desynchronisation
    entre les profils naming, compliance et UI.

    Profils retournes :
    - 'video'  : Films / Series / Anime / Doc (cats 1, 2, 6, 7, 13, 14)
    - 'show'   : Emission TV (cat 15)
    - 'sport'  : Sports (cat 10)
    - 'book'   : Livres (cat 12)
    - 'game'   : Jeux (cat 3)
    - 'manual' : Logiciels (17), Formations (18)
    - 'video' par defaut si category_id inconnu ou None

    Note : on differencie ici 'show' et 'sport' de 'video' contrairement a
    compliance._profile_for_category qui les agglomere en 'video' pour eviter
    de casser la compat. C'est volontaire : Sprint F (Emission TV) et Sprint G
    (Sport) auront leurs propres templates UI specialises.
    """
    if category_id is None:
        return "video"
    from ..trackers.gemini.unit3d_mapping import (
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
        CATEGORY_SPORTS, CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
        CATEGORY_GAME, CATEGORY_BOOKS, CATEGORY_SOFTWARE, CATEGORY_TRAINING,
    )
    video_cats = {
        CATEGORY_MOVIE, CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_MOVIE_ANIME,
        CATEGORY_MOVIE_DOC, CATEGORY_TV_DOC,
    }
    if category_id in video_cats:
        return "video"
    if category_id == CATEGORY_TV_SHOW:
        return "show"
    if category_id == CATEGORY_SPORTS:
        return "sport"
    if category_id == CATEGORY_BOOKS:
        return "book"
    if category_id == CATEGORY_GAME:
        return "game"
    if category_id in (CATEGORY_SOFTWARE, CATEGORY_TRAINING):
        return "manual"
    return "video"  # fallback safe
