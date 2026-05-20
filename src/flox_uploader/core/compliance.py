"""Verification de conformite : release_name vs MediaInfo reel + regles Gemini.

Compare ce que le release name AFFICHE avec ce que MediaInfo DETECTE dans le
fichier video, ET applique les regles strictes de la charte G3MINI TR4CK3R
(MKV obligatoire, MP3 interdit, teams interdites, etc.).

Conformement a la charte Gemini : "Permet d'identifier immediatement la source,
la qualite, la langue, le codec, l'equipe". Si un de ces champs est faux dans
le release name OU si le pack viole une regle dure, l'upload est rejete.

Trois niveaux de severite :
- WARN     : info, n'empeche rien (ex : russe present, saison incomplete).
- ERROR    : divergence visible, le user doit verifier mais l'upload reste possible
             (ex : codec annonce vs detecte). Penalise le score.
- BLOCKING : violation dure de la charte. Le pipeline va die() et marquer
             le package en FAILED (ex : MKV absent, team interdite, MP3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Severity(Enum):
    WARN = "WARN"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


@dataclass
class ComplianceIssue:
    severity: Severity
    field: str
    message: str

    def __str__(self) -> str:
        if self.severity == Severity.BLOCKING:
            prefix = "[BLOCKED]"
        elif self.severity == Severity.ERROR:
            prefix = "[!! ERROR]"
        else:
            prefix = "[ WARN ]"
        return f"{prefix} {self.field}: {self.message}"


# ============================================================
# Constantes G3MINI (charte officielle PDF)
# ============================================================

# Teams qui ne peuvent faire QUE des encodes (pas de remux/raw).
# Si on detecte un de ces teams sur un release type "REMUX" ou "BluRay" raw -> BLOCKING.
TEAMS_ENCODE_ONLY: tuple[str, ...] = ("EXTREME",)

# Teams interdites par defaut (peuvent etre etendues via .env BANNED_TEAMS).
# Source : doc PDF G3MINI TR4CK3R - TEAMS INTERDITES. Cette liste est un
# point de depart : l'utilisateur peut la mettre a jour depuis /config car
# elle change frequemment cote tracker.
DEFAULT_BANNED_TEAMS: tuple[str, ...] = ("k0RE", "Slay3R")


# ============================================================
# CHECKS INDIVIDUELS - DIVERGENCE NOM <-> MEDIAINFO
# ============================================================

def _check_resolution(release_name: str, mi_video: dict) -> list[ComplianceIssue]:
    """Verifie que la resolution annoncee dans le nom correspond au media."""
    detected = (mi_video.get("resolution_label") or "").lower()
    if not detected:
        return []
    name_lower = release_name.lower()
    name_resolutions = re.findall(r"(2160p|1080p|1080i|720p|576p|480p|480i)", name_lower)
    if not name_resolutions:
        return [ComplianceIssue(
            Severity.ERROR, "resolution",
            f"Aucune resolution dans le nom alors que MediaInfo detecte {detected}"
        )]
    if detected not in name_resolutions:
        return [ComplianceIssue(
            Severity.ERROR, "resolution",
            f"Nom annonce {name_resolutions} mais MediaInfo detecte {detected}"
        )]
    return []


def _check_video_codec(release_name: str, mi_video: dict) -> list[ComplianceIssue]:
    """Verifie codec video : x264/x265/HEVC/AVC dans le nom <-> codec reel."""
    detected_codec = (mi_video.get("codec") or "").lower()
    if not detected_codec:
        return []
    name = release_name.lower()

    is_hevc = "hevc" in detected_codec or "x265" in detected_codec or "h.265" in detected_codec
    is_avc = "avc" in detected_codec or "x264" in detected_codec or "h.264" in detected_codec

    name_says_hevc = any(t in name for t in ["x265", "hevc", "h.265", "h265"])
    name_says_avc = any(t in name for t in ["x264", "avc", "h.264", "h264"])

    if is_hevc and name_says_avc and not name_says_hevc:
        return [ComplianceIssue(
            Severity.ERROR, "video_codec",
            "Le nom dit AVC/x264 mais MediaInfo detecte HEVC/x265"
        )]
    if is_avc and name_says_hevc and not name_says_avc:
        return [ComplianceIssue(
            Severity.ERROR, "video_codec",
            "Le nom dit HEVC/x265 mais MediaInfo detecte AVC/x264"
        )]
    if (is_hevc or is_avc) and not (name_says_hevc or name_says_avc):
        return [ComplianceIssue(
            Severity.WARN, "video_codec",
            f"MediaInfo detecte {detected_codec} mais aucun tag codec video dans le nom"
        )]
    return []


def _check_audio_codec(release_name: str, audio_tracks: list[dict]) -> list[ComplianceIssue]:
    """Verifie que le codec audio annonce correspond a la piste principale."""
    if not audio_tracks:
        return []
    main_codec = (audio_tracks[0].get("codec") or "").upper()
    if not main_codec:
        return []
    name = release_name.upper()

    # Les noms canoniques attendus dans le release name
    codec_aliases = {
        "DDP": ["DDP", "E-AC3", "EAC3", "DOLBY.DIGITAL.PLUS"],
        "DD": ["DD", "AC3", "AC-3", "DOLBY.DIGITAL"],
        "DTS": ["DTS"],
        "DTS-HD MA": ["DTS-HD", "DTS-HDMA", "DTS.MA"],
        "TRUEHD": ["TRUEHD", "MLP"],
        "AAC": ["AAC"],
        "FLAC": ["FLAC"],
        "OPUS": ["OPUS"],
    }
    expected = codec_aliases.get(main_codec, [main_codec])
    if not any(alias in name for alias in expected):
        return [ComplianceIssue(
            Severity.WARN, "audio_codec",
            f"Piste audio principale est {main_codec} mais aucun alias trouve dans le nom (cherche : {expected})"
        )]
    return []


def _check_audio_channels(release_name: str, audio_tracks: list[dict]) -> list[ComplianceIssue]:
    """Verifie le layout audio (5.1 / 7.1 / etc.) dans le nom vs MediaInfo.

    Sprint 8 hotfix v16 : refonte de la detection + check apres 3 faux positifs
    rapportes par Louis (Edge of Tomorrow, Elemental, Everythings).

    Fix 1 (regex) : avant on utilisait deux regex separes —
      - `\\b\\d\\.\\d\\b` (rate les formats colles `AC35.1`/`DDP5.1`)
      - `[A-Z]\\d\\.\\d` (faux positif `F2.2` dans `VF2.2160p`)
    Maintenant : `\\d\\.\\d(?!\\d)` (digit-point-digit non suivi de digit).
    Match `5.1`, `7.1`, `2.0` partout (y compris colles `AC35.1`), evite `2.2`
    de `VF2.2160p` (suivi de `1` -> lookahead negatif fail).

    Fix 2 (check) : avant on comparait uniquement avec `audio_tracks[0]`
    (piste principale). Si le release contient 2 pistes (ex: une 7.1 default
    + une 5.1 alternative) et l'user a tagge la 5.1 dans le nom, on faussait
    le warning. Maintenant : on accepte le nom si N'IMPORTE QUELLE piste
    match. Le warning ne se declenche que si AUCUNE piste ne match.
    """
    if not audio_tracks:
        return []
    # Toutes les channels detectees par MediaInfo (toutes pistes, pas juste la 1ere)
    all_channels = {
        (t.get("channels") or "").strip()
        for t in audio_tracks
        if (t.get("channels") or "").strip()
    }
    if not all_channels:
        return []

    # Extraction des layouts dans le nom : digit.digit non suivi d'un digit.
    # Exclut donc `2.2160` (resolution `2160p`) qui aurait matche le pattern
    # `2.2` avec les regex precedents.
    name = release_name
    found = re.findall(r"\d\.\d(?!\d)", name)

    if not found:
        # Pour le message : on indique la piste principale comme reference
        # (mais on accepterait n'importe quelle piste si elle etait dans le nom).
        main_channels = (audio_tracks[0].get("channels") or "").strip()
        return [ComplianceIssue(
            Severity.WARN, "audio_channels",
            f"Piste principale est {main_channels} mais aucun layout dans le nom"
        )]
    # Au moins UNE piste audio doit matcher au moins UN layout dans le nom.
    if not (set(found) & all_channels):
        return [ComplianceIssue(
            Severity.WARN, "audio_channels",
            f"Nom dit {found} mais MediaInfo detecte uniquement "
            f"{sorted(all_channels)} (aucune piste ne correspond)"
        )]
    return []


def _check_hdr(release_name: str, mi_video: dict) -> list[ComplianceIssue]:
    """Verifie que HDR est mentionne si le media est HDR."""
    detected_hdr = (mi_video.get("hdr") or "").upper()
    if detected_hdr in {"", "SDR"}:
        return []
    name = release_name.upper()
    hdr_tags = ["HDR", "HDR10", "HDR10+", "DOVI", "DV.HLG", "HLG", "PQ10"]
    if not any(tag in name for tag in hdr_tags):
        return [ComplianceIssue(
            Severity.WARN, "hdr",
            f"MediaInfo detecte {detected_hdr} mais aucun tag HDR dans le nom"
        )]
    return []


def _check_french_audio_in_name(release_name: str, audio_tracks: list[dict]) -> list[ComplianceIssue]:
    """Verifie qu'au moins un tag FR est dans le nom si une piste FR existe."""
    has_fr_audio = any((t.get("language") or "").lower() == "fr" for t in audio_tracks)
    if not has_fr_audio:
        return []
    name = release_name.upper()
    fr_tags = [
        "MULTI", "MULTi", "VFF", "VFQ", "VFB", "VF2", "VOF", "VOQ", "VOB",
        "FRENCH", "TRUEFRENCH", "VOSTFR", "SUBFRENCH",
    ]
    if not any(tag in name for tag in fr_tags):
        return [ComplianceIssue(
            Severity.ERROR, "language",
            "Piste audio FR detectee mais aucun tag langue (MULTi/VFF/VFQ/...) dans le nom"
        )]
    return []


