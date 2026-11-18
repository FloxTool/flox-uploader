"""FastAPI app : routes pour l'interface web."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config
from ..core.confidence import (
    ConfidenceScore, compute_confidence_score, shorten_warning_label,
)
from ..core.package_state import PackageState, read_state, transition


# ============================================================
# CHEMINS
# ============================================================

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Extensions video supportees pour le browser de fichiers (les "vrais"
# release candidates : un upload simple cible un de ces fichiers).
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".iso", ".mov", ".m4v", ".webm"}
# NOTES round 7 : extensions complementaires AFFICHEES dans l'inbox
# pour permettre les bundles non-emboites (film + nfo + poster + subs).
# Toutes les extensions ici sont selectionnables comme parties d'un
# bundle ; mais seules VIDEO_EXTS sont des releases standalone.
COMPANION_EXTS = {
    # NFO / docs
    ".nfo", ".txt", ".md",
    # Images (posters, screenshots)
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
    # Sous-titres externes
    ".srt", ".sub", ".idx", ".ass", ".ssa", ".vtt", ".usf",
    # Archives / autres
    ".zip", ".rar", ".7z",
    # Torrent / sample
    ".torrent",
}
# Ensemble total des extensions visibles dans l'inbox
INBOX_EXTS = VIDEO_EXTS | COMPANION_EXTS


def _safe_resolve_path(raw: str) -> Path:
    """Resout un path utilisateur en rejetant les patterns suspects.

    On garde le scope "n'importe ou sur le filesystem local" (intentionnel
    pour un outil local-only) mais on bloque :
    - les chaines vides ou whitespace-only (Path("") = cwd, surprise effect)
    - les null-bytes (technique d'evasion classique)
    - les patterns relatifs evidents qui ne devraient PAS arriver via la UI
      (`..` solitaire, `.`, etc.)

    Pour les paths absolus normaux, on resout simplement et on retourne.
    Leve HTTPException(400) si suspect.
    """
    if not raw or not raw.strip():
        raise HTTPException(400, "Path vide")
    if "\x00" in raw:
        raise HTTPException(400, "Null-byte interdit dans le path")
    cleaned = raw.strip()
    # On rejette les patterns relatifs degeneres
    if cleaned in (".", "..", "./", "../"):
        raise HTTPException(400, f"Path relatif refuse : {cleaned!r}")
    try:
        return Path(cleaned).resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(400, f"Path invalide : {e}")


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class FileEntry:
    """Une entree dans le browser de fichiers."""
    name: str
    path: str            # absolu
    is_dir: bool
    size_pretty: str     # vide si dossier
    is_video: bool       # True si extension video (release candidate)
    # Sprint D.32 v0.5.0 : 'book' ajoute pour visualiser livres/BD/manga
    # (epub/pdf/cbz/cbr/mobi/azw/djvu) avec une icone livre verte.
    kind: str = "other"  # 'dir' | 'video' | 'book' | 'audiobook' | 'image' | 'subtitle' | 'nfo' | 'archive' | 'torrent' | 'other'


@dataclass
class PackageEntry:
    """Resume d'un package pour la liste de la queue."""
    release_name: str
    package_dir: str
    package_name: str    # basename du dossier (utilise pour l'URL detail)
    state: str
    updated_at: str
    uploaded_torrent_id: int | None
    uploaded_torrent_url: str
    final_torrent_path: str
    last_error: str
    existing_torrent_id: int | None = None
    existing_torrent_url: str = ""
    dedup_confidence: str = ""
    # Score de confiance (Phase 3b.2)
    confidence_score: int = 0
    confidence_bucket: str = ""        # ready / review / blocked
    confidence_emoji: str = ""
    confidence_color: str = ""         # tailwind: green / amber / red / slate
    # R5 : sous-type du bucket blocked ("action_required" / "refused" / None)
    confidence_bucket_kind: str | None = None
    confidence_reasons: list[str] = field(default_factory=list)
    # Lot U.2 : penalties brutes (label, points) pour permettre a la queue
    # de coloriser chaque warning selon sa severite (rouge >=10pts, orange
    # 5-9pts, bleu 1-4pts) sans avoir a parser le label.
    confidence_penalties: list[tuple] = field(default_factory=list)
    # Lot U.3 : version courte de chaque label pour l'affichage compact
    # de la queue. Meme ordre que confidence_penalties. Tooltip = label long.
    confidence_short_labels: list[str] = field(default_factory=list)
    # Taille du contenu (depuis mediainfo_data.size_bytes du debug)
    size_bytes: int = 0
    size_pretty: str = ""
    # Sprint C.2 v0.5.0 : categorie effective du package (override sticky
    # state.manual_category_id si > 0, sinon auto-detection TMDB+keywords).
    # Permet a la Queue d'afficher un badge couleur sans recalcul cote JS.
    category_id: int = 1                  # CATEGORY_MOVIE par defaut
    category_label: str = "Film"          # libelle humain
    category_color: str = "primary"       # palette Tailwind


@dataclass
class PendingJobEntry:
    """Resume d'un job pending pour la queue."""
    id: int
    file_name: str
    file_path: str
    status: str
    force_fr: str
    error: str
    created_at: str
    # Lot post-NOTES round 5 fix B2 : le template lisait `j.is_paused` mais
    # PendingJobEntry ne copiait pas ce flag depuis PendingJob -> le bouton
    # pause ne switchait jamais en "resume" malgre la pause cote DB.
    is_paused: bool = False
    priority_order: int = 0


# ============================================================
# HELPERS
# ============================================================

def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} Ko"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    return f"{size_bytes / (1024 ** 3):.2f} Go"


_KIND_BY_EXT = {
    **{ext: "video"    for ext in VIDEO_EXTS},
    # Sprint D.32 v0.5.0 : livres / BD / manga (kind='book') avec icone verte
    # dans l'inbox pour visualiser d'un coup d'oeil.
    **{ext: "book"     for ext in {".epub", ".pdf", ".cbz", ".cbr", ".mobi",
                                    ".azw3", ".azw", ".djvu"}},
    # Audiobooks separes (m4b est livre audio, mp3 ambigu mais on l'inclut)
    **{ext: "audiobook" for ext in {".m4b"}},
    **{ext: "image"    for ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}},
    **{ext: "subtitle" for ext in {".srt", ".sub", ".idx", ".ass", ".ssa", ".vtt", ".usf"}},
    **{ext: "nfo"      for ext in {".nfo", ".txt", ".md"}},
    **{ext: "archive"  for ext in {".zip", ".rar", ".7z"}},
    ".torrent": "torrent",
}


def _list_directory(
    target: Path,
    show_all: bool = False,
    show_videos: bool = True,
    show_books: bool = True,
) -> list[FileEntry]:
    """Liste le contenu d'un dossier : sous-dossiers d'abord (alpha), puis
    fichiers d'interet (alpha).

    Filtre :
    - `show_all=False` (defaut) : dossiers + fichiers video (VIDEO_EXTS) uniquement.
      Les NFO / posters / sous-titres ne sont PAS visibles par defaut — l'inbox
      reste claire pour le workflow normal "je selectionne un film a uploader".
    - `show_all=True` : tout (videos + companions NFO/posters/subs + exotiques
      .iso/.exe/.bin). Utile pour les bundles non-emboites (film + poster + nfo
      regroupes en un seul torrent) et pour explorer un dossier inhabituel.

    NOTES Sprint 8 hotfix : la note Louis disait que les NFO/JPEG apparaissaient
    par defaut alors que la checkbox "Tous les fichiers" etait decochee. C'etait
    le comportement "round 7" qui exposait les companions sans toggle. On
    revient a un defaut plus strict (videos seulement) ; les companions
    redeviennent accessibles via la checkbox.
    """
    if not target.is_dir():
        raise HTTPException(404, f"Dossier introuvable : {target}")

    # Sprint 8 hotfix v4 : scandir() est ~10-100x plus rapide que iterdir() sur
    # Windows car il cache les infos is_dir() + stat() en mémoire à partir
    # d'UN SEUL syscall par entrée. Avant on faisait 3+ syscalls par fichier
    # (iterdir + is_dir + stat + resolve). Pour 714 fichiers, on passe de
    # ~2000 syscalls a ~1 (le scandir initial). Gain perceptible immediat.
    entries: list[FileEntry] = []
    target_str = str(target)
    try:
        with os.scandir(target) as it:
            raw_entries = list(it)
    except PermissionError:
        raise HTTPException(403, f"Acces refuse : {target}")

    # Tri : dossiers d'abord, alpha (insensitif a la casse).
    # is_dir() sur un DirEntry utilise le cache scandir → pas de syscall.
    raw_entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

    for child in raw_entries:
        # Dossiers caches : on ignore (.git, __pycache__, etc.)
        if child.name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        name = child.name
        # Extension : substr du nom, pas de syscall.
        if is_dir or "." not in name:
            ext = ""
        else:
            ext = "." + name.rsplit(".", 1)[-1].lower()
        is_video = (not is_dir) and (ext in VIDEO_EXTS)
        # Sprint D.32 v0.5.0 : les fichiers livre (epub/pdf/cbz/cbr/mobi/...)
        # sont AUSSI visibles par defaut. Avant ils ne l'etaient que via
        # 'Tous les fichiers'. Inutile maintenant que le pipeline livre est
        # mature.
        kind_for_filter = _KIND_BY_EXT.get(ext, "other") if not is_dir else "dir"
        is_book = kind_for_filter in {"book", "audiobook"}
        # Sprint D.38 v0.5.0 : filtres independants Films/Series et Livres.
        # show_videos=False -> cache les fichiers video
        # show_books=False -> cache les fichiers livre
        # Combinaison libre : si les 2 sont False, on n'affiche que les
        # dossiers (et 'tout' si show_all). Logique :
        # - dossier : toujours visible
        # - video : visible si show_videos OU show_all
        # - book : visible si show_books OU show_all
        # - autres (NFO, archives, ...) : visible si show_all
        if is_dir:
            pass  # toujours visible
        elif is_video and not show_videos and not show_all:
            continue
        elif is_book and not show_books and not show_all:
            continue
        elif not is_video and not is_book and not show_all:
            continue
        # Size : stat() sur DirEntry est cached → 0 syscall supplementaire.
        size = 0
        if not is_dir:
            try:
                size = child.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
        kind = "dir" if is_dir else _KIND_BY_EXT.get(ext, "other")
        # Path absolu : on joint juste target + name (target deja resolved).
        # Evite child.resolve() qui ferait un syscall (readlink, etc.).
        path_str = os.path.join(target_str, name)
        entries.append(FileEntry(
            name=name,
            path=path_str,
            is_dir=is_dir,
            size_pretty=_format_size(size) if not is_dir else "",
            is_video=is_video,
            kind=kind,
        ))
    return entries


