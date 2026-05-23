"""Devine la categorie Gemini d'un fichier d'entree TRES TOT dans le pipeline.

Sprint A v0.5.0 (PLAN-MULTICAT §5.1 Etape 0). Cette fonction est appelee
au tout debut de `pipeline.process_one`, AVANT `detect_media_type` (qui
suppose une video) et AVANT `parse_mediainfo_json` (qui plante sur non-video).

Le resultat est stocke dans `debug["category_id_early"]` comme simple signal.
**Aucun comportement du pipeline n'est modifie en PR-2** : c'est la
PR-3 qui consommera ce signal pour decider de skip MediaInfo et le naming
sur les fichiers non-video.

Principe de la dégradation gracieuse :
- Priorite 1 : si l'utilisateur a explicitement choisi une categorie (depuis
  l'Inbox modal — futur Sprint C), on respecte son choix sans deviner.
- Priorite 2 : on regarde l'extension du fichier (ou des fichiers du dossier
  si on a un repertoire) pour mapper vers une categorie raisonnable.
- Priorite 3 (fallback) : si rien ne matche (cas exotique ou erreur), on
  retourne CATEGORY_MOVIE (= comportement v0.3.x : "tout est suppose video").
  Cela garantit la non-regression : si on n'a aucune info, on agit comme avant.
"""
from __future__ import annotations

from pathlib import Path

from ..trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_SOFTWARE,
)


# Mapping extension fichier -> category_id Gemini.
#
# Choix de design : on mappe **les extensions sans ambiguite**. Si un format
# peut etre soit video soit autre (cas .iso : peut etre une iso de jeu OU
# une iso BluRay video), on PRIVILEGIE la categorie video (CATEGORY_MOVIE)
# pour rester retro-compatible. Le pipeline detectera plus tard via MediaInfo
# si le .iso contient en fait des pistes video, et l'utilisateur peut toujours
# override la categorie depuis la page detail (Sprint C).
#
# Source des extensions : usages courants + PLAN-MULTICAT §6.2 (Détection
# automatique + suggestion catégorie sur Inbox).
_EXTENSION_TO_CATEGORY: dict[str, int] = {
    # === Livres / Ebooks (cat 12) ===
    ".epub": CATEGORY_BOOKS,
    ".pdf": CATEGORY_BOOKS,
    ".mobi": CATEGORY_BOOKS,
    ".azw3": CATEGORY_BOOKS,
    ".azw": CATEGORY_BOOKS,
    ".djvu": CATEGORY_BOOKS,
    ".cbr": CATEGORY_BOOKS,   # BD / Comics / Manga
    ".cbz": CATEGORY_BOOKS,
    ".m4b": CATEGORY_BOOKS,   # Livre audio
    # Note : on ne mappe pas `.mp3` ici car il peut être une musique normale
    # ou un livre audio — trop ambigu, l'user devra choisir explicitement.

    # === Logiciels (cat 17) ===
    ".exe": CATEGORY_SOFTWARE,
    ".msi": CATEGORY_SOFTWARE,
    ".dmg": CATEGORY_SOFTWARE,    # macOS installer
    ".pkg": CATEGORY_SOFTWARE,    # macOS package
    ".deb": CATEGORY_SOFTWARE,    # Debian package
    ".rpm": CATEGORY_SOFTWARE,    # RedHat package
    ".appimage": CATEGORY_SOFTWARE,

    # === Vidéo (cat 1 par défaut — sera affinée par TMDB en cat 2/6/7/13/14/15) ===
    ".mkv": CATEGORY_MOVIE,
    ".mp4": CATEGORY_MOVIE,
    ".avi": CATEGORY_MOVIE,
    ".ts": CATEGORY_MOVIE,
    ".m2ts": CATEGORY_MOVIE,
    ".mov": CATEGORY_MOVIE,
    ".wmv": CATEGORY_MOVIE,
    ".flv": CATEGORY_MOVIE,
    # .iso : ambigu (BluRay vs jeu). Defaut video — l'user peut override.
    ".iso": CATEGORY_MOVIE,

    # Note : les formations (cat 18) n'ont pas d'extension dédiée — c'est
    # typiquement un .mp4 + ressources, ou une playlist YouTube. Pas
    # d'auto-detect possible : l'user devra cocher manuellement en Sprint C.
}


# Extensions "satellites" qui ne definissent PAS la nature du contenu
# principal d'un dossier. Typiquement : couvertures, NFOs, sous-titres,
# checksums, metadonnees Calibre (.opf), parite, etc. On les ignore quand
# on scanne un dossier pour deviner la categorie — sinon un "Cover.jpg"
# (alphabetiquement avant le vrai contenu) ferait deviner faux.
#
# Cas reel rapporte par Louis (Sprint A test PR-3) :
#   "X:\torrents\completed\Decoupe en tranches (10354)\" contenait
#   cover.jpg + le .pdf. L'algo prenait .jpg en premier (ordre alpha),
#   fallback movie, puis plantait avec un message generique.
_SATELLITE_EXTENSIONS: frozenset[str] = frozenset({
    # Images de couverture / posters
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff",
    # Documents d'accompagnement
    ".nfo", ".txt", ".md", ".rtf", ".html", ".htm",
    # Checksums et parite
    ".sfv", ".md5", ".sha", ".sha256", ".par2", ".par",
    # Metadonnees ebook (Calibre, etc.)
    ".opf", ".bib",
    # Sous-titres externes (la charte Gemini les rejette de toute facon
    # mais on les considere comme satellites pour la detection categorie)
    ".srt", ".sub", ".idx", ".vtt", ".ass", ".ssa", ".sup",
    # Divers
    ".log", ".cue", ".m3u", ".m3u8",
})


