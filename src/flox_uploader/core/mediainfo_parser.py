"""Parse la sortie JSON de `mediainfo --Output=JSON`.

On normalise en structures simples (TypedDict implicites) prêtes pour le
renderer BBCode. Toute la logique de "lecture" du média vit ici, le renderer
n'a plus qu'à formater.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .errors import die
from .nfo import MEDIAINFO_BIN


# ============================================================
# CODE INTERNE : CONVERSIONS / NORMALISATIONS
# ============================================================

def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_audio_codec(format_str: str, format_commercial: str = "") -> str:
    """Mappe les noms MediaInfo vers les noms compacts attendus dans la fiche.

    E-AC-3 -> DDP, AC-3 -> DD, DTS-HD MA -> DTS-HD MA, TrueHD -> TrueHD, etc.
    """
    f = (format_str or "").upper()
    fc = (format_commercial or "").upper()

    # E-AC-3 / Dolby Digital Plus -> DDP
    if "E-AC-3" in f or "DOLBY DIGITAL PLUS" in fc or "EAC3" in f:
        return "DDP"
    # AC-3 / Dolby Digital -> DD
    if "AC-3" in f or "AC3" in f or "DOLBY DIGITAL" == fc:
        return "DD"
    # DTS variants
    if "DTS" in f:
        if "MA" in fc or "MASTER AUDIO" in fc:
            return "DTS-HD MA"
        if "HRA" in fc or "HIGH RESOLUTION" in fc:
            return "DTS-HD HRA"
        if "X" in fc:
            return "DTS:X"
        if "ES" in fc:
            return "DTS-ES"
        return "DTS"
    # TrueHD
    if "TRUEHD" in f or "MLP" in f:
        if "ATMOS" in fc:
            return "TrueHD Atmos"
        return "TrueHD"
    # AAC
    if "AAC" in f:
        return "AAC"
    # Opus
    if "OPUS" in f:
        return "Opus"
    # FLAC
    if "FLAC" in f:
        return "FLAC"
    # PCM
    if "PCM" in f:
        return "PCM"

    # Fallback : on laisse le format brut nettoyé
    return format_str.strip() if format_str else "?"


def _normalize_video_codec(format_str: str) -> str:
    f = (format_str or "").upper()
    if "HEVC" in f or "H.265" in f or "H265" in f:
        return "HEVC / x265"
    if "AVC" in f or "H.264" in f or "H264" in f:
        return "AVC / x264"
    if "AV1" in f:
        return "AV1"
    if "VC-1" in f or "VC1" in f:
        return "VC-1"
    if "MPEG-2" in f or "MPEG2" in f:
        return "MPEG-2"
    return format_str or "?"


def _extract_crf(encoding_settings: str) -> float | None:
    """Parse `crf=XX.X` depuis Encoded_Library_Settings de MediaInfo.

    Format typique x265 :
      "cpuid=1111039 / frame-threads=4 / numa-pools=8,8 / wpp / ... /
       crf=20.0 / qcomp=0.60 / qpmin=0 / ..."

    Format typique x264 :
      "cabac=1 / ref=4 / deblock=1:-3:-3 / ... / crf=18.0 / qcomp=0.60 / ..."

    AV1 / VP9 / autres : champ souvent absent ou format different (qp= au
    lieu de crf=). On retourne None : c'est le boulot du caller de gerer
    le cas "info indisponible".
    """
    if not encoding_settings:
        return None
    m = re.search(r"\bcrf\s*=\s*(\d+(?:\.\d+)?)", encoding_settings, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _channels_to_layout(channels: int | None) -> str:
    """Mappe nombre de canaux vers le layout standard (1.0, 2.0, 5.1, 7.1)."""
    if channels is None:
        return ""
    mapping = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
    return mapping.get(channels, f"{channels}ch")


def _format_bitrate(bps: int | None) -> str:
    """5_500_000 -> '~5500 kb/s'. Renvoie '' si inconnu."""
    if not bps:
        return ""
    return f"~{bps // 1000} kb/s"


def _format_filesize(size_bytes: int | None) -> str:
    """Formate la taille en Mo / Go / GiB selon le seuil."""
    if not size_bytes:
        return ""
    gib = size_bytes / (1024 ** 3)
    if gib < 1.0:
        mb = size_bytes / (1024 ** 2)
        return f"{mb:.0f} Mo"
    return f"{gib:.2f} Go"


def total_size_recursive(path: Path) -> int:
    """Somme la taille de tous les fichiers sous `path` (recursif).

    Utile pour les saisons / integrales ou le .torrent contient tout le dossier
    (episodes + NFO + sample + posters), donc la taille du seul fichier video
    de reference n'est pas representative.
    """
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def format_filesize(size_bytes: int | None) -> str:
    """Public alias de `_format_filesize`."""
    return _format_filesize(size_bytes)


def _format_runtime(minutes: int | None) -> str:
    """120 -> '2h00', 50 -> '50min'."""
    if not minutes:
        return ""
    if minutes < 60:
        return f"{minutes}min"
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}"


# ============================================================
# PARSING PRINCIPAL
# ============================================================

_REGION_KEYWORDS: dict[str, str] = {
    "QUEBEC": "CA", "QUÉBEC": "CA", "CANADIAN": "CA", "CANADA": "CA",
    "BELG": "BE",
    "SUISSE": "CH", "SWITZERLAND": "CH", "SWISS": "CH",
    "BRAZIL": "BR", "BRESIL": "BR", "BRASIL": "BR",
    "MEXICO": "MX", "MEXIQUE": "MX",
    "BRITISH": "GB",
    "AUSTRALIAN": "AU",
}

# Codes regionaux qu'on accepte tels quels dans lang/title (ISO 3166-1 a-2)
_KNOWN_REGION_CODES = {
    "CA", "FR", "BE", "CH", "US", "GB", "UK", "BR", "PT", "MX",
    "AR", "AU", "NZ", "IE", "DE", "AT", "IT", "ES",
}


def _extract_region(lang_raw: str, title: str) -> str:
    """Extrait le code region 2 lettres depuis lang ou title.

    Exemples :
      'French (CA)'             -> 'CA'
      'fr-CA'                   -> 'CA'
      title='French CA'         -> 'CA'
      title='French (CA) Forced'-> 'CA'
      title='Quebec'            -> 'CA'
      'English' + 'English'     -> '' (pas de region explicite)

    Le suffixe '(XX)' est prioritaire ; sinon mots-cles, sinon '-XX' ISO.
    """
    text = f"{lang_raw or ''} | {title or ''}".upper()

    # 1. Patterns "(XX)"
    m = re.search(r"\(([A-Z]{2})\)", text)
    if m and m.group(1) in _KNOWN_REGION_CODES:
        return m.group(1)
    # 2. fr-CA / en-US
    m = re.search(r"\b[A-Z]{2,3}-([A-Z]{2})\b", text)
    if m and m.group(1) in _KNOWN_REGION_CODES:
        return m.group(1)
    # 3. Mots-cles
    for kw, code in _REGION_KEYWORDS.items():
        if kw in text:
            return code
    # 4. Token isole "CA" / "BE" / etc. dans le title (precede d'espace ou debut)
    title_upper = (title or "").upper()
    for code in _KNOWN_REGION_CODES:
        if re.search(rf"(?:^|\s){code}(?:\s|$)", title_upper):
            return code
    return ""


def _normalize_language_code(raw: str) -> str:
    """Normalise un code langue MediaInfo en ISO 639-1 minuscules.

    Exemples:
      'fr-FR' -> 'fr', 'en-US' -> 'en', 'pt-BR' -> 'pt'
      'French' -> 'fr', 'English' -> 'en'
      'fra' -> 'fr' (ISO 639-2 -> 639-1)
      'fr' -> 'fr'
    """
    if not raw:
        return ""
    s = raw.strip().lower()
    # Code regional 'fr-FR', 'pt-BR' -> on garde la partie avant '-'
    if "-" in s:
        s = s.split("-", 1)[0].strip()
    # Si plusieurs valeurs separees par espace, on garde la premiere
    if " " in s:
        s = s.split()[0].strip()

    # Noms anglais de langue -> ISO 639-1
    name_map = {
        "french": "fr", "francais": "fr", "français": "fr",
        "english": "en", "anglais": "en",
        "spanish": "es", "espagnol": "es",
        "german": "de", "allemand": "de", "deutsch": "de",
        "italian": "it", "italien": "it",
        "portuguese": "pt", "portugais": "pt",
        "japanese": "ja", "japonais": "ja",
        "korean": "ko", "coreen": "ko",
        "chinese": "zh", "chinois": "zh",
        "russian": "ru", "russe": "ru",
        "arabic": "ar", "arabe": "ar",
    }
    if s in name_map:
        return name_map[s]
    # ISO 639-2 (3 lettres) -> 639-1 (2 lettres)
    iso3_to_iso2 = {
        "fra": "fr", "fre": "fr", "eng": "en", "spa": "es",
        "deu": "de", "ger": "de", "ita": "it", "por": "pt",
        "jpn": "ja", "kor": "ko", "zho": "zh", "chi": "zh",
        "rus": "ru", "ara": "ar", "hin": "hi", "tur": "tr",
        "pol": "pl", "nld": "nl", "dut": "nl", "swe": "sv",
        "nor": "no", "dan": "da", "fin": "fi",
    }
    if s in iso3_to_iso2:
        return iso3_to_iso2[s]
    return s


def parse_mediainfo_json(video_path: Path) -> dict:
    """Lance mediainfo en mode JSON et parse en structure exploitable.

    Retourne :
    {
        "container": "MKV",
        "size_bytes": int,
        "size_pretty": "4.93 Go",
        "duration_min": int,
        "duration_pretty": "2h07",
        "video": {
            "codec": "HEVC / x265",
            "width": 3840, "height": 1632,
            "resolution_label": "2160p",
            "hdr": "HDR10" | "DoVi" | "SDR",
            "bitrate_pretty": "~4683 kb/s",
            "bit_depth": "10 bits",
            "framerate": "23.976 FPS",
        },
        "audio_tracks": [
            {"language": "fr", "codec": "DDP", "channels": "5.1",
             "bitrate_pretty": "~576 kb/s", "title": "VFF",
             "is_commentary": False, "default": True}
        ],
        "subtitle_tracks": [
            {"language": "fr", "title": "Forced", "format": "PGS"}
        ],
    }
    """
    if not video_path.exists():
        die(f"Fichier vidéo introuvable pour MediaInfo : {video_path}")

    result = subprocess.run(
        [MEDIAINFO_BIN, "--Output=JSON", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        die(
            f"MediaInfo --Output=JSON a échoué (code {result.returncode}) : "
            f"{result.stderr or 'pas de détail'}"
        )
    if not result.stdout.strip():
        die(f"MediaInfo a retourné un résultat JSON vide pour : {video_path}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        die(f"MediaInfo JSON invalide : {e}")

    media = data.get("media") or {}
    tracks = media.get("track") or []

    # Sépare les tracks par type
    general_track: dict = {}
    video_track: dict = {}
    audio_tracks_raw: list[dict] = []
    text_tracks_raw: list[dict] = []

    for t in tracks:
        ttype = (t.get("@type") or "").lower()
        if ttype == "general":
            general_track = t
        elif ttype == "video":
            if not video_track:  # premier seulement
                video_track = t
        elif ttype == "audio":
            audio_tracks_raw.append(t)
        elif ttype == "text":
            text_tracks_raw.append(t)

    # General
    container_format = (general_track.get("Format") or "").upper()
    size_bytes = _to_int(general_track.get("FileSize"))
    duration_seconds = _to_float(general_track.get("Duration"))
    duration_min = (
        int(round(duration_seconds / 60)) if duration_seconds else None
    )

    # Video
    width = _to_int(video_track.get("Width"))
    height = _to_int(video_track.get("Height"))
    video_codec = _normalize_video_codec(video_track.get("Format", ""))
    bit_depth = _to_int(video_track.get("BitDepth"))
    framerate = _to_float(video_track.get("FrameRate"))
    video_bitrate = _to_int(video_track.get("BitRate"))
    if video_bitrate is None:
        video_bitrate = _to_int(video_track.get("BitRate_Nominal"))
    # Lot M : extrait le CRF des Encoding_Settings (x264/x265 surtout).
    # Format brut : "cabac=1 / ref=4 / ... / crf=20.0 / qcomp=0.60 / ..."
    # On expose le texte brut + le CRF parse pour les checks de conformite.
    encoding_settings = (
        video_track.get("Encoded_Library_Settings")
        or video_track.get("Encoding_settings")
        or ""
    )
    crf_value = _extract_crf(encoding_settings)

    # R3 (audit AUDIT_2026-07-19) : writing library REELLE (encodeur logiciel).
    # Un re-encode x264/x265 renseigne Encoded_Library[_Name] ; un flux
    # untouched (WEB-DL/BluRay natif) ne l'a pas (ou un autre encodeur). C'est
    # le VRAI signal d'un encode — le champ `codec` ("HEVC / x265") ne l'est
    # pas (il vaut toujours "x265" pour du HEVC, d'ou l'ancienne tautologie).
    writing_library = (
        video_track.get("Encoded_Library_Name")
        or video_track.get("Encoded_Library")
        or ""
    ).strip()

    # HDR detection
    hdr_format = (video_track.get("HDR_Format") or "").upper()
    hdr_format_compat = (video_track.get("HDR_Format_Compatibility") or "").upper()
    transfer = (video_track.get("transfer_characteristics") or "").upper()
    hdr_label = "SDR"
    if "DOLBY VISION" in hdr_format or "DOVI" in hdr_format:
        hdr_label = "DoVi"
    elif "HDR10+" in hdr_format or "HDR10+" in hdr_format_compat:
        hdr_label = "HDR10+"
    elif "HDR10" in hdr_format or "HDR10" in hdr_format_compat:
        hdr_label = "HDR10"
    elif "PQ" in transfer or "SMPTE ST 2084" in transfer:
        hdr_label = "HDR"
    elif "HLG" in transfer:
        hdr_label = "HLG"

    resolution_label = _resolution_label(width, height)

    video_block = {
        "codec": video_codec,
        "width": width,
        "height": height,
        "resolution_label": resolution_label,
        "hdr": hdr_label,
        "bitrate_pretty": _format_bitrate(video_bitrate),
        "bit_depth": f"{bit_depth} bits" if bit_depth else "",
        "bit_depth_int": bit_depth,
        "framerate": f"{framerate:.3f} FPS".rstrip("0").rstrip(".") + (
            " FPS" if framerate else ""
        ) if framerate else "",
        "encoding_settings": encoding_settings,
        "writing_library": writing_library,
        "crf": crf_value,
    }
    # Le ".rstrip" ci-dessus laisse parfois un trailing " FPS" mal placé.
    # On reformate proprement :
    if framerate:
        video_block["framerate"] = f"{framerate:g} FPS"
    else:
        video_block["framerate"] = ""

    # Audio tracks
    audio_tracks = []
    for t in audio_tracks_raw:
        codec = _normalize_audio_codec(
            t.get("Format", ""), t.get("Format_Commercial_IfAny", "")
        )
        channels = _to_int(t.get("Channels"))
        layout = _channels_to_layout(channels)
        bitrate = _to_int(t.get("BitRate"))
        title = (t.get("Title") or "").strip()
        lang_raw = t.get("Language") or ""
        language = _normalize_language_code(lang_raw)
        region = _extract_region(lang_raw, title)
        is_default = (t.get("Default") or "").lower() == "yes"
        is_forced = (t.get("Forced") or "").lower() == "yes"
        is_commentary = "commentary" in title.lower() or "commentaire" in title.lower()
        is_audio_description = (
            "audio description" in title.lower()
            or "audiodescription" in title.lower()
            or " ad " in f" {title.lower()} "
            or "(ad)" in title.lower()
            or "[ad]" in title.lower()
        )

        audio_tracks.append({
            "language": language,
            "region": region,
            "title": title,
            "codec": codec,
            "channels": layout,
            "bitrate_pretty": _format_bitrate(bitrate),
            "default": is_default,
            "forced": is_forced,
            "is_commentary": is_commentary,
            "is_audio_description": is_audio_description,
        })

    # Text tracks (subs)
    subtitle_tracks = []
    for t in text_tracks_raw:
        title = (t.get("Title") or "").strip()
        lang_raw = t.get("Language") or ""
        language = _normalize_language_code(lang_raw)
        region = _extract_region(lang_raw, title)
        fmt = (t.get("Format") or "").strip().upper()
        is_forced = (t.get("Forced") or "").lower() == "yes"

        # Catégorisation : Forced / SDH / Complet
        title_upper = title.upper()
        if is_forced or "FORCED" in title_upper or "FORCÉ" in title_upper:
            kind = "Forced"
        elif "SDH" in title_upper or "HEARING" in title_upper:
            kind = "SDH"
        else:
            kind = "Complet"

        subtitle_tracks.append({
            "language": language,
            "region": region,
            "title": title,
            "format": fmt,
            "kind": kind,
        })

    return {
        "container": container_format or "?",
        "size_bytes": size_bytes,
        "size_pretty": _format_filesize(size_bytes),
        "duration_min": duration_min,
        "duration_pretty": _format_runtime(duration_min),
        "video": video_block,
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }


def _resolution_label(width, height) -> str:
    """Width + height -> '2160p' / '1080p' / etc.

    Convention scene/p2p : on classe au plus haut bucket atteint par la WIDTH
    OU la HEIGHT. C'est important pour deux cas tordus :

    - CinemaScope 2.40:1 : 2160p donne une image 3840x1606. Width 3840 -> 2160p
      (la height seule ferait classer en 1080p, ce qui est faux).
    - Academy 1.37:1 (vieux films, ex: 1948) : 1080p donne une image 1480x1080.
      Height 1080 -> 1080p (la width seule ferait classer en 720p, ce qui est faux).

    Strategie : pour chaque bucket, du plus haut au plus bas, on retourne le
    premier qui matche soit par width, soit par height (avec des seuils height
    legerement permissifs pour absorber les variations de crop/decoupe).
    """
    w, h = width or 0, height or 0
    if not (w or h):
        return ""

    # 2160p : 3840x2160 standard ; CinemaScope 2160p -> 3840x1600
    if w >= 3000 or h >= 1900:
        return "2160p"
    # 1080p : 1920x1080 standard ; CinemaScope 1080p -> 1920x800 ;
    # Academy 1080p (vieux films 1.37:1) -> 1480x1080
    if w >= 1800 or h >= 950:
        return "1080p"
    # 720p : 1280x720 standard ; CinemaScope 720p -> 1280x534 ;
    # Academy 720p -> 988x720
    if w >= 1200 or h >= 680:
        return "720p"
    # PAL 576p (720x576) vs NTSC 480p (720x480) : meme width 720, on tranche
    # par height. C'est l'inverse des resolutions superieures ou la width
    # discrimine bien (CinemaScope vs Academy).
    if h >= 540:
        return "576p"
    if h >= 400 or (w >= 600 and h == 0):
        return "480p"
    # Fallback : si on est en dessous de tous les seuils mais qu'on a une height
    # connue, on retourne `{h}p` brut (utile pour debug, rare en pratique).
    if h:
        return f"{h}p"
    return ""


def deduce_release_type(release_name: str, video_codec: str):
    """Deduit (Type, Source) depuis release_name + codec."""
    name = release_name.upper()
    codec_upper = (video_codec or "").upper()

    if "REMUX" in name:
        type_ = "BluRay Remux"
        source = "UHD BluRay" if "2160P" in name or "UHD" in name else "BluRay"
        return type_, source
    if "BLURAY" in name or "BDRIP" in name:
        if "X264" in codec_upper or "X265" in codec_upper or "HEVC" in codec_upper or "AVC" in codec_upper:
            type_ = "BDRip"
        else:
            type_ = "BluRay"
        source = "UHD BluRay" if "2160P" in name or "UHD" in name else "BluRay"
        return type_, source
    if "WEB-DL" in name or "WEBDL" in name:
        return "WEB-DL", "WEB"
    if "WEBRIP" in name:
        return "WEBRip", "WEB"
    if "WEB" in name:
        return "WEB-DL", "WEB"
    if "HDTV" in name:
        return "HDTV", "HDTV"
    if "DVDRIP" in name:
        return "DVDRip", "DVD"
    if "DVD" in name:
        return "DVD", "DVD"
    if codec_upper in {"X264", "X265"}:
        return "Encode", "Inconnue"
    return "", ""