def _list_packages() -> list[PackageEntry]:
    """Liste tous les packages dans data/upload_packages/."""
    pkgs_dir = config.packages_dir()
    out: list[PackageEntry] = []
    for d in sorted(pkgs_dir.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        state_data = read_state(d)
        if state_data is None:
            # Package sans state (ancien) : on l'affiche quand meme avec etat "?"
            out.append(PackageEntry(
                release_name=d.name,
                package_dir=str(d),
                package_name=d.name,
                state="(pas d'etat)",
                updated_at="",
                uploaded_torrent_id=None,
                uploaded_torrent_url="",
                final_torrent_path="",
                last_error="",
                existing_torrent_id=None,
                existing_torrent_url="",
                dedup_confidence="",
            ))
            continue
        # Sprint D.6 v0.5.0 : route le score via la bonne strategy selon la
        # categorie effective. Pour un livre -> BookConfidenceStrategy
        # (penalites auteur/ISBN/cover/etc.). Pour video -> VideoConfidenceStrategy
        # (= comportement historique compute_confidence_score). Evite que les
        # livres recoivent les penalites video bidon (TMDB manquant, IMDB absent).
        try:
            from ..core.category_resolver import resolve_effective_category
            from ..core.confidence_strategies.strategy import (
                get_confidence_strategy,
            )
            _eff_cat = resolve_effective_category(d)
            _strategy = get_confidence_strategy(_eff_cat)
            conf = _strategy.compute(d)
        except (OSError, ValueError, KeyError) as e:
            conf = ConfidenceScore(score=0, bucket="blocked", bucket_emoji="?", bucket_color="slate")
            print(f"[WARN] confidence strategy ({d.name}) : {e}")
        # Lecture du release_name.txt (contient le suffixe FR si active)
        rn_txt = _read_text_safe(d / "release_name.txt")
        rn_display = state_data.release_name or d.name
        if rn_txt:
            first_line = rn_txt.splitlines()[0].strip()
            if first_line:
                rn_display = first_line
        # _read_package_size lit + parse debug.json. Une seule lecture par
        # iteration (avant : 2 appels = 2 lectures pour rien).
        size = _read_package_size(d)
        # Sprint C.2 : categorie effective (override > auto > fallback).
        from ..core.category_resolver import resolve_effective_category
        from ..trackers.gemini.unit3d_mapping import (
            category_label as _cat_label,
            category_ui_metadata as _cat_meta,
        )
        try:
            cat_id = resolve_effective_category(d)
        except (OSError, ValueError) as e:
            print(f"[WARN] resolve_effective_category({d.name}) : {e}")
            cat_id = 1  # CATEGORY_MOVIE fallback
        cat_meta_dict = _cat_meta(cat_id) or {}
        out.append(PackageEntry(
            release_name=rn_display,
            package_dir=str(d),
            package_name=d.name,
            state=state_data.state.value,
            updated_at=state_data.updated_at,
            uploaded_torrent_id=state_data.uploaded_torrent_id,
            uploaded_torrent_url=state_data.uploaded_torrent_url,
            final_torrent_path=state_data.final_torrent_path,
            last_error=state_data.last_error,
            existing_torrent_id=state_data.existing_torrent_id,
            existing_torrent_url=state_data.existing_torrent_url or "",
            dedup_confidence=(state_data.dedup_confidence or ""),
            confidence_score=conf.score,
            confidence_bucket=conf.bucket,
            confidence_emoji=conf.bucket_emoji,
            confidence_color=conf.bucket_color,
            confidence_bucket_kind=conf.bucket_kind,
            confidence_reasons=conf.reasons,
            confidence_penalties=conf.penalties,
            confidence_short_labels=[
                shorten_warning_label(label) for label, _ in conf.penalties
            ],
            size_bytes=size,
            size_pretty=_format_size_pretty(size),
            category_id=cat_id,
            category_label=_cat_label(cat_id),
            category_color=cat_meta_dict.get("color", "primary"),
        ))
    # Trier par updated_at decroissant (plus recent en haut)
    out.sort(key=lambda p: p.updated_at, reverse=True)
    return out


def _resolve_package_dir(name: str) -> Path:
    """Resout un nom de package vers son dossier sur disque, en blindant
    contre le path traversal. Leve HTTPException(404) si introuvable.

    `name` est traite comme un nom de dossier seul (pas de slash, pas de ..).
    """
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(400, f"Nom de package invalide : {name}")
    pkgs_dir = config.packages_dir().resolve()
    target = (pkgs_dir / name).resolve()
    # Securite : on verifie que target est bien un enfant direct de pkgs_dir
    try:
        target.relative_to(pkgs_dir)
    except ValueError:
        raise HTTPException(400, "Path traversal detecte")
    if not target.is_dir():
        raise HTTPException(404, f"Package introuvable : {name}")
    return target


def _read_package_size(package_dir: Path) -> int:
    """Lit la taille du contenu depuis _debug/debug.json (mediainfo_data.size_bytes)."""
    import json as _json
    debug_file = package_dir / "_debug" / "debug.json"
    if not debug_file.is_file():
        return 0
    try:
        debug = _json.loads(debug_file.read_text(encoding="utf-8"))
    except Exception:
        return 0
    mi = debug.get("mediainfo_data") or {}
    if isinstance(mi, dict):
        try:
            v = int(mi.get("size_bytes") or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    try:
        return int(debug.get("torrent_size") or 0)
    except (TypeError, ValueError):
        return 0


def _format_size_pretty(size_bytes: int) -> str:
    """Comme _format_size mais utilise par la page detail (Go par defaut)."""
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} Mo"
    return f"{size_bytes / (1024 ** 3):.2f} Go"


def _read_text_safe(p: Path, max_bytes: int = 200_000) -> str:
    """Lit un fichier texte avec garde-fou taille. Vide si absent ou erreur."""
    try:
        if not p.is_file():
            return ""
        if p.stat().st_size > max_bytes:
            return p.read_text(encoding="utf-8", errors="replace")[:max_bytes] + "\n... (tronque)\n"
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_package_detail(name: str) -> dict[str, Any]:
    """Charge toutes les infos affichees sur la page detail d'un package."""
    import json as _json
    from ..core import jobs_db

    target = _resolve_package_dir(name)
    state_data = read_state(target)
    # Sprint D.6 v0.5.0 : route le score via la bonne strategy selon la
    # categorie effective du package (livre vs video).
    try:
        from ..core.category_resolver import resolve_effective_category
        from ..core.confidence_strategies.strategy import (
            get_confidence_strategy,
        )
        _eff_cat = resolve_effective_category(target)
        _strategy = get_confidence_strategy(_eff_cat)
        conf = _strategy.compute(target)
    except (OSError, ValueError, KeyError) as e:
        conf = ConfidenceScore(score=0, bucket="blocked", bucket_emoji="?", bucket_color="slate")
        print(f"[WARN] confidence strategy detail ({target.name}) : {e}")

    # Debug.json pour TMDB / IMDB / media_type / size
    debug = {}
    debug_file = target / "_debug" / "debug.json"
    if debug_file.is_file():
        try:
            debug = _json.loads(debug_file.read_text(encoding="utf-8"))
        except Exception:
            debug = {}
    tmdb_ctx = debug.get("tmdb_context") or {}
    tmdb_id = tmdb_ctx.get("movie_id") or tmdb_ctx.get("tv_id") or tmdb_ctx.get("tmdb_id") or 0
    imdb_id = tmdb_ctx.get("imdb_id") or ""
    tmdb_title = (tmdb_ctx.get("title") or tmdb_ctx.get("name") or tmdb_ctx.get("original_title") or "").strip()
    tmdb_year = (tmdb_ctx.get("release_date") or tmdb_ctx.get("first_air_date") or "")[:4]
    poster_path = (tmdb_ctx.get("tmdb_poster_path") or "").strip()
    poster_url = f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else ""
    media_type = debug.get("media_type") or ""
    # Lot U.1 : champs supplementaires pour la carte Media redesignee.
    tmdb_overview = (tmdb_ctx.get("overview") or "").strip()
    tmdb_genres = tmdb_ctx.get("genres") or []
    tmdb_original_language = (tmdb_ctx.get("original_language") or "").strip().lower()
    tmdb_production_countries = tmdb_ctx.get("production_countries") or []
    tmdb_runtime = tmdb_ctx.get("runtime") or 0
    tmdb_rating = tmdb_ctx.get("tmdb_rating")
    imdb_rating = tmdb_ctx.get("imdb_rating") or ""
    tvdb_id_ctx = tmdb_ctx.get("tvdb_id") or 0
    # NOTES round 9 UX-3 : director (films) ou created_by (series).
    # TMDB met tout dans la clef "director" dans nos contextes (cf. tmdb.py
    # qui fait `creators[0]` pour les series).
    tmdb_director = (tmdb_ctx.get("director") or "").strip()
    # Synopsis tronque pour la carte (200 chars + ellipsis si plus long).
    # La version full est aussi exposee pour le "afficher tout" client-side.
    tmdb_overview_short = (
        tmdb_overview[:200] + "…" if len(tmdb_overview) > 200 else tmdb_overview
    )
    # Taille + resolution : priorite mediainfo_data
    mi = debug.get("mediainfo_data") or {}
    video_info = mi.get("video") if isinstance(mi, dict) else {}
    if not isinstance(video_info, dict):
        video_info = {}
    resolution_label = (video_info.get("resolution_label") or "").strip()
    video_codec = (video_info.get("codec") or "").strip()
    hdr_label = (video_info.get("hdr") or "").strip()
    size_bytes = 0
    if isinstance(mi, dict):
        try:
            size_bytes = int(mi.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
    if not size_bytes:
        size_bytes = debug.get("torrent_size") or 0
    # Sprint D.11 v0.5.0 : pour les packages livre, mediainfo_data n'est pas
    # rempli (pas de pipeline video). On lit la taille reelle depuis le
    # .torrent qui contient bien la taille du contenu (somme info.files).
    # Reuse le helper existant utilise par l'upload orchestrator.
    if not size_bytes:
        from ..core.upload_orchestrator import _extract_size_bytes
        try:
            # Cherche le .torrent dans le package dir
            torrent_files = list(target.glob("*.torrent"))
            if torrent_files:
                size_bytes = _extract_size_bytes(debug or {}, torrent_files[0])
        except Exception as e:
            print(f"[WARN] taille torrent fallback ({target.name}) : {e}")

    # release_name.txt + NFO
    release_name = (state_data.release_name if state_data else "") or target.name
    release_name_txt = _read_text_safe(target / "release_name.txt")
    # Le suffixe FR (option append_fr_title) est dans release_name.txt mais
    # pas dans state.release_name. On utilise la 1ere ligne du fichier comme
    # nom affiche dans le titre de la page.
    release_name_display = release_name
    if release_name_txt:
        first_line = release_name_txt.splitlines()[0].strip()
        if first_line:
            release_name_display = first_line
    presentation_text = _read_text_safe(target / "presentation.txt")
    # F4 : version editee par l'user (override de la regen) si presente
    presentation_user_text = _read_text_safe(target / "presentation_user.txt")
    presentation_is_overridden = bool(presentation_user_text)
    # Le texte affiche en priorite : la version user si editee, sinon la regen
    presentation_active_text = presentation_user_text or presentation_text
    # Deux NFO possibles :
    # - <release>.mediainfo.nfo : genere par nous (toujours present)
    # - <release>.nfo           : NFO scene d'origine (present si une release
    #   scene avec son .nfo a ete utilisee comme source)
    mediainfo_nfo_text = ""
    scene_nfo_text = ""
    for nfo_file in target.glob("*.nfo"):
        text = _read_text_safe(nfo_file)
        if nfo_file.name.endswith(".mediainfo.nfo"):
            mediainfo_nfo_text = text
        else:
            scene_nfo_text = text
    # Fallback : anciens packages ou le NFO MediaInfo n'avait pas le double
    # suffixe `.mediainfo.nfo`. Si on a UN seul .nfo et qu'il commence par
    # "General" (signature MediaInfo --Output=TEXT), on le re-classe comme
    # mediainfo plutot que NFO scene.
    # Le bug operator-precedence d'avant (parentheses manquantes autour du
    # OR) faisait que "Format" dans n'importe quel NFO scene declenchait le
    # reclassement, ecrasant un mediainfo.nfo deja present. Ici on borne
    # le fallback au cas explicite : pas de mediainfo ET un scene qui
    # ressemble a MediaInfo.
    if mediainfo_nfo_text == "" and scene_nfo_text and scene_nfo_text.lstrip().startswith("General"):
        mediainfo_nfo_text = scene_nfo_text
        scene_nfo_text = ""
    mediainfo_nfo_lines = mediainfo_nfo_text.count("\n")
    scene_nfo_lines = scene_nfo_text.count("\n")

    # Source job (file_path d'origine + force_fr utilise)
    source_job = jobs_db.find_job_for_package(str(target))
    source_file_path = source_job.file_path if source_job else ""
    source_force_fr = source_job.force_fr if source_job else ""
    # Sprint D.48 v0.5.0 : source forcee saisie precedemment (pour pre-fill UI).
    source_manual_source = source_job.manual_source if source_job else ""
    log_text = ""
    log_lines = 0
    if source_job and source_job.log_path:
        log_text = _read_text_safe(Path(source_job.log_path))
        log_lines = log_text.count("\n") if log_text else 0

    # Champs envoyes au tracker (F3 NOTES.md) : auto-detection + override.
    from ..trackers.gemini import unit3d_mapping
    from ..core.media_type import MediaType as _MT
    try:
        mt_enum = _MT(media_type) if media_type else _MT.MOVIE
    except ValueError:
        mt_enum = _MT.MOVIE
    # category_id_for prend les genres TMDB pour heuristique Animation/Documentaire,
    # et le release_name pour fallback keywords sport (Lot N).
    auto_category = unit3d_mapping.category_id_for(
        mt_enum, tmdb_context=tmdb_ctx, release_name=release_name,
    )
    # Source du guess (Lot N.3) : libelle humain affiche sous la dropdown.
    auto_category_source = unit3d_mapping.category_guess_source(
        mt_enum, tmdb_context=tmdb_ctx, release_name=release_name,
    )
    auto_type = unit3d_mapping.type_id_for(release_name)
    auto_resolution = unit3d_mapping.resolution_id_for(release_name)

    manual_category = state_data.manual_category_id if state_data else 0
    manual_type = state_data.manual_type_id if state_data else 0
    manual_resolution = state_data.manual_resolution_id if state_data else 0
    # Sprint D.43 v0.5.0 (feedback Louis) : on calcule eff_category AVANT
    # auto_type pour pouvoir router le auto-fill type sur la categorie
    # effective (manual_category gagne sur auto). Avant : si auto_category
    # etait 1 (Films par defaut) mais manual_category=12 (Livre), le type
    # restait sur BDRip (default video) au lieu de Livre. Maintenant on
    # utilise eff_category pour le routing du auto-fill type.
    eff_category = manual_category if manual_category > 0 else auto_category

    # Sprint D.40 v0.5.0 (feedback Louis) : auto-fill du type livre si la
    # categorie EFFECTIVE est Livre. Utilise book_type_id_for() qui combine
    # format + sous-type + ISBN + langue + genres.
    auto_type_source = ""
    if eff_category == unit3d_mapping.CATEGORY_BOOKS:
        bm = (debug or {}).get("book_metadata") or {}
        is_periodical = bool((debug or {}).get("is_periodical"))
        book_subtype = (state_data.manual_book_subtype if state_data else "") or ""
        b_type, b_src = unit3d_mapping.book_type_id_for(
            file_format=bm.get("file_format", ""),
            book_subtype=book_subtype,
            is_periodical=is_periodical,
            publication_name=target.name,
            genres=bm.get("genres", []),
            language=bm.get("language", ""),
            isbn_13=bm.get("isbn_13", ""),
        )
        if b_type > 0:
            auto_type = b_type
        else:
            # Sprint D.43 : si non-devinable, on retombe sur TYPE_BOOK_EBOOK (27)
            # plutot que sur BDRip (default video) qui n'est meme pas une option
            # valide pour la categorie Livre.
            auto_type = unit3d_mapping.TYPE_BOOK_EBOOK
        auto_type_source = b_src
    eff_type = manual_type if manual_type > 0 else auto_type
    eff_resolution = manual_resolution if manual_resolution > 0 else auto_resolution

    # Sprint D.46 v0.5.0 (feedback Louis) : on detecte si un log d'upload
    # passe existe pour ce package (meme apres redemarrage serveur).
    # Permet d'afficher la section "Log d'upload" peu importe le state
    # (avant : visible seulement si state in failed/aborted_duplicate, mais
    # un upload peut echouer apres etre passe en validated).
    import hashlib as _hashlib_dx
    _upload_log_digest = _hashlib_dx.md5(str(target).encode("utf-8")).hexdigest()[:12]
    _upload_log_path = (
        config.data_dir() / "jobs" / f"upload_{_upload_log_digest}.log"
    )
    _upload_log_exists = _upload_log_path.is_file()

    return {
        "package_dir": str(target),
        "package_name": target.name,
        "release_name": release_name_display,
        "release_name_technical": release_name,
        "state": state_data.state.value if state_data else "(pas d'etat)",
        "updated_at": state_data.updated_at if state_data else "",
        # Sprint D.46 : flag affichage du bloc "Log d'upload" sur la page.
        "upload_log_exists": _upload_log_exists,
        "uploaded_torrent_id": state_data.uploaded_torrent_id if state_data else None,
        "uploaded_torrent_url": state_data.uploaded_torrent_url if state_data else "",
        # Sprint 8 hotfix v12 : path du .torrent final (avec passkey) + le watch
        # folder (TORRENT_FINAL_DIR) si configure. Permet d'afficher sur la
        # page detail un bouton "Ouvrir le dossier du torrent uploade".
        "final_torrent_path": (state_data.final_torrent_path if state_data else "") or "",
        "torrent_final_dir": (os.environ.get("TORRENT_FINAL_DIR") or "").strip(),
        "existing_torrent_id": state_data.existing_torrent_id if state_data else None,
        "existing_torrent_url": state_data.existing_torrent_url if state_data else "",
        "dedup_confidence": (state_data.dedup_confidence if state_data else "") or "",
        "last_error": state_data.last_error if state_data else "",
        # Overrides
        "personal_release": state_data.personal_release if state_data else False,
        "anonymous": state_data.anonymous if state_data else False,
        "manual_tmdb_id": state_data.manual_tmdb_id if state_data else 0,
        # Lot Q : nouveaux overrides — IDs externes + champs upload
        "manual_imdb_id": state_data.manual_imdb_id if state_data else "",
        "manual_tvdb_id": state_data.manual_tvdb_id if state_data else 0,
        "manual_mal_id": state_data.manual_mal_id if state_data else 0,
        "manual_season_number": state_data.manual_season_number if state_data else 0,
        "manual_episode_number": state_data.manual_episode_number if state_data else 0,
        "manual_distributor_id": state_data.manual_distributor_id if state_data else 0,
        "manual_region_id": state_data.manual_region_id if state_data else 0,
        "manual_keywords": state_data.manual_keywords if state_data else "",
        # Sprint D.12 v0.5.0 - Options upload livre (cat 12).
        "manual_cover_url": (
            state_data.manual_cover_url if state_data else ""
        ),
        "manual_book_subtype": (
            state_data.manual_book_subtype if state_data else ""
        ),
        # Sprint D.40 v0.5.0 - Banner URL livre (complement de cover).
        "manual_banner_url": (
            state_data.manual_banner_url if state_data else ""
        ),
        # Auto-derived (depuis tmdb_context et media_info) — pour pre-remplir
        # les nouveaux champs avec les bonnes valeurs par defaut.
        "auto_imdb_id": (tmdb_ctx or {}).get("imdb_id", "") or "",
        "auto_tvdb_id": int((tmdb_ctx or {}).get("tvdb_id") or 0),
        "auto_season_number": (
            (debug or {}).get("season_number") or 0
        ),
        "auto_episode_number": (
            (debug or {}).get("episode_number") or 0
        ),
        "auto_keywords": ", ".join((tmdb_ctx or {}).get("keywords", []) or []),
        # Champs Unit3D (Gemini) — F3 : preview + override
        "gemini_category_id": eff_category,
        "gemini_category_label": unit3d_mapping.category_label(eff_category),
        "gemini_category_auto": auto_category,
        "gemini_category_auto_source": auto_category_source,
        "gemini_category_overridden": manual_category > 0,
        "gemini_type_id": eff_type,
        "gemini_type_label": unit3d_mapping.type_label(eff_type),
        "gemini_type_auto": auto_type,
        "gemini_type_overridden": manual_type > 0,
        # Sprint D.40 : source du auto-fill (affiche sous la dropdown Type
        # pour les livres). Vide pour les categories non-livre.
        "gemini_type_auto_source": auto_type_source,
        "gemini_resolution_id": eff_resolution,
        "gemini_resolution_label": unit3d_mapping.resolution_label(eff_resolution),
        "gemini_resolution_auto": auto_resolution,
        "gemini_resolution_overridden": manual_resolution > 0,
        "gemini_category_options": unit3d_mapping.CATEGORY_OPTIONS,
        # Sprint C.6 v0.5.0 : type_options conditionnel a la categorie
        # effective (eff_category). Pour un Jeu -> Windows/PS5/...
        # Pour un Livre -> EPUB/PDF/... Pour video/Formation -> BluRay/WEB-DL/...
        "gemini_type_options": unit3d_mapping.type_options_for_category(eff_category),
        "gemini_resolution_options": unit3d_mapping.RESOLUTION_OPTIONS,
        # Confidence
        "confidence_score": conf.score,
        "confidence_bucket": conf.bucket,
        "confidence_emoji": conf.bucket_emoji,
        "confidence_color": conf.bucket_color,
        "confidence_bucket_kind": conf.bucket_kind,
        "penalties": conf.penalties,
        # Signaux de fallback emis pendant la construction du release_name
        # (cf. naming_signals.py). Affichage : panneau dedie sur la page.
        "naming_signals": _build_naming_signals_panel(debug),
        # Metadata
        "tmdb_id": tmdb_id,
        "tmdb_title": tmdb_title,
        "tmdb_year": tmdb_year,
        "poster_url": poster_url,
        "imdb_id": imdb_id,
        "media_type": media_type,
        "size_pretty": _format_size_pretty(size_bytes) if size_bytes else "",
        "resolution_label": resolution_label,
        "video_codec": video_codec,
        "hdr_label": hdr_label,
        # Lot U.1 : metadata enrichies pour la carte Media
        "tmdb_overview": tmdb_overview,
        "tmdb_overview_short": tmdb_overview_short,
        "tmdb_genres": tmdb_genres,
        "tmdb_director": tmdb_director,
        "tmdb_original_language": tmdb_original_language,
        "tmdb_production_countries": tmdb_production_countries,
        "tmdb_runtime": tmdb_runtime,
        "tmdb_rating": tmdb_rating,
        "imdb_rating": imdb_rating,
        "tvdb_id_ctx": tvdb_id_ctx,
        # Lot U.1 : pistes audio + sous-titres pour la carte Technique
        "mediainfo_audio_tracks": mi.get("audio_tracks") if isinstance(mi, dict) else [],
        "mediainfo_subtitle_tracks": mi.get("subtitle_tracks") if isinstance(mi, dict) else [],
        "mediainfo_container": (mi.get("container") if isinstance(mi, dict) else "") or "",
        "mediainfo_duration_pretty": (mi.get("duration_pretty") if isinstance(mi, dict) else "") or "",
        "mediainfo_bit_depth": (video_info.get("bit_depth") or "") if isinstance(video_info, dict) else "",
        "mediainfo_framerate": (video_info.get("framerate") or "") if isinstance(video_info, dict) else "",
        # Source
        "source_file_path": source_file_path,
        "source_force_fr": source_force_fr,
        "source_manual_source": source_manual_source,
        # Contenu
        "release_name_txt": release_name_txt,
        # presentation_text = version active (user-edit si presente, sinon regen).
        # presentation_original = la version regenere par le pipeline (pour Reset).
        # presentation_is_overridden = True si l'user a edite (presentation_user.txt existe).
        "presentation_text": presentation_active_text,
        "presentation_original": presentation_text,
        "presentation_is_overridden": presentation_is_overridden,
        "mediainfo_nfo_text": mediainfo_nfo_text,
        "mediainfo_nfo_lines": mediainfo_nfo_lines,
        "scene_nfo_text": scene_nfo_text,
        "scene_nfo_lines": scene_nfo_lines,
        "log_text": log_text,
        "log_lines": log_lines,
        # Sprint D.5 v0.5.0 : metadonnees livre extraites par le pipeline.
        # Consommees par _detail_book.html (couverture, auteur, ISBN, etc.).
        # Pour les packages non-livres, ce dict est vide / non present.
        "book_metadata": (debug or {}).get("book_metadata") if isinstance(debug, dict) else None,
        # Sprint D.21 fix Bug-2 : on expose scene_parsed pour que le form
        # Re-preparer pre-remplisse manual_book_title / manual_author avec
        # les valeurs PROPRES du parser scene (pas le book_metadata qui peut
        # contenir des residus de l'ancien run avec parser primitif).
        "scene_parsed": (debug or {}).get("scene_parsed") if isinstance(debug, dict) else None,
    }


def _build_naming_signals_panel(debug: dict) -> list[dict]:
    """Construit la liste des signaux de fallback affichee sur la page detail.

    Retourne une liste de dicts {label, penalty} prets pour le template.
    Les signaux sont tries par penalite decroissante (les plus impactants
    en premier) pour que l'utilisateur voie d'abord ce qui pese le plus.
    """
    from ..core.naming_signals import (
        SIGNAL_METADATA,
        compute_signal_penalty,
        get_signals,
        render_signal_label,
    )

    sigs = get_signals(debug)
    panel: list[dict] = []
    for sig_key, sig_value in sigs.items():
        if sig_key not in SIGNAL_METADATA:
            continue
        penalty = compute_signal_penalty(sig_key, sig_value)
        if penalty <= 0:
            continue
        panel.append({
            "key": sig_key,
            "label": render_signal_label(sig_key, sig_value),
            "penalty": penalty,
        })
    panel.sort(key=lambda x: x["penalty"], reverse=True)
    return panel


def _browse_root() -> Path:
    """Racine par defaut du browser de fichiers : home utilisateur."""
    override = os.getenv("BROWSE_ROOT", "").strip()
    if override and Path(override).is_dir():
        return Path(override).resolve()
    return Path.home().resolve()


def _list_quick_roots() -> list[dict[str, str]]:
    """Liste des racines rapides a afficher en haut du browser :
    - Sur Windows : tous les drives existants (C:\\, D:\\, X:\\, etc.)
    - Sur Linux/macOS : / et home
    - Plus le home utilisateur en premier
    - Plus les chemins definis dans BROWSE_ROOTS (separes par `;`)

    Format : list de dicts {label, path}.
    """
    import string
    roots: list[dict[str, str]] = []
    seen: set[str] = set()

    # CHARTE §9 : pas d'emoji decoratif dans l'UI. On expose un `icon` (nom
    # Lucide, rendu par la macro icon() cote template) au lieu d'un prefixe
    # emoji dans le label.
    def _add(label: str, path: Path, icon: str = "folder") -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        roots.append({"label": label, "path": resolved, "icon": icon})

    # Home utilisateur en priorite
    home = Path.home()
    _add("Home", home, icon="home")

    # Drives Windows
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            d = Path(f"{letter}:/")
            if d.exists():
                _add(f"{letter}:\\", d, icon="hard-drive")
    else:
        # Sur Linux/Mac : /, /mnt
        _add("/", Path("/"), icon="hard-drive")
        for mnt in (Path("/mnt"), Path("/media")):
            if mnt.exists():
                _add(f"{mnt.name}/", mnt, icon="folder")

    # Favoris custom via env (BROWSE_ROOTS=X:\;Y:\Films;...)
    custom = os.getenv("BROWSE_ROOTS", "").strip()
    if custom:
        for raw in custom.split(";"):
            raw = raw.strip()
            if raw:
                p = Path(raw)
                if p.is_dir():
                    _add(f"{p.name or str(p)}", p, icon="star")

    return roots


# ============================================================
# SSE log tail
# ============================================================

def _sse_tail_log(
    log_path: Path,
    is_done: "Callable[[], bool]",
    poll_interval: float = 0.4,
    max_seconds: float = 600.0,
) -> "Iterator[str]":
    """Generateur SSE qui tail un fichier log jusqu'a ce que `is_done()` soit
    True (et qu'on ait rattrape la fin du fichier) OU jusqu'au timeout
    `max_seconds`.

    Format SSE : `data: <ligne>\n\n`. Lignes vides converties en ` ` pour
    eviter de couper le stream.
    """
    import time

    deadline = time.monotonic() + max_seconds
    # Attendre que le fichier existe (le worker peut etre lent a le creer)
    while not log_path.exists():
        if time.monotonic() > deadline or is_done():
            yield "event: end\ndata: log absent\n\n"
            return
        time.sleep(poll_interval)

    f = open(log_path, "r", encoding="utf-8", errors="replace")
    try:
        while True:
            line = f.readline()
            if line:
                # Garder les retours-charrette mais nettoyer le \n final pour
                # respecter le format SSE.
                payload = line.rstrip("\n") or " "
                yield f"data: {payload}\n\n"
                continue
            # Plus rien a lire pour l'instant
            if is_done():
                # Lit le reste eventuel
                rest = f.read()
                if rest:
                    for r_line in rest.splitlines():
                        yield f"data: {r_line or ' '}\n\n"
                yield "event: end\ndata: ok\n\n"
                return
            if time.monotonic() > deadline:
                yield "event: end\ndata: timeout\n\n"
                return
            time.sleep(poll_interval)
    finally:
        f.close()


# ============================================================
# APP FACTORY
# ============================================================

def _reconcile_stuck_jobs() -> None:
    """Au boot du serveur : repare les jobs en status 'preparing' qui
    n'avancent plus (worker mort).

    Strategie :
    - Si le job a un package_dir + le state on-disk est PREPARED -> done.
    - Sinon -> failed avec message clair.
    """
    from ..core import jobs_db
    stuck = jobs_db.list_jobs(statuses=["preparing"])
    if not stuck:
        return
    print(f"[INFO] Reconciliation : {len(stuck)} job(s) bloque(s) en 'preparing'.")
    for job in stuck:
        if job.package_dir and Path(job.package_dir).is_dir():
            state_data = read_state(Path(job.package_dir))
            if state_data and state_data.state in (
                PackageState.PREPARED, PackageState.ABORTED_DUPLICATE,
                PackageState.VALIDATED, PackageState.UPLOADED,
            ):
                jobs_db.update_job(
                    job.id, status="done",
                    release_name=state_data.release_name or job.release_name,
                )
                print(f"  Job {job.id} -> done (state on-disk = {state_data.state.value})")
                continue
        # Sinon : on ne peut pas confirmer, on marque failed
        jobs_db.update_job(
            job.id, status="failed",
            error="Worker interrompu pendant la preparation (serveur redemarre).",
        )
        print(f"  Job {job.id} -> failed (worker interrompu)")


class _SystemExitGuardMiddleware:
    """Middleware ASGI PUR : intercepte un SystemExit (leve par `die()`) dans
    le traitement d'une requete et renvoie un 500 au lieu de laisser mourir
    tout le serveur.

    On n'utilise PAS BaseHTTPMiddleware (@app.middleware) : sa boucle
    call_next via task-group HANG sur une BaseException comme SystemExit.
    Ici on wrappe directement l'app ASGI, ce qui propage proprement.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = {"v": False}

        async def _send(message):
            if message.get("type") == "http.response.start":
                started["v"] = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except SystemExit as e:
            import traceback
            print(f"[ERREUR] die()/SystemExit intercepte sur "
                  f"{scope.get('path', '?')} — le serveur reste debout : {e}")
            traceback.print_exc()
            if not started["v"]:
                body = (b'{"ok":false,"detail":"Erreur interne pendant le '
                        b'traitement. Le serveur est reste actif."}')
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})


def create_app() -> FastAPI:
    """Construit et retourne l'app FastAPI."""
    config.load_env()
    _reconcile_stuck_jobs()

    # Bugfix (2026-07-19, remonte par Louis) : reprise auto d'un batch apres
    # un redemarrage. Le scheduler ne se lançait qu'a l'AJOUT d'un job
    # (submit_job) ; apres un crash/restart, un batch de N fichiers deja en
    # file restait bloque en 'pending' tant qu'on n'ajoutait pas un nouveau
    # fichier. Ici on relance le scheduler au boot s'il reste des jobs a faire.
    try:
        from ..core import jobs_db as _jdb
        if _jdb.get_next_pending_job() is not None:
            from .jobs_runner import _ensure_scheduler_started
            _ensure_scheduler_started()
            print("[INFO] Jobs en attente detectes au boot -> reprise automatique.")
    except Exception as _e:
        print(f"[WARN] Reprise auto des jobs impossible : {_e}")

    # Health check MediaInfo au boot : log clair pour le user packagé.
    from ..core.nfo import check_mediainfo_available
    ok, mi_info = check_mediainfo_available()
    if ok:
        print(f"[INFO] MediaInfo : {mi_info}")
    else:
        print(f"[ATTENTION] MediaInfo indisponible : {mi_info}")
        print("           Les uploads planteront tant que ce n'est pas resolu.")

    app = FastAPI(
        title="Flox Uploader",
        description="Interface web locale pour preparer et uploader des releases.",
        version="0.1.0",
        docs_url="/api/docs",
    )

    # Bugfix (2026-07-19, remonte par Louis) : un `die()` (= sys.exit) appele
    # depuis un handler de requete (upload, torrent-files, dedup-check...)
    # remontait en SystemExit jusqu'a uvicorn et TUAIT TOUT LE SERVEUR (le web
    # devenait injoignable — ERR_CONNECTION_REFUSED — sans crash ni trace AV).
    # On intercepte SystemExit au niveau ASGI (middleware PUR, pas
    # BaseHTTPMiddleware qui HANG sur une BaseException) et on renvoie un 500 :
    # le process reste debout, seule la requete fautive echoue. Protege contre
    # toute cette classe de bug (les nombreux die() du pipeline).
    app.add_middleware(_SystemExitGuardMiddleware)

    # R2 (audit AUDIT_2026-07-19) : garde-fou anti DNS-rebinding. L'app est
    # local-only (bind 127.0.0.1) mais n'importe quel site web visite par
    # l'user peut faire pointer un domaine vers 127.0.0.1 (rebinding) et
    # POSTer vers l'API locale (upload reel, DELETE package...). Le header
    # Host de la requete reboundee porte le domaine de l'attaquant, pas
    # localhost -> on valide le Host contre une liste locale. En mode
    # --insecure-host (l'user a explicitement expose hors localhost), on
    # laisse passer (il a opte pour l'exposition reseau).
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    _insecure = os.getenv("FLOX_UPLOADER_INSECURE_HOST", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if _insecure:
        _allowed_hosts = ["*"]
    else:
        # "testserver" = Host par defaut du TestClient Starlette (tests web).
        _allowed_hosts = ["localhost", "127.0.0.1", "::1", "[::1]", "testserver"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Q2 NOTES.md : injecte le status setup dans tous les templates pour
    # que base.html puisse afficher le banner "Configuration incomplete"
    # quand l'user a clique "Configurer plus tard".
    def _setup_context_processor():
        return {
            "setup_incomplete": not config.is_setup_complete(),
            "setup_missing": config.missing_required_keys(),
        }
    templates.env.globals["setup_incomplete"] = lambda: not config.is_setup_complete()
    templates.env.globals["setup_missing"] = lambda: config.missing_required_keys()
    # NOTES round 9 Q1 : app_version exposee a TOUS les templates pour
    # afficher la version dans la sidebar/footer sans avoir a la passer
    # explicitement dans chaque route.
    from .. import __version__ as _app_version
    templates.env.globals["app_version"] = _app_version

    # R2 (audit AUDIT_2026-07-19) : page d'erreur stylee pour la NAVIGATION
    # navigateur. Avant, un GET /packages/inexistant renvoyait le JSON brut
    # {"detail": ...} affiche cru dans le navigateur. On garde le JSON pour
    # les appels API/XHR (le JS front en depend) et on rend une page HTML
    # propre pour une navigation top-level (Accept: text/html hors /api/).
    from fastapi.responses import JSONResponse as _JSONResponse
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    _ERROR_ICONS = {404: "search", 403: "lock", 400: "alert-triangle"}
    _ERROR_TITLES = {
        404: "Page introuvable",
        403: "Accès refusé",
        400: "Requête invalide",
    }

    @app.exception_handler(_StarletteHTTPException)
    async def _render_http_exception(request: Request, exc: _StarletteHTTPException):
        detail = exc.detail
        path = request.url.path
        accepts_html = "text/html" in (request.headers.get("accept") or "")
        wants_json = path.startswith("/api/") or not accepts_html
        if wants_json:
            # Preserve strictement la forme FastAPI par defaut : {"detail": ...}
            # (le JS front lit body.detail, y compris quand detail est un dict).
            headers = getattr(exc, "headers", None)
            return _JSONResponse(
                status_code=exc.status_code,
                content={"detail": detail},
                headers=headers,
            )
        # Navigation navigateur : page HTML stylee.
        message = detail if isinstance(detail, str) else "Une erreur est survenue."
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "title": _ERROR_TITLES.get(exc.status_code),
                "message": message,
                "icon_name": _ERROR_ICONS.get(exc.status_code, "alert-triangle"),
            },
            status_code=exc.status_code,
        )

    # Sprint 6 PLAN-V1 : auto-update v1. On expose `update_info()` aux
    # templates (cache disque, jamais de fetch synchrone — instantane) et
    # on lance un refresh background au boot pour que le banner soit a
    # jour des le premier hit utilisateur.
    from ..core.update_check import (
        read_cached_update_info as _read_update_info,
        refresh_cache_if_stale_async as _refresh_update_async,
        ensure_cache_exists_sync as _ensure_update_cache_sync,
    )
    templates.env.globals["update_info"] = lambda: _read_update_info()
    # Sprint 8 hotfix v8 : si le cache n'existe pas (1er boot ou silent fail
    # precedent), on bloque max 5s pour le creer SYNC. Garantit que le banner
    # update est visible des le 1er hit utilisateur. Cas observe v0.3.7 :
    # le thread daemon ne creait jamais le cache (raison inconnue, probable
    # specifique au bundle PyInstaller --windowed).
    try:
        _ensure_update_cache_sync(timeout_seconds=5.0)
    except Exception:
        pass
    # Best-effort apres : spawn thread daemon pour refresh si stale (>6h).
    try:
        _refresh_update_async()
    except Exception:
        pass

    # Sprint 8 PLAN-V1 : crash report helper. On expose `app_diagnostic()`
    # aux templates pour qu'il puisse etre injecte cote JS et utilise par
    # les boutons "Copier rapport" (toast danger) et "Signaler un bug"
    # (page Guide). Aucun secret n'est inclus dans le diagnostic.
    from ..core.diagnostic import collect_diagnostic as _collect_diagnostic
    templates.env.globals["app_diagnostic"] = lambda: _collect_diagnostic()

    # Sprint C.2 v0.5.0 : expose category_ui_metadata() aux templates pour
    # que la macro `category_badge` puisse rendre n'importe quel badge cat
    # depuis son id. Source de verite unique : CATEGORY_UI_METADATA.
    from ..trackers.gemini.unit3d_mapping import (
        category_ui_metadata as _category_ui_metadata,
    )
    templates.env.globals["category_ui_metadata"] = _category_ui_metadata

    # Sprint C.4 v0.5.0 : helper pour determiner le profil UI d'un package
    # (video / show / sport / book / game / manual). Utilise par
    # package_detail.html pour inclure le bon `_detail_<profile>.html`
    # selon la categorie effective.
    from ..core.category_resolver import category_profile as _category_profile
    templates.env.globals["category_profile"] = _category_profile

    # Filtre fmt_date : convertit ISO "2026-05-11T19:17:00Z" en
    # "2026-05-11 19:17" (T -> space, drop Z, drop ms, drop secondes).
    # Format compact et lisible humain.
    def _fmt_date(iso_str):
        if not iso_str:
            return iso_str or ""
        s = str(iso_str).replace("T", " ")
        if s.endswith("Z"):
            s = s[:-1]
        if "." in s:
            s = s.split(".")[0]
        # Drop secondes (HH:MM:SS -> HH:MM)
        if len(s) >= 16 and s[10] == " " and s[13] == ":" and s[16:17] == ":":
            s = s[:16]
        return s
    templates.env.filters["fmt_date"] = _fmt_date

    # Sprint D.35 v0.5.0 : helpers URL Google Books moderne + BnF.
    # Genere /books/edition/<slug>/<id> au lieu de l'ancien books?id=ID.
    from ..core.providers._url_helpers import google_books_url, bnf_url
    templates.env.filters["google_books_url"] = google_books_url
    templates.env.filters["bnf_url"] = bnf_url

    # ------------------------------------------------------------
    # Middleware first-run : redirige vers /setup si la config n'est pas
    # complete (TRACKER_API_*, TMDB_API_KEY, TRACKER_ANNOUNCE manquants).
    # Le user lambda atterit sur le wizard au lieu de tomber sur des
    # erreurs cryptiques au premier upload.
    # ------------------------------------------------------------
    _SETUP_BYPASS_PREFIXES = (
        "/setup",
        "/api/setup",
        # Bugfix first-run : les boutons « Tester » / « Vérifier » du wizard
        # appellent /api/config/test-key. Sans ce bypass, le middleware
        # first-run les bloquait en 503 « Aller sur /setup » — impossible de
        # valider ses cles PENDANT la config initiale (paradoxe : on est sur
        # /setup justement parce que la config est incomplete).
        "/api/config/test-key",
        "/static",
        "/api/docs",
        "/openapi.json",
        "/favicon.ico",
    )

    # Q2 NOTES.md round 2 : seul le PREMIER hit (cookie absent + setup incomplet)
    # redirige vers /setup. Apres "Configurer plus tard", l'user pose un cookie
    # `tu_setup_skip=1` qui empeche les redirects suivants. Le wizard reste
    # accessible via /setup et un banner persistant sur chaque page indique
    # que la config est incomplete. Les actions blocking (add-to-queue,
    # upload, prepare) sont gardes par les endpoints qui retournent 503
    # avec "missing" pour permettre a la UI de pointer vers /setup.
    _ACTION_BLOCKING_PATHS = (
        "/api/queue/add",
        "/api/queue/upload-batch",
    )

    @app.middleware("http")
    async def _redirect_when_setup_incomplete(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _SETUP_BYPASS_PREFIXES):
            return await call_next(request)
        if config.is_setup_complete():
            return await call_next(request)
        # Setup incomplet : on bloque seulement les endpoints d'action
        # (add-to-queue, upload-batch). Sinon on laisse passer (la UI
        # affiche un banner persistant pour avertir l'user).
        if any(path.startswith(p) for p in _ACTION_BLOCKING_PATHS):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "setup_required": True,
                    "missing": config.missing_required_keys(),
                    "detail": "Configuration incomplete. Va sur /setup pour configurer.",
                },
            )
        # /api/packages/<name>/upload : meme blocage cote 503
        if path.startswith("/api/packages/") and path.endswith("/upload"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "setup_required": True,
                    "missing": config.missing_required_keys(),
                    "detail": "Configuration incomplete. Va sur /setup pour configurer.",
                },
            )
        # Premier hit (cookie skip absent) : redirect /setup pour onboarding.
        # Apres skip, on laisse passer.
        if request.cookies.get("tu_setup_skip") != "1":
            # Pour /api/* (hors blocking ci-dessus) : 503 explicit
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=503,
                    content={
                        "ok": False,
                        "setup_required": True,
                        "missing": config.missing_required_keys(),
                        "detail": "Configuration incomplete. Aller sur /setup.",
                    },
                )
            return RedirectResponse(url="/setup", status_code=303)
        # Cookie skip pose : on laisse acceder a la UI (banner persistant gerera l'avertissement)
        return await call_next(request)

    # ------------------------------------------------------------
    # Routes pages
    # ------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        if not config.is_setup_complete():
            return RedirectResponse(url="/setup", status_code=303)
        return RedirectResponse(url="/inbox")

    # ------------------------------------------------------------
    # Wizard first-run
    # ------------------------------------------------------------

    @app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
    def page_setup(request: Request):
        """Page wizard de setup initiale.

        Affichee tant que les variables critiques ne sont pas toutes definies.
        Une fois setup complete, accessible quand meme (utile si le user
        veut rejouer la procedure : la page redirige vers /inbox via JS apres
        save reussi).
        """
        from .config_view import read_env_values, masked_secret_value, SCHEMA
        values = read_env_values()
        # Sprint 8 hotfix : masque dynamique de longueur reelle pour les
        # secrets (autant de puces que de caracteres) cote setup wizard aussi.
        display_values: dict[str, str] = {}
        for f in SCHEMA:
            v = values.get(f.key, "")
            display_values[f.key] = masked_secret_value(v) if f.is_secret else v
        # Sprint 2 : detection 1er run pour afficher un welcome plus prominent.
        # Critere : fichier .env absent OU aucune valeur critique definie.
        # On utilise REQUIRED_ENV_KEYS (source de verite de "qu'est-ce qui est
        # critique") plutot que d'inferer depuis SCHEMA.
        env_file = config.env_file()
        is_first_run = (
            not env_file.exists()
            or not any(values.get(k) for k in config.REQUIRED_ENV_KEYS)
        )
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "page": "setup",
                "values": display_values,
                "missing": config.missing_required_keys(),
                "setup_complete": config.is_setup_complete(),
                "is_first_run": is_first_run,
                "data_dir_path": str(config.data_dir()),
                "env_file_path": str(env_file),
            },
        )

    # ============================================================
    # Test-key endpoints (Sprint 2 — PLAN-V1.md)
    # ============================================================
    # Endpoint unifie `/api/config/test-key` qui prend `kind` dans le body
    # et delegue a la bonne fonction de test.
    #
    # Les anciens endpoints `/api/setup/test-tmdb` et `/api/setup/test-tracker`
    # sont conserves comme wrappers (backward compat pour tests / scripts
    # eventuels). A supprimer dans une release future.
    # ============================================================

    def _test_tmdb_key(api_key: str) -> dict:
        """Ping TMDB /configuration avec la cle. Retourne dict {ok, message}."""
        import requests as _requests
        if not api_key:
            raise HTTPException(400, "Clé TMDB vide.")
        try:
            resp = _requests.get(
                "https://api.themoviedb.org/3/configuration",
                params={"api_key": api_key},
                timeout=10,
            )
        except _requests.RequestException as e:
            raise HTTPException(502, f"Erreur réseau TMDB : {e}")
        if resp.status_code == 200:
            return {"ok": True, "message": "Clé TMDB valide."}
        if resp.status_code == 401:
            raise HTTPException(401, "Clé TMDB invalide (401 Unauthorized).")
        raise HTTPException(
            502,
            f"TMDB a répondu HTTP {resp.status_code} : {(resp.text or '')[:120]}",
        )

    def _test_omdb_key(api_key: str) -> dict:
        """Ping OMDb avec la cle (recherche bidon). Retourne dict {ok, message}."""
        import requests as _requests
        if not api_key:
            raise HTTPException(400, "Clé OMDb vide.")
        try:
            # OMDb : on fait une requete legere avec un IMDb ID connu.
            # tt0111161 = The Shawshank Redemption (toujours present).
            resp = _requests.get(
                "https://www.omdbapi.com/",
                params={"apikey": api_key, "i": "tt0111161"},
                timeout=10,
            )
        except _requests.RequestException as e:
            raise HTTPException(502, f"Erreur réseau OMDb : {e}")
        # OMDb renvoie toujours 200 mais avec Response="True" ou "False".
        # Si la cle est invalide : 401 OU 200 + Error="Invalid API key!".
        if resp.status_code == 401:
            raise HTTPException(401, "Clé OMDb invalide (401).")
        try:
            data = resp.json()
        except Exception:
            raise HTTPException(502, f"OMDb a répondu HTTP {resp.status_code} (JSON invalide).")
        if data.get("Response") == "False":
            err = data.get("Error", "Erreur inconnue")
            if "Invalid API key" in err or "limit reached" in err.lower():
                raise HTTPException(401, f"OMDb : {err}")
            raise HTTPException(502, f"OMDb : {err}")
        return {"ok": True, "message": "Clé OMDb valide."}

    def _test_tracker_creds(api_url: str, api_key: str) -> dict:
        """Ping le tracker Unit3D avec auth Bearer. Retourne dict {ok, message}."""
        import requests as _requests
        if not api_url or not api_key:
            raise HTTPException(400, "URL et clé tracker requises.")
        api_url = api_url.rstrip("/")
        try:
            resp = _requests.get(
                f"{api_url}/torrents/filter",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                params={"id": 1},
                timeout=10,
            )
        except _requests.RequestException as e:
            raise HTTPException(502, f"Erreur réseau tracker : {e}")
        # 200 ou 404 = endpoint joint et auth OK (404 = pas de torrent id=1)
        if resp.status_code in (200, 404):
            return {"ok": True, "message": "API tracker joignable, auth OK."}
        if resp.status_code == 401:
            raise HTTPException(401, "Clé API tracker invalide (401).")
        if resp.status_code == 403:
            raise HTTPException(403, "Accès refusé (403, rang utilisateur ?).")
        raise HTTPException(
            502,
            f"Tracker a répondu HTTP {resp.status_code} : {(resp.text or '')[:120]}",
        )

    def _test_announce_url(announce_url: str) -> dict:
        """Valide le FORMAT d'une URL announce (on ne peut pas vraiment ping un
        tracker BitTorrent sans simuler un client). Verifie :
        - URL bien formee (scheme http/https)
        - Path contient '/announce' ou ressemble a un endpoint announce
        - Path a un segment apres /announce (la passkey)
        """
        from urllib.parse import urlparse
        if not announce_url:
            raise HTTPException(400, "URL announce vide.")
        try:
            parsed = urlparse(announce_url)
        except Exception as e:
            raise HTTPException(400, f"URL malformée : {e}")
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(400, "Le scheme doit être http ou https.")
        if not parsed.netloc:
            raise HTTPException(400, "URL sans host (vérifie le format).")
        path = parsed.path or ""
        if "/announce" not in path:
            raise HTTPException(
                400,
                "L'URL ne contient pas '/announce' — vérifie que c'est bien "
                "une URL announce de tracker (pas l'URL du site).",
            )
        # Le segment apres /announce devrait etre la passkey
        # Format Unit3D : /announce/<passkey>
        segments = [s for s in path.split("/") if s]
        try:
            ann_idx = segments.index("announce")
        except ValueError:
            ann_idx = -1
        if ann_idx == -1 or ann_idx == len(segments) - 1:
            # Cas particulier : announce avec query string `?passkey=...` (rare)
            if not parsed.query and "passkey" not in announce_url.lower():
                raise HTTPException(
                    400,
                    "Aucune passkey détectée après /announce. Format attendu : "
                    "https://tracker.example/announce/<TA_PASSKEY>",
                )
        return {
            "ok": True,
            "message": f"Format URL announce valide ({parsed.netloc}). "
                       "Note : on ne peut pas tester l'authenticité de la passkey "
                       "sans simuler un client BitTorrent.",
        }

    @app.post("/api/config/test-key")
    def api_config_test_key(payload: dict[str, Any]):
        """Sprint 2 : endpoint unifie pour tester n'importe quelle cle / URL
        de config. Le `kind` dans le body determine quel test on lance.

        Body :
          {
            "kind": "tmdb" | "omdb" | "tracker" | "announce",
            ... params specifiques au kind ...
          }

        Pour tmdb / omdb : {api_key: "..."}
        Pour tracker     : {api_url: "...", api_key: "..."}
        Pour announce    : {announce_url: "..."}

        Retourne {ok: True, message: "..."} si OK, sinon HTTPException avec
        le code adequat (401 pour invalide, 502 pour erreur reseau, 400 pour
        payload mal forme).
        """
        kind = (payload.get("kind") or "").strip().lower()
        if kind == "tmdb":
            return _test_tmdb_key((payload.get("api_key") or "").strip())
        if kind == "omdb":
            return _test_omdb_key((payload.get("api_key") or "").strip())
        if kind == "tracker":
            return _test_tracker_creds(
                (payload.get("api_url") or "").strip(),
                (payload.get("api_key") or "").strip(),
            )
        if kind == "announce":
            return _test_announce_url((payload.get("announce_url") or "").strip())
        raise HTTPException(
            400,
            f"kind inconnu : {kind!r}. Attendu : tmdb, omdb, tracker, announce.",
        )

    # NOTES Sprint 4 cleanup : les endpoints /api/data-dir/legacy-status et
    # /api/data-dir/migrate ont ete retires en v0.3.5. Voir config.py pour
    # la note explicative. Pour un import manuel futur (option C), on
    # ajoutera un nouvel endpoint qui prend un path explicite plutot que
    # de detecter automatiquement.

    # --- Backward-compat (anciens endpoints, deprecated) -----------------
    @app.post("/api/setup/test-tmdb")
    def api_setup_test_tmdb(payload: dict[str, Any]):
        """DEPRECATED Sprint 2 : utiliser /api/config/test-key avec kind=tmdb.
        Conserve pour ne pas casser les scripts/tests externes."""
        return _test_tmdb_key((payload.get("api_key") or "").strip())

    @app.post("/api/setup/test-tracker")
    def api_setup_test_tracker(payload: dict[str, Any]):
        """DEPRECATED Sprint 2 : utiliser /api/config/test-key avec kind=tracker."""
        return _test_tracker_creds(
            (payload.get("api_url") or "").strip(),
            (payload.get("api_key") or "").strip(),
        )

    @app.post("/api/setup/save")
    def api_setup_save(payload: dict[str, Any]):
        """Persiste les valeurs du wizard (meme schema que /api/config).

        Apres save reussi, recharge l'env pour que les valeurs soient effectives
        immediatement sans redemarrage.
        """
        from .config_view import validate_updates, write_env_values, apply_updates
        values = payload.get("values") or {}
        updates, errors = validate_updates(values)
        if errors:
            raise HTTPException(400, "; ".join(errors))
        if updates:
            write_env_values(updates)
            apply_updates(updates)
        return {
            "ok": True,
            "setup_complete": config.is_setup_complete(),
            "missing": config.missing_required_keys(),
            "updated_keys": sorted(updates.keys()),
        }

    def _is_path_in_favorites(target_path: str) -> bool:
        """True si `target_path` est dans BROWSE_ROOTS (separe par `;`).

        Comparaison sur la chaine normalisee (resolved) pour eviter les
        faux negatifs entre "C:/Foo" et "C:\\Foo" ou "C:/Foo/".
        """
        custom = os.getenv("BROWSE_ROOTS", "").strip()
        if not custom:
            return False
        normalized_target = str(Path(target_path).resolve()).rstrip("\\/")
        for raw in custom.split(";"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                if str(Path(raw).resolve()).rstrip("\\/") == normalized_target:
                    return True
            except OSError:
                continue
        return False

    @app.get("/inbox", response_class=HTMLResponse)
    def page_inbox(
        request: Request,
        path: str | None = None,
        show_all: int = 0,
        show_videos: int = 1,
        show_books: int = 1,
    ):
        """Browser de fichiers : navigation + selection multi pour ajouter
        a la queue.

        Sprint 8 hotfix v5 : le serveur retourne TOUT le listing (toutes les
        rows en HTML). La pagination + search se font 100% cote client :
        - pagination = cache les rows hors page via display:none (perf DOM minimale)
        - search = filtre instantane sur l'ensemble (zero latence)

        Pourquoi pas server-side : v3 etait propre mais le filesystem scan
        prenait le meme temps quel que soit la pagination (le filesystem ne
        sait pas paginer). Mieux vaut tout rendre une fois et garder l'UI
        client-side fluide. `os.scandir()` (v4) rend le scan rapide meme
        pour 5000+ fichiers.

        NOTES round 9 Feat-1 : `?show_all=1` retire le filtre extension et
        affiche tous les fichiers. Le toggle UI persiste la preference en
        localStorage et ajoute / retire le query param.
        """
        target = _safe_resolve_path(path) if path else _browse_root()
        try:
            entries = _list_directory(
                target,
                show_all=bool(show_all),
                show_videos=bool(show_videos),
                show_books=bool(show_books),
            )
        except HTTPException as e:
            entries = []
            error = e.detail
        else:
            error = None
        crumbs: list[dict[str, str]] = []
        cur = target
        while True:
            crumbs.append({"name": cur.name or str(cur), "path": str(cur)})
            if cur.parent == cur:
                break
            cur = cur.parent
        crumbs.reverse()
        return templates.TemplateResponse(
            request,
            "inbox.html",
            {
                "page": "inbox",
                "current_path": str(target),
                "entries": entries,
                "crumbs": crumbs,
                "parent_path": str(target.parent) if target.parent != target else None,
                "error": error,
                "quick_roots": _list_quick_roots(),
                "show_all": bool(show_all),
                # Sprint D.38 v0.5.0 : filtres Films/Series et Livres
                "show_videos": bool(show_videos),
                "show_books": bool(show_books),
                # NOTES Sprint 8 hotfix v6 : indique si le dossier courant est
                # deja un favori. Le bouton "Ajouter aux favoris" dans le
                # header devient "Retirer des favoris" si vrai.
                "is_current_favorite": _is_path_in_favorites(str(target)),
            },
        )

    @app.post("/api/inbox/favorites/toggle")
    def api_inbox_favorites_toggle(payload: dict[str, Any]):
        """Sprint 8 hotfix v6 : toggle un dossier dans BROWSE_ROOTS.

        Permet d'ajouter / retirer un favori directement depuis la page
        Inbox sans passer par /config. Le BROWSE_ROOTS est ecrit dans le
        .env (persistant) ET applique a os.environ (effet immediat).
        """
        target_path = (payload.get("path") or "").strip()
        if not target_path:
            raise HTTPException(400, "Path requis")
        # Valide que c'est un dossier reel sur disque
        try:
            target = Path(target_path).resolve()
        except OSError:
            raise HTTPException(400, f"Path invalide : {target_path}")
        if not target.is_dir():
            raise HTTPException(400, f"Pas un dossier : {target_path}")
        target_str = str(target).rstrip("\\/")

        from .config_view import write_env_values, apply_updates
        current = os.getenv("BROWSE_ROOTS", "").strip()
        # Liste actuelle avec chemins normalises pour la dedup
        paths_raw = [p.strip() for p in current.split(";") if p.strip()] if current else []
        paths_normalized: list[str] = []
        seen: set[str] = set()
        for p in paths_raw:
            try:
                norm = str(Path(p).resolve()).rstrip("\\/")
            except OSError:
                continue
            if norm not in seen:
                seen.add(norm)
                paths_normalized.append(norm)

        is_currently_favorite = target_str in seen
        if is_currently_favorite:
            paths_normalized = [p for p in paths_normalized if p != target_str]
            action = "removed"
        else:
            paths_normalized.append(target_str)
            action = "added"

        new_value = ";".join(paths_normalized)
        write_env_values({"BROWSE_ROOTS": new_value})
        apply_updates({"BROWSE_ROOTS": new_value})
        return {
            "is_favorite": not is_currently_favorite,
            "action": action,
            "favorites_count": len(paths_normalized),
        }

    @app.get("/history", response_class=HTMLResponse)
    def page_history(request: Request):
        """Liste des packages deja uploades.

        Filtre `_list_packages()` sur state == 'uploaded' et expose des
        champs supplementaires utiles : url tracker, ID torrent, date upload.
        Tri par updated_at decroissant (plus recent en haut).
        """
        all_packages = _list_packages()
        uploaded = [p for p in all_packages if p.state == "uploaded"]
        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "page": "history",
                "packages": uploaded,
                "total": len(uploaded),
            },
        )

    @app.get("/queue", response_class=HTMLResponse)
    def page_queue(request: Request):
        """Liste tous les packages existants + jobs pending + uploads en cours."""
        from ..core import jobs_db
        from .jobs_runner import list_upload_statuses
        packages = _list_packages()
        # NOTES round 9 Bug-1 : jobs_db.list_jobs() a un default limit=100 qui
        # tronque la liste quand le user a > 100 jobs en attente. On force
        # un limit eleve (10k = pratiquement illimite ; on n'imagine pas
        # avoir plus de 10k jobs simultanes dans la queue). Le template gere
        # deja l'overflow visuel (>100 -> bouton "Afficher les N autres").
        pending = jobs_db.list_jobs(
            statuses=["pending", "preparing", "failed"],
            limit=10000,
        )
        pending_entries = [
            PendingJobEntry(
                id=j.id,
                file_name=Path(j.file_path).name,
                file_path=j.file_path,
                status=j.status,
                force_fr=j.force_fr,
                error=j.error,
                created_at=j.created_at,
                is_paused=j.is_paused,
                priority_order=j.priority_order,
            )
            for j in pending
        ]
        uploads = list_upload_statuses(include_done=True)
        return templates.TemplateResponse(
            request,
            "queue.html",
            {
                "page": "queue",
                "packages": packages,
                "pending_jobs": pending_entries,
                "uploads": uploads,
            },
        )

    @app.get("/config", response_class=HTMLResponse)
    def page_config(request: Request):
        """Page d'edition des variables d'environnement (.env)."""
        from .config_view import schema_grouped, read_env_values, masked_secret_value
        values = read_env_values()
        # Sprint 8 hotfix : masque dynamique de longueur reelle pour les
        # secrets (autant de puces que de caracteres). Donne un retour visuel
        # coherent au lieu de "***" fixe qui faisait croire que le champ
        # etait vide.
        sections = []
        for section_name, fields in schema_grouped():
            display_fields = []
            for f in fields:
                v = values.get(f.key, "")
                display = masked_secret_value(v) if f.is_secret else v
                display_fields.append((f, v, display))
            sections.append((section_name, display_fields))
        return templates.TemplateResponse(
            request,
            "config.html",
            {
                "page": "config",
                "sections": sections,
            },
        )

    @app.get("/guide", response_class=HTMLResponse)
    def page_guide(request: Request):
        """Guide utilisateur : presentation app + concepts + raccourcis +
        a propos. Page statique mais data-driven (version, env, etc.)."""
        from .. import __version__ as _tu_version
        return templates.TemplateResponse(
            request,
            "guide.html",
            {
                "page": "guide",
                "app_version": _tu_version,
            },
        )

    @app.get("/api/categories")
    def api_categories():
        """Sprint C.1 v0.5.0 — metadonnees UI des 12 categories Gemini.

        Source : `unit3d_mapping.CATEGORY_UI_METADATA`. Consomme par la modal
        selecteur sur Inbox (auto-detection extension -> suggestion), les
        badges couleur sur Queue / Page detail, et toute UI multi-categorie.

        Aucun secret, aucune donnee user. Pure metadata produit.

        Returns:
            {
              "categories": [
                {"id": 1, "label": "Film", "icon": "clapperboard",
                 "color": "primary", "extensions": [".mkv", ...], "hint": "..."},
                ...
              ],
              "extension_to_category": {".epub": 12, ".pdf": 12, ".exe": 17, ...}
            }
        """
        from ..trackers.gemini.unit3d_mapping import CATEGORY_UI_METADATA
        ext_to_cat: dict[str, int] = {}
        for meta in CATEGORY_UI_METADATA:
            for ext in meta.get("extensions") or []:
                ext_to_cat[ext.lower()] = meta["id"]
        return {
            "categories": CATEGORY_UI_METADATA,
            "extension_to_category": ext_to_cat,
        }

    @app.get("/api/diagnostic")
    def api_diagnostic():
        """Sprint 8 PLAN-V1 — diagnostic systeme pour rapport de bug.

        Retourne le dict de `Diagnostic` :
            - version : version Flox Uploader
            - python_version : ex "3.12.4"
            - os : "Windows" / "macOS" / "Linux" / "Autre"
            - os_release : version OS (ex "11", "23.5.0")
            - mediainfo_available : bool
            - mediainfo_version : str (vide si non dispo)
            - setup_complete : bool

        Aucun secret, aucun path absolu, aucun identifiant user. Le payload
        est destine a etre colle dans une GitHub Issue publique.
        """
        from ..core.diagnostic import collect_diagnostic
        return collect_diagnostic().to_dict()

    # R7 (audit AUDIT_2026-07-19) : backup / export des donnees. Comble le trou
    # « perte disque = perte passkey + historique » : aucun moyen de sauvegarder
    # sa config et son historique. On expose la taille + un export ZIP.
    # Dossiers/fichiers exclus du backup : volumineux ou regenerables.
    _BACKUP_EXCLUDE_DIRS = {"temp", "jobs", "torrents_to_seed"}
    _BACKUP_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 Mo : on saute les gros previews

    def _iter_backup_files():
        """Genere (path_absolu, arcname_relatif) des fichiers a sauvegarder."""
        root = config.data_dir()
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            # Skip les dossiers exclus (au 1er niveau du chemin relatif).
            if rel.parts and rel.parts[0] in _BACKUP_EXCLUDE_DIRS:
                continue
            # Skip les .log et les fichiers trop gros (previews, covers lourdes).
            if path.suffix.lower() == ".log":
                continue
            try:
                if path.stat().st_size > _BACKUP_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path, str(rel).replace("\\", "/")

    @app.get("/api/data/info")
    def api_data_info():
        """Taille et localisation du dossier de donnees (carte « Mes données »)."""
        root = config.data_dir()
        total = 0
        backup_total = 0
        pkg_count = 0
        for path in root.rglob("*") if root.is_dir() else []:
            if not path.is_file():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                pass
        for path, _arc in _iter_backup_files():
            try:
                backup_total += path.stat().st_size
            except OSError:
                pass
        pkgs = config.packages_dir()
        if pkgs.is_dir():
            pkg_count = sum(
                1 for p in pkgs.iterdir() if (p / "package_state.json").is_file()
            )
        return {
            "data_dir": str(root),
            "total_bytes": total,
            "backup_bytes": backup_total,
            "package_count": pkg_count,
        }

    @app.get("/api/data/export")
    def api_data_export():
        """Export ZIP (config + historique) pour backup. Streaming, sans les
        gros fichiers/logs (cf. _iter_backup_files). Contient le .env (passkey/
        cles) : c'est un backup personnel, a garder prive."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, arcname in _iter_backup_files():
                try:
                    zf.write(path, arcname)
                except OSError:
                    continue
        buf.seek(0)
        headers = {
            "Content-Disposition": 'attachment; filename="flox-uploader-backup.zip"'
        }
        return StreamingResponse(
            iter([buf.getvalue()]), media_type="application/zip", headers=headers,
        )

    @app.post("/api/update-info/refresh")
    def api_update_info_refresh():
        """Sprint 8 hotfix v10 : force un refresh sync + retourne l'erreur eventuelle.

        Utilise par le bouton "Verifier maintenant" dans la page Guide.
        Bloque jusqu'a 5s (timeout fetch GitHub) puis retourne :
          {info: {...UpdateInfo...}, fetch_error: "" ou message}

        Si fetch_error est non-vide, le JS doit signaler l'echec a l'user
        au lieu de pretendre "A jour" (qui serait base sur l'ancien cache).
        """
        from ..core.update_check import force_refresh_sync
        info, err = force_refresh_sync()
        return {"info": info.to_dict(), "fetch_error": err}

    @app.get("/api/update-info")
    def api_update_info():
        """Sprint 6 PLAN-V1 — statut de la mise a jour.

        Lit le cache disque (rapide), declenche un refresh background si
        stale (>6h ou absent). L'user voit toujours le cache : c'est
        l'appel HTTP /releases/latest qui se rafraichit en arriere-plan.

        Retourne le dict de `UpdateInfo` :
            - available : bool (True ssi latest > current en semver strict)
            - current : str (ex: "0.3.5")
            - latest : str (ex: "0.4.0", "" si jamais fetched)
            - release_url : str (page GitHub Releases pour cette version)
            - release_notes : str (body markdown de la release, peut etre long)
            - fetched_at : str (ISO UTC du dernier fetch reussi, "" si jamais)
        """
        from ..core.update_check import (
            read_cached_update_info,
            refresh_cache_if_stale_async,
        )
        try:
            refresh_cache_if_stale_async()
        except Exception:
            pass
        return read_cached_update_info().to_dict()

    @app.get("/api/config")
    def api_config_get():
        """Retourne les valeurs courantes (secrets masques par defaut).

        NOTES Sprint 8 hotfix : pour les secrets non vides, on retourne
        `"●" * len(value)` (autant de puces que de caracteres). Donne un
        retour visuel coherent (32 chars => 32 puces) au lieu de "***" fixe
        qui peut faire croire que la cle est vide.
        """
        from .config_view import read_env_values, masked_secret_value, SCHEMA
        values = read_env_values()
        return {
            "values": {
                f.key: (
                    masked_secret_value(values.get(f.key, ""))
                    if f.is_secret
                    else values.get(f.key, "")
                )
                for f in SCHEMA
            },
        }

    @app.get("/api/config/reveal")
    def api_config_reveal(key: str = Query(..., description="Cle secrete a reveler")):
        """Retourne la VRAIE valeur d'un secret pour affichage a la demande.

        Restreint aux cles du SCHEMA avec `is_secret=True` (TRACKER_API_KEY,
        TRACKER_ANNOUNCE, TMDB_API_KEY, OMDB_API_KEY). Le bouton oeil dans
        la page /config appelle cet endpoint quand le user veut verifier
        sa cle. Le HTML par defaut n'expose pas le secret (utile si tu
        partages ton ecran sur Discord, etc.) — il faut un click explicite.

        Avertissement : si la web UI est exposee hors localhost via
        --insecure-host, cet endpoint expose le secret a quiconque y
        accede. Acceptable en local-only (defaut), pas en multi-user.
        """
        from .config_view import SCHEMA
        field = next((f for f in SCHEMA if f.key == key), None)
        if field is None:
            raise HTTPException(404, f"Cle inconnue : {key}")
        if not field.is_secret:
            raise HTTPException(400, f"Pas un secret : {key} (utiliser /api/config)")
        return {"key": key, "value": os.getenv(key, "")}

    @app.post("/api/config")
    def api_config_save(payload: dict[str, Any]):
        """Sauvegarde les modifications dans le .env + applique a os.environ.

        Body : {"values": {KEY: VALUE, ...}}
        - Cles inconnues rejetees.
        - Secrets : si valeur == "***", on conserve l'existant.
        - Booleens normalises en "0"/"1".
        """
        from .config_view import validate_updates, write_env_values, apply_updates
        values = payload.get("values") or {}
        updates, errors = validate_updates(values)
        if errors:
            raise HTTPException(400, "; ".join(errors))
        if updates:
            write_env_values(updates)
            apply_updates(updates)
        return {
            "ok": True,
            "updated_keys": sorted(updates.keys()),
            "message": (
                f"{len(updates)} cle(s) mise(s) a jour" if updates
                else "Aucun changement (les secrets restent inchanges si tu n'as pas saisi de valeur)."
            ),
        }

    @app.get("/packages/{name}", response_class=HTMLResponse)
    def page_package_detail(request: Request, name: str):
        """Page detail d'un package : score breakdown, NFO, logs, overrides."""
        ctx = _load_package_detail(name)
        ctx["page"] = "queue"
        return templates.TemplateResponse(request, "package_detail.html", ctx)

    @app.get("/packages/{name}/cover")
    def serve_package_cover(name: str):
        """Sert la couverture extraite localement (Sprint D.7 v0.5.0).

        Cherche `cover.jpg`, `cover.png`, `cover.webp` dans le package_dir.
        Si rien -> 404. Utilise par le template _detail_book.html quand
        l'extraction locale a reussi (EPUB/PDF/CBZ).
        """
        from fastapi.responses import FileResponse, Response
        try:
            target = _resolve_package_dir(name)
        except HTTPException:
            return Response(status_code=404)
        for candidate in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
            cover_path = target / candidate
            if cover_path.is_file():
                # On detecte le content-type au header par l'extension du file
                # local — meme si on a tjs ecrit en .jpg cote pipeline, on
                # garde la flexibilite si une future extraction sauve en png.
                return FileResponse(cover_path)
        return Response(status_code=404)

    # ------------------------------------------------------------
    # Routes API JSON
    # ------------------------------------------------------------

    @app.get("/api/files")
    def api_files(path: str = Query(..., description="Path du dossier a lister")):
        target = _safe_resolve_path(path)
        entries = _list_directory(target)
        return {
            "current_path": str(target),
            "parent_path": str(target.parent) if target.parent != target else None,
            "entries": [asdict(e) for e in entries],
        }

    @app.get("/api/packages")
    def api_packages():
        return {"packages": [asdict(p) for p in _list_packages()]}

    @app.post("/api/inbox/peek-category")
    def api_inbox_peek_category(payload: dict[str, Any]):
        """Sprint D.7 v0.5.0 — devine la categorie pour 1 ou N paths.

        Permet a la modal Inbox de pre-cocher le bon bouton (Vidéo / Livre /
        Jeu / Logiciel) selon le contenu detecte. Aucun side-effect : pure
        lecture filesystem.

        Body :
            {"paths": ["C:\\...\\file.epub", ...]}

        Returns :
            {"category_id": 12, "category_label": "Livres",
             "confidence": "high"|"low"}
            confidence='low' si fallback CATEGORY_MOVIE par defaut
            (= aucun signal exploitable, on a devine video).
        """
        from ..core.early_category import early_category_guess
        from ..trackers.gemini.unit3d_mapping import (
            CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_SOFTWARE,
            CATEGORY_OPTIONS,
        )

        paths = payload.get("paths") or []
        if not paths:
            return {
                "category_id": CATEGORY_MOVIE,
                "category_label": "Films",
                "confidence": "low",
            }

        # Tente sur le premier path. Si plusieurs paths : on prend la cat la
        # plus frequente (les outliers sont l'exception).
        votes: dict[int, int] = {}
        for p in paths[:20]:  # cap a 20 pour eviter de bloquer sur un gros bundle
            try:
                target = _safe_resolve_path(str(p))
            except HTTPException:
                continue
            if not target.exists():
                continue
            cat = early_category_guess(target)
            votes[cat] = votes.get(cat, 0) + 1

        if not votes:
            return {
                "category_id": CATEGORY_MOVIE,
                "category_label": "Films",
                "confidence": "low",
            }

        # Cat la plus votee
        best_cat = max(votes.items(), key=lambda kv: kv[1])[0]
        # Confidence : 'high' si la cat detectee est explicitement non-default
        # (livre / jeu / logiciel), 'low' si c'est Films par defaut.
        confidence = "high" if best_cat != CATEGORY_MOVIE else "low"

        # Label depuis CATEGORY_OPTIONS (cf. unit3d_mapping)
        label_map = {cat_id: label for cat_id, label in CATEGORY_OPTIONS}
        label = label_map.get(best_cat, "Films")

        return {
            "category_id": best_cat,
            "category_label": label,
            "confidence": confidence,
        }

    @app.post("/api/queue/add")
    def api_queue_add(payload: dict[str, Any]):
        from ..core import jobs_db
        from .jobs_runner import submit_prepare_job

        paths = payload.get("paths") or []
        force_fr = (payload.get("force_fr") or "").strip().upper()
        # Sprint C.1 v0.5.0 : hint categorie depuis la modal Inbox.
        # 0 / absent / non-int -> auto-detect via early_category_guess.
        try:
            category_id_hint = int(payload.get("category_id_hint") or 0)
        except (TypeError, ValueError):
            category_id_hint = 0
        if not paths:
            raise HTTPException(400, "Aucun path fourni.")
        # Sanity check : null-bytes / patterns suspects ; resolution absolue.
        resolved: list[Path] = []
        for p in paths:
            target = _safe_resolve_path(str(p))
            if not target.exists():
                raise HTTPException(400, f"Path inexistant : {target}")
            resolved.append(target)
        created_ids: list[int] = []
        for target in resolved:
            job = jobs_db.add_job(
                str(target), force_fr=force_fr,
                category_id_hint=category_id_hint,
            )
            submit_prepare_job(job.id)
            created_ids.append(job.id)
        return {
            "ok": True,
            "added": len(created_ids),
            "job_ids": created_ids,
            "message": (
                f"{len(created_ids)} preparation(s) lancee(s) en arriere-plan. "
                "Voir l'onglet Queue pour suivre l'avancement."
            ),
        }

    @app.post("/api/queue/add-bundle")
    def api_queue_add_bundle(payload: dict[str, Any]):
        """NOTES round 6 F1 : packager 2+ fichiers/dossiers non-emboîtés
        en UN seul torrent.

        Le user fournit `paths[]` + `bundle_name`. On cree un dossier
        temp local dans `data/temp/bundle_<timestamp>/<bundle_name>/`
        avec un hardlink vers chaque item. Puis on lance le pipeline
        sur ce dossier comme s'il etait un dossier classique.
        Le user gere les overrides (FR variant, TMDB ID) apres la prepa.
        """
        import os
        import shutil
        import time
        from ..core import jobs_db
        from ..config import data_dir
        from .jobs_runner import submit_prepare_job

        paths_raw = payload.get("paths") or []
        bundle_name = (payload.get("bundle_name") or "").strip()
        if len(paths_raw) < 2:
            raise HTTPException(400, "Au moins 2 items requis pour un bundle.")
        if not bundle_name:
            raise HTTPException(400, "Nom de bundle requis.")
        if " " in bundle_name:
            raise HTTPException(400, "Le nom de bundle ne doit pas contenir d'espaces.")
        # Sanity : pas de path traversal
        if "/" in bundle_name or "\\" in bundle_name or ".." in bundle_name:
            raise HTTPException(400, "Nom de bundle invalide (pas de séparateur, pas de '..').")
        # Resolution + verification des paths
        resolved: list[Path] = []
        for p in paths_raw:
            target = _safe_resolve_path(str(p))
            if not target.exists():
                raise HTTPException(400, f"Path inexistant : {target}")
            resolved.append(target)

        # Cree le dossier temp
        ts = int(time.time())
        bundle_root = data_dir() / "temp" / f"bundle_{ts}" / bundle_name
        try:
            bundle_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise HTTPException(409, "Bundle deja existant, retente.")
        except OSError as e:
            raise HTTPException(500, f"Impossible de creer le dossier bundle : {e}")

        # Pour chaque item : hardlink si fichier (rapide, zero copie),
        # ou un dossier-hardlink-recursif via copytree avec hardlinks (fallback)
        try:
            for src in resolved:
                dst = bundle_root / src.name
                if src.is_file():
                    try:
                        os.link(str(src), str(dst))
                    except OSError:
                        # Hardlink impossible (FS different, perm) : copie
                        shutil.copy2(str(src), str(dst))
                elif src.is_dir():
                    # copytree avec copy_function = os.link pour hardlink chaque fichier
                    def _link_or_copy(s, d):
                        try:
                            os.link(s, d)
                        except OSError:
                            shutil.copy2(s, d)
                    shutil.copytree(str(src), str(dst), copy_function=_link_or_copy)
                else:
                    raise HTTPException(400, f"Path ni fichier ni dossier : {src}")
        except HTTPException:
            shutil.rmtree(bundle_root.parent, ignore_errors=True)
            raise
        except Exception as e:
            shutil.rmtree(bundle_root.parent, ignore_errors=True)
            raise HTTPException(500, f"Erreur creation bundle : {e}")

        # Lance le job sur le dossier bundle
        # Sprint C.1 : propage le category_id_hint si present dans le payload.
        try:
            category_id_hint = int(payload.get("category_id_hint") or 0)
        except (TypeError, ValueError):
            category_id_hint = 0
        job = jobs_db.add_job(
            str(bundle_root),
            category_id_hint=category_id_hint,
        )
        submit_prepare_job(job.id)
        return {
            "ok": True,
            "job_id": job.id,
            "bundle_path": str(bundle_root),
            "items": len(resolved),
            "message": f"Bundle '{bundle_name}' cree avec {len(resolved)} items, preparation lancee.",
        }

    @app.get("/api/jobs")
    def api_jobs(status: str | None = None):
        from ..core import jobs_db
        statuses = [s.strip() for s in status.split(",")] if status else None
        # NOTES round 9 Bug-1 : limit eleve pour eviter la troncature a 100
        # quand l'user a une grande file de prep en cours.
        jobs = jobs_db.list_jobs(statuses=statuses, limit=10000)
        return {"jobs": [
            {
                "id": j.id, "file_path": j.file_path, "status": j.status,
                "force_fr": j.force_fr, "package_dir": j.package_dir,
                "release_name": j.release_name, "error": j.error,
                "created_at": j.created_at, "updated_at": j.updated_at,
            }
            for j in jobs
        ]}

    @app.delete("/api/jobs/{job_id}")
    def api_jobs_delete(job_id: int):
        from ..core import jobs_db
        if jobs_db.delete_job(job_id):
            return {"ok": True}
        raise HTTPException(404, f"Job {job_id} introuvable")

    # === Lot F.2 : controle de la file de preparation ===
    @app.post("/api/jobs/{job_id}/pause")
    def api_jobs_pause(job_id: int):
        """Marque un job comme pause (le scheduler le skip)."""
        from ..core import jobs_db
        if jobs_db.pause_job(job_id):
            return {"ok": True, "is_paused": True}
        raise HTTPException(
            404,
            f"Job {job_id} introuvable ou pas en status 'pending'",
        )

    @app.post("/api/jobs/{job_id}/resume")
    def api_jobs_resume(job_id: int):
        """Enleve le flag pause d'un job."""
        from ..core import jobs_db
        if jobs_db.resume_job(job_id):
            return {"ok": True, "is_paused": False}
        raise HTTPException(
            404,
            f"Job {job_id} introuvable ou pas en status 'pending'",
        )

    @app.post("/api/jobs/{job_id}/move")
    def api_jobs_move(job_id: int, payload: dict[str, Any]):
        """Reordonne un job. Body : {"direction": "up"|"down"|"top"|"bottom"}."""
        from ..core import jobs_db
        direction = (payload.get("direction") or "").strip().lower()
        if direction not in ("up", "down", "top", "bottom"):
            raise HTTPException(
                400,
                "direction doit etre 'up', 'down', 'top' ou 'bottom'",
            )
        if jobs_db.move_job(job_id, direction):
            return {"ok": True, "direction": direction}
        raise HTTPException(
            404,
            f"Job {job_id} introuvable, deja en position extreme, "
            "ou pas en status 'pending'",
        )

    @app.post("/api/jobs/flush")
    def api_jobs_flush():
        """Supprime tous les jobs `pending` (sauf `preparing`). Bouton
        "Vider la file" dans la UI Queue."""
        from ..core import jobs_db
        n = jobs_db.flush_pending_jobs()
        return {"ok": True, "deleted_count": n}

    @app.post("/api/jobs/{job_id}/cancel")
    def api_jobs_cancel(job_id: int):
        """Lot post-NOTES round 5 F1 : Cancel hard d'un job en cours de
        prepare. Kill le subprocess (TerminateProcess Windows / SIGKILL
        Linux) et cleanup le partial package_dir cree.

        Utilise quand l'utilisateur lance une grosse prepa (serie entiere,
        torrent 30+ min) et veut l'annuler immediatement sans attendre
        la fin de torf.generate().
        """
        from . import jobs_runner
        from ..core import jobs_db
        job = jobs_db.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job {job_id} introuvable")
        if job.status != "preparing":
            raise HTTPException(
                400,
                f"Job {job_id} pas en cours d'execution (status={job.status})",
            )
        killed = jobs_runner.request_job_cancel(job_id)
        if not killed:
            raise HTTPException(
                500,
                f"Job {job_id} marque 'preparing' en DB mais subprocess "
                "introuvable cote scheduler. Etat incoherent — relance "
                "manuellement.",
            )
        return {"ok": True, "killed": True}

    @app.get("/api/packages/{name}/torrent-files")
    def api_package_torrent_files(name: str):
        """NOTES round 7 : retourne la liste des fichiers contenus dans le
        .torrent du package (decode via torf). Permet a la UI d'afficher
        un tree view des fichiers/dossiers qui seront uploades.

        Reponse :
          {
            "root": "Release.Name",  # nom de la racine du torrent
            "is_multi": True,          # multi-fichiers (dossier englobant)
            "total_size": 1234567,
            "files": [
              {"path": "Release.Name/movie.mkv", "size": 1230000},
              {"path": "Release.Name/movie.nfo", "size": 7000},
            ],
          }

        Pour un torrent single-file (sans dossier englobant), "files"
        contient 1 seul item et is_multi=False.
        """
        from torf import Torrent
        from ..core.package_state import read_state
        from ..core.upload_orchestrator import resolve_torrent_path
        target = _resolve_package_dir(name)
        state_data = read_state(target)
        release_name = state_data.release_name if state_data else target.name
        # Meme resolution que l'upload : nom exact, sinon l'unique .torrent
        # du package. Le pipeline raccourcit le nom du fichier quand le
        # chemin complet approche Windows MAX_PATH
        # (pipeline._short_torrent_filename) ; exiger le nom exact affichait
        # ".torrent introuvable" sur un package pourtant uploadable (cas
        # reel 2026-11-15, chemin de 267 caracteres).
        torrent_path = resolve_torrent_path(target, release_name)
        if torrent_path is None:
            others = sorted(p.name for p in target.glob("*.torrent"))
            if len(others) > 1:
                raise HTTPException(
                    404,
                    "Plusieurs .torrent dans le package et aucun ne porte le "
                    f"nom attendu ({release_name}.torrent) : "
                    f"{', '.join(others)}. Garde uniquement le bon.",
                )
            raise HTTPException(
                404,
                f".torrent introuvable : {release_name}.torrent. "
                "Re-prepare le package pour le regenerer.",
            )
        try:
            t = Torrent.read(str(torrent_path))
        except Exception as e:
            raise HTTPException(500, f"Erreur de lecture du .torrent : {e}")
        files = []
        for f in t.files:
            # torf >= 4 expose File.path (PurePosixPath) et File.size
            try:
                p = str(f).replace("\\", "/")
            except Exception:
                p = str(f.path) if hasattr(f, "path") else str(f)
            try:
                sz = int(f.size)
            except Exception:
                sz = 0
            files.append({"path": p, "size": sz})
        # Root name : si single-file (1 fichier sans dossier englobant),
        # le torrent.name == le fichier. Sinon torrent.name est le dossier
        # racine.
        is_multi = len(files) > 1 or "/" in (files[0]["path"] if files else "")
        return {
            "root": str(t.name) if t.name else "",
            "is_multi": is_multi,
            "total_size": int(t.size or 0),
            "files": files,
        }

    @app.delete("/api/packages/{name}")
    def api_package_delete(name: str, payload: dict[str, Any]):
        """Supprime un package : rm -rf le dossier + clean les jobs lies.

        Body : {"confirm_name": "..."} doit matcher le nom du package, sinon 400.

        Sprint 8 hotfix v11 : on accepte maintenant la suppression d'un package
        UPLOADED (avant on bloquait avec HTTP 409). La confirmation tape-le-nom
        est suffisante comme garde-fou pour eviter les suppressions accidentelles.
        L'UI cote page detail affiche un warning specifique pour les uploaded
        ("recreer ce package creera un nouveau .torrent dont l'infohash ne
        matchera pas celui uploade").
        """
        import shutil
        from ..core import jobs_db

        target = _resolve_package_dir(name)
        confirm = (payload.get("confirm_name") or "").strip()
        if confirm != target.name:
            raise HTTPException(
                400,
                f"Confirmation invalide. Attendu : '{target.name}', recu : '{confirm}'",
            )
        # Cleanup jobs lies (le file_path source reste sur disque, on touche pas)
        source_job = jobs_db.find_job_for_package(str(target))
        if source_job:
            jobs_db.delete_job(source_job.id)
        # rm -rf
        try:
            shutil.rmtree(target)
        except OSError as e:
            raise HTTPException(500, f"Echec suppression : {e}")
        return {"ok": True, "deleted": target.name}

    @app.post("/api/packages/{name}/regenerate-presentation")
    def api_regenerate_presentation(name: str):
        """Sprint D.18 v0.5.0 — re-render la fiche BBCode du package livre
        avec les Options upload actuelles (notamment manual_cover_url).

        Use case : l'user a saisi une cover URL externe dans Options upload
        APRES la prepare initiale. Au lieu de relancer toute la prepare,
        ce endpoint regenere juste presentation.txt avec la nouvelle cover.

        Limite : reserve aux packages livre (profile == 'book').
        """
        from ..core.category_resolver import resolve_effective_category, category_profile
        from ..core.bbcode_book import render_book_bbcode, build_torrent_info
        from ..core.providers.book_metadata import book_from_dict
        from ..trackers import get_tracker
        import json as _json

        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(422, "Package sans state. Re-prepare d'abord.")

        eff_cat = resolve_effective_category(target)
        if category_profile(eff_cat) != "book":
            raise HTTPException(
                400,
                "Ce endpoint est reserve aux packages livre (cat 12). "
                "Pour les autres categories, edite la presentation manuellement.",
            )

        # Lire le book_metadata depuis le debug
        debug_path = target / "_debug" / "debug.json"
        book_meta_dict: dict[str, Any] = {}
        if debug_path.is_file():
            try:
                debug_data = _json.loads(debug_path.read_text(encoding="utf-8"))
                book_meta_dict = debug_data.get("book_metadata") or {}
            except (OSError, _json.JSONDecodeError):
                book_meta_dict = {}
        if not book_meta_dict:
            raise HTTPException(
                422,
                "Aucune metadonnee livre dans debug.json. Re-prepare le package "
                "pour extraire les metadonnees du fichier source.",
            )

        meta = book_from_dict(book_meta_dict)

        # torrent_info depuis le .torrent existant
        torrent_files = list(target.glob("*.torrent"))
        torrent_info = (
            build_torrent_info(torrent_files[0]) if torrent_files else {}
        )

        announce_url = config.get_required_env("TRACKER_ANNOUNCE")
        tracker = get_tracker(state_data.tracker_key or "gemini", announce_url)

        try:
            bbcode = render_book_bbcode(
                meta,
                state_data.release_name or name,
                tracker,
                torrent_info=torrent_info,
                manual_cover_url=state_data.manual_cover_url,
            )
        except Exception as e:
            raise HTTPException(500, f"Echec rendu BBCode : {e}")

        # Ecrit presentation.txt. Si presentation_user.txt existait (override
        # manuel), on le retire car la regen prime maintenant.
        presentation_path = target / "presentation.txt"
        presentation_path.write_text(bbcode, encoding="utf-8")
        user_path = target / "presentation_user.txt"
        if user_path.is_file():
            try:
                user_path.unlink()
            except OSError:
                pass

        cover_used = (
            state_data.manual_cover_url
            if state_data.manual_cover_url
            else (meta.cover_url if meta.cover_url.startswith("http") else "")
        )
        return {
            "ok": True,
            "message": (
                "Presentation BBCode regeneree avec la cover URL actuelle. "
                "Rafraichis la page pour la voir."
            ),
            "cover_used": cover_used,
            "cover_is_local": (
                bool(meta.cover_url)
                and not meta.cover_url.startswith("http")
                and not state_data.manual_cover_url
            ),
        }

    @app.post("/api/packages/bulk-reprepare")
    def api_packages_bulk_reprepare(payload: dict[str, Any]):
        """Sprint D.13 v0.5.0 — relance la pipeline sur TOUS les packages
        d'une categorie effective donnee.

        Use case : apres une evolution majeure de l'extracteur (ex: D.10
        qui a fixe l'extraction depuis dossier), on veut re-traiter les
        packages preexistants sans intervention manuelle un par un.

        Body :
            {
              "category_id": 12,         # categorie filtree (ex: 12=Livres)
              "include_uploaded": false, # si False, skip les packages
                                         #   deja uploades (defaut)
              "dry_run": false           # si True, retourne ce qui serait
                                         #   fait mais ne lance rien
            }
        """
        import shutil
        from ..core import jobs_db
        from ..core.category_resolver import resolve_effective_category
        from .jobs_runner import submit_prepare_job

        try:
            target_cat = int(payload.get("category_id") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "category_id doit etre un entier (ex: 12)")
        if target_cat <= 0:
            raise HTTPException(
                400,
                "category_id requis. Ex: 12 pour Livres, 1 pour Films.",
            )
        include_uploaded = bool(payload.get("include_uploaded", False))
        dry_run = bool(payload.get("dry_run", False))

        packages_root = config.packages_dir()
        if not packages_root.is_dir():
            return {
                "ok": True, "scanned": 0, "matching": 0,
                "skipped_uploaded": 0, "skipped_no_source": 0,
                "relaunched": [], "skipped_other": [],
                "dry_run": dry_run,
                "message": "Aucun package present.",
            }

        scanned = 0
        matching = 0
        skipped_uploaded = 0
        skipped_no_source = 0
        relaunched: list[dict] = []
        skipped_other: list[dict] = []

        for pkg_dir in sorted(packages_root.iterdir()):
            if not pkg_dir.is_dir():
                continue
            scanned += 1
            try:
                eff_cat = resolve_effective_category(pkg_dir)
            except Exception:
                skipped_other.append({
                    "name": pkg_dir.name,
                    "reason": "resolve_effective_category a echoue",
                })
                continue
            if eff_cat != target_cat:
                continue
            matching += 1

            state_data = read_state(pkg_dir)
            if (
                state_data is not None
                and state_data.state == PackageState.UPLOADED
                and not include_uploaded
            ):
                skipped_uploaded += 1
                continue

            source_job = jobs_db.find_job_for_package(str(pkg_dir))
            if not source_job:
                skipped_no_source += 1
                skipped_other.append({
                    "name": pkg_dir.name,
                    "reason": "Pas de job source (package legacy)",
                })
                continue
            if not Path(source_job.file_path).exists():
                skipped_no_source += 1
                skipped_other.append({
                    "name": pkg_dir.name,
                    "reason": f"Fichier source absent : {source_job.file_path}",
                })
                continue

            if dry_run:
                relaunched.append({
                    "name": pkg_dir.name,
                    "job_id": None,
                    "source": source_job.file_path,
                })
                continue

            # Supprime l'ancien package + le job, recree un job avec les
            # MEMES overrides existants (preserve les choix user).
            try:
                jobs_db.delete_job(source_job.id)
                shutil.rmtree(pkg_dir)
            except OSError as e:
                skipped_other.append({
                    "name": pkg_dir.name,
                    "reason": f"rmtree echec : {e}",
                })
                continue

            new_job = jobs_db.add_job(
                source_job.file_path,
                force_fr=source_job.force_fr,
                append_fr_title=source_job.append_fr_title,
                tmdb_id_override=source_job.tmdb_id_override,
                manual_release_name=source_job.manual_release_name,
                category_id_hint=source_job.category_id_hint or target_cat,
                manual_isbn=source_job.manual_isbn,
                manual_author=source_job.manual_author,
                manual_book_title=source_job.manual_book_title,
                manual_book_year=source_job.manual_book_year,
                manual_google_books_url=source_job.manual_google_books_url,
                manual_source=source_job.manual_source,
            )
            submit_prepare_job(new_job.id)
            relaunched.append({"name": pkg_dir.name, "job_id": new_job.id})

        return {
            "ok": True,
            "scanned": scanned,
            "matching": matching,
            "skipped_uploaded": skipped_uploaded,
            "skipped_no_source": skipped_no_source,
            "relaunched": relaunched,
            "skipped_other": skipped_other,
            "dry_run": dry_run,
            "message": (
                f"{'Dry-run : ' if dry_run else ''}"
                f"{len(relaunched)} package(s) {'seraient ' if dry_run else ''}"
                f"relance(s) sur {matching} matching la cat {target_cat}."
            ),
        }

    @app.post("/api/packages/{name}/reprepare")
    def api_package_reprepare(name: str, payload: dict[str, Any]):
        """Cree un nouveau job de prepare avec des overrides, en supprimant
        l'ancien package + le job lie pour eviter les doublons dans la queue.

        Body : {"force_fr": "" | "VFF" | "VOF" | ...}
        """
        import shutil
        from ..core import jobs_db
        from .jobs_runner import submit_prepare_job

        target = _resolve_package_dir(name)
        source_job = jobs_db.find_job_for_package(str(target))
        if not source_job:
            raise HTTPException(
                422,
                "Package legacy : pas de fichier source connu. "
                "Re-prepare impossible. Re-ajoute le fichier depuis l'inbox.",
            )
        if not Path(source_job.file_path).exists():
            raise HTTPException(422, f"Fichier source absent : {source_job.file_path}")
        # Protection : on ne touche pas a un package deja uploade
        state_data = read_state(target)
        if state_data is not None and state_data.state == PackageState.UPLOADED:
            raise HTTPException(
                409,
                "Package deja uploade : re-prepare refuse.",
            )
        force_fr = (payload.get("force_fr") or "").strip().upper()
        append_fr_title = bool(payload.get("append_fr_title"))
        try:
            tmdb_id_override = int(payload.get("manual_tmdb_id") or 0)
        except (TypeError, ValueError):
            tmdb_id_override = 0
        manual_release_name = (payload.get("manual_release_name") or "").strip()
        # Sprint C.3 v0.5.0 : si l'user a clique "Changer de categorie" sur la
        # page detail, on recoit category_id_hint. Le pipeline le persistera
        # dans state.manual_category_id via la logique C.1bis (override sticky).
        try:
            category_id_hint = int(payload.get("category_id_hint") or 0)
        except (TypeError, ValueError):
            category_id_hint = 0
        # Sprint D.9 v0.5.0 : overrides livre (ISBN/auteur/titre).
        # Sprint D.11 v0.5.0 : annee de publication forcee.
        manual_isbn = (payload.get("manual_isbn") or "").strip()
        manual_author = (payload.get("manual_author") or "").strip()
        manual_book_title = (payload.get("manual_book_title") or "").strip()
        try:
            manual_book_year = int(payload.get("manual_book_year") or 0)
        except (TypeError, ValueError):
            manual_book_year = 0
        # Sprint D.40 v0.5.0 : URL Google Books forcee.
        manual_google_books_url = (payload.get("manual_google_books_url") or "").strip()
        # Sprint D.48 v0.5.0 : source forcee (BluRay/WEB-DL/...).
        manual_source = (payload.get("manual_source") or "").strip()
        # Supprime l'ancien package + l'ancien job pour laisser place au nouveau.
        jobs_db.delete_job(source_job.id)
        try:
            shutil.rmtree(target)
        except OSError as e:
            print(f"[WARN] reprepare : rmtree {target} echoue : {e}")
        new_job = jobs_db.add_job(
            source_job.file_path,
            force_fr=force_fr,
            append_fr_title=append_fr_title,
            tmdb_id_override=tmdb_id_override,
            manual_release_name=manual_release_name,
            category_id_hint=category_id_hint,
            manual_isbn=manual_isbn,
            manual_author=manual_author,
            manual_book_title=manual_book_title,
            manual_book_year=manual_book_year,
            manual_google_books_url=manual_google_books_url,
            manual_source=manual_source,
        )
        submit_prepare_job(new_job.id)
        return {
            "ok": True,
            "job_id": new_job.id,
            "message": "Re-prepare lance. Ancien package supprime.",
        }

    @app.post("/api/packages/{name}/validate")
    def api_package_validate(name: str):
        """NOTES round 7+ : transitionne un package PREPARED vers VALIDATED
        sans uploader. Workflow batch :
        1. User fait le tour de ses packages "prepared"
        2. Click "Valider sans uploader" sur ceux qu'il veut envoyer
        3. Va sur /queue, filtre par etat "Valide", coche tout, click
           "Uploader la selection" -> batch upload.

        Refuse si state != prepared.
        """
        from ..core.package_state import transition

        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(422, "Package sans state. Re-prepare d'abord.")
        if state_data.state != PackageState.PREPARED:
            raise HTTPException(
                409,
                f"Validation impossible : le package est en etat '{state_data.state.value}'. "
                "Seuls les packages 'prepared' peuvent etre valides manuellement.",
            )
        try:
            transition(
                target, PackageState.VALIDATED,
                note="validation manuelle (sans upload)",
            )
        except Exception as e:
            raise HTTPException(500, f"Echec transition : {e}")
        return {
            "ok": True,
            "new_state": PackageState.VALIDATED.value,
            "message": "Package validé. Tu peux le batch-uploader depuis la Queue.",
        }

    @app.post("/api/packages/{name}/unvalidate")
    def api_package_unvalidate(name: str):
        """NOTES round 7+ : annule une validation manuelle. Transition
        VALIDATED -> PREPARED. Permet au user de toggle le bouton
        "Valider" (cliquer une 2e fois pour annuler avant l'upload).

        Refuse si state != validated.
        """
        from ..core.package_state import transition

        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(422, "Package sans state. Re-prepare d'abord.")
        if state_data.state != PackageState.VALIDATED:
            raise HTTPException(
                409,
                f"Devalidation impossible : le package est en etat '{state_data.state.value}'. "
                "Seuls les packages 'validated' peuvent etre devalides.",
            )
        try:
            transition(
                target, PackageState.PREPARED,
                note="devalidation manuelle (toggle UI)",
            )
        except Exception as e:
            raise HTTPException(500, f"Echec transition : {e}")
        return {
            "ok": True,
            "new_state": PackageState.PREPARED.value,
            "message": "Package dévalidé. Il revient en 'Préparé'.",
        }

    @app.post("/api/packages/{name}/dedup-check")
    def api_package_dedup_check(name: str):
        """NOTES round 8 P5.7 : re-execute un check_duplicate cote tracker pour
        ce package et persiste le resultat dans package_state (existing_torrent_id,
        existing_torrent_url, dedup_confidence, dedup_checked_at).

        Utile quand :
        - L'user a recu une erreur "doublon" mais pense que c'est resolu sur le
          tracker (admin a delete le doublon)
        - Le package a ete prepare il y a longtemps et l'user veut un check frais
        - L'user a force_upload et veut revalider l'absence de doublon

        Requiert TRACKER_API_URL + TRACKER_API_KEY. Skip silencieux sinon (200 + warning).
        Si confidence=CERTAIN, transitionne automatiquement vers ABORTED_DUPLICATE
        (meme logique que _try_dedup_check pendant la preparation initiale).
        """
        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(422, "Package sans state. Re-prepare d'abord.")
        # Pas de check sur les packages deja UPLOADED — on a deja l'ID sur le tracker.
        if state_data.state == PackageState.UPLOADED:
            raise HTTPException(
                409,
                "Package deja uploade. Pas de re-check de doublon pertinent.",
            )

        # Reuse _try_dedup_check : il gere TRACKER_API_URL absent, transitions,
        # CERTAIN -> ABORTED_DUPLICATE, et persist les infos.
        from .jobs_runner import _try_dedup_check
        try:
            _try_dedup_check(target)
        except Exception as e:
            raise HTTPException(500, f"Echec du dedup check : {e}")

        # Re-lit l'etat apres la verification pour renvoyer le resultat actuel.
        new_state = read_state(target)
        if new_state is None:
            raise HTTPException(500, "State perdu apres dedup check (anormal).")
        return {
            "ok": True,
            "new_state": new_state.state.value,
            "existing_torrent_id": new_state.existing_torrent_id,
            "existing_torrent_url": new_state.existing_torrent_url or "",
            "dedup_confidence": getattr(new_state, "dedup_confidence", "") or "",
            "dedup_checked_at": getattr(new_state, "dedup_checked_at", "") or "",
        }

    @app.post("/api/packages/{name}/rescore")
    def api_package_rescore(name: str):
        """NOTES round 8 P5.8 : re-execute le compliance check + recalcule le
        score sans toucher au .torrent ni au state machine.

        Use case : un package a ete upload il y a longtemps avec un score 50
        (par ex. cause par un bug "PGS bloquant" depuis fixe). Le user veut
        rafraichir le score affiche sans :
        - regenerer le .torrent (changerait l'infohash, casserait le seed)
        - re-uploader sur le tracker

        Le re-score lit `_debug/debug.json` (mediainfo_data, release_name,
        tmdb_context — tout est cache), re-execute check_compliance() avec
        les regles actuelles, ecrit le nouveau compliance_issues, et invalide
        le cache de score. Le prochain rendu page recalcule automatiquement.

        Accepte TOUS les etats (y compris UPLOADED — c'est le cas d'usage
        principal). Le seul prerequis est que debug.json existe et contienne
        mediainfo_data + release_name.

        Si le package n'a pas de debug.json (legacy / supprime), retourne 422.
        """
        from ..core.rescore import rescore_package

        target = _resolve_package_dir(name)
        try:
            result = rescore_package(target)
        except FileNotFoundError as e:
            raise HTTPException(422, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, f"Echec rescore : {e}")

        return {
            "ok": True,
            "old_score": result.old_score,
            "new_score": result.new_score,
            "old_bucket": result.old_bucket,
            "new_bucket": result.new_bucket,
            "changed": result.changed,
            "removed_issues_count": len(result.removed_issues),
            "added_issues_count": len(result.added_issues),
            "removed_issues": result.removed_issues[:5],   # cap pour le toast
            "added_issues": result.added_issues[:5],
            "new_issues_count": len(result.new_issues),
        }

    @app.post("/api/packages/{name}/upload")
    def api_package_upload(name: str, payload: dict[str, Any]):
        """Lance un upload (dry-run ou reel) pour un package en background.

        Body : {
            "dry_run": bool,
            "force_upload": bool,           # bypass dedup CERTAIN
            "force_existing_id": int|null,  # ID requis si force_upload
        }
        Le worker lit personal_release/anonymous depuis package_state (poses
        via /api/packages/{name}/options). Retourne immediatement avec un
        status "queued" ; le client polle /api/packages/{name}/upload-status.
        """
        from .jobs_runner import submit_upload_job
        from ..core.upload_orchestrator import (
            get_blocking_compliance_messages,
            resolve_torrent_path,
        )

        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(422, "Package sans state. Re-prepare d'abord.")
        if state_data.state == PackageState.UPLOADED:
            raise HTTPException(409, "Package deja uploade.")
        dry_run = bool(payload.get("dry_run", False))
        force_upload = bool(payload.get("force_upload", False))
        force_existing_id = payload.get("force_existing_id")
        if force_existing_id is not None:
            try:
                force_existing_id = int(force_existing_id)
            except (TypeError, ValueError):
                raise HTTPException(400, "force_existing_id doit etre un entier")
        if state_data.state == PackageState.ABORTED_DUPLICATE and not force_upload:
            raise HTTPException(
                409,
                "Package marque comme doublon. Active force_upload + fournis force_existing_id.",
            )
        # R1 (audit AUDIT_2026-07-19) : garde-fou compliance a l'upload. On
        # refuse en 409 tout package dont la conformite est BLOQUANTE (team
        # bannie, encode EXTREME, MP3, etc.), meme si son state a ete reanime.
        blocking_msgs = get_blocking_compliance_messages(target)
        if blocking_msgs and not force_upload:
            raise HTTPException(
                409,
                {
                    "error": "compliance_blocking",
                    "package": target.name,
                    "messages": blocking_msgs,
                    "message": (
                        "Upload refuse : ce package viole une regle dure de la "
                        "charte Gemini (" + " ; ".join(blocking_msgs) + "). "
                        "Corrige le fichier/nom et re-prepare avant d'uploader."
                    ),
                },
            )
        # Precondition critique : le .torrent doit exister sur disque. Le
        # pre-check anticipe peut avoir skip create_torrent quand un doublon
        # CERTAIN a ete detecte ; tant qu'on n'a pas re-prepare, l'upload
        # va planter. On retourne 409 explicite avec un message qui pointe
        # vers la solution (re-preparer).
        #
        # R1 : on utilise resolve_torrent_path (fallback D.46 pour les noms
        # raccourcis Windows MAX_PATH) au lieu du nom exact — sinon 52 packages
        # du corpus au .torrent raccourci se voyaient refuser l'upload avec un
        # message accusant a tort un "doublon CERTAIN".
        torrent_file = resolve_torrent_path(target, state_data.release_name)
        if torrent_file is None:
            existing = (
                f" (torrent existant ID {state_data.existing_torrent_id})"
                if state_data.existing_torrent_id else ""
            )
            raise HTTPException(
                409,
                {
                    "error": "torrent_missing",
                    "package": target.name,
                    "state": state_data.state.value,
                    "existing_torrent_id": state_data.existing_torrent_id,
                    "message": (
                        f"Aucun .torrent exploitable dans le package{existing}. "
                        f"Soit le pre-check a saute create_torrent (doublon "
                        f"CERTAIN detecte), soit plusieurs .torrent coexistent. "
                        f"Re-prepare le package (bouton 'Re-preparer' sur la "
                        f"page detail) pour regenerer un .torrent unique, puis "
                        f"re-tente l'upload."
                    ),
                },
            )
        anonymous = bool(state_data.anonymous)
        submit_upload_job(
            target,
            dry_run=dry_run,
            force_upload=force_upload,
            force_existing_id=force_existing_id,
            anonymous=anonymous,
        )
        return {
            "ok": True,
            "package": target.name,
            "dry_run": dry_run,
            "message": (
                "Upload simule lance en arriere-plan." if dry_run
                else "Upload reel lance en arriere-plan."
            ),
        }

    @app.get("/api/jobs/{job_id}/stream")
    def api_job_stream(job_id: int):
        """SSE : stream live du log d'un job de prepare."""
        from ..core import jobs_db

        job = jobs_db.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job {job_id} introuvable")
        log_path = Path(job.log_path) if job.log_path else None
        if not log_path:
            raise HTTPException(404, "Pas de log_path sur ce job")

        def _is_done():
            j = jobs_db.get_job(job_id)
            return j is None or j.status in ("done", "failed")

        return StreamingResponse(
            _sse_tail_log(log_path, _is_done),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/uploads/{name}/log")
    def api_upload_log(name: str):
        """Retourne le contenu COMPLET du log d'upload d'un package.

        Sprint 8 hotfix v14 : permet a l'user de consulter le log apres
        coup (pas seulement pendant l'upload live via SSE).

        Sprint D.46 v0.5.0 (feedback Louis upload echec sans log) :
        fallback sur la recherche par md5 deterministe si le status
        n'est pas en memoire. Le serveur perd `_upload_status` entre les
        redemarrages mais les fichiers log persistent sur disque dans
        `data/jobs/upload_<md5>.log` (cf. _run_upload_job). On reconstruit
        donc le path depuis le package_dir, et on lit le fichier s'il existe.
        Permet de consulter les logs d'echec meme apres restart serveur.
        """
        from .jobs_runner import get_upload_status
        from ..core import jobs_db
        import hashlib

        target = _resolve_package_dir(name)
        status = get_upload_status(str(target))

        log_path: Path | None = None
        if status is not None and status.get("log_path"):
            log_path = Path(status["log_path"])

        # Sprint D.46 : fallback md5 (deterministe depuis package_dir)
        if log_path is None or not log_path.exists():
            digest = hashlib.md5(str(target).encode("utf-8")).hexdigest()[:12]
            candidate = jobs_db.jobs_log_dir() / f"upload_{digest}.log"
            if candidate.is_file():
                log_path = candidate

        if log_path is None or not log_path.exists():
            raise HTTPException(
                404,
                "Aucun log d'upload pour ce package (jamais uploade, ou "
                "fichier log supprime).",
            )
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise HTTPException(500, f"Echec lecture log : {e}")
        return {"content": content, "path": str(log_path), "size": len(content)}

    @app.get("/api/uploads/{name}/stream")
    def api_upload_stream(name: str):
        """SSE : stream live du log d'un upload."""
        from .jobs_runner import get_upload_status

        target = _resolve_package_dir(name)
        status = get_upload_status(str(target))
        if status is None:
            raise HTTPException(404, "Aucun upload pour ce package")
        log_path = Path(status.get("log_path") or "")
        if not log_path or not str(log_path):
            raise HTTPException(404, "Pas de log_path sur cet upload")

        def _is_done():
            s = get_upload_status(str(target))
            return s is None or s.get("status") in ("done", "failed")

        return StreamingResponse(
            _sse_tail_log(log_path, _is_done),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/diag/packages")
    def api_diag_packages():
        """Diagnostic : liste BRUTE de ce qu'on trouve dans data/upload_packages.

        Utile quand la queue n'affiche pas tout : on peut voir la difference
        entre ce qui est sur disque et ce qui est rendu par _list_packages.
        """
        pkgs_dir = config.packages_dir()
        on_disk: list[dict] = []
        if pkgs_dir.is_dir():
            for d in sorted(pkgs_dir.iterdir(), key=lambda p: p.name.lower()):
                if not d.is_dir():
                    continue
                state_file = d / "package_state.json"
                size = state_file.stat().st_size if state_file.is_file() else 0
                state_data = read_state(d)
                on_disk.append({
                    "name": d.name,
                    "has_state_file": state_file.is_file(),
                    "state_file_size": size,
                    "read_ok": state_data is not None,
                    "state": state_data.state.value if state_data else None,
                })
        listed = _list_packages()
        return {
            "data_dir": str(config.data_dir()),
            "packages_dir": str(pkgs_dir),
            "on_disk_count": len(on_disk),
            "listed_count": len(listed),
            "on_disk": on_disk,
            "listed_names": [p.package_name for p in listed],
        }

    @app.get("/api/command-palette")
    def api_command_palette():
        """Lot post-refonte Sprint 3 : liste les packages pour le Cmd+K
        (navigation rapide). Top 50 par mise a jour decroissante.

        Reponse :
          {"packages": [
             {"name": "release_X", "release_name": "Release.X.foo",
              "state": "prepared", "score": 95},
             ...
          ]}
        """
        packages = _list_packages()
        # Tri par updated_at desc, top 50. Si pas d'updated_at, on garde
        # l'ordre naturel (filesystem).
        try:
            packages = sorted(packages, key=lambda p: p.updated_at or "", reverse=True)
        except Exception:
            pass
        return {
            "packages": [
                {
                    "name": p.package_name,
                    "release_name": p.release_name,
                    "state": p.state,
                    "score": p.confidence_score,
                }
                for p in packages[:50]
            ]
        }

    @app.get("/api/queue/snapshot")
    def api_queue_snapshot():
        """Retourne une signature courte de l'etat de la queue.

        Le client polle cet endpoint au lieu de reload toute la page : reload
        UNIQUEMENT si la signature change (= au moins un job/upload a change).
        Plus rapide qu'un reload de page complete, et evite le glitch visuel.
        """
        import hashlib
        from ..core import jobs_db
        from .jobs_runner import list_upload_statuses
        parts: list[str] = []
        # Jobs : id + status + updated_at
        # NOTES round 9 Bug-1 : meme correctif que page_queue, limit eleve
        # pour ne pas tronquer la signature quand user a > 200 jobs.
        for j in jobs_db.list_jobs(limit=10000):
            parts.append(f"j{j.id}:{j.status}:{j.updated_at}")
        # Uploads : package + status + updated_at
        for u in list_upload_statuses(include_done=True):
            parts.append(f"u{u.get('package_name','')}:{u.get('status','')}:{u.get('updated_at','')}")
        # Packages : name + state + updated_at
        for pkg in _list_packages():
            parts.append(f"p{pkg.package_name}:{pkg.state}:{pkg.updated_at}")
        sig = hashlib.md5("\n".join(parts).encode()).hexdigest()[:16]
        # Indique aussi s'il y a quelque chose en cours (pour decider si on continue a poller)
        has_active = any(
            j.status in ("pending", "preparing")
            for j in jobs_db.list_jobs(statuses=["pending", "preparing"])
        ) or any(
            u.get("status") in ("queued", "uploading")
            for u in list_upload_statuses(include_done=True)
        )
        return {"sig": sig, "has_active": has_active}

    @app.get("/api/uploads")
    def api_uploads_list():
        """Retourne tous les uploads connus (en cours + termines recents)."""
        from .jobs_runner import list_upload_statuses
        return {"uploads": list_upload_statuses(include_done=True)}

    @app.delete("/api/uploads/{name}")
    def api_uploads_clear(name: str):
        """Efface l'entree d'upload pour un package (utile pour cacher
        les uploads termines de la liste)."""
        from .jobs_runner import clear_upload_status
        target = _resolve_package_dir(name)
        if clear_upload_status(str(target)):
            return {"ok": True}
        raise HTTPException(404, "Aucune entree d'upload pour ce package")

    @app.get("/api/packages/{name}/upload-status")
    def api_package_upload_status(name: str):
        """Retourne l'etat courant d'un upload pour polling depuis l'UI."""
        from .jobs_runner import get_upload_status

        target = _resolve_package_dir(name)
        status = get_upload_status(str(target))
        if status is None:
            return {"status": "idle"}
        # On enrichit avec le state on-disk au cas ou le worker a fini et
        # transite -> uploaded.
        state_data = read_state(target)
        if state_data:
            status = {**status, "state": state_data.state.value}
        return status

    @app.post("/api/queue/upload-batch")
    def api_queue_upload_batch(payload: dict[str, Any]):
        """Lance des uploads en serie pour une liste de packages (selection queue).

        Body : {
            "package_names": [...],
            "dry_run": bool,
        }
        L'executor est single-thread donc les uploads s'enchainent.
        """
        from .jobs_runner import submit_upload_job

        names = payload.get("package_names") or []
        dry_run = bool(payload.get("dry_run", False))
        if not names:
            raise HTTPException(400, "Aucun package fourni.")
        accepted: list[str] = []
        skipped: list[dict[str, str]] = []
        for n in names:
            try:
                target = _resolve_package_dir(n)
            except HTTPException as e:
                skipped.append({"name": n, "reason": str(e.detail)})
                continue
            state_data = read_state(target)
            if state_data is None or state_data.state in (
                PackageState.UPLOADED, PackageState.ABORTED_DUPLICATE,
            ):
                skipped.append({
                    "name": n,
                    "reason": f"state={state_data.state.value if state_data else 'no-state'}",
                })
                continue
            submit_upload_job(target, dry_run=dry_run, anonymous=bool(state_data.anonymous))
            accepted.append(n)
        return {
            "ok": True,
            "accepted": accepted,
            "skipped": skipped,
            "dry_run": dry_run,
        }

    @app.post("/api/packages/{name}/presentation")
    def api_package_presentation_save(name: str, payload: dict[str, Any]):
        """F4 : persiste la version editee par l'user de la presentation BBCode.

        Body : {"text": "..."}. Ecrit `presentation_user.txt` a cote de
        `presentation.txt` (regenere). Au prochain upload, c'est cette
        version qui sera utilisee. Reset via DELETE pour supprimer le
        user-edit et revenir a la regen automatique.
        """
        target = _resolve_package_dir(name)
        text = payload.get("text")
        if text is None or not isinstance(text, str):
            raise HTTPException(400, "Body doit contenir un champ 'text' (string)")
        try:
            (target / "presentation_user.txt").write_text(text, encoding="utf-8")
        except OSError as e:
            raise HTTPException(500, f"Echec ecriture : {e}")
        return {"ok": True, "size": len(text), "overridden": True}

    def _open_folder_in_explorer(target: Path) -> None:
        """Helper : ouvre `target` dans l'explorateur OS du serveur.

        os.startfile sur Windows (Explorer), `open` sur macOS, `xdg-open`
        sur Linux. Leve HTTPException si le path n'existe pas ou si l'OS
        refuse l'ouverture."""
        import os as _os
        if not target.exists():
            raise HTTPException(404, f"Dossier introuvable : {target}")
        try:
            if _os.name == "nt":
                _os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(target)])
            else:  # Linux / autre
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except (OSError, FileNotFoundError) as e:
            raise HTTPException(500, f"Impossible d'ouvrir : {e}")

    @app.post("/api/packages/{name}/open-folder")
    def api_package_open_folder(name: str):
        """UI4 : ouvre le dossier package dans l'explorateur OS du serveur.

        `window.open('file:///...')` cote browser est bloque par Chrome /
        Edge / Firefox pour des raisons de securite. Comme la web UI tourne
        sur la meme machine que le user, on contourne via os.startfile.
        Action serveur — accepte uniquement en local (la UI etant a 127.0.0.1
        par defaut, le risque est nul ; si l'user passe --insecure-host,
        c'est sa responsabilite)."""
        target = _resolve_package_dir(name)
        _open_folder_in_explorer(target)
        return {"ok": True, "path": str(target)}

    @app.post("/api/packages/{name}/open-torrent-folder")
    def api_package_open_torrent_folder(name: str):
        """Ouvre le dossier qui CONTIENT le .torrent final uploadé.

        Priorite :
        1. `TORRENT_FINAL_DIR` env var si configure (watch folder qBittorrent /
           Transmission ou l'user a copie le .torrent pour le seed).
        2. Parent de `state.final_torrent_path` (le .torrent dans le package_dir).

        Si aucun des deux n'est dispo (package non uploaded, ou state corrompu),
        retourne 404 avec un message explicite."""
        target = _resolve_package_dir(name)
        # Priorite 1 : TORRENT_FINAL_DIR (le watch folder configure)
        final_dir = (os.environ.get("TORRENT_FINAL_DIR") or "").strip()
        if final_dir:
            candidate = Path(final_dir)
            if candidate.is_dir():
                _open_folder_in_explorer(candidate)
                return {"ok": True, "path": str(candidate), "source": "TORRENT_FINAL_DIR"}
        # Priorite 2 : parent du .torrent final stocke dans le package_dir
        state_data = read_state(target)
        if state_data and state_data.final_torrent_path:
            torrent_path = Path(state_data.final_torrent_path)
            if torrent_path.exists():
                _open_folder_in_explorer(torrent_path.parent)
                return {"ok": True, "path": str(torrent_path.parent), "source": "package_state"}
        raise HTTPException(
            404,
            "Aucun .torrent final n'est connu pour ce package. "
            "Soit l'upload n'a pas eu lieu, soit TORRENT_FINAL_DIR n'est pas configuré "
            "et le state ne contient pas final_torrent_path.",
        )

    @app.post("/api/packages/{name}/open-source-folder")
    def api_package_open_source_folder(name: str):
        """Sprint 8 hotfix v11 : ouvre le dossier qui CONTIENT le fichier
        source du package (le .mkv qu'on a uploade). Utile sur la page detail
        d'un package uploade pour aller retrouver le fichier original
        (changer de seedbox, re-encoder, etc.).

        Lit le `source_file_path` depuis le state du package, ouvre son parent."""
        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None or not state_data.source_file_path:
            raise HTTPException(404, "Pas de fichier source connu pour ce package")
        source = Path(state_data.source_file_path)
        if not source.exists():
            raise HTTPException(
                404,
                f"Le fichier source n'existe plus à l'emplacement enregistré : {source}",
            )
        _open_folder_in_explorer(source.parent)
        return {"ok": True, "path": str(source.parent)}

    @app.delete("/api/packages/{name}/presentation")
    def api_package_presentation_reset(name: str):
        """F4 : supprime le user-edit, revient a la version regeneree."""
        target = _resolve_package_dir(name)
        user_file = target / "presentation_user.txt"
        if user_file.is_file():
            try:
                user_file.unlink()
            except OSError as e:
                raise HTTPException(500, f"Echec suppression : {e}")
        return {"ok": True, "overridden": False}

    @app.post("/api/packages/{name}/options")
    def api_package_options(name: str, payload: dict[str, Any]):
        """Met a jour les options upload du package : personal_release, anonymous,
        manual_tmdb_id. Sauvegarde dans package_state.json sans changer l'etat.
        """
        target = _resolve_package_dir(name)
        state_data = read_state(target)
        if state_data is None:
            raise HTTPException(
                422,
                "Package sans state : ne peut pas stocker d'options. "
                "Re-prepare le package d'abord.",
            )
        updates: dict[str, Any] = {}
        if "personal_release" in payload:
            updates["personal_release"] = bool(payload["personal_release"])
        if "anonymous" in payload:
            updates["anonymous"] = bool(payload["anonymous"])
        if "manual_tmdb_id" in payload:
            try:
                updates["manual_tmdb_id"] = int(payload["manual_tmdb_id"] or 0)
            except (TypeError, ValueError):
                raise HTTPException(400, "manual_tmdb_id doit etre un entier")
        # F3 : overrides Unit3D category/type/resolution (0 = auto)
        for key in ("manual_category_id", "manual_type_id", "manual_resolution_id"):
            if key in payload:
                try:
                    updates[key] = int(payload[key] or 0)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{key} doit etre un entier")
        # Lot Q : overrides champs upload supplementaires (formulaire Gemini)
        # Champs entiers (IDs, numeros saison/episode, distributeur, region)
        for key in (
            "manual_tvdb_id", "manual_mal_id",
            "manual_season_number", "manual_episode_number",
            "manual_distributor_id", "manual_region_id",
        ):
            if key in payload:
                try:
                    updates[key] = int(payload[key] or 0)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{key} doit etre un entier")
        # Champs string (IMDB ID, mots-cles)
        if "manual_imdb_id" in payload:
            v = str(payload["manual_imdb_id"] or "").strip()
            # Validation souple : accepte 'tt1234567' OU juste '1234567'
            # (la UI affiche sans le 'tt' depuis round 4, l'user peut taper
            # les 2). On normalise en ajoutant 'tt' si manquant.
            if v:
                if re.match(r"^\d+$", v):
                    v = "tt" + v
                elif not re.match(r"^tt\d+$", v):
                    raise HTTPException(
                        400,
                        "manual_imdb_id doit etre un nombre IMDb (ex: 0405159 ou tt0405159) ou vide.",
                    )
            updates["manual_imdb_id"] = v
        if "manual_keywords" in payload:
            updates["manual_keywords"] = str(payload["manual_keywords"] or "").strip()
        # Sprint D.12 v0.5.0 - Options upload livre.
        if "manual_cover_url" in payload:
            cover = str(payload["manual_cover_url"] or "").strip()
            # Validation legere : http(s) ou vide
            if cover and not cover.startswith(("http://", "https://")):
                raise HTTPException(
                    400,
                    "manual_cover_url doit etre une URL http(s) ou vide.",
                )
            updates["manual_cover_url"] = cover
        if "manual_book_subtype" in payload:
            subtype = str(payload["manual_book_subtype"] or "").strip().lower()
            allowed_subtypes = {
                "", "roman", "bd", "manga", "comics", "audiobook",
                "essai", "manuel",
            }
            if subtype not in allowed_subtypes:
                raise HTTPException(
                    400,
                    f"manual_book_subtype invalide. Valeurs autorisees : "
                    f"{', '.join(sorted(allowed_subtypes - {''}))}.",
                )
            updates["manual_book_subtype"] = subtype
        # Sprint D.40 v0.5.0 (feedback Louis) - Banner URL livre.
        if "manual_banner_url" in payload:
            banner = str(payload["manual_banner_url"] or "").strip()
            if banner and not banner.startswith(("http://", "https://")):
                raise HTTPException(
                    400,
                    "manual_banner_url doit etre une URL http(s) ou vide.",
                )
            updates["manual_banner_url"] = banner
        if not updates:
            return {"ok": True, "message": "Rien a mettre a jour."}
        try:
            transition(target, state_data.state, note="options update via UI", **updates)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"ok": True, "updated": list(updates.keys())}

    @app.on_event("shutdown")
    def _shutdown():
        from .jobs_runner import shutdown_executor
        shutdown_executor(wait=False)

    return app
