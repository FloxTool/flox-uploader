"""Orchestration de la boucle upload.

Compose `gemini_api` (le client) + `package_state` (la machine d'etat) +
les fichiers du package sur disque pour executer la sequence :

    1. Lire le package depuis le dossier (release_name, presentation, mediainfo,
       taille du torrent, TMDB/IMDB depuis debug.json).
    2. Verifier la duplication cote tracker (cascade TMDB ID -> taille).
    3. Selon la confiance du doublon :
         CERTAIN     -> abort silencieux par defaut (overridable par --force-upload)
         VERY_LIKELY -> prompt CLI (C)ontinue/(S)kip/(Q)uit
         AMBIGUOUS   -> prompt CLI avec contexte
         NONE        -> on continue normalement
    4. Upload (dry-run par defaut, ou reel selon config).
    5. Si reel reussi -> telecharger le .torrent final, remplacer le local,
       state = UPLOADED.

Toute la logique HTTP est isolee dans gemini_api ; toute la logique de
transition d'etat est isolee dans package_state. Ce module n'est qu'un
chef d'orchestre + l'UX du prompt CLI (qu'une UI web remplacera plus tard
par une page de revue).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from torf import Torrent

from .. import config
from ..trackers.gemini import unit3d_mapping
from .errors import die
from .gemini_api import (
    DELTA_PCT_AMBIGUOUS,
    DELTA_PCT_CERTAIN,
    DELTA_PCT_VERY_LIKELY,
    DupConfidence,
    DuplicateCandidate,
    DuplicateCheckResult,
    GeminiAPIError,
    GeminiClient,
    UploadPayload,
    UploadResult,
)
from .media_type import MediaType
from .package_state import (
    PackageState,
    init_state,
    read_state,
    transition,
)


# ============================================================
# Configuration utilisateur
# ============================================================

# Prefixes que le tracker met devant ses .torrent (convention native).
# Permet de reconnaitre d'un coup d'oeil le bon .torrent (avec passkey du tracker)
# par opposition au .torrent local genere par nous dans le dossier package.
_TORRENT_FILENAME_PREFIX: dict[str, str] = {
    "gemini": "[G3MINI]",
}


def _copy_to_torrent_final_dir(torrent_path: Path) -> None:
    """NOTES round 7 : copie le .torrent final vers TORRENT_FINAL_DIR
    (env var optionnelle) si configure. Pratique pour pointer vers le
    watch folder de qBittorrent / Transmission qui lance auto le seed.

    Echec silencieux : on log un warning mais on ne plante pas l'upload.
    Le .torrent reste de toute facon disponible dans le package_dir.
    """
    import os
    import shutil

    target_dir_str = (os.getenv("TORRENT_FINAL_DIR") or "").strip()
    if not target_dir_str:
        return
    target_dir = Path(target_dir_str)
    if not target_dir.is_absolute():
        # On exige un chemin absolu pour eviter les confusions
        print(
            f"[WARN] TORRENT_FINAL_DIR n'est pas un chemin absolu : "
            f"'{target_dir_str}'. Copie skip."
        )
        return
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[WARN] TORRENT_FINAL_DIR introuvable / non-creable : {e}. Copie skip.")
        return
    target = target_dir / torrent_path.name
    try:
        shutil.copy2(str(torrent_path), str(target))
        print(f"[OK] .torrent copie aussi vers : {target}")
    except (OSError, shutil.SameFileError) as e:
        print(f"[WARN] Copie vers TORRENT_FINAL_DIR a echoue : {e}")


def _torrent_filename_prefix(tracker_key: str) -> str:
    return _TORRENT_FILENAME_PREFIX.get(tracker_key, "")


@dataclass
class UploadConfig:
    """Parametres d'execution de la boucle upload, definis par les flags CLI
    et l'environnement."""

    api_url: str
    api_key: str
    dry_run: bool = True
    force_upload: bool = False
    force_existing_id: int | None = None  # ID du doublon que l'user accepte de bypasser
    anonymous: bool = False
    # Hook de prompt injectable (utile pour les tests, et plus tard pour l'UI web).
    # Recoit un DuplicateCheckResult, retourne True pour continuer, False pour skip.
    prompt: Callable[[DuplicateCheckResult], bool] | None = None