def _scan_dir_for_content_extension(folder: Path) -> str:
    """Scanne un dossier et retourne l'extension du fichier 'principal'.

    Strategie :
    1. Scanne recursivement le dossier (ordre alpha stable).
    2. Ignore les fichiers caches (.DS_Store, .gitkeep, etc.) et les
       fichiers d'extensions 'satellites' (cover.jpg, info.nfo, .opf
       Calibre, sous-titres .srt, etc.).
    3. Retourne la PREMIERE extension trouvee qui est dans notre mapping
       connu (`_EXTENSION_TO_CATEGORY`). Ca garantit que si le dossier
       contient un .pdf et 50 fichiers .jpg, on retourne `.pdf`.
    4. Si aucune extension connue n'est trouvee mais qu'il y a des
       fichiers non-satellites : retourne la premiere extension non-satellite
       (le caller fera fallback movie).
    5. Si tout est satellite, vide, ou erreur d'acces : retourne "".

    Ne plante jamais (try/except sur les erreurs de filesystem).
    """
    try:
        first_unknown_non_satellite = ""
        for p in sorted(folder.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            ext = p.suffix.lower()
            if not ext or ext in _SATELLITE_EXTENSIONS:
                continue
            if ext in _EXTENSION_TO_CATEGORY:
                # Extension connue : on retourne immediatement (priorite max).
                return ext
            # Extension non-satellite mais inconnue : on memorise la premiere
            # comme fallback si on ne trouve rien de connu plus tard.
            if not first_unknown_non_satellite:
                first_unknown_non_satellite = ext
        return first_unknown_non_satellite
    except (OSError, PermissionError):
        return ""


def _first_file_extension(input_path: Path) -> str:
    """Retourne l'extension (en minuscule, avec le point) du fichier d'interet.

    - Si `input_path` est un fichier : son extension.
    - Si `input_path` est un dossier : appelle `_scan_dir_for_content_extension`
      qui ignore les fichiers satellites (cover.jpg, .nfo, .opf, etc.) et
      privilegie les extensions connues du mapping `_EXTENSION_TO_CATEGORY`.

    Ne plante jamais : si le path n'existe pas ou est inaccessible, retourne "".
    """
    try:
        if input_path.is_file():
            return input_path.suffix.lower()
        if input_path.is_dir():
            return _scan_dir_for_content_extension(input_path)
        return ""
    except (OSError, PermissionError):
        return ""


def early_category_guess(
    input_path: Path,
    category_hint: int | None = None,
) -> int:
    """Devine le category_id Gemini d'un fichier d'entree, sans appel reseau.

    Cette fonction est appelée AVANT MediaInfo / TMDB / parsing video — elle
    se base uniquement sur le path d'entrée et un hint utilisateur optionnel.

    Args:
        input_path : path du fichier (ou dossier) d'entree.
        category_hint : si l'utilisateur a explicitement choisi une categorie
            depuis l'UI Inbox (futur Sprint C), passer son category_id ici. Il
            sera respecte sans qu'on essaie de deviner autre chose.

    Returns:
        Un category_id Gemini valide. Garantit de retourner CATEGORY_MOVIE
        comme fallback si aucun signal n'est exploitable — c'est le
        comportement retro-compatible v0.3.x.

    Exemples :
        >>> early_category_guess(Path("Movie.mkv"))
        1  # CATEGORY_MOVIE
        >>> early_category_guess(Path("Tolkien.epub"))
        12  # CATEGORY_BOOKS
        >>> early_category_guess(Path("Movie.mkv"), category_hint=12)
        12  # hint user prioritaire (l'user a peut-etre nomme son book .mkv)
    """
    # Priorite 1 : hint user respecte sans question.
    if category_hint is not None and category_hint > 0:
        return category_hint

    # Priorite 2 : extension fichier (ou premier fichier du dossier).
    ext = _first_file_extension(input_path)
    if ext and ext in _EXTENSION_TO_CATEGORY:
        return _EXTENSION_TO_CATEGORY[ext]

    # Priorite 3 : fallback retro-compatible = on suppose video.
    # IMPORTANT : ce defaut PRESERVE le comportement v0.3.x quand aucun hint
    # n'est passe et que l'extension est inconnue. Le pipeline va continuer
    # de tenter detect_media_type / MediaInfo et plantera comme avant si le
    # fichier n'est vraiment pas video. C'est intentionnel : pas de
    # changement de comportement silencieux en PR-2.
    return CATEGORY_MOVIE