def _check_vfi_not_present(release_name: str) -> list[ComplianceIssue]:
    """Charte Gemini : VFi est interdit, doit etre VFF ou VFQ."""
    if re.search(r"\bVFi\b", release_name, flags=re.IGNORECASE):
        return [ComplianceIssue(
            Severity.ERROR, "language",
            "VFi present dans le nom : la charte Gemini exige VFF ou VFQ"
        )]
    return []


def _check_multi_has_variant(release_name: str) -> list[ComplianceIssue]:
    """Charte Gemini : MULTi sans precision = upload rejete."""
    name = release_name.upper()
    has_multi = re.search(r"\bMULTI\b", name) is not None
    if not has_multi:
        return []
    has_precise = any(
        f"MULTI.{v}" in name or f".{v}." in f".{name}." or name.endswith(f".{v}")
        for v in ["VFF", "VFQ", "VFB", "VF2"]
    )
    if not has_precise:
        return [ComplianceIssue(
            Severity.ERROR, "language",
            "MULTi present sans precision VFF/VFQ/VFB/VF2 (upload sera rejete)"
        )]
    return []


def _check_team_present(release_name: str) -> list[ComplianceIssue]:
    """Charte Gemini : TEAM apres tiret final, jamais vide."""
    if not re.search(r"-[A-Za-z0-9._+-]+$", release_name):
        return [ComplianceIssue(
            Severity.ERROR, "team",
            "Pas de team detectee en fin de nom (format attendu : '...-TEAM')"
        )]
    return []