def load_upload_config(
    dry_run: bool,
    force_upload: bool,
    force_existing_id: int | None,
    anonymous: bool,
    prompt: Callable[[DuplicateCheckResult], bool] | None = None,
) -> UploadConfig:
    """Construit la config en lisant les variables d'environnement requises."""
    config.load_env()
    api_url = config.get_optional_env("TRACKER_API_URL", "")
    if not api_url:
        die(
            "TRACKER_API_URL absent dans le .env. "
            "Ex : TRACKER_API_URL=https://gemini-tracker.org/api"
        )
    api_key = config.get_required_env("TRACKER_API_KEY")

    return UploadConfig(
        api_url=api_url,
        api_key=api_key,
        dry_run=dry_run,
        force_upload=force_upload,
        force_existing_id=force_existing_id,
        anonymous=anonymous,
        prompt=prompt,
    )


# ============================================================
# Lecture du package depuis le disque
# ============================================================

@dataclass
class PackageBundle:
    """Tout ce qu'il faut savoir d'un package pour pouvoir l'uploader.

    Reconstruit en lisant les fichiers ecrits par process_one() :
    release_name.txt, presentation.txt, *.mediainfo.nfo, *.torrent, debug.json.
    """

    package_dir: Path
    release_name: str
    description: str           # BBCode (presentation.txt)
    mediainfo: str             # contenu *.mediainfo.nfo
    torrent_path: Path
    nfo_path: Path | None
    infohash: str              # purement informatif, conserve dans le state
    size_bytes: int            # taille du contenu (pour la dedup)
    tmdb_id: int
    imdb_id: int
    tvdb_id: int
    media_type: MediaType
    season_number: int
    episode_number: int
    # Genres TMDB extraits du debug.json. Utilises par category_id_for pour
    # distinguer Animation/Documentaire des Films/Series classiques (cf.
    # unit3d_mapping et NOTES.md round 2).
    tmdb_genres: tuple[str, ...] = ()


def _read_release_name(package_dir: Path) -> str:
    """release_name.txt peut contenir 'Release.Name (Titre FR)' ; on retient
    seulement la partie release_name (avant l'eventuelle parenthese)."""
    path = package_dir / "release_name.txt"
    if not path.is_file():
        die(f"release_name.txt manquant dans {package_dir}")
    raw = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    paren_idx = raw.rfind(" (")
    if paren_idx > 0 and raw.endswith(")"):
        return raw[:paren_idx].strip()
    return raw


def _read_presentation(package_dir: Path) -> str:
    """Lit la presentation BBCode, en preferant la version editee par l'user.

    Si `presentation_user.txt` existe (cf. F4 NOTES.md : editor BBCode avec
    Edit + Reset), c'est cette version qui est uploadee au tracker. Sinon
    on retombe sur `presentation.txt` regeneree par le pipeline. Reset cote
    UI = suppression de presentation_user.txt.
    """
    user_edit = package_dir / "presentation_user.txt"
    if user_edit.is_file():
        return user_edit.read_text(encoding="utf-8")
    path = package_dir / "presentation.txt"
    if not path.is_file():
        die(f"presentation.txt manquant dans {package_dir}")
    return path.read_text(encoding="utf-8")


def _read_mediainfo(package_dir: Path, release_name: str) -> str:
    path = package_dir / f"{release_name}.mediainfo.nfo"
    if not path.is_file():
        die(f"{path.name} manquant dans {package_dir}")
    return path.read_text(encoding="utf-8")


