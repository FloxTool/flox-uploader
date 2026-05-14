"""Detection du type de media a partir d'un path d'entree.

Le pipeline doit savoir si on traite :
- un FILM (1 fichier video, pas de SxxEyy)
- un EPISODE de serie (1 fichier video avec SxxEyy)
- une SAISON complete (plusieurs fichiers SxxEyy avec le meme Sxx)
- une INTEGRALE (plusieurs Sxx differents)

On scanne le contenu sans rien modifier (charte Gemini : preservation
totale du torrent original pour cross-seed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts"}

# Patterns reconnus dans les noms d'episodes (par ordre de priorite)
# - Standard scene : S01E01, s01e01, S1E1
# - Alt : 1x01, 01x01 (DURCI Lot O.1 : evite les faux positifs)
# - Au plus simple : Episode.01 (rare)
#
# IMPORTANT (Lot O.1) — le pattern alt `1x01` est tres faux-positif sur les
# codecs (`x264`, `x265`, `x.265`) et les channel layouts (`5.1`). Il etait
# responsable du bug "Furiosa S01E265" : `5.1x265` matchait season=1
# episode=265 et le film etait classe en TV_EPISODE.
#
# Les deux durcissements :
#  1. `(?<!\d\.)` : rejet si le 1er chiffre est precede d'un autre chiffre
#     suivi d'un point (ex: `5.1x265` -> le `1` est precede de `5.`).
#  2. `(\d{1,2})` au lieu de `(\d{1,3})` : episode borne a 99 max pour le
#     pattern alt. C'est suffisant en pratique (`1x100+` etant rare et
#     toujours ambigu avec un codec/channel).
EPISODE_PATTERNS = [
    re.compile(r"\bS(\d{1,2})E(\d{1,3})\b", re.IGNORECASE),               # S01E01
    re.compile(r"(?<!\d\.)\b(\d{1,2})x(\d{1,2})\b(?!\d)"),                # 1x01 alt
    re.compile(r"\bSeason[._\s-]?(\d{1,2})[._\s-]?Episode[._\s-]?(\d{1,3})\b", re.IGNORECASE),
]

# Pattern saison entiere : S01, Season 1, Sxx.COMPLETE
SEASON_PATTERNS = [
    re.compile(r"\bS(\d{1,2})\b(?!\s*E\d)", re.IGNORECASE),  # S01 (sans E suiviant)
    re.compile(r"\bSeason[._\s-](\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\bSaison[._\s-](\d{1,2})\b", re.IGNORECASE),
]

# Mots qui suggerent une INTEGRALE (toutes saisons). Attention : "COMPLETE"
# n'est pas un marqueur d'integrale dans la convention scene FR (c'est juste
# "saison complete"). Seul iNTEGRALE / FULL.SERIES / ALL.SEASONS le sont.
INTEGRALE_KEYWORDS = re.compile(
    r"\b(iNTEGRALE|INTEGRALE|FULL[._\s-]?SERIES|ALL[._\s-]?SEASONS)\b",
    re.IGNORECASE,
)


class MediaType(str, Enum):
    MOVIE = "movie"
    TV_EPISODE = "tv_episode"
    TV_SEASON = "tv_season"
    TV_INTEGRALE = "tv_integrale"


@dataclass
class MediaInfo:
    """Resultat de la detection : type + fichier video de reference + metadata."""
    media_type: MediaType
    # Le fichier video qu'on utilise pour MediaInfo (1er episode pour saison/integrale)
    reference_video: Path
    # Le path qui sera mis dans le .torrent (fichier seul ou dossier entier)
    torrent_target: Path
    # Liste de tous les fichiers video detectes (utile pour saisons/integrales)
    all_videos: list[Path]
    # Numero de saison detecte (None si film)
    season: int | None = None
    # Numero d'episode detecte (None si film/saison/integrale)
    episode: int | None = None
    # Liste des saisons detectees (pour integrales : [1, 2, 3, ...])
    seasons_found: list[int] | None = None


# ============================================================
# HELPERS
# ============================================================

def _extract_season_episode(name: str) -> tuple[int | None, int | None]:
    """Extrait (saison, episode) depuis un nom de fichier."""
    for pattern in EPISODE_PATTERNS:
        m = pattern.search(name)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def _extract_season_only(name: str) -> int | None:
    """Extrait le numero de saison si pattern Sxx (sans episode)."""
    for pattern in SEASON_PATTERNS:
        m = pattern.search(name)
        if m:
            return int(m.group(1))
    return None


def _list_videos_recursive(path: Path) -> list[Path]:
    """Liste tous les fichiers video sous le path (recursivement, dossiers exclus)."""
    if path.is_file():
        return [path] if path.suffix.lower() in VIDEO_EXTS else []
    videos: list[Path] = []
    for p in sorted(path.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            videos.append(p)
    return videos


# ============================================================
# DETECTION PRINCIPALE
# ============================================================

def detect_media_type(input_path: Path) -> MediaInfo:
    """Detecte automatiquement le type de media depuis le path donne.

    Regle :
    - Si fichier seul -> MOVIE ou TV_EPISODE selon nom
    - Si dossier avec 1 video -> idem
    - Si dossier avec plusieurs videos toutes meme Sxx -> TV_SEASON
    - Si dossier avec plusieurs Sxx differents -> TV_INTEGRALE
    - Si keyword "INTEGRALE" / "COMPLETE" detecte au niveau du dossier -> force INTEGRALE
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Path introuvable : {input_path}")

    videos = _list_videos_recursive(input_path)
    if not videos:
        raise ValueError(f"Aucun fichier video trouve dans : {input_path}")

    # Pour le .torrent : si input est un dossier, on torrente le dossier (pour cross-seed).
    # Si input est un fichier, on torrente le fichier.
    torrent_target = input_path

    # Cas 1 : 1 seul fichier video (input = fichier OU dossier avec 1 seul .mkv)
    if len(videos) == 1:
        single = videos[0]
        # On regarde aussi le nom du dossier parent : les releases scene
        # nomment souvent "Show.S01.MULTi.../Show.S01E01.mkv" et le pattern
        # SxxEyy peut etre dans le filename ou dans le folder.
        candidates_for_pattern = [single.name]
        if input_path.is_dir():
            candidates_for_pattern.append(input_path.name)
        elif input_path.is_file():
            candidates_for_pattern.append(input_path.parent.name)
        season = episode = None
        for cand in candidates_for_pattern:
            season, episode = _extract_season_episode(cand)
            if season is not None and episode is not None:
                break
        if season is not None and episode is not None:
            return MediaInfo(
                media_type=MediaType.TV_EPISODE,
                reference_video=single,
                torrent_target=torrent_target,
                all_videos=videos,
                season=season,
                episode=episode,
            )
        # Pas de SxxEyy -> on cherche un pattern saison "S01" / "Saison 01" /
        # "Season 01" SANS episode (cas frequent : pack saison release scene
        # avec 1 seul fichier joint, ou nom de dossier qui marque la saison).
        # Sans ce fallback, "Dune.Prophecy.S01.MULTi.x265.mkv" (1 fichier
        # standalone) etait classifie en MOVIE -> pipeline plante en
        # exigeant une annee.
        season_only = None
        for cand in candidates_for_pattern:
            season_only = _extract_season_only(cand)
            if season_only is not None:
                break
        if season_only is not None:
            return MediaInfo(
                media_type=MediaType.TV_SEASON,
                reference_video=single,
                torrent_target=torrent_target,
                all_videos=videos,
                season=season_only,
            )
        return MediaInfo(
            media_type=MediaType.MOVIE,
            reference_video=single,
            torrent_target=torrent_target,
            all_videos=videos,
        )

    # Cas 2 : plusieurs videos -> serie (saison ou integrale)
    seasons: set[int] = set()
    episodes_per_season: dict[int, list[int]] = {}
    for v in videos:
        s, e = _extract_season_episode(v.name)
        if s is not None:
            seasons.add(s)
            if e is not None:
                episodes_per_season.setdefault(s, []).append(e)

    # Detection forcee par keyword au niveau du dossier
    folder_name = input_path.name if input_path.is_dir() else input_path.parent.name
    forced_integrale = bool(INTEGRALE_KEYWORDS.search(folder_name))

    if forced_integrale or len(seasons) > 1:
        return MediaInfo(
            media_type=MediaType.TV_INTEGRALE,
            reference_video=videos[0],
            torrent_target=torrent_target,
            all_videos=videos,
            seasons_found=sorted(seasons) if seasons else None,
        )

    if len(seasons) == 1:
        return MediaInfo(
            media_type=MediaType.TV_SEASON,
            reference_video=videos[0],
            torrent_target=torrent_target,
            all_videos=videos,
            season=next(iter(seasons)),
        )

    # Plusieurs videos sans pattern de saison reconnu : on suppose "release multi-fichiers"
    # type discographie ou pack. On le traite comme un MOVIE (le 1er fichier sert de reference).
    return MediaInfo(
        media_type=MediaType.MOVIE,
        reference_video=videos[0],
        torrent_target=torrent_target,
        all_videos=videos,
    )


def format_episode_tag(season: int, episode: int) -> str:
    """Formate (1, 1) -> 'S01E01' (charte Gemini)."""
    return f"S{season:02d}E{episode:02d}"


def format_season_tag(season: int) -> str:
    """Formate 1 -> 'S01' (charte Gemini)."""
    return f"S{season:02d}"