def _check_media_type_tag(release_name: str, media_info) -> list[ComplianceIssue]:
    """Verifie qu'on a le bon tag dans le release name selon le media_type."""
    if media_info is None:
        return []
    from .media_type import MediaType
    name = release_name.upper()

    if media_info.media_type == MediaType.TV_EPISODE:
        if media_info.season is not None and media_info.episode is not None:
            expected = f"S{media_info.season:02d}E{media_info.episode:02d}"
            if expected not in name:
                return [ComplianceIssue(
                    Severity.ERROR, "media_type",
                    f"Episode mais tag {expected} absent du release name"
                )]
    elif media_info.media_type == MediaType.TV_SEASON:
        if media_info.season is not None:
            expected = f"S{media_info.season:02d}"
            if expected not in name or "COMPLETE" not in name:
                return [ComplianceIssue(
                    Severity.ERROR, "media_type",
                    f"Saison mais tag {expected}.COMPLETE absent du release name"
                )]
    elif media_info.media_type == MediaType.TV_INTEGRALE:
        if "INTEGRALE" not in name:
            return [ComplianceIssue(
                Severity.ERROR, "media_type",
                "Integrale mais tag iNTEGRALE absent du release name"
            )]
    return []


# ============================================================
# CHECKS INDIVIDUELS - REGLES DURES G3MINI (Lot K)
# ============================================================