def _torrent_path_for(package_dir: Path, release_name: str) -> Path:
    """Retourne le path du .torrent. Si absent, message d'erreur contextuel.

    Cas frequent : le pre-check anticipe (pipeline.process_one) detecte un
    doublon CERTAIN avant create_torrent et marque le package en
    ABORTED_DUPLICATE pour eviter de gaspiller du SHA-1. Le .torrent n'a
    donc jamais ete genere. Si l'user clique "Upload" sur ce package
    via la UI, le message d'erreur doit dire EXACTEMENT pourquoi et
    proposer la solution (re-preparer = bouton dans la UI), pas un
    cryptique "torrent manquant".
    """
    p = package_dir / f"{release_name}.torrent"
    if p.is_file():
        return p

    # Lecture du state pour produire un message contextuel
    state_data = read_state(package_dir)
    if state_data and state_data.state == PackageState.ABORTED_DUPLICATE:
        existing = (
            f" (torrent existant ID {state_data.existing_torrent_id})"
            if state_data.existing_torrent_id else ""
        )
        die(
            "Le .torrent n'a pas ete genere lors de la preparation parce "
            f"qu'un doublon CERTAIN a ete detecte sur le tracker{existing}. "
            "Pour forcer l'upload : 1) ouvre la page detail du package, "
            "2) clique sur 'Re-preparer' pour regenerer le .torrent, "
            "3) coche 'Force upload' avec l'ID exact du doublon. "
            f"(Package : {package_dir.name})"
        )
    die(
        f"Fichier .torrent introuvable : {p.name}. "
        f"Le package est peut-etre incomplet (state={state_data.state.value if state_data else '?'}). "
        "Re-prepare le package depuis la page detail."
    )


def _scene_nfo_path_for(package_dir: Path, release_name: str) -> Path | None:
    """Choisit le fichier NFO a joindre au upload, par ordre de priorite :
    1. Le NFO scene `{release_name}.nfo` s'il a ete copie depuis la release
       d'origine (presence de creds team, ASCII art, etc.). Toujours preferable.
    2. Sinon fallback sur `{release_name}.mediainfo.nfo` qu'on genere toujours.
       Ainsi le tracker recoit au moins quelque chose comme NFO joint
       (utile quand on uploade un rip personnel sans NFO scene).

    Retourne None si meme le fallback est absent (cas pathologique).
    """
    scene = package_dir / f"{release_name}.nfo"
    if scene.is_file():
        return scene
    mediainfo_nfo = package_dir / f"{release_name}.mediainfo.nfo"
    if mediainfo_nfo.is_file():
        return mediainfo_nfo
    return None


def _compute_infohash(torrent_path: Path) -> str:
    """Retourne l'infohash SHA-1 du .torrent en hex (informatif)."""
    try:
        t = Torrent.read(str(torrent_path))
        return (t.infohash or "").lower()
    except Exception as e:
        die(f"Impossible de lire l'infohash de {torrent_path.name} : {e}")


def _read_debug_metadata(package_dir: Path) -> dict[str, Any]:
    """Lit _debug/debug.json (cree par process_one)."""
    debug_file = package_dir / "_debug" / "debug.json"
    if not debug_file.is_file():
        return {}
    try:
        return json.loads(debug_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] debug.json illisible : {e}")
        return {}


def _imdb_id_to_int(raw: Any) -> int:
    """'tt0123456' -> 123456. Retourne 0 si non parseable."""
    if not raw:
        return 0
    s = str(raw).strip().lower()
    if s.startswith("tt"):
        s = s[2:]
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else 0


def _media_type_from_debug(debug: dict[str, Any]) -> MediaType:
    raw = debug.get("media_type", "movie")
    try:
        return MediaType(raw)
    except ValueError:
        return MediaType.MOVIE


def _extract_size_bytes(debug: dict[str, Any], torrent_path: Path) -> int:
    """Recupere la taille du contenu en octets.

    Priorite :
    1. mediainfo_data.size_bytes (recalculee pour les saisons/integrales par
       process_one, donc fiable et la moins chere a lire).
    2. Fallback : Torrent.size, qui est la SOMME des tailles du contenu
       decrit dans le .torrent (info.length ou somme des info.files), PAS la
       taille du fichier .torrent lui-meme. C'est exactement le critere de
       dedup. Indispensable pour les packages legacy ou debug.json est
       incomplet : sans ce fallback, la dedup par taille etait silencieusement
       desactivee et un doublon CERTAIN pouvait passer (= ban tracker).
    """
    mi = debug.get("mediainfo_data") or {}
    if isinstance(mi, dict):
        v = mi.get("size_bytes")
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    # Fallback : lecture du .torrent. torf retourne la taille du CONTENU.
    try:
        return int(Torrent.read(str(torrent_path)).size or 0)
    except Exception as e:
        print(f"[WARN] Lecture taille depuis .torrent echouee : {e}")
        return 0


