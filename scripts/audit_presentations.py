"""Audit des fiches BBCode : pour un echantillon representatif d'anciens
packages, on parse le NFO TEXT et le debug.json pour reconstituer une
mediainfo_data + tmdb_context, on re-genere la fiche avec le NOUVEAU
renderer, et on sauvegarde a cote de l'ancienne pour comparaison.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flox_uploader.core.bbcode_renderer import render_bbcode
from flox_uploader.core.mediainfo_parser import deduce_release_type
from flox_uploader.trackers import get_tracker


# ============================================================
# PARSEUR NFO TEXT -> structure equivalente a mediainfo --Output=JSON
# ============================================================

def parse_nfo_text(nfo_text: str) -> dict:
    """Parse la sortie 'mediainfo --Output=TEXT' en dict comparable a JSON."""
    blocks = re.split(r"\n(?=(?:General|Video|Audio|Text|Menu)\b)", nfo_text)

    general: dict = {}
    video: dict = {}
    audios: list[dict] = []
    texts: list[dict] = []

    for block in blocks:
        m = re.match(r"^(General|Video|Audio|Text|Menu)", block)
        if not m:
            continue
        ttype = m.group(1)
        fields = _parse_kv(block)

        if ttype == "General":
            general = fields
        elif ttype == "Video" and not video:
            video = fields
        elif ttype == "Audio":
            audios.append(fields)
        elif ttype == "Text":
            texts.append(fields)

    return _build_structure(general, video, audios, texts)


def _parse_kv(block: str) -> dict:
    """Extrait les paires 'Key : Value' du bloc."""
    fields: dict = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and value and key.lower() != "complete name":
            # On peut avoir plusieurs valeurs pour le meme champ (ex: Format,
            # Format/Info), on garde la premiere
            if key not in fields:
                fields[key] = value
    return fields


def _build_structure(general, video, audios, texts) -> dict:
    """Construit la meme structure que core.mediainfo_parser.parse_mediainfo_json."""
    container = (general.get("Format") or "").upper()

    # Taille : "4.93 GiB" -> bytes
    size_str = general.get("File size") or general.get("FileSize") or ""
    size_bytes = _parse_size(size_str)
    size_pretty = size_str or ""

    # Duree : "2 h 32 min" -> minutes
    duration_str = general.get("Duration") or ""
    duration_min = _parse_duration(duration_str)

    # Video
    video_format = (video.get("Format") or "").upper()
    if "HEVC" in video_format:
        codec = "HEVC / x265"
    elif "AVC" in video_format:
        codec = "AVC / x264"
    elif video_format:
        codec = video_format
    else:
        codec = ""

    width = _parse_int(video.get("Width") or "")
    height = _parse_int(video.get("Height") or "")
    bit_depth = _parse_int(video.get("Bit depth") or video.get("BitDepth") or "")
    framerate = video.get("Frame rate") or video.get("FrameRate") or ""

    hdr_label = "SDR"
    hdr_format = (video.get("HDR format") or video.get("HDR_Format") or "").upper()
    if "DOLBY VISION" in hdr_format:
        hdr_label = "DoVi"
    elif "HDR10+" in hdr_format:
        hdr_label = "HDR10+"
    elif "HDR10" in hdr_format:
        hdr_label = "HDR10"
    elif hdr_format:
        hdr_label = "HDR"

    # Use core's resolution detection (width-based for cinema scope)
    from flox_uploader.core.mediainfo_parser import _resolution_label
    res_label = _resolution_label(width, height)

    bitrate_str = (
        video.get("Bit rate") or video.get("BitRate") or ""
    )
    bitrate_pretty = _normalize_bitrate(bitrate_str)

    video_block = {
        "codec": codec,
        "width": width, "height": height,
        "resolution_label": res_label,
        "hdr": hdr_label,
        "bitrate_pretty": bitrate_pretty,
        "bit_depth": f"{bit_depth} bits" if bit_depth else "",
        "framerate": _clean_framerate(framerate),
    }

    # Audio
    audio_tracks = []
    for a in audios:
        codec = _normalize_audio(a)
        channels = _parse_channels(a.get("Channel(s)") or a.get("Channels") or "")
        bitrate = _normalize_bitrate(a.get("Bit rate") or a.get("BitRate") or "")
        title = a.get("Title") or ""
        language = (a.get("Language") or "").lower()
        # ISO -> 2 lettres
        if " " in language:
            language = language.split()[0]
        audio_tracks.append({
            "language": _normalize_lang(language),
            "title": title,
            "codec": codec,
            "channels": channels,
            "bitrate_pretty": bitrate,
            "default": False, "forced": False,
            "is_commentary": "comment" in title.lower(),
        })

    # Subs
    subtitle_tracks = []
    for t in texts:
        language = (t.get("Language") or "").lower()
        if " " in language:
            language = language.split()[0]
        title = t.get("Title") or ""
        title_upper = title.upper()
        kind = "Forced" if "FORCED" in title_upper or "FORCÉ" in title_upper else (
            "SDH" if "SDH" in title_upper else "Complet"
        )
        subtitle_tracks.append({
            "language": _normalize_lang(language),
            "title": title,
            "format": (t.get("Format") or "").upper(),
            "kind": kind,
        })

    return {
        "container": container or "MKV",
        "size_bytes": size_bytes,
        "size_pretty": size_pretty,
        "duration_min": duration_min,
        "duration_pretty": _format_runtime(duration_min),
        "video": video_block,
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }


def _parse_size(s: str) -> int | None:
    """'4.93 GiB' -> bytes."""
    m = re.match(r"([\d.]+)\s*(GiB|MiB|KiB|GB|MB|KB)", s)
    if not m: return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    mult = {"GIB": 1024**3, "MIB": 1024**2, "KIB": 1024,
            "GB": 1000**3, "MB": 1000**2, "KB": 1000}.get(unit, 1)
    return int(val * mult)


def _parse_duration(s: str) -> int | None:
    """'2 h 32 min 14 s' -> 152 minutes."""
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*min", s)
    total = 0
    if h: total += int(h.group(1)) * 60
    if m: total += int(m.group(1))
    return total if total else None


def _parse_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def _parse_channels(s: str) -> str:
    """'6 channels' or '5.1' -> '5.1'."""
    if not s: return ""
    if "." in s and re.match(r"\d\.\d", s):
        return re.match(r"(\d\.\d)", s).group(1)
    n = _parse_int(s)
    if n is None: return ""
    mapping = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
    return mapping.get(n, f"{n}ch")


def _normalize_bitrate(s: str) -> str:
    """'4 683 kb/s' -> '~4683 kb/s'."""
    if not s: return ""
    n = _parse_int(s.split("/")[0])
    if n is None: return ""
    if "Mb" in s: n *= 1000
    return f"~{n} kb/s"


def _clean_framerate(s: str) -> str:
    """'23.976 (24000/1001) FPS' -> '23.976 FPS'."""
    if not s: return ""
    m = re.match(r"([\d.]+)", s)
    if not m: return ""
    return f"{float(m.group(1)):g} FPS"


def _normalize_audio(a: dict) -> str:
    fmt = (a.get("Format") or "").upper()
    fc = (a.get("Commercial name") or a.get("Format/Info") or "").upper()
    if "E-AC-3" in fmt or "DOLBY DIGITAL PLUS" in fc: return "DDP"
    if "AC-3" in fmt or "DOLBY DIGITAL" in fc: return "DD"
    if "DTS" in fmt:
        if "MA" in fc or "MASTER" in fc: return "DTS-HD MA"
        return "DTS"
    if "TRUEHD" in fmt or "MLP" in fmt:
        if "ATMOS" in fc: return "TrueHD Atmos"
        return "TrueHD"
    if "AAC" in fmt: return "AAC"
    if "OPUS" in fmt: return "Opus"
    if "FLAC" in fmt: return "FLAC"
    return fmt or "?"


def _normalize_lang(lang: str) -> str:
    """Normalise un code langue : 'fr' / 'french' / 'francais' -> 'fr'."""
    lang = lang.strip().lower()
    if not lang: return ""
    full_to_iso = {
        "french": "fr", "francais": "fr", "français": "fr",
        "english": "en", "anglais": "en",
        "japanese": "ja", "japonais": "ja",
        "spanish": "es", "espagnol": "es",
        "german": "de", "allemand": "de",
        "italian": "it", "italien": "it",
        "portuguese": "pt", "korean": "ko", "chinese": "zh",
        "russian": "ru", "arabic": "ar", "hindi": "hi",
    }
    if lang in full_to_iso: return full_to_iso[lang]
    if len(lang) == 2: return lang
    if len(lang) == 3:
        # iso 639-3 -> on garde tel quel, le renderer fera le mapping
        return lang
    return lang[:2]


def _format_runtime(minutes):
    if not minutes: return ""
    if minutes < 60: return f"{minutes}min"
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}"


# ============================================================
# AUDIT
# ============================================================

def main():
    tracker = get_tracker("gemini", "https://example.com/announce/test")
    packages_dir = PROJECT_ROOT / "data" / "upload_packages"
    audit_dir = PROJECT_ROOT / "data" / "_audit_presentations"
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Echantillon representatif : on prend des cas tries selon variete
    # (US/FR/VOSTFR/2160p/1080p/recompenses notable)
    sample = [
        "Capharnaum.2018.MULTi.VFF.1080p.10Bit.BluRay.x265-k7",                       # Lebanese ar
        "Casino.1995.MULTi.VFF.2160p.10Bit.HDR.BluRay.AAC.x265-QTZ",                  # classique US 2160p HDR
        "Caught.Stealing.2025.MULTi.VF2.1080p.WEBRip.x265-TyHD",                      # MULTi VF2
        "Chien.de.la.casse.2023.VOF.1080p.BluRay.x265-k7",                            # FR original
        "Didi.2024.VOSTFR.1080p.WEB.H.265-FW",                                        # VOSTFR
        "Die.Hard.1988.MULTi.VFF.2160p.10Bit.DoVi.HDR10+.BluRay.DDP.x265-QTZ",        # action HDR10+ DoVi
        "Jurassic.World.Rebirth.2025.MULTi.VFQ.2160p.WEBRip.x265-TyHD",               # VFQ Quebec
        "OSS.117.Le.Caire.nid.despions.2006.VOF.1080p.10Bit.BluRay.AC3.x265-QTZ",    # FR avec apostrophe
        "PERFECT.DAYS.2023.VOSTFR.1080p.10Bit.WEBRip.6CH.HEVC-SERQPH",                # JP VOSTFR
        "The.Matrix.1999.MULTi.VFF.2160p.10Bit.HDR.BluRay.x265-QTZ",                  # ULTRA classique
    ]

    summary = []

    for release_name in sample:
        pkg_dir = packages_dir / release_name
        if not pkg_dir.exists():
            print(f"[SKIP] {release_name} introuvable")
            continue

        debug_path = pkg_dir / "_debug" / "debug.json"
        nfo_path = next(pkg_dir.glob("*.nfo"), None)
        old_pres_path = pkg_dir / "presentation.txt"

        if not debug_path.exists() or not nfo_path or not old_pres_path.exists():
            print(f"[SKIP] {release_name} : fichiers manquants")
            continue

        old_debug = json.loads(debug_path.read_text(encoding="utf-8"))
        nfo_text = nfo_path.read_text(encoding="utf-8", errors="replace")
        old_pres = old_pres_path.read_text(encoding="utf-8")

        # Reconstitue mediainfo_data depuis le NFO TEXT
        mi_data = parse_nfo_text(nfo_text)

        # Reconstitue tmdb_context partiel : on a juste les champs essentiels
        # dans debug.json (pas le casting complet). On fait ce qu'on peut.
        tmdb_ctx = None
        if old_debug.get("tmdb_original_language"):
            # Il y a eu un match TMDB. On reconstitue un contexte minimal.
            tmdb_ctx = {
                "title": "",  # pas dans debug
                "original_title": "",
                "original_language": old_debug.get("tmdb_original_language", ""),
                "production_countries": old_debug.get("tmdb_production_countries") or [],
                "release_date": "",  # pas direct dans debug
                "overview": "",
                "runtime": None,
                "tmdb_rating": None,
                "tmdb_vote_count": None,
                "genres": [],
                "director": "",
                "writers": [],
                "cast": [],
                "imdb_id": "",
                "imdb_rating": old_debug.get("omdb_imdb_rating_raw", ""),
                "tmdb_poster_path": "",
            }
            # Note : on n'a pas le casting/genres/director dans debug.json,
            # donc la fiche generee aura ces champs vides. C'est attendu.

        poster_url = old_debug.get("poster_url") or ""
        release_type, release_source = deduce_release_type(
            release_name, mi_data["video"].get("codec", "")
        )

        new_pres = render_bbcode(
            tracker=tracker,
            video_path=Path(f"{old_debug.get('original_stem', release_name)}.mkv"),
            release_name=release_name,
            mediainfo_data=mi_data,
            tmdb_context=tmdb_ctx,
            poster_url=poster_url,
            awards_text="",  # OMDb awards pas dans l'ancien debug
            omdb_plot="",
            release_type=release_type,
            release_source=release_source,
        )

        # Sauvegarde
        out_dir = audit_dir / release_name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "old_presentation.txt").write_text(old_pres, encoding="utf-8")
        (out_dir / "new_presentation.txt").write_text(new_pres, encoding="utf-8")

        # Mini-stats
        summary.append({
            "release": release_name,
            "old_lines": len(old_pres.splitlines()),
            "new_lines": len(new_pres.splitlines()),
            "audio_tracks": len(mi_data["audio_tracks"]),
            "sub_tracks": len(mi_data["subtitle_tracks"]),
            "tmdb_resolved": tmdb_ctx is not None,
        })
        print(f"[OK]   {release_name}")

    print()
    print("=" * 80)
    print(f"FICHES GENEREES : {len(summary)}")
    print("=" * 80)
    print(f"Fichiers ecrits dans : data/_audit_presentations/")
    print()

    for s in summary:
        print(f"  {s['release']}")
        print(f"    {s['old_lines']:>3} lignes (ancien) -> {s['new_lines']:>3} lignes (nouveau)  audio={s['audio_tracks']} subs={s['sub_tracks']} tmdb={'OK' if s['tmdb_resolved'] else 'KO'}")


if __name__ == "__main__":
    main()