def _check_container_mkv(mediainfo_data: dict) -> list[ComplianceIssue]:
    """C1 — Charte Gemini : conteneur OBLIGATOIRE MKV pour video.

    Exception : DVD (categorie qui accepte VOB/IFO) et raw BluRay (M2TS).
    Pour tout encode, remux, web : MKV est exige.
    """
    container = (mediainfo_data.get("container") or "").upper()
    if not container:
        return []
    # Acceptes : MATROSKA (.mkv) — c'est le seul vraiment toleré pour Gemini.
    # Tolere : pour les categories raw (BluRay full disc, DVD), on a M2TS / VOB
    # mais on est rarement la-dedans dans le pipeline (qui torrente des fichiers).
    if "MATROSKA" in container:
        return []
    # M2TS/VOB sont specifiques aux full discs — peu probables ici, on warn.
    if container in {"BDAV", "MPEG-TS", "VOB", "ISO"}:
        return [ComplianceIssue(
            Severity.WARN, "container",
            f"Conteneur {container} detecte. Gemini exige MKV pour les encodes "
            "(toleré pour Full Disc/DVD uniquement)."
        )]
    # MP4, AVI, etc. : interdit.
    return [ComplianceIssue(
        Severity.BLOCKING, "container",
        f"Conteneur {container} interdit par la charte Gemini. "
        "Le fichier doit etre un MKV (MATROSKA). Re-mux requis avant upload."
    )]


def _check_audio_codec_allowed(audio_tracks: list[dict]) -> list[ComplianceIssue]:
    """C2 — MP3 interdit. FLAC autorise uniquement en mono / stereo."""
    issues: list[ComplianceIssue] = []
    for i, t in enumerate(audio_tracks):
        codec = (t.get("codec") or "").upper()
        channels = (t.get("channels") or "").strip()
        title = (t.get("title") or "").strip()
        # Skip pistes auxiliaires (commentaires, AD) : on verifie surtout
        # la qualite des pistes principales.
        if t.get("is_commentary") or t.get("is_audio_description"):
            continue
        # MP3 interdit, peu importe le contexte.
        if codec == "MP3" or codec.startswith("MPEG AUDIO"):
            issues.append(ComplianceIssue(
                Severity.BLOCKING, "audio_codec",
                f"Piste audio #{i+1} ({title or 'sans titre'}) en MP3 — "
                "interdit par la charte Gemini. Reencoder en AAC/AC3/DDP."
            ))
            continue
        # FLAC autorise uniquement en 1.0 / 2.0.
        if codec == "FLAC":
            if channels and channels not in {"1.0", "2.0"}:
                issues.append(ComplianceIssue(
                    Severity.BLOCKING, "audio_codec",
                    f"Piste audio #{i+1} en FLAC {channels} — "
                    "Gemini autorise FLAC uniquement en mono ou stereo."
                ))
    return issues