def load_package_bundle(package_dir: Path) -> PackageBundle:
    """Reconstruit un PackageBundle complet depuis un dossier package."""
    if not package_dir.is_dir():
        die(f"Dossier package introuvable : {package_dir}")

    release_name = _read_release_name(package_dir)
    description = _read_presentation(package_dir)
    mediainfo = _read_mediainfo(package_dir, release_name)
    torrent_path = _torrent_path_for(package_dir, release_name)
    nfo_path = _scene_nfo_path_for(package_dir, release_name)
    infohash = _compute_infohash(torrent_path)

    debug = _read_debug_metadata(package_dir)
    tmdb_ctx = debug.get("tmdb_context") or {}
    media_type = _media_type_from_debug(debug)
    size_bytes = _extract_size_bytes(debug, torrent_path)

    tmdb_id_raw = (
        tmdb_ctx.get("movie_id")
        or tmdb_ctx.get("tv_id")
        or tmdb_ctx.get("tmdb_id")
        or tmdb_ctx.get("id")
        or debug.get("tmdb_id", 0)
    )
    imdb_id_raw = tmdb_ctx.get("imdb_id") or debug.get("imdb_id", "")

    # Extraction des genres TMDB pour l'heuristique category_id_for
    raw_genres = tmdb_ctx.get("genres") or []
    tmdb_genres = tuple(
        str(g).strip() for g in raw_genres if isinstance(g, str) and g.strip()
    )

    return PackageBundle(
        package_dir=package_dir,
        release_name=release_name,
        description=description,
        mediainfo=mediainfo,
        torrent_path=torrent_path,
        nfo_path=nfo_path,
        infohash=infohash,
        size_bytes=size_bytes,
        tmdb_id=int(tmdb_id_raw) if tmdb_id_raw else 0,
        imdb_id=_imdb_id_to_int(imdb_id_raw),
        tvdb_id=int(tmdb_ctx.get("tvdb_id") or 0),
        media_type=media_type,
        season_number=int(debug.get("season_number") or 0),
        episode_number=int(debug.get("episode_number") or 0),
        tmdb_genres=tmdb_genres,
    )


# ============================================================
# Construction du payload Unit3D
# ============================================================

