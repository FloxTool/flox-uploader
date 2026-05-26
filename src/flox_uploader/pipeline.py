"""Orchestrateur : traite UN fichier video et produit un package complet.

Le rendu de la fiche BBCode est entierement deterministe (cf. core/bbcode_renderer.py).
Plus aucun appel OpenAI : tout sort de TMDB + OMDb + MediaInfo.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .core.bbcode_renderer import render_bbcode
from .core.debug import Debug
from .core.early_category import early_category_guess
from .core.errors import die
from .core.media_type import MediaType, detect_media_type
from .core.mediainfo_parser import (
    deduce_release_type, format_filesize, parse_mediainfo_json,
    total_size_recursive,
)
from .core.nfo import generate_nfo, find_companion_nfo
from .core.omdb import fetch_omdb_data, pick_best_poster_url
from .core.package_state import init_state
from .core.naming.strategy import get_strategy
from .core.release_name import build_release_name  # re-export historique conserve
from .core.tmdb import (
    make_tmdb_resolver,
    make_tv_resolver,
    make_tmdb_forced_id_resolver,
    make_tv_forced_id_resolver,
)
from .core.torrent import create_torrent
from .trackers import get_tracker
from .trackers.base import Tracker


def _short_torrent_filename(
    release_name: str, package_dir: Path, max_path: int = 240,
) -> str:
    """Retourne le nom de fichier .torrent, eventuellement raccourci.

    Windows a une limite historique MAX_PATH = 260 chars. Quand le path
    complet du .torrent (package_dir + filename) approche cette limite,
    le navigateur peut afficher le fichier en nom court 8.3 (DOWNTO~1.TOR)
    au moment de l'upload web.

    Si le path total reste sous `max_path` (240 par defaut, marge sur 260) :
    on garde le nom complet. Sinon : on tronque le release_name dans le
    filename juste assez pour rentrer. Le contenu interne du .torrent
    (info.name = release_name complet) n'est pas affecte.

    Le tronque garde la fin du release_name (qui contient la team) si
    possible : 'Downton.Abbey...x265-Amen' -> 'Down...x265-Amen.torrent'.
    """
    full_filename = f"{release_name}.torrent"
    full_path = str(package_dir / full_filename)
    if len(full_path) <= max_path:
        return full_filename

    overflow = len(full_path) - max_path
    # On enleve `overflow` chars dans le release_name. Si on retire trop,
    # fallback sur un nom generique.
    if overflow >= len(release_name) - 5:
        return "release.torrent"
    # Tronque le milieu pour preserver debut (titre) et fin (team)
    keep = len(release_name) - overflow
    head_len = keep // 2
    tail_len = keep - head_len
    short = release_name[:head_len] + release_name[-tail_len:]
    return f"{short}.torrent"


def process_one(
    input_path: Path,
    tracker_key: str = "gemini",
    force_fr: str | None = None,
    explicit_companion_nfo: Path | None = None,
    tmdb_id_override: int | None = None,
    manual_release_name: str | None = None,
    category_hint: int | None = None,
    manual_isbn: str | None = None,
    manual_author: str | None = None,
    manual_book_title: str | None = None,
    manual_book_year: int | None = None,
    manual_google_books_url: str | None = None,
) -> Path:
    config.load_env()
    announce_url = config.get_required_env("TRACKER_ANNOUNCE")
    tracker: Tracker = get_tracker(tracker_key, announce_url)

    # Sprint A v0.5.0 Etape 0 (PLAN-MULTICAT §5.1) : on devine la categorie
    # Gemini TRES TOT, juste a partir du path + d'un hint user optionnel.
    # Le signal est utilise immediatement par la Brique 1 ci-dessous pour
    # router le pipeline.
    category_id_early = early_category_guess(input_path, category_hint=category_hint)

    # Sprint A.3 PR-3 — Brique 1 : MediaInfo conditionnel.
    # Sprint D.4 v0.5.0 : on supporte maintenant la categorie Livres (cat 12).
    # Pour les autres categories non-video (Jeux, Logiciels, Formations), on
    # arrete toujours proprement avec un message clair (la roadmap Sprint E/H
    # les ajoutera a SUPPORTED_NON_VIDEO_CATEGORIES en temps voulu).
    from .trackers.gemini.unit3d_mapping import (
        CATEGORY_BOOKS, MEDIAINFO_REQUIRED_CATEGORIES,
        SUPPORTED_NON_VIDEO_CATEGORIES, category_label,
    )
    if category_id_early == CATEGORY_BOOKS:
        # Sprint D.4 : pipeline Livre dedie (pas de MediaInfo ni TMDB).
        # Sprint D.9 + D.11 : forward des overrides livre (ISBN/auteur/titre/annee).
        # Sprint D.40 : forward de manual_google_books_url.
        return _process_book(
            input_path, tracker,
            category_id_early=category_id_early,
            category_hint=category_hint,
            manual_isbn=manual_isbn or "",
            manual_author=manual_author or "",
            manual_book_title=manual_book_title or "",
            manual_book_year=int(manual_book_year or 0),
            manual_google_books_url=manual_google_books_url or "",
        )
    if (category_id_early not in MEDIAINFO_REQUIRED_CATEGORIES
            and category_id_early not in SUPPORTED_NON_VIDEO_CATEGORIES):
        cat_name = category_label(category_id_early)
        die(
            f"Categorie '{cat_name}' (id={category_id_early}) pas encore "
            f"supportee. Pipeline disponible aujourd'hui : Films, Series, "
            f"Anime, Documentaires, Sport, Emission TV, Livres. Categories "
            f"restantes (Jeux, Logiciels, Formations) prevues en v0.5.0 "
            f"(PLAN-MULTICAT.md sprints E + H). Glisse un fichier video "
            f"(.mkv / .mp4 / .avi) ou un livre (.epub / .pdf / .cbz) pour "
            f"preparer un upload."
        )

    # Detection du type de media (film / episode / saison / integrale)
    media_info = detect_media_type(input_path)
    print(f"[INFO] Type detecte : {media_info.media_type.value}")
    if media_info.media_type == MediaType.TV_EPISODE:
        print(f"        Saison {media_info.season:02d} Episode {media_info.episode:02d}")
    elif media_info.media_type == MediaType.TV_SEASON:
        print(f"        Saison {media_info.season:02d} ({len(media_info.all_videos)} episodes)")
    elif media_info.media_type == MediaType.TV_INTEGRALE:
        print(f"        Integrale ({len(media_info.all_videos)} episodes total, saisons {media_info.seasons_found})")

    video_path = media_info.reference_video  # 1er episode pour saison/integrale

    temp_debug_dir = config.temp_dir() / "debug"
    temp_debug_dir.mkdir(parents=True, exist_ok=True)
    debug = Debug(temp_debug_dir)
    # Sprint A v0.5.0 : persist du signal Etape 0. Utilise par PR-3 pour
    # router le pipeline (skip MediaInfo / naming non-video). Visible dans
    # le debug.json du package pour traçabilité.
    debug.set("category_id_early", category_id_early)
    debug.set("category_hint_user", category_hint)
    debug.set("media_type", media_info.media_type.value)
    debug.set("torrent_target", str(media_info.torrent_target))

    temp_nfo_path = temp_debug_dir / "temp_source.nfo"
    generate_nfo(video_path, temp_nfo_path)
    nfo_text = temp_nfo_path.read_text(encoding="utf-8", errors="replace")

    mediainfo_data = parse_mediainfo_json(video_path)

    # Pour saisons/integrales : la taille du fichier video parse n'est pas
    # representative (c'est juste 1 episode). Le .torrent englobe tout le
    # dossier (episodes + NFO + extras), donc on recalcule la taille totale.
    if media_info.media_type in {MediaType.TV_SEASON, MediaType.TV_INTEGRALE}:
        total_bytes = total_size_recursive(media_info.torrent_target)
        mediainfo_data["size_bytes"] = total_bytes
        mediainfo_data["size_pretty"] = format_filesize(total_bytes)
        print(f"[INFO] Taille totale du dossier : {mediainfo_data['size_pretty']}")

    debug.set("mediainfo_data", mediainfo_data)

    tmdb_api_key = config.get_optional_env("TMDB_API_KEY")

    # Resolver adapte au type de media (movies vs TV)
    is_tv = media_info.media_type in {
        MediaType.TV_EPISODE, MediaType.TV_SEASON, MediaType.TV_INTEGRALE,
    }
    if is_tv:
        season_num = media_info.season
        if tmdb_id_override and tmdb_id_override > 0:
            print(f"[INFO] TMDB ID force par l'utilisateur : {tmdb_id_override} (TV)")
            tmdb_resolver = make_tv_forced_id_resolver(
                tmdb_api_key, config.tmdb_cache_path(),
                forced_id=tmdb_id_override, season_num=season_num,
            )
        else:
            tv_resolver = make_tv_resolver(tmdb_api_key, config.tmdb_cache_path())
            # On passe season_num pour les saisons (et les episodes via .season)
            # Lot O.6 : on propage release_lang_hint kwarg pour bonifier les
            # candidats francophones natifs (cf. _detect_french_only_hint).
            def _tmdb_resolver_tv(parts, year, dbg, release_lang_hint=None):
                return tv_resolver(
                    parts, year, dbg,
                    season_num=season_num,
                    release_lang_hint=release_lang_hint,
                )
            tmdb_resolver = _tmdb_resolver_tv
    else:
        if tmdb_id_override and tmdb_id_override > 0:
            print(f"[INFO] TMDB ID force par l'utilisateur : {tmdb_id_override}")
            tmdb_resolver = make_tmdb_forced_id_resolver(
                tmdb_api_key, config.tmdb_cache_path(),
                forced_id=tmdb_id_override,
            )
        else:
            tmdb_resolver = make_tmdb_resolver(tmdb_api_key, config.tmdb_cache_path())

    # Sprint B.4 v0.5.0 (PLAN-MULTICAT §5.5) : on passe par la NamingStrategy
    # adaptee a la categorie au lieu d'appeler build_release_name() directement.
    # Pour les cats video (= les seules atteignables ici car la Brique 1 PR-3
    # a deja early-return les cats non-video plus haut), get_strategy retourne
    # VideoNamingStrategy qui wrap build_release_name() — comportement
    # strictement identique a l'appel direct (verifie par
    # test_video_strategy_build_release_name_equals_direct_call).
    naming_strategy = get_strategy(category_id_early)
    debug.set("naming_strategy", naming_strategy.name)
    release_name, tmdb_context = naming_strategy.build_release_name(
        video_path, tracker, nfo_text, debug,
        force_fr=force_fr, tmdb_resolver=tmdb_resolver,
        media_info=media_info,
        mediainfo_data=mediainfo_data,
    )
    # Override manuel du release_name si l'user l'a explicitement fourni
    # depuis la page detail (champ deverrouille). Bypass total de la logique
    # du pipeline : on garde tmdb_context/mediainfo mais le nom est celui
    # qu'a tape l'user. Verification minimale : non-vide et pas d'espaces.
    if manual_release_name:
        cleaned = manual_release_name.strip()
        if cleaned and " " not in cleaned:
            print(f"[INFO] release_name force par l'utilisateur : '{release_name}' -> '{cleaned}'")
            release_name = cleaned
            debug.set("manual_release_name", cleaned)
            # Signal trust badge : intervention humaine maximale (Lot E NOTES.md)
            from .core import naming_signals as _ns
            _ns.emit_signal(debug, _ns.SIG_USER_MANUAL_RELEASE_NAME, True)
        elif cleaned:
            print(f"[WARN] manual_release_name '{cleaned}' contient des espaces : ignore.")

    # Signal trust badge : TMDB ID force manuellement (Lot E NOTES.md)
    if tmdb_id_override and tmdb_id_override > 0:
        from .core import naming_signals as _ns
        _ns.emit_signal(debug, _ns.SIG_USER_MANUAL_TMDB_ID, int(tmdb_id_override))

    # Sauvegarde du contexte TMDB dans le debug pour que upload_orchestrator
    # puisse le relire (tmdb_id, imdb_id, titre VF/VO).
    debug.set("tmdb_context", tmdb_context or {})
    debug.set("season_number", media_info.season if media_info.season else 0)
    debug.set("episode_number", media_info.episode if media_info.episode else 0)

    if not tmdb_context:
        print(
            "[AVERTISSEMENT] TMDB n'a pas trouve de correspondance. "
            "Fiche partielle (technique uniquement). Verifier avant upload."
        )

    # Lot N.4 : signal "categorie potentiellement incertaine".
    # On l'emet uniquement quand le pipeline auto a tombe sur le defaut
    # FILM/SERIE (cat 1 ou 2) faute d'autre signal — ni genre TMDB
    # Animation/Documentaire, ni keyword sport. Dans ce cas le user devrait
    # verifier avant upload (cat 15 Emission TV ne s'auto-detecte pas non
    # plus, donc un talk-show passe pour une serie classique sans warning).
    from .trackers.gemini import unit3d_mapping as _u3d
    _auto_cat = _u3d.category_id_for(
        media_info.media_type,
        tmdb_context=tmdb_context,
        release_name=release_name,
    )
    if _auto_cat in {_u3d.CATEGORY_MOVIE, _u3d.CATEGORY_TV} and not tmdb_context:
        from .core import naming_signals as _ns_cat
        _ns_cat.emit_signal(debug, _ns_cat.SIG_CATEGORY_LOW_CONFIDENCE, True)

    package_dir = config.packages_dir() / release_name
    # B4 NOTES.md : si le package existe deja ET state == UPLOADED, on
    # refuse de l'ecraser (le .torrent uploade a son infohash sur le
    # tracker, le regenerer creerait un different fichier qui ne match
    # pas l'enregistrement Gemini -> orphelin cote seed). Le user doit
    # supprimer le package via la UI s'il veut vraiment recommencer.
    if package_dir.is_dir():
        from .core.package_state import read_state, PackageState
        existing_state = read_state(package_dir)
        if existing_state and existing_state.state == PackageState.UPLOADED:
            # NOTES round 9 UX-1 : message court (s'affiche en row de queue
            # ou de toast, dans des champs souvent tronques). L'explication
            # detaillee (infohash etc.) reste dispo sur la page detail.
            tid = existing_state.uploaded_torrent_id
            die(
                f"Deja uploade au tracker"
                f"{f' (ID {tid})' if tid else ''}. "
                f"Supprime le package via la page detail si tu veux recommencer."
            )
    package_dir.mkdir(parents=True, exist_ok=True)
    final_debug_dir = package_dir / "_debug"
    final_debug_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # Dedup check ANTICIPE (Phase 3b.5+) : avant create_torrent (couteux)
    # ============================================================
    # Si on a deja TMDB_id + size_bytes + release_name, on peut consulter le
    # tracker pour voir si un doublon CERTAIN existe deja. Si oui, on cree
    # juste un package_state minimal ABORTED_DUPLICATE et on skip toute la
    # suite (NFO, BBCode, .torrent SHA-1).
    early_dedup_certain = False
    early_dedup_result = None
    api_url = (config.get_optional_env("TRACKER_API_URL") or "").strip()
    api_key = (config.get_optional_env("TRACKER_API_KEY") or "").strip()
    early_tmdb_id = 0
    if tmdb_context:
        early_tmdb_id = (
            tmdb_context.get("movie_id")
            or tmdb_context.get("tv_id")
            or tmdb_context.get("tmdb_id")
            or 0
        )
    early_size = int(mediainfo_data.get("size_bytes") or 0)
    if api_url and api_key and early_tmdb_id > 0 and early_size > 0:
        print("[INFO] Pre-check doublon avant generation .torrent...")
        from .core.gemini_api import DupConfidence, GeminiClient
        from .core.upload_orchestrator import try_check_duplicate
        client = GeminiClient(api_url=api_url, api_key=api_key)
        early_dedup_result = try_check_duplicate(
            client,
            tmdb_id=early_tmdb_id,
            size_bytes=early_size,
            release_name=release_name,
        )
        if (
            early_dedup_result
            and early_dedup_result.confidence == DupConfidence.CERTAIN
            and early_dedup_result.primary
        ):
            print(
                f"[INFO] Doublon CERTAIN detecte AVANT generation .torrent : "
                f"ID {early_dedup_result.primary.torrent_id}. On skip "
                "create_torrent + NFO + BBCode."
            )
            early_dedup_certain = True

    # Note : on ne return PAS tot meme si CERTAIN. On continue jusqu'au bout
    # pour generer NFO + BBCode + release_name.txt (page detail riche), on
    # skip juste la creation du .torrent (etape coûteuse) et a la fin on
    # transitionne vers ABORTED_DUPLICATE au lieu de PREPARED.

    # Pour Gemini : on fournit TOUJOURS notre mediainfo (.mediainfo.nfo).
    # Si une release scene a deja un .nfo (avec creds team etc.), on le
    # copie en plus tel quel comme release_name.nfo.
    mediainfo_nfo_path = package_dir / f"{release_name}.mediainfo.nfo"
    scene_nfo_dest_path = package_dir / f"{release_name}.nfo"
    # Auto-shorten du nom de fichier .torrent si le path total dépasse la
    # limite Windows MAX_PATH (260) : on tronque le release_name dans le
    # filename pour rester sous 240 chars de path total. Le release_name
    # complet reste intact partout ailleurs (info.name dans le torrent,
    # release_name.txt, BBCode, dossier package).
    torrent_filename = _short_torrent_filename(release_name, package_dir)
    torrent_path = package_dir / torrent_filename
    presentation_path = package_dir / "presentation.txt"
    release_name_path = package_dir / "release_name.txt"

    mediainfo_nfo_path.write_text(nfo_text, encoding="utf-8")

    # Detection du NFO scene :
    # - Pour un dossier scene : on scanne le top-level
    # - Pour un mkv standalone : aucun auto-detect ; le user doit
    #   passer explicitement --companion-nfo (ou ajouter le .nfo dans
    #   input_list a cote du .mkv pour que le batch les regroupe).
    scene_nfo_source = explicit_companion_nfo
    if scene_nfo_source is None:
        scene_nfo_source = find_companion_nfo(
            media_info.torrent_target, video_path,
        )
    if scene_nfo_source is not None:
        scene_nfo_dest_path.write_bytes(scene_nfo_source.read_bytes())
        print(
            f"[OK] NFO scene detecte et copie : "
            f"{scene_nfo_source.name} -> {scene_nfo_dest_path.name}"
        )
    else:
        print("[INFO] Pas de NFO scene fourni avec la release.")

    omdb_data = {
        "imdb_rating": "", "imdb_vote_count": 0,
        "poster_url": "", "awards": "", "plot": "",
    }
    if tmdb_context:
        omdb_api_key = config.get_optional_env("OMDB_API_KEY")
        omdb_data = fetch_omdb_data(
            tmdb_context.get("imdb_id", ""), omdb_api_key, debug,
        )
        tmdb_context["imdb_rating"] = omdb_data["imdb_rating"]
        tmdb_context["imdb_vote_count"] = omdb_data.get("imdb_vote_count", 0)
        if omdb_data["imdb_rating"]:
            print(f"[OK] Note IMDb : {omdb_data['imdb_rating']}")
        if omdb_data["awards"]:
            print(f"[OK] Recompenses : {omdb_data['awards']}")
        # Signal trust badge : OMDb n'a rien retourne (Lot E NOTES.md)
        # Critere : on a un IMDB ID mais pas de note recuperee.
        #
        # Lot O.5 : on N'EMET PAS le signal pour les films < 6 mois — OMDb
        # peut prendre plusieurs semaines a indexer une nouvelle sortie, ce
        # n'est pas un signal de fiche partielle, juste un delai externe.
        #
        # Sprint 3 PLAN-V1.md : on N'EMET PAS NON PLUS si OMDB_API_KEY est
        # absent. L'user a explicitement choisi de ne pas configurer OMDb
        # (champ optionnel dans /setup), on ne va pas le penaliser pour ce
        # choix volontaire. Sans cle, le pipeline saute proprement les
        # appels OMDb et ne genere pas de warning.
        from .core import naming_signals as _ns_omdb
        omdb_configured = bool((omdb_api_key or "").strip())
        if (
            omdb_configured
            and tmdb_context.get("imdb_id")
            and not omdb_data["imdb_rating"]
        ):
            release_date_str = (tmdb_context.get("release_date") or "").strip()
            is_recent = False
            if release_date_str and len(release_date_str) >= 10:
                try:
                    from datetime import date as _date
                    rel_date = _date.fromisoformat(release_date_str[:10])
                    today = _date.today()
                    days_since_release = (today - rel_date).days
                    # Films sortis dans les 6 derniers mois OU pas encore sortis
                    is_recent = days_since_release < 180
                except (ValueError, TypeError):
                    is_recent = False
            if is_recent:
                debug.set("omdb_skipped_reason_recent", release_date_str)
                print(
                    f"[INFO] OMDb pas de note pour film recent "
                    f"({release_date_str}) — probable delai d'indexation, "
                    "pas un signal de fiche partielle."
                )
            else:
                _ns_omdb.emit_signal(debug, _ns_omdb.SIG_OMDB_DATA_MISSING, True)
        elif not omdb_configured:
            # Trace de debug uniquement (pas un warning visible cote UI)
            debug.set("omdb_not_configured", True)

    poster_url = pick_best_poster_url(tmdb_context, omdb_data["poster_url"])
    debug.set("poster_url", poster_url)
    if poster_url:
        source_label = "TMDB" if "image.tmdb.org" in poster_url else "OMDb"
        print(f"[OK] Poster ({source_label}) : {poster_url}")
    else:
        print("[INFO] Aucun poster disponible")

    release_type, release_source = deduce_release_type(
        release_name, mediainfo_data["video"].get("codec", ""),
    )
    debug.set("release_type", release_type)
    debug.set("release_source", release_source)

    # Important : on cree le torrent sur le torrent_target (= dossier entier
    # si l'input est un dossier, fichier sinon). Cela preserve la structure du
    # torrent original (NFO, poster, sample) pour le cross-seed.
    #
    # Cas particulier : input = .mkv standalone avec un .nfo passe
    # EXPLICITEMENT par l'utilisateur (--companion-nfo ou regroupe via
    # input_list). On cree alors un torrent multi-fichiers contenant les 2.
    # On NE le fait PAS automatiquement : la majorite des seeders ne
    # partagent que le mkv, donc inclure un .nfo en silence casserait
    # le cross-seed.
    companion_files: list[Path] = []
    if (
        media_info.torrent_target.is_file()
        and explicit_companion_nfo is not None
        and explicit_companion_nfo.parent == media_info.torrent_target.parent
    ):
        companion_files.append(explicit_companion_nfo)

    if early_dedup_certain:
        print("[INFO] Doublon CERTAIN -> skip create_torrent (gain de temps : pas de SHA-1).")
    else:
        create_torrent(
            media_info.torrent_target, torrent_path,
            announce_url=tracker.announce_url,
            source=tracker.torrent_source,
            private=tracker.private,
            companion_files=companion_files,
            torrent_root_name=release_name if companion_files else None,
        )

    debug.output_dir = final_debug_dir

    print("[INFO] Generation de presentation.txt (rendu deterministe)...")
    presentation_text = render_bbcode(
        tracker=tracker,
        video_path=video_path,
        release_name=release_name,
        mediainfo_data=mediainfo_data,
        tmdb_context=tmdb_context,
        poster_url=poster_url,
        awards_text=omdb_data["awards"],
        omdb_plot=omdb_data["plot"],
        release_type=release_type,
        release_source=release_source,
        media_info=media_info,
    )
    presentation_path.write_text(presentation_text, encoding="utf-8")

    # release_name.txt : par defaut on ecrit le release_name pur (sans titre
    # FR entre parentheses). Le suffixe FR n'est ajoute que si l'utilisateur
    # le demande explicitement via APPEND_FR_TITLE_TO_RELEASE_NAME=1 dans le
    # .env (a terme la web UI exposera une case a cocher dediee).
    #
    # Raison : souvent inutile parce que le titre international et le titre FR
    # se ressemblent (ex: "Downton Abbey"). Ca pollue la lecture pour rien.
    display_name = release_name
    append_fr = config.get_optional_env(
        "APPEND_FR_TITLE_TO_RELEASE_NAME", "0",
    ).strip() in ("1", "true", "yes", "on")
    if append_fr and tmdb_context:
        title_fr = (tmdb_context.get("title") or "").strip()
        title_en = (tmdb_context.get("original_title") or "").strip()
        if title_fr and title_en and title_fr != title_en:
            display_name = f"{release_name} ({title_fr})"
    release_name_path.write_text(display_name + "\n", encoding="utf-8")

    # Verification de conformite (NFO <-> release_name + regles Gemini)
    # Sprint A.3 PR-3 : on passe category_id pour router vers le bon profil
    # de checks. Pour la video (= categories actuellement supportees), le
    # profil 'video' reproduit a l'identique le comportement v0.3.x.
    from .core.compliance import check_compliance, format_report, has_blocking, Severity
    issues = check_compliance(
        release_name, mediainfo_data, media_info,
        torrent_target=media_info.torrent_target,
        banned_teams=config.banned_teams_list(),
        category_id=category_id_early,
    )
    debug.set("compliance_issues", [str(i) for i in issues])

    if issues:
        print()
        print(format_report(issues))
        blockings = [i for i in issues if i.severity == Severity.BLOCKING]
        n_errors = sum(1 for i in issues if i.severity == Severity.ERROR)
        warns = [i for i in issues if i.severity == Severity.WARN]
        if n_errors:
            print(
                f"[ATTENTION] {n_errors} erreur(s) de conformite : verifier "
                "manuellement le release_name avant l'upload."
            )
        # NOTES round 6 B3 : on N'EMET PLUS SIG_COMPLIANCE_WARNS ici.
        # Cause du double-comptage observe par Louis : une meme issue
        # PGS-only etait penalisee 2x :
        #   1. via compliance_issues[] (gate is_warn_minor dans confidence.py)
        #      -> -4 pts "Preference Gemini (mineur)"
        #   2. via SIG_COMPLIANCE_WARNS (penality dans naming_signals.py)
        #      -> -1 pt "Conformite (non-bloquant)"
        # Source canonique unique = compliance_issues[] traite par confidence.py.
        # Lot K : si une regle DURE est violee (MKV manquant, team interdite,
        # MP3, FLAC > 2ch, PGS dans encode, etc.) -> on initialise quand
        # meme le state pour que le package apparaisse dans la queue, mais
        # on le marque immediatement FAILED avec la liste des blockings.
        # L'user pourra le voir dans /queue et /packages/<name>.
        if blockings:
            debug.set(
                "blocking_compliance_messages",
                [b.message for b in blockings],
            )

    debug.save()

    # Initialise le state du package (PREPARED). C'est ce qui permet a la
    # commande `upload` de savoir ou en est le package et de garantir
    # l'idempotence (pas de double-upload).
    init_state(package_dir, release_name, tracker.key)

    # Sprint C.1bis v0.5.0 : propagation du hint user vers state.manual_category_id.
    # Si l'user a fourni un hint explicite via la modal Inbox (sous-categorie
    # video precise via menu Avance, ou cat non-video), on le persiste comme
    # override pour qu'il ne soit pas ecrase par l'auto-detection TMDB dans
    # build_upload_payload() (qui prend manual_category_id en priorite quand > 0).
    #
    # Si category_hint=0 ou None (cas "Video" generique top-level de la modal,
    # ou pas de modal du tout en CLI), on NE patche PAS manual_category_id ->
    # l'auto-detection TMDB+keywords reste pleinement active. C'est le comportement
    # v0.4.x par defaut.
    if category_hint is not None and category_hint > 0:
        from .core.package_state import read_state, write_state
        _state_data = read_state(package_dir)
        if _state_data is not None and _state_data.manual_category_id != int(category_hint):
            _state_data.manual_category_id = int(category_hint)
            write_state(package_dir, _state_data)
            print(
                f"[INFO] Hint user persiste : manual_category_id = "
                f"{category_hint} (override sticky depuis modal Inbox)."
            )
    if early_dedup_certain and early_dedup_result is not None:
        # On a tout genere sauf le .torrent, on marque le state final.
        from .core.upload_orchestrator import mark_aborted_duplicate
        mark_aborted_duplicate(
            package_dir,
            early_dedup_result,
            note="dedup pre-check CERTAIN (apres generation NFO/BBCode, sans .torrent)",
        )
    elif issues and has_blocking(issues):
        # Lot K : violation dure de la charte Gemini (MKV manquant, team
        # interdite, MP3, etc.). On a quand meme genere le NFO/BBCode pour
        # que l'user voie ce qui pose probleme, mais on transitionne en
        # FAILED pour que /upload soit refuse jusqu'a re-prepare.
        from .core.package_state import PackageState, transition
        blocking_msgs = [
            i.message
            for i in issues
            if i.severity == Severity.BLOCKING
        ]
        transition(
            package_dir,
            PackageState.FAILED,
            note=(
                "Conformite Gemini : "
                + " | ".join(blocking_msgs[:3])
                + ("…" if len(blocking_msgs) > 3 else "")
            ),
        )
        print(
            f"[FAILED] {len(blocking_msgs)} violation(s) dure(s) de la charte "
            "Gemini — package marque en echec. Voir la page detail pour les "
            "messages d'erreur exacts."
        )

    print("\n[TERMINE]")
    print(f"Tracker : {tracker.display_name}")
    print(f"Type media : {media_info.media_type.value}")
    print(f"Dossier package : {package_dir}")
    print(f"Release name : {release_name}")
    if display_name != release_name:
        print(f"Affichage    : {display_name}")
    print(f"Force FR : {force_fr if force_fr else 'Aucun'}")
    print(f"TMDB : {'Oui' if tmdb_context else 'Non'}")
    return package_dir


# ============================================================
# Sprint D.4 v0.5.0 — Pipeline Livre dedie
# ============================================================
# Court-circuite tout le pipeline video (detect_media_type, MediaInfo, TMDB,
# BBCode video) et utilise BookNamingStrategy + providers livre. Genere un
# package minimaliste avec release_name + state PREPARED + .torrent + NFO
# minimaliste + compliance ebook. La page detail enrichie (couverture,
# resume, formulaire override) viendra en Sprint D.5.

def _process_book(
    input_path: Path,
    tracker: Tracker,
    *,
    category_id_early: int,
    category_hint: int | None = None,
    manual_isbn: str = "",
    manual_author: str = "",
    manual_book_title: str = "",
    manual_book_year: int = 0,
    manual_google_books_url: str = "",
) -> Path:
    """Traite un upload livre (cat 12). Pipeline simplifie sans MediaInfo / TMDB.

    Etapes :
    1. BookNamingStrategy.build_release_name() -> release_name + book_metadata
    2. Cree le package_dir base sur release_name
    3. Genere un NFO minimaliste (texte simple avec les metadata livre)
    4. Cree le .torrent
    5. Verifie compliance avec profile='book'
    6. State PREPARED (ou FAILED si compliance bloquant)

    Args:
        input_path : path du fichier livre (.epub, .pdf, .cbz, etc.) ou dossier.
        tracker : Tracker (gemini par defaut).
        category_id_early : doit etre CATEGORY_BOOKS (12).
        category_hint : hint user depuis modal Inbox (pour state.manual_category_id).

    Returns:
        Path du package_dir cree.
    """
    print(f"[INFO] Type detecte : ebook ({input_path.suffix.lower() or 'dossier'})")

    # ---- Setup debug ----
    temp_debug_dir = config.temp_dir() / "debug"
    temp_debug_dir.mkdir(parents=True, exist_ok=True)
    debug = Debug(temp_debug_dir)
    debug.set("category_id_early", category_id_early)
    debug.set("category_hint_user", category_hint)
    debug.set("media_type", "book")
    debug.set("torrent_target", str(input_path))

    # ---- Naming livre ----
    from .core.naming.strategy import get_strategy
    naming_strategy = get_strategy(category_id_early)
    debug.set("naming_strategy", naming_strategy.name)
    # Sprint D.9 v0.5.0 : on injecte les overrides livre via un closure
    # `_book_lookup` qui pre-remplit le meta AVANT le lookup en ligne.
    # Si manual_isbn fourni, le lookup BnF/Google va l'utiliser direct
    # (au lieu de chercher par titre). Si manual_author/title fournis,
    # ils ecrasent l'extraction locale du fichier.
    # Sprint D.40 v0.5.0 : si manual_google_books_url fourni, on extrait
    # le volumeId et on fetch directement la fiche Google Books (bypasse
    # toute la recherche par titre/auteur).
    _strategy_kwargs = {}
    # Sprint D.40 : pre-extract du volumeId Google Books URL
    forced_gb_volume_id = ""
    if manual_google_books_url:
        from .core.providers.google_books import extract_volume_id_from_url
        forced_gb_volume_id = extract_volume_id_from_url(manual_google_books_url)
        debug.set("manual_google_books_url", manual_google_books_url)
        debug.set("manual_google_books_volume_id", forced_gb_volume_id)
    if (manual_isbn or manual_author or manual_book_title
            or manual_book_year or forced_gb_volume_id):
        from .core.providers.book_lookup import lookup_book_metadata

        def _book_lookup_with_overrides(meta):
            # Surcharge les champs livre AVANT le lookup en ligne.
            if manual_isbn:
                isbn_clean = manual_isbn.strip().replace("-", "").replace(" ", "")
                if len(isbn_clean) == 13 and isbn_clean.isdigit():
                    meta.isbn_13 = isbn_clean
                elif len(isbn_clean) == 10:
                    meta.isbn_10 = isbn_clean.upper()
            if manual_author:
                # Sprint D.21 fix : si l'user envoie un manual_author qui
                # ressemble a un release_name scene complet (avec dots et
                # tokens techniques), on le parse via scene_parser pour le
                # nettoyer. Sinon on prend la valeur brute. Cas reel : form
                # pre-fill ancien avant D.20 qui contenait
                # "Andrzej.Sapkowski" tokens dots.
                clean_author = manual_author.strip()
                if "." in clean_author and len(clean_author.split(".")) >= 2:
                    # Probablement un input pollue scene-like : on parse
                    from .core.providers._scene_parser import parse_book_filename
                    sp_author = parse_book_filename(clean_author)
                    if sp_author.authors:
                        clean_author = sp_author.authors[0]
                    else:
                        clean_author = clean_author.replace(".", " ").strip()
                meta.authors = [clean_author]
            if manual_book_title:
                # Sprint D.21 fix Bug-2 : pareil pour le title. Si l'input
                # ressemble a un release_name scene pollue (dots + tokens
                # techniques type 2026/FRENCH/MP3), on le passe au scene
                # parser pour ne garder que le vrai title. Sinon on prend
                # tel quel.
                clean_title = manual_book_title.strip()
                if "." in clean_title and len(clean_title.split(".")) >= 4:
                    # Long string avec beaucoup de dots : probablement un
                    # release_name scene mal-saisi (ou pre-fill ancien).
                    from .core.providers._scene_parser import parse_book_filename
                    sp = parse_book_filename(clean_title)
                    if sp.title:
                        clean_title = sp.title
                meta.title = clean_title
            # Sprint D.11 : annee forcee
            if manual_book_year and 1900 <= manual_book_year <= 2099:
                meta.publication_year = manual_book_year
            # Cache + Google API key depuis la config
            google_key = config.get_optional_env("GOOGLE_BOOKS_API_KEY", "")
            # Sprint D.40 : si on a un volumeId Google Books force, on fetch
            # la fiche directement et on merge prioritairement (authoritative).
            if forced_gb_volume_id:
                from .core.providers.google_books import fetch_volume_by_id
                gb_cache_file = config.data_dir() / ".google_books_cache.json"
                gb_meta = fetch_volume_by_id(
                    forced_gb_volume_id,
                    cache_file=gb_cache_file,
                    api_key=google_key,
                )
                if gb_meta is not None:
                    # Override authoritatif : Google Books force ecrase
                    # title/authors/publisher/year/cover_url etc.
                    meta.merge_from(gb_meta, "google_books_forced", authoritative=True)
            return lookup_book_metadata(
                meta,
                cache_dir=config.data_dir(),
                google_api_key=google_key,
            )

        _strategy_kwargs["_book_lookup"] = _book_lookup_with_overrides

    release_name, _ = naming_strategy.build_release_name(
        input_path, tracker, nfo_text="", debug=debug,
        **_strategy_kwargs,
    )
    print(f"[INFO] Release name : {release_name}")

    # ---- Creation du package_dir ----
    package_dir = config.packages_dir() / release_name
    # Protection : ne pas ecraser un package UPLOADED
    if package_dir.is_dir():
        from .core.package_state import read_state, PackageState
        existing_state = read_state(package_dir)
        if existing_state and existing_state.state == PackageState.UPLOADED:
            tid = existing_state.uploaded_torrent_id
            die(
                f"Deja uploade au tracker"
                f"{f' (ID {tid})' if tid else ''}. "
                f"Supprime le package via la page detail si tu veux recommencer."
            )
    package_dir.mkdir(parents=True, exist_ok=True)
    final_debug_dir = package_dir / "_debug"
    final_debug_dir.mkdir(parents=True, exist_ok=True)

    # ---- NFO minimaliste pour livre (Sprint D.5 ameliorera) ----
    book_meta = debug.data.get("book_metadata") or {}
    nfo_lines = [
        f"Release name : {release_name}",
        f"Categorie    : Livre / BD / Manga",
        "",
        f"Titre        : {book_meta.get('title', 'N/A')}",
        f"Auteur(s)    : {', '.join(book_meta.get('authors', []) or ['N/A'])}",
        f"Editeur      : {book_meta.get('publisher', 'N/A')}",
        f"Annee        : {book_meta.get('publication_year', 'N/A')}",
        f"Langue       : {book_meta.get('language', 'N/A')}",
        f"Format       : {book_meta.get('file_format', '').upper() or 'N/A'}",
        f"Pages        : {book_meta.get('page_count', 'N/A')}",
    ]
    if book_meta.get("isbn_13") or book_meta.get("isbn_10"):
        isbn = book_meta.get("isbn_13") or book_meta.get("isbn_10")
        nfo_lines.append(f"ISBN         : {isbn}")
    if book_meta.get("series"):
        idx = book_meta.get("series_index") or 0
        series_str = book_meta["series"]
        if idx:
            series_str += f" (tome {idx:g})"
        nfo_lines.append(f"Serie        : {series_str}")
    if book_meta.get("description"):
        nfo_lines.extend(["", "Resume :", book_meta["description"][:500]])
    sources = book_meta.get("sources") or []
    if sources:
        nfo_lines.append("")
        nfo_lines.append(f"Metadata fournies par : {', '.join(sources)}")

    nfo_path = package_dir / f"{release_name}.nfo"
    nfo_path.write_text("\n".join(nfo_lines), encoding="utf-8")
    print(f"[OK] NFO ebook genere : {nfo_path.name}")

    # ---- release_name.txt ----
    (package_dir / "release_name.txt").write_text(release_name + "\n", encoding="utf-8")

    # ---- Extraction de la couverture locale (Sprint D.7) ----
    # Si on n'a pas de cover_url depuis un provider en ligne, on tente
    # d'extraire la cover depuis le fichier source (EPUB/PDF/CBZ).
    if not book_meta.get("cover_url"):
        cover_extracted = _try_extract_local_cover(
            input_path, package_dir, book_meta,
        )
        if cover_extracted:
            # Reflet dans debug pour que la page detail / template BBCode
            # voient bien la cover.
            book_meta["cover_url"] = cover_extracted
            debug.set("book_metadata", book_meta)

    # ---- Sprint D.19 v0.5.0 : extraction cover + 4 previews + upload imgbb ----
    # Si IMGBB_API_KEY est configure, on extrait cover + N previews depuis
    # le fichier source et on upload tout vers imgbb. Les URLs publiques
    # sont stockees dans book_metadata.preview_urls, utilisees dans le
    # BBCode pour afficher une galerie tracker-readable.
    # Si pas de cle ou format non supporte : extraction locale seulement
    # (visible page detail, mais pas dans la fiche tracker).
    imgbb_key = config.get_optional_env("IMGBB_API_KEY", "")
    if imgbb_key:
        try:
            _try_extract_and_upload_previews(
                input_path, package_dir, book_meta, imgbb_key, debug=debug,
            )
            debug.set("book_metadata", book_meta)
        except Exception as e:
            print(f"[WARN] previews extraction/upload echec : {type(e).__name__} {e}")

    # ---- .torrent (cree AVANT BBCode pour Sprint D.12 : enrichissement
    # du BBCode livre avec contenu du torrent / nb fichiers / taille) ----
    torrent_path = package_dir / f"{release_name}.torrent"
    create_torrent(
        input_path, torrent_path,
        announce_url=tracker.announce_url,
        source=tracker.torrent_source,
        private=tracker.private,
    )

    # ---- BBCode livre (Sprint D.5 + D.12 enrichi avec contenu torrent) ----
    from .core.bbcode_book import render_book_bbcode, build_torrent_info
    from .core.providers.book_metadata import book_from_dict
    book_meta_obj = book_from_dict(book_meta)
    # Sprint D.14 : file_format est maintenant proprement (de)serialise dans
    # book_to_dict/book_from_dict. Plus besoin de patcher en post.
    # Sprint D.12 : compute torrent contents (file count, list, total size).
    # Le .torrent existe deja (cree juste avant), on peut le lire.
    torrent_info = build_torrent_info(torrent_path)
    try:
        bbcode = render_book_bbcode(
            book_meta_obj, release_name, tracker,
            torrent_info=torrent_info,
        )
        (package_dir / "presentation.txt").write_text(bbcode, encoding="utf-8")
        print(f"[OK] BBCode livre genere : presentation.txt ({len(bbcode)} chars)")
    except Exception as e:
        print(f"[WARN] BBCode livre echec : {type(e).__name__} {e}. Fallback texte simple.")
        # Au minimum, on garde le NFO comme presentation
        (package_dir / "presentation.txt").write_text(
            "\n".join(nfo_lines), encoding="utf-8",
        )

    # ---- Compliance ebook ----
    from .core.compliance import (
        check_compliance, format_report, has_blocking, Severity,
    )
    issues = check_compliance(
        release_name, mediainfo_data={}, media_info=None,
        torrent_target=input_path,
        banned_teams=config.banned_teams_list(),
        category_id=category_id_early,
        package_dir=package_dir,
    )
    debug.set("compliance_issues", [str(i) for i in issues])
    if issues:
        print()
        print(format_report(issues))

    # ---- State init ----
    debug.output_dir = final_debug_dir
    debug.save()
    from .core.package_state import init_state, transition, PackageState
    from .core.package_state import read_state, write_state
    init_state(package_dir, release_name, tracker.key)

    # Sprint D.21 fix Bug-1 : on persiste TOUJOURS manual_category_id =
    # CATEGORY_BOOKS pour les livres. Sinon resolve_effective_category lit
    # debug.json {media_type: "book"} qui n'est pas un MediaType enum
    # (qui n'a que movie/tv_*), tombe en ValueError, fallback CATEGORY_MOVIE.
    # Resultat avant fix : un livre re-prepare passait en categorie "Film"
    # apres re-prepare meme sans changement de l'user.
    _state_data = read_state(package_dir)
    if _state_data is not None:
        new_cat_id = (
            int(category_hint)
            if (category_hint is not None and category_hint > 0)
            else int(category_id_early)  # = CATEGORY_BOOKS pour _process_book
        )
        if _state_data.manual_category_id != new_cat_id:
            _state_data.manual_category_id = new_cat_id
            write_state(package_dir, _state_data)

    # Si compliance bloquante -> state FAILED
    if issues and has_blocking(issues):
        blocking_msgs = [i.message for i in issues if i.severity == Severity.BLOCKING]
        transition(
            package_dir, PackageState.FAILED,
            note="Conformite ebook : " + " | ".join(blocking_msgs[:3])
                 + ("…" if len(blocking_msgs) > 3 else ""),
        )
        print(
            f"[FAILED] {len(blocking_msgs)} violation(s) dure(s) de la charte "
            "Gemini ebook — package marque en echec."
        )

    print("\n[TERMINE]")
    print(f"Tracker : {tracker.display_name}")
    print(f"Type media : ebook")
    print(f"Dossier package : {package_dir}")
    print(f"Release name : {release_name}")
    return package_dir


def _try_extract_local_cover(
    input_path: Path,
    package_dir: Path,
    book_meta: dict,
) -> str:
    """Tente d'extraire la couverture depuis le fichier source vers le package.

    Sprint D.7 v0.5.0 — augmente le taux de couverture (0/33 sur tests reels).

    Args:
        input_path : path du fichier source (.epub / .pdf / .cbz / .cbr).
        package_dir : dossier package ou stocker la cover extraite.
        book_meta : dict des metadonnees livre (pour file_format).

    Returns:
        URL relative (ex: "cover.jpg") de la cover si extraite, sinon "".
        L'URL est relative au package_dir et sera resolue par la route
        `/packages/{name}/cover` cote web app.
    """
    if not input_path.is_file():
        return ""
    ext = input_path.suffix.lower()
    output = package_dir / "cover.jpg"
    try:
        if ext == ".epub":
            from .core.providers.epub_metadata import extract_epub_cover
            if extract_epub_cover(input_path, output):
                # Renommer si l'extension reelle est differente (PNG/webp)
                # On garde .jpg pour simplifier le servage; le navigateur
                # devine le content-type au header.
                return f"/packages/{package_dir.name}/cover"
        elif ext == ".cbz":
            from .core.providers.cbz_metadata import extract_cbz_cover
            if extract_cbz_cover(input_path, output):
                return f"/packages/{package_dir.name}/cover"
        elif ext == ".pdf":
            from .core.providers.pdf_metadata import extract_pdf_cover
            if extract_pdf_cover(input_path, output):
                return f"/packages/{package_dir.name}/cover"
    except Exception as e:
        print(f"[WARN] cover extraction local ({ext}) : {type(e).__name__} {e}")
        return ""
    return ""


def _try_extract_and_upload_previews(
    input_path: Path,
    package_dir: Path,
    book_meta: dict,
    imgbb_api_key: str,
    debug: "Debug | None" = None,
) -> None:
    """Sprint D.19 v0.5.0 (note Louis Q3) : extrait cover + 4 previews et
    upload sur host externe (imgbb + fallback Imgur D.42). Modifie
    book_meta in-place :
      - book_meta['cover_url'] : URL externe (override cover locale si
        on en avait extrait une avant)
      - book_meta['preview_urls'] : liste d'URLs externes des previews

    Sprint D.42 v0.5.0 (feedback Louis) : si IMGUR_CLIENT_ID est configure,
    on bascule sur Imgur quand imgbb rate-limit. La fonction upload_image
    abstrait ce choix.

    Si l'extraction echoue ou les 2 hosts refusent, on log + on continue
    (le BBCode sera juste plus pauvre, le pipeline ne plante pas).
    """
    from .core.providers.image_extraction import extract_cover_and_previews
    from .core.providers.image_host import upload_image

    # Sprint D.42 : lire Imgur Client-ID en complement de la cle imgbb.
    imgur_client_id = config.get_optional_env("IMGUR_CLIENT_ID", "")

    previews_dir = package_dir / "_previews"
    if imgur_client_id:
        print(f"[INFO] Extraction cover + previews (imgbb + fallback Imgur)...")
    else:
        print(f"[INFO] Extraction cover + previews (imgbb seul)...")

    extracted = extract_cover_and_previews(
        input_path, previews_dir, preview_count=4,
    )
    if extracted.get("warning"):
        print(f"[INFO] Extraction previews : {extracted['warning']}")

    # Sprint D.24 v0.5.0 (note Louis N-LS1) : fallback cover backup depuis
    # le dossier source. Si un fichier "cover.*" / "couverture.*" / "front.*"
    # existe a cote du fichier ebook, on le prefere a la cover extraite
    # du fichier (l'user qui a mis ce fichier l'a fait expres : c'est la
    # VRAIE cover, pas une 1re page de PDF qui est juste un titre interne).
    cover_local = extracted.get("cover")
    folder_cover = _find_folder_cover(input_path, previews_dir)
    if folder_cover is not None:
        cover_local = folder_cover
        print(f"[INFO] Cover backup detectee dans le dossier source : {folder_cover.name}")

    # Sprint D.38 v0.5.0 (feedback Louis) : la cover LOCALE a TOUJOURS
    # priorite si elle est extraite du fichier. La cover web (BnF/Google)
    # est conservee dans web_cover_url pour comparaison visuelle sur la
    # page detail. Avant : on n'uploadait pas la cover locale si une web
    # existait deja -> Louis voulait l'inverse.
    current_cover_url = book_meta.get("cover_url", "")
    is_current_web = (
        current_cover_url.startswith(("http://", "https://"))
        and "i.ibb.co" not in current_cover_url
    )
    # Sauvegarde le web_cover_url avant override par local (pour comparaison)
    if is_current_web and not book_meta.get("web_cover_url"):
        book_meta["web_cover_url"] = current_cover_url

    # Sprint D.41 v0.5.0 (feedback Louis) : on track les rate-limits imgbb
    # pour les remonter dans la note (banner orange UI + suggestion de
    # re-prepare plus tard). Distinct des autres echecs imgbb (cle invalide,
    # fichier trop gros, network) qui n'ont aucun benefice a re-tenter.
    imgbb_rate_limited = False
    imgbb_failures: list[str] = []  # libelle de chaque image qui a echoue

    # Upload la cover LOCALE et l'utiliser pour la presentation (override web).
    if cover_local:
        result = upload_image(
            cover_local,
            imgbb_api_key=imgbb_api_key,
            imgur_client_id=imgur_client_id,
        )
        if result.success:
            book_meta["cover_url"] = result.url
            print(f"[OK] Cover LOCALE uploadee ({result.host}) -> {result.url}")
        else:
            print(f"[WARN] Cover upload echec : {result.error}")
            if result.rate_limited:
                imgbb_rate_limited = True
                imgbb_failures.append("cover")

    # Upload previews
    preview_paths = extracted.get("previews") or []
    if preview_paths:
        uploaded_urls: list[str] = []
        for i, p in enumerate(preview_paths, start=1):
            result = upload_image(
                p,
                imgbb_api_key=imgbb_api_key,
                imgur_client_id=imgur_client_id,
            )
            if result.success:
                uploaded_urls.append(result.url)
                print(f"[OK] Preview {i}/{len(preview_paths)} uploaded ({result.host}) -> {result.url}")
            else:
                print(f"[WARN] Preview {i} upload echec : {result.error}")
                if result.rate_limited:
                    imgbb_rate_limited = True
                    imgbb_failures.append(f"preview_{i}")
        if uploaded_urls:
            book_meta["preview_urls"] = uploaded_urls

    # Sprint D.41 : propage le flag rate-limited dans book_meta pour qu'il
    # soit visible dans debug.json -> Confidence + UI.
    if imgbb_rate_limited:
        book_meta["imgbb_rate_limited"] = True
        book_meta["imgbb_failed_images"] = imgbb_failures
        print(
            f"[WARN] imgbb rate limit atteint sur {len(imgbb_failures)} image(s) "
            f"({', '.join(imgbb_failures)}). Re-prepare plus tard pour completer "
            f"la fiche."
        )
        # Emet le signal de naming pour que le score reflete la situation
        # et que le panneau "Detail du score" affiche le warning.
        if debug is not None:
            try:
                from .core import naming_signals as _ns
                _ns.emit_signal(debug, _ns.SIG_IMGBB_RATE_LIMITED, True)
            except Exception:
                pass


# Noms de fichiers cover backup reconnus (case-insensitive).
# On preserve l'extension reelle (jpg/png/webp/...).
_COVER_BACKUP_STEMS = frozenset({
    "cover", "couverture", "couv", "front", "frontcover",
    "folder",  # standard Windows musique/cover
    "thumb", "thumbnail",
})
_COVER_BACKUP_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
})


def _find_folder_cover(input_path: Path, output_dir: Path) -> Path | None:
    """Sprint D.24 v0.5.0 (note Louis N-LS1) : cherche un fichier cover de
    backup a cote du fichier source.

    Strategies (par ordre de priorite) :
    1. Si input_path est un FICHIER : cherche dans son dossier parent
       les fichiers cover.* / couverture.* / front.* / folder.*
    2. Si input_path est un DOSSIER : cherche dedans (root level uniquement,
       pas recursif).

    Si trouve, copie le fichier dans output_dir et retourne le Path local.
    Sinon retourne None.

    Le fichier est COPIE (pas link) pour eviter d'avoir des refs vers le
    dossier source qui pourrait disparaitre (NAS deconnecte, etc.).
    """
    try:
        if input_path.is_file():
            search_dir = input_path.parent
        elif input_path.is_dir():
            search_dir = input_path
        else:
            return None

        if not search_dir.is_dir():
            return None

        # Lister les fichiers a cote (non recursif, sinon trop de bruit)
        for child in sorted(search_dir.iterdir()):
            if not child.is_file():
                continue
            stem_lower = child.stem.lower()
            ext_lower = child.suffix.lower()
            if (stem_lower in _COVER_BACKUP_STEMS
                    and ext_lower in _COVER_BACKUP_EXTS):
                # Copie dans output_dir pour traitement
                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / f"folder_cover{ext_lower}"
                import shutil
                shutil.copyfile(child, target)
                # Sprint D.42 : recompresse aussi le folder cover (Pillow
                # optionnel ; no-op si pas installe).
                try:
                    from .core.providers.image_extraction import (
                        _maybe_recompress_external_image,
                    )
                    _maybe_recompress_external_image(target)
                except Exception:
                    pass
                return target
        return None
    except (OSError, PermissionError) as e:
        print(f"[WARN] _find_folder_cover : {type(e).__name__} {e}")
        return None