def _check_pgs_in_encode(
    subtitle_tracks: list[dict], release_name: str,
) -> list[ComplianceIssue]:
    """C3 — Sous-titres PGS dans un encode.

    Règle Gemini precisee (Louis) :
    - REMUX / Full Disc : toujours OK, on ne check rien (preserve la source)
    - Encode AVEC PGS ET subs texte (SRT/ASS/SSA/UTF-8) : OK
      (les subs texte sont la, le PGS est juste un bonus tolere)
    - Encode AVEC PGS UNIQUEMENT (aucun sub texte) : WARN bleu (~3 pts)
      Le user devrait soit ajouter des subs texte, soit re-mux en REMUX.
      Pas bloquant : la release peut quand meme partir.

    Avant : tout PGS dans un encode etait BLOCKING -> trop strict.
    """
    if not subtitle_tracks:
        return []
    name_upper = release_name.upper()
    is_remux_or_full = "REMUX" in name_upper or "FULL.DISC" in name_upper
    if is_remux_or_full:
        return []
    # Detection "encode" elargie (post-NOTES round 4) : on flag aussi quand
    # le release contient juste un codec encode (x264/x265/AV1/HEVC/AVC) sans
    # tag source explicite. Cas reel : "Red.Shoes...1080p.x264-mHDgz" (BDRip
    # ou WEBRip non tague). Avant : on ratait ce cas et le PGS passait.
    is_encode = (
        any(t in name_upper for t in (
            "BDRIP", "WEBRIP", "HDTV", "WEB-DL", "WEB.DL", "BLURAY",
        ))
        or any(t in name_upper for t in (
            "X264", "X265", "H.264", "H.265", "H264", "H265", "HEVC", "AVC", "AV1",
        ))
    )
    if not is_encode:
        return []
    pgs_subs = [t for t in subtitle_tracks if (t.get("format") or "").upper() == "PGS"]
    if not pgs_subs:
        return []

    # Y a-t-il au moins une piste sub TEXTE (SRT/ASS/SSA/UTF-8/SUBRIP) ?
    # Si oui : PGS toleré en bonus, AUCUN warning.
    TEXT_SUB_FORMATS = {
        "UTF-8", "UTF8", "SRT", "SUBRIP", "ASS", "SSA",
        "WEBVTT", "VTT", "MICRODVD", "USF",
    }
    has_text_sub = any(
        (t.get("format") or "").upper() in TEXT_SUB_FORMATS
        for t in subtitle_tracks
    )
    if has_text_sub:
        return []  # PGS + texte = OK, pas de warning

    # PGS uniquement, sans sub texte : WARN bleu (~3 pts via signal dedie).
    # Pas bloquant — l'upload peut quand meme passer, mais on signale que
    # ce serait mieux d'ajouter des subs texte ou de re-mux.
    return [ComplianceIssue(
        Severity.WARN, "subtitles",
        f"{len(pgs_subs)} sous-titre(s) PGS uniquement (aucun SRT/ASS) — "
        "Gemini préfère les subs texte. Considérer ajouter des SRT "
        "ou re-muxer en REMUX. Non bloquant."
    )]


def _check_season_complete(media_info) -> list[ComplianceIssue]:
    """C5 — Saison incomplete : episodes non consecutifs dans un pack TV_SEASON."""
    if media_info is None:
        return []
    from .media_type import MediaType
    if media_info.media_type != MediaType.TV_SEASON:
        return []
    if not media_info.all_videos or len(media_info.all_videos) < 2:
        return []

    # Extrait le numero d'episode de chaque fichier
    episode_pattern = re.compile(r"S\d{1,2}E(\d{1,3})", re.IGNORECASE)
    episodes_found: list[int] = []
    for v in media_info.all_videos:
        m = episode_pattern.search(v.name)
        if m:
            episodes_found.append(int(m.group(1)))
    if len(episodes_found) < 2:
        return []
    episodes_found = sorted(set(episodes_found))
    expected = list(range(min(episodes_found), max(episodes_found) + 1))
    missing = [e for e in expected if e not in episodes_found]
    if not missing:
        return []
    if len(missing) > 5:
        miss_label = f"{missing[0]:02d}, {missing[1]:02d}, … ({len(missing)} manquants)"
    else:
        miss_label = ", ".join(f"{e:02d}" for e in missing)
    return [ComplianceIssue(
        Severity.WARN, "season_completeness",
        f"Saison incomplete : episode(s) {miss_label} manquants entre "
        f"E{min(episodes_found):02d} et E{max(episodes_found):02d}. "
        "Charte Gemini : un pack saison doit etre complet — verifier."
    )]