def build_upload_payload(
    bundle: PackageBundle,
    cfg: UploadConfig,
) -> UploadPayload:
    """Construit le UploadPayload a partir d'un bundle + config.

    Si l'utilisateur a defini des overrides dans le package_state.json
    (manual_category_id / manual_type_id / manual_resolution_id, F3 NOTES.md),
    ils prennent le pas sur l'auto-detection a partir du release_name.
    """
    # Auto-detection par defaut. category_id_for utilise les genres TMDB
    # pour distinguer Animation/Documentaire, et le release_name pour le
    # fallback keywords sport (Lot N).
    category_id = unit3d_mapping.category_id_for(
        bundle.media_type,
        tmdb_context={"genres": list(bundle.tmdb_genres)},
        release_name=bundle.release_name,
    )
    type_id = unit3d_mapping.type_id_for(bundle.release_name)
    resolution_id = unit3d_mapping.resolution_id_for(bundle.release_name)

    # Overrides si presents dans le state
    state_data = read_state(bundle.package_dir)

    # Lot Q : champs upload supplementaires + IDs externes overridables.
    # Defaults : valeurs auto du bundle / TMDB.
    imdb_id_eff = bundle.imdb_id
    tvdb_id_eff = bundle.tvdb_id
    mal_id_eff = 0
    season_eff = bundle.season_number
    episode_eff = bundle.episode_number
    distributor_id_eff = 0
    region_id_eff = 0
    keywords_eff = ""

    if state_data:
        if state_data.manual_category_id > 0:
            category_id = state_data.manual_category_id
        if state_data.manual_type_id > 0:
            type_id = state_data.manual_type_id
        if state_data.manual_resolution_id > 0:
            resolution_id = state_data.manual_resolution_id

        # Override IMDB ID (format "tt1234567" -> int)
        if state_data.manual_imdb_id:
            try:
                # On retire le prefixe 'tt' et on convertit en int
                imdb_str = state_data.manual_imdb_id.strip().lower()
                if imdb_str.startswith("tt"):
                    imdb_str = imdb_str[2:]
                imdb_id_eff = int(imdb_str) or imdb_id_eff
            except (TypeError, ValueError):
                pass
        if state_data.manual_tvdb_id > 0:
            tvdb_id_eff = state_data.manual_tvdb_id
        if state_data.manual_mal_id > 0:
            mal_id_eff = state_data.manual_mal_id
        # Saison/Episode : 0 = laisser auto (bundle), >0 = forcer.
        # Cas particulier S/E = 0 demande par l'user pour packs / specials :
        # on detecte ca par "user a coche override" ie. value differente de auto.
        if state_data.manual_season_number > 0:
            season_eff = state_data.manual_season_number
        if state_data.manual_episode_number > 0:
            episode_eff = state_data.manual_episode_number
        # Distributeur / Region : seulement si Full Disc (type=1)
        if state_data.manual_distributor_id > 0:
            distributor_id_eff = state_data.manual_distributor_id
        if state_data.manual_region_id > 0:
            region_id_eff = state_data.manual_region_id
        # Mots-cles
        if state_data.manual_keywords:
            keywords_eff = state_data.manual_keywords

    # Construction du extra dict pour les champs Gemini specifiques
    # (distributor_id, region_id, keywords). Vide -> on n'envoie pas.
    extra: dict = {}
    if distributor_id_eff > 0 and type_id == unit3d_mapping.TYPE_FULL_DISC:
        extra["distributor_id"] = distributor_id_eff
    if region_id_eff > 0 and type_id == unit3d_mapping.TYPE_FULL_DISC:
        extra["region_id"] = region_id_eff
    if keywords_eff:
        extra["keywords"] = keywords_eff

    return UploadPayload(
        name=bundle.release_name,
        description=bundle.description,
        mediainfo=bundle.mediainfo,
        torrent_path=bundle.torrent_path,
        nfo_path=bundle.nfo_path,
        tmdb_id=bundle.tmdb_id,
        imdb_id=imdb_id_eff,
        tvdb_id=tvdb_id_eff,
        mal_id=mal_id_eff,
        category_id=category_id,
        type_id=type_id,
        resolution_id=resolution_id,
        season_number=season_eff,
        episode_number=episode_eff,
        anonymous=cfg.anonymous,
        personal_release=bool(state_data and state_data.personal_release),
        extra=extra,
    )


# ============================================================
# Affichage et prompt CLI
# ============================================================