def _check_multi_team_in_pack(
    media_info, release_name: str,
) -> list[ComplianceIssue]:
    """C6 — Pack TV avec plusieurs teams differentes.

    Si saison/integrale et que les episodes ne viennent pas tous du meme uploader,
    le pack est mixte — Gemini prefere des packs homogenes.
    """
    if media_info is None:
        return []
    from .media_type import MediaType
    if media_info.media_type not in {MediaType.TV_SEASON, MediaType.TV_INTEGRALE}:
        return []
    if not media_info.all_videos or len(media_info.all_videos) < 2:
        return []

    # Extrait la team de chaque fichier : on prend le stem (sans extension)
    # et on applique la meme logique que _extract_team — segment apres le
    # dernier tiret. Tolere les chiffres, lettres, underscores, points.
    teams_found: dict[str, int] = {}
    for v in media_info.all_videos:
        stem = v.stem  # ex: "Show.S01E01.MULTi.VFF.1080p.WEB-DL.x265-TEAM_A"
        team = _extract_team(stem)
        if team:
            teams_found[team] = teams_found.get(team, 0) + 1
    if len(teams_found) < 2:
        return []
    summary = ", ".join(f"{t} ({n})" for t, n in sorted(teams_found.items()))
    return [ComplianceIssue(
        Severity.WARN, "team_consistency",
        f"Pack contient plusieurs teams differentes : {summary}. "
        "Charte Gemini : un pack saison doit avoir une team coherente."
    )]


def _check_russian_audio(audio_tracks: list[dict]) -> list[ComplianceIssue]:
    """C7 — Piste russe detectee.

    Charte Gemini : interdit. On warn (pas de blocage) pour laisser le
    user demuxer s'il veut, sans casser son workflow.
    """
    russian_tracks = [
        t for t in audio_tracks
        if (t.get("language") or "").lower() == "ru"
    ]
    if not russian_tracks:
        return []
    return [ComplianceIssue(
        Severity.WARN, "language_blacklist",
        f"{len(russian_tracks)} piste(s) russe(s) detectee(s). "
        "Charte Gemini : pistes russes interdites — demuxer avant upload."
    )]


def _extract_team(release_name: str) -> str:
    """Extrait la team du release_name (suffixe '-TEAM' a la fin).

    On utilise `[^-]+` (et non `[A-Za-z0-9._+-]+`) pour ne capturer QUE le
    segment apres le DERNIER tiret. Sinon des sous-chaines comme `WEB-DL`
    feraient matcher l'engine au mauvais endroit (ex: `WEB-DL.x265-k0RE`
    -> capture `DL.x265-k0RE` au lieu de `k0RE`).
    """
    m = re.search(r"-([^-]+)$", release_name)
    return m.group(1).strip() if m else ""


def _check_banned_team(
    release_name: str, banned_teams: list[str] | None,
) -> list[ComplianceIssue]:
    """C8 — Team interdite par le tracker.

    Liste configurable depuis /config (env BANNED_TEAMS). Defaut : k0RE, Slay3R.
    Cas-insensitive. BLOCKING : le pipeline marque le package en FAILED.
    """
    team = _extract_team(release_name)
    if not team:
        return []
    pool = list(DEFAULT_BANNED_TEAMS) + list(banned_teams or [])
    pool_lower = {t.lower().strip() for t in pool if t and t.strip()}
    if team.lower() in pool_lower:
        return [ComplianceIssue(
            Severity.BLOCKING, "team",
            f"Team '{team}' interdite par le tracker Gemini. "
            "Upload refuse — le package est marque en echec. "
            "(Liste editable depuis /config)"
        )]
    return []


def _check_extreme_team_only_encodes(
    release_name: str,
) -> list[ComplianceIssue]:
    """C9 — La team EXTREME ne peut faire que des encodes (pas de remux/raw).

    Charte Gemini specifique : si on detecte EXTREME en team sur un REMUX
    ou un BluRay raw, on bloque.
    """
    team = _extract_team(release_name)
    if team.upper() not in {t.upper() for t in TEAMS_ENCODE_ONLY}:
        return []
    name_upper = release_name.upper()
    is_remux_or_raw = (
        "REMUX" in name_upper
        or re.search(r"\bBLURAY\b", name_upper) and not re.search(r"\b(BDRIP|X264|X265|HEVC|AVC)\b", name_upper)
    )
    if is_remux_or_raw:
        return [ComplianceIssue(
            Severity.BLOCKING, "team_scope",
            f"Team '{team}' n'est autorisee que pour les encodes "
            "(BDRip / WEBRip). Detectee sur un REMUX ou BluRay raw."
        )]
    return []


def _check_crf_in_range(mi_video: dict) -> list[ComplianceIssue]:
    """Lot M — CRF hors plage recommandee Gemini (WARN uniquement).

    Plages issues du PDF "Regles d'encodage" G3MINI :

      x264 8-bit  720p / 1080p : 18 - 21
      x265 10-bit 720p          : 19 - 22
      x265 10-bit 1080p         : 20 - 23
      x265 10-bit 2160p         : 22 - 26
      AV1            1080p      : 22 - 28
      AV1            2160p      : 24 - 32

    Si le CRF parse depuis Encoded_Library_Settings est en dehors -> WARN.
    Si le champ est absent (cas frequent : pas un encode x264/x265, source
    non taguee) -> on ne dit RIEN (silence : ce n'est pas verifiable).
    """
    crf = mi_video.get("crf")
    if crf is None:
        return []
    codec = (mi_video.get("codec") or "").upper()
    res = (mi_video.get("resolution_label") or "").lower()

    # Table des plages : (codec_match, resolution, min, max)
    ranges = [
        (("X264", "AVC", "H.264"), "720p",  18.0, 21.0),
        (("X264", "AVC", "H.264"), "1080p", 18.0, 21.0),
        (("X265", "HEVC", "H.265"), "720p",  19.0, 22.0),
        (("X265", "HEVC", "H.265"), "1080p", 20.0, 23.0),
        (("X265", "HEVC", "H.265"), "2160p", 22.0, 26.0),
        (("AV1",), "1080p", 22.0, 28.0),
        (("AV1",), "2160p", 24.0, 32.0),
    ]
    for codec_keys, resolution, min_crf, max_crf in ranges:
        if not any(k in codec for k in codec_keys):
            continue
        if resolution != res:
            continue
        if min_crf <= crf <= max_crf:
            return []  # Conforme : on ne dit rien (pas de bruit positif)
        codec_label = codec_keys[0].lower()
        return [ComplianceIssue(
            Severity.WARN, "crf",
            f"CRF {crf:g} hors plage Gemini pour {codec_label} {resolution} "
            f"({min_crf:g}-{max_crf:g}). Encode trop "
            f"{'leger' if crf > max_crf else 'lourd'} pour les standards du tracker."
        )]
    return []


def _check_separate_subs(torrent_target: Path | None) -> list[ComplianceIssue]:
    """C10 — Sous-titres separes du MKV (fichiers .srt/.ass/.sup a cote).

    Charte Gemini : les subs doivent etre muxes dans le MKV. Un .srt frere
    est tolere mais signale en WARN.
    """
    if torrent_target is None or not torrent_target.exists():
        return []
    if not torrent_target.is_dir():
        return []
    SUB_EXTS = {".srt", ".ass", ".ssa", ".sup", ".vtt", ".idx", ".sub"}
    sub_files = [
        p for p in torrent_target.rglob("*")
        if p.is_file() and p.suffix.lower() in SUB_EXTS
    ]
    if not sub_files:
        return []
    sample = ", ".join(p.name for p in sub_files[:3])
    extra = f" (+{len(sub_files) - 3})" if len(sub_files) > 3 else ""
    return [ComplianceIssue(
        Severity.WARN, "subtitles_external",
        f"Sous-titre(s) externe(s) detecte(s) : {sample}{extra}. "
        "Charte Gemini : muxer les subs dans le MKV avant upload."
    )]