def _format_size_gb(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "?"
    return f"{size_bytes / (1024 ** 3):.2f} Go"


def _print_candidates(candidates: list[DuplicateCandidate], our_size: int) -> None:
    print(f"[INFO] {len(candidates)} candidat(s) detecte(s) sur le tracker :")
    print(f"        Notre taille : {_format_size_gb(our_size)}")
    for c in candidates:
        print(
            f"          - ID {c.torrent_id:>6} | delta {c.delta_pct:6.2f}% | "
            f"{_format_size_gb(c.size_bytes):>10} | {c.confidence.value:<11} | "
            f"{c.name[:60]}"
        )
        if c.url:
            print(f"            -> {c.url}")


def _default_cli_prompt(result: DuplicateCheckResult) -> bool:
    """Prompt CLI bloquant. Retourne True pour continuer, False pour skip.

    (Q)uit termine le process avec exit code 1 (action de l'utilisateur, pas
    une erreur).
    """
    while True:
        try:
            ans = input("Action ? (C)ontinue, (S)kip, (Q)uit : ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nInterruption utilisateur.")
            sys.exit(1)
        if ans in ("c", "continue"):
            return True
        if ans in ("s", "skip"):
            return False
        if ans in ("q", "quit", "exit"):
            print("Sortie demandee par l'utilisateur.")
            sys.exit(1)
        print("Reponse non comprise. Tape 'c', 's' ou 'q'.")


# ============================================================
# Helpers reutilisables pour le pipeline (pre-check + transition)
# ============================================================


def try_check_duplicate(
    client: GeminiClient,
    *,
    tmdb_id: int,
    size_bytes: int,
    release_name: str,
) -> DuplicateCheckResult | None:
    """Wrapper de `client.check_duplicate` qui swallow les erreurs reseau.

    Retourne None si le check n'a pas pu etre fait (erreur API, parametres
    insuffisants, etc.). Logs en `[WARN]`. Utilise par les 3 sites qui font
    un dedup check :
    - pipeline.process_one (pre-check anticipe avant create_torrent)
    - web.jobs_runner._try_dedup_check (apres prepare reussi)
    - upload_orchestrator.upload_package (avant l'upload reel)
    """
    if tmdb_id <= 0 and not release_name:
        return None
    try:
        return client.check_duplicate(
            tmdb_id=tmdb_id,
            size_bytes=size_bytes,
            release_name=release_name,
        )
    except GeminiAPIError as e:
        print(f"[WARN] check_duplicate echoue (non-bloquant) : {e}")
        return None


def mark_aborted_duplicate(
    package_dir: Path,
    dup: DuplicateCheckResult,
    note: str,
    infohash: str = "",
) -> None:
    """Transitionne un package vers ABORTED_DUPLICATE en preservant les
    champs lies au doublon (id tracker existant, url, niveau de confiance,
    timestamp). Centralise la logique dupliquee dans pipeline / jobs_runner /
    upload_orchestrator.
    """
    primary = dup.primary
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    transition(
        package_dir, PackageState.ABORTED_DUPLICATE,
        note=note,
        infohash=infohash or "",
        existing_torrent_id=primary.torrent_id if primary else None,
        existing_torrent_url=primary.url if primary else "",
        dedup_confidence=dup.confidence.value,
        dedup_checked_at=now,
    )


# ============================================================
# Sequence principale
# ============================================================

@dataclass
class UploadOutcome:
    """Resultat de la sequence dedup -> upload -> download."""

    final_state: PackageState
    duplicate: DuplicateCheckResult | None = None
    upload: UploadResult | None = None
    final_torrent_path: Path | None = None
    message: str = ""


def upload_package(
    package_dir: Path,
    cfg: UploadConfig,
    tracker_key: str = "gemini",
) -> UploadOutcome:
    """Execute la boucle complete sur un package deja prepare.

    Mode dry_run : ne POST rien, montre ce qu'il aurait fait.
    Mode reel : check duplicate, abort si doublon (sauf force avec ID), upload, download.
    """
    bundle = load_package_bundle(package_dir)
    client = GeminiClient(api_url=cfg.api_url, api_key=cfg.api_key)

    state_data = init_state(package_dir, bundle.release_name, tracker_key)
    if state_data.state == PackageState.UPLOADED:
        msg = (
            f"Package deja uploade (torrent ID {state_data.uploaded_torrent_id}). "
            "Aucune action."
        )
        print(f"[INFO] {msg}")
        return UploadOutcome(
            final_state=PackageState.UPLOADED,
            message=msg,
        )

    # ------------------------------------------------------------
    # 1. Verification de doublon (cascade TMDB -> taille)
    # ------------------------------------------------------------
    print(
        f"[INFO] Verification doublon sur le tracker "
        f"(tmdb_id={bundle.tmdb_id}, taille={_format_size_gb(bundle.size_bytes)})"
    )
    if bundle.tmdb_id <= 0 and bundle.size_bytes <= 0:
        print(
            "[WARN] Ni tmdb_id ni taille connus : la dedup va se baser uniquement "
            "sur le nom de release. Resultat moins fiable."
        )

    try:
        dup = client.check_duplicate(
            tmdb_id=bundle.tmdb_id,
            size_bytes=bundle.size_bytes,
            release_name=bundle.release_name,
        )
    except GeminiAPIError as e:
        transition(
            package_dir, PackageState.FAILED,
            note="echec check_duplicate", last_error=str(e),
        )
        die(f"Erreur API lors de la verification de doublon : {e}")
        return UploadOutcome(final_state=PackageState.FAILED, message=str(e))  # unreachable

    if dup.note:
        print(f"[WARN] {dup.note}")

    # ------------------------------------------------------------
    # 2. Decision selon la confiance du doublon
    # ------------------------------------------------------------
    proceed = True   # par defaut on continue (pas de doublon trouve)

    if dup.candidates:
        _print_candidates(dup.candidates, bundle.size_bytes)

    primary = dup.primary
    force_authorized = (
        cfg.force_upload
        and primary is not None
        and cfg.force_existing_id is not None
        and cfg.force_existing_id == primary.torrent_id
    )

    if dup.confidence == DupConfidence.CERTAIN:
        if force_authorized:
            print(
                f"[ATTENTION] --force-upload confirme avec ID {cfg.force_existing_id}. "
                "L'upload va proceder malgre le doublon CERTAIN."
            )
            proceed = True
        else:
            if cfg.force_upload and primary and cfg.force_existing_id != primary.torrent_id:
                print(
                    f"[ATTENTION] --force-upload ignore : tu as fourni "
                    f"--i-know-this-is-a-duplicate={cfg.force_existing_id} mais le "
                    f"doublon detecte est l'ID {primary.torrent_id}."
                )
            print(
                f"[INFO] Doublon CERTAIN (delta {primary.delta_pct:.2f}%). "
                "Abort propre, aucun prompt."
            )
            transition(
                package_dir, PackageState.ABORTED_DUPLICATE,
                note=f"doublon certain via {dup.matched_via}",
                infohash=bundle.infohash,
                existing_torrent_id=primary.torrent_id if primary else None,
                existing_torrent_url=primary.url if primary else "",
            )
            return UploadOutcome(
                final_state=PackageState.ABORTED_DUPLICATE,
                duplicate=dup,
                message=(
                    f"Doublon certain : torrent ID {primary.torrent_id if primary else '?'}."
                ),
            )

    elif dup.confidence in (DupConfidence.VERY_LIKELY, DupConfidence.AMBIGUOUS):
        if force_authorized:
            print(
                f"[ATTENTION] --force-upload confirme avec ID {cfg.force_existing_id}. "
                f"L'upload va proceder malgre le doublon {dup.confidence.value}."
            )
            proceed = True
        else:
            label = (
                "DOUBLON TRES PROBABLE" if dup.confidence == DupConfidence.VERY_LIKELY
                else "AMBIGU"
            )
            print(f"[INFO] {label} : decision humaine requise.")
            prompt_fn = cfg.prompt or _default_cli_prompt
            proceed = prompt_fn(dup)
            if not proceed:
                transition(
                    package_dir, PackageState.ABORTED_DUPLICATE,
                    note=f"doublon {dup.confidence.value} confirme par l'utilisateur (skip)",
                    infohash=bundle.infohash,
                    existing_torrent_id=primary.torrent_id if primary else None,
                    existing_torrent_url=primary.url if primary else "",
                )
                return UploadOutcome(
                    final_state=PackageState.ABORTED_DUPLICATE,
                    duplicate=dup,
                    message="Skip demande par l'utilisateur.",
                )

    # confidence == NONE -> on continue normalement

    # En dry-run on n'effectue PAS la transition vers VALIDATED : la simulation
    # ne doit pas modifier l'etat sur disque pour rester re-jouable.
    if not cfg.dry_run:
        transition(
            package_dir, PackageState.VALIDATED,
            note=(
                "dedup ok" if dup.confidence == DupConfidence.NONE
                else f"force/continue malgre doublon {dup.confidence.value}"
            ),
            infohash=bundle.infohash,
        )

    # ------------------------------------------------------------
    # 3. Upload (dry-run ou reel)
    # ------------------------------------------------------------
    payload = build_upload_payload(bundle, cfg)
    print(
        f"[INFO] Upload {'(DRY-RUN)' if cfg.dry_run else '(REEL)'} : "
        f"{bundle.release_name}"
    )
    try:
        upload_res = client.upload_torrent(payload, dry_run=cfg.dry_run)
    except (GeminiAPIError, FileNotFoundError) as e:
        transition(
            package_dir, PackageState.FAILED,
            note="echec upload_torrent", last_error=str(e),
        )
        die(f"Erreur lors de l'upload : {e}")
        return UploadOutcome(final_state=PackageState.FAILED, message=str(e))  # unreachable

    if cfg.dry_run:
        print("[OK] DRY-RUN reussi. Payload prepare :")
        for k, v in (upload_res.dry_run_payload or {}).items():
            display = v if not isinstance(v, str) or len(v) < 200 else v[:200] + "...[tronque]"
            print(f"        {k} = {display}")
        # State sur disque non modifie en dry-run -> on reflete l'etat reel
        current = read_state(package_dir)
        return UploadOutcome(
            final_state=current.state if current else PackageState.PREPARED,
            duplicate=dup,
            upload=upload_res,
            message="Dry-run reussi : aucun POST envoye.",
        )

    # ------------------------------------------------------------
    # 4. Upload reel reussi : on telecharge le .torrent final
    # ------------------------------------------------------------
    if upload_res.torrent_id is None and not upload_res.download_url:
        # Diagnostique : on dump le body brut pour aider au debug
        print("[ERREUR] Upload accepte mais ni torrent_id ni download_url retournes.")
        print("[ERREUR] Reponse brute du tracker :")
        import json as _json
        try:
            print(_json.dumps(upload_res.raw, indent=2, ensure_ascii=False))
        except Exception:
            print(repr(upload_res.raw))
        transition(
            package_dir, PackageState.FAILED,
            note="upload sans torrent_id ni download_url",
            last_error="Reponse API valide mais aucun moyen d'identifier le torrent.",
        )
        die("Inspectez la reponse ci-dessus pour comprendre le format renvoye.")

    print(f"[OK] Upload reussi : torrent ID {upload_res.torrent_id}")
    if upload_res.torrent_url:
        print(f"[OK] Page tracker : {upload_res.torrent_url}")

    # Construction du chemin final : dossier centralise + naming a la facon
    # du tracker ([G3MINI]release_name.torrent). Permet de pointer qBittorrent
    # sur ce dossier comme watch-folder, et le prefixe rend visuellement
    # evident que c'est LE bon .torrent a seeder (pas celui du dossier package
    # qui aura un infohash different - Unit3D regenere un infohash random a l'upload).
    download_dir = config.torrent_download_dir()
    prefix = _torrent_filename_prefix(tracker_key)
    final_filename = f"{prefix}{bundle.release_name}.torrent"
    final_path = download_dir / final_filename

    print(f"[INFO] Telechargement du .torrent final (avec passkey) vers {final_path}...")
    try:
        # Priorite : URL directe avec passkey (format Gemini observe).
        # Fallback : endpoint API auth-bearer si on n'a que l'id.
        if upload_res.download_url:
            final_torrent = client.download_torrent_from_url(
                url=upload_res.download_url,
                dest_path=final_path,
            )
        else:
            final_torrent = client.download_torrent(
                torrent_id=upload_res.torrent_id,
                dest_path=final_path,
            )
    except GeminiAPIError as e:
        transition(
            package_dir, PackageState.UPLOADED,
            note=f"upload OK mais download .torrent KO : {e}",
            uploaded_torrent_id=upload_res.torrent_id,
            uploaded_torrent_url=upload_res.torrent_url,
        )
        die(
            f"Upload OK (ID {upload_res.torrent_id}) mais download .torrent final "
            f"a echoue : {e}. Tu peux le recuperer manuellement depuis le tracker."
        )

    transition(
        package_dir, PackageState.UPLOADED,
        note="upload + download OK",
        uploaded_torrent_id=upload_res.torrent_id,
        uploaded_torrent_url=upload_res.torrent_url,
        uploaded_at=state_data.updated_at,
        final_torrent_path=str(final_torrent),
    )
    print(f"[OK] .torrent final ecrit : {final_torrent}")

    # NOTES round 7 : copie aussi le .torrent vers TORRENT_FINAL_DIR si
    # configure (watch folder qBittorrent / rTorrent / Transmission).
    # Pratique : le client torrent demarre automatiquement le seed sans
    # qu'il faille glisser le fichier a la main.
    _copy_to_torrent_final_dir(final_torrent)

    print(f"[OK] Page tracker : {upload_res.torrent_url}")

    return UploadOutcome(
        final_state=PackageState.UPLOADED,
        duplicate=dup,
        upload=upload_res,
        final_torrent_path=final_torrent,
        message="Upload complet.",
    )