# ============================================================
# ENTREE PUBLIQUE
# ============================================================

def check_compliance(
    release_name: str,
    mediainfo_data: dict,
    media_info=None,
    *,
    torrent_target: Path | None = None,
    banned_teams: list[str] | None = None,
) -> list[ComplianceIssue]:
    """Lance tous les checks et retourne la liste des issues triees par severite.

    Args:
        release_name : nom de release final (ex: "Foo.2024.MULTi.VFF.1080p...")
        mediainfo_data : dict produit par parse_mediainfo_json (container,
            video, audio_tracks, subtitle_tracks).
        media_info : optionnel — l'objet MediaInfo (type detecte, all_videos,
            torrent_target). Permet les checks media_type, season_complete,
            multi_team_in_pack.
        torrent_target : optionnel — le path qui sera mis dans le .torrent
            (fichier ou dossier). Permet le check separate_subs.
        banned_teams : optionnel — liste supplementaire de teams interdites
            (en plus de DEFAULT_BANNED_TEAMS), provient de la config user.

    Returns:
        Liste d'issues triees BLOCKING > ERROR > WARN. Vide si tout est OK.
    """
    issues: list[ComplianceIssue] = []
    video = mediainfo_data.get("video", {}) or {}
    audio = mediainfo_data.get("audio_tracks", []) or []
    subs = mediainfo_data.get("subtitle_tracks", []) or []

    # --- Divergence nom <-> mediainfo (legacy) ---
    issues.extend(_check_resolution(release_name, video))
    issues.extend(_check_video_codec(release_name, video))
    issues.extend(_check_audio_codec(release_name, audio))
    issues.extend(_check_audio_channels(release_name, audio))
    issues.extend(_check_hdr(release_name, video))
    issues.extend(_check_french_audio_in_name(release_name, audio))
    issues.extend(_check_vfi_not_present(release_name))
    issues.extend(_check_multi_has_variant(release_name))
    issues.extend(_check_team_present(release_name))
    issues.extend(_check_media_type_tag(release_name, media_info))

    # --- Lot K : regles dures G3MINI ---
    issues.extend(_check_container_mkv(mediainfo_data))
    issues.extend(_check_audio_codec_allowed(audio))
    issues.extend(_check_pgs_in_encode(subs, release_name))
    issues.extend(_check_season_complete(media_info))
    issues.extend(_check_multi_team_in_pack(media_info, release_name))
    issues.extend(_check_russian_audio(audio))
    issues.extend(_check_banned_team(release_name, banned_teams))
    issues.extend(_check_extreme_team_only_encodes(release_name))
    issues.extend(_check_separate_subs(torrent_target))

    # --- Lot M : CRF hors plage (WARN uniquement, silence si absent) ---
    issues.extend(_check_crf_in_range(video))

    # Tri : BLOCKING > ERROR > WARN
    severity_order = {Severity.BLOCKING: 0, Severity.ERROR: 1, Severity.WARN: 2}
    issues.sort(key=lambda i: severity_order[i.severity])
    return issues


def has_blocking(issues: list[ComplianceIssue]) -> bool:
    """Vrai s'il existe au moins une issue BLOCKING -> pipeline doit FAILED."""
    return any(i.severity == Severity.BLOCKING for i in issues)


def format_report(issues: list[ComplianceIssue]) -> str:
    if not issues:
        return "[OK] Conformite : aucun probleme detecte."
    blocking = [i for i in issues if i.severity == Severity.BLOCKING]
    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARN]
    lines = [
        f"[CONFORMITE] {len(blocking)} bloquant(s), "
        f"{len(errors)} erreur(s), {len(warnings)} avertissement(s) :"
    ]
    for issue in issues:
        lines.append(f"  {issue}")
    return "\n".join(lines)
