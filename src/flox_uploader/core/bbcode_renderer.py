"""Génère la fiche BBCode finale à partir des données structurées.

Remplace l'appel à OpenAI : tout est déterministe, fondé sur TMDB + OMDb + MediaInfo.
Le template par tracker est dans `trackers/<key>/template.bbcode` avec des
placeholders Python (ex: {title}, {audio_block}). Les sections optionnelles
sont rendues à vide si la donnée est absente.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .flags import flag_for_country, flag_for_language, flag_for_language_with_context

if TYPE_CHECKING:
    from ..trackers.base import Tracker


# Couleurs de la charte (par défaut Gemini ; un tracker peut les surcharger
# en exposant son propre template).
COLOR_GOLD = "#C9B27D"
COLOR_TAUPE = "#8B8680"


# ============================================================
# FORMATAGE INDIVIDUEL
# ============================================================

def _format_runtime(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes < 60:
        return f"⏱ {minutes}min"
    h, m = divmod(minutes, 60)
    return f"⏱ {h}h{m:02d}"


def _format_genres(genres: list[str]) -> str:
    """Drame, Musique -> Drame / Musique"""
    return " / ".join(g for g in genres if g)


# Mapping nom TMDB (anglais) -> (ISO 3166-2, nom francais court)
# Couvre les pays principaux ; pour les autres, on retombe sur le nom TMDB.
_COUNTRY_NAME_FR: dict[str, tuple[str, str]] = {
    "United States of America": ("US", "Etats-Unis"),
    "United States": ("US", "Etats-Unis"),
    "USA": ("US", "Etats-Unis"),
    "France": ("FR", "France"),
    "Canada": ("CA", "Canada"),
    "United Kingdom": ("GB", "Royaume-Uni"),
    "UK": ("GB", "Royaume-Uni"),
    "Germany": ("DE", "Allemagne"),
    "Spain": ("ES", "Espagne"),
    "Italy": ("IT", "Italie"),
    "Japan": ("JP", "Japon"),
    "South Korea": ("KR", "Coree du Sud"),
    "Korea": ("KR", "Coree"),
    "China": ("CN", "Chine"),
    "Russia": ("RU", "Russie"),
    "India": ("IN", "Inde"),
    "Australia": ("AU", "Australie"),
    "Brazil": ("BR", "Bresil"),
    "Mexico": ("MX", "Mexique"),
    "Belgium": ("BE", "Belgique"),
    "Switzerland": ("CH", "Suisse"),
    "Netherlands": ("NL", "Pays-Bas"),
    "Sweden": ("SE", "Suede"),
    "Denmark": ("DK", "Danemark"),
    "Norway": ("NO", "Norvege"),
    "Finland": ("FI", "Finlande"),
    "Iceland": ("IS", "Islande"),
    "Ireland": ("IE", "Irlande"),
    "Poland": ("PL", "Pologne"),
    "Czech Republic": ("CZ", "Republique tcheque"),
    "Hungary": ("HU", "Hongrie"),
    "Greece": ("GR", "Grece"),
    "Turkey": ("TR", "Turquie"),
    "Israel": ("IL", "Israel"),
    "New Zealand": ("NZ", "Nouvelle-Zelande"),
    "Argentina": ("AR", "Argentine"),
    "Hong Kong": ("HK", "Hong Kong"),
    "Taiwan": ("TW", "Taiwan"),
    "Thailand": ("TH", "Thailande"),
    "Vietnam": ("VN", "Vietnam"),
    "Indonesia": ("ID", "Indonesie"),
    "Philippines": ("PH", "Philippines"),
    "South Africa": ("ZA", "Afrique du Sud"),
    "Iran": ("IR", "Iran"),
    "Lebanon": ("LB", "Liban"),
    "Egypt": ("EG", "Egypte"),
    "Morocco": ("MA", "Maroc"),
    "Tunisia": ("TN", "Tunisie"),
    "Algeria": ("DZ", "Algerie"),
    "Saudi Arabia": ("SA", "Arabie saoudite"),
    "United Arab Emirates": ("AE", "Emirats arabes unis"),
}


def _format_country_with_flag(country_name: str) -> str:
    """'United States of America' -> '🇺🇸 Etats-Unis'."""
    if not country_name:
        return ""

    info = _COUNTRY_NAME_FR.get(country_name)
    if info:
        iso, fr_name = info
        flag = flag_for_country(iso)
        return f"{flag} {fr_name}".strip()

    # Fallback : si c'est deja un code ISO 2 lettres, on le respecte
    if len(country_name) == 2 and country_name.isalpha():
        flag = flag_for_country(country_name.upper())
        if flag:
            return f"{flag} {country_name.upper()}"

    return country_name


def _format_iso_date_year(release_date: str) -> str:
    if not release_date:
        return ""
    return release_date[:4] if len(release_date) >= 4 else ""


def _format_episode_tag_for_template(media_info) -> str:
    """Pour template_episode : retourne 'S01E01' (charte Gemini)."""
    if media_info is None or media_info.season is None or media_info.episode is None:
        return ""
    return f"S{media_info.season:02d}E{media_info.episode:02d}"


def _format_episode_title_block(media_info, tmdb_context) -> str:
    """Si on a le titre de l'episode via TMDB, on le retourne tel quel.

    Le template gere deja le saut de ligne avant, donc pas besoin de tiret.
    """
    if media_info is None or not tmdb_context:
        return ""
    eps = tmdb_context.get("season_episodes") or []
    if not eps or media_info.episode is None:
        return ""
    for e in eps:
        if e.get("ep") == media_info.episode:
            name = (e.get("name") or "").strip()
            if name:
                return name
            break
    return ""


def _format_episode_list(media_info, tmdb_context) -> str:
    """Formate la liste des episodes pour les saisons (depuis TMDB season_episodes).

    Astuce alignement : on wrap en [font=monospace] (les caracteres ont alors
    la meme largeur) et on padde chaque ligne avec des espaces insecables
    (U+00A0, non-collapses par BBCode/HTML) pour que toutes les lignes aient
    la meme longueur visuelle. Resultat : meme dans un bloc centre, le bloc
    apparait visuellement aligne (chaque ligne fait la meme largeur, donc
    le centrage aligne automatiquement les bords gauches).
    """
    if media_info is None or not tmdb_context:
        return "(liste indisponible)"
    eps = tmdb_context.get("season_episodes") or []
    if not eps:
        return "(liste indisponible)"
    raw_lines = []
    for e in eps:
        ep_num = e.get("ep")
        name = (e.get("name") or "").strip()
        if ep_num is not None:
            tag = f"S{media_info.season:02d}E{ep_num:02d}"
            if name:
                raw_lines.append(f"• {tag} — {name}")
            else:
                raw_lines.append(f"• {tag}")
    if not raw_lines:
        return "(liste indisponible)"

    # Padding pour egalisation : on prend la longueur max et on rajoute des
    # espaces insecables a droite des lignes plus courtes.
    max_len = max(len(l) for l in raw_lines)
    NBSP = " "
    padded = [l + NBSP * (max_len - len(l)) for l in raw_lines]
    body = "\n".join(padded)
    return f"[font=monospace]{body}[/font]"


def _format_seasons_list(tmdb_context) -> str:
    """Pour les integrales : liste des saisons avec nombre d'episodes.

    Format aligne en monospace avec espaces insecables (meme principe que
    la liste des episodes).
    """
    if not tmdb_context:
        return "(saisons indisponibles)"
    seasons = tmdb_context.get("seasons_summary") or []
    if not seasons:
        return "(saisons indisponibles)"
    raw_lines = []
    for s in seasons:
        sn = s.get("season_number")
        ec = s.get("episode_count", 0)
        if sn is not None:
            raw_lines.append(f"• Saison {sn} — {ec} épisodes")
    if not raw_lines:
        return "(saisons indisponibles)"
    max_len = max(len(l) for l in raw_lines)
    NBSP = " "
    padded = [l + NBSP * (max_len - len(l)) for l in raw_lines]
    body = "\n".join(padded)
    return f"[font=monospace]{body}[/font]"


def _format_avg_episode_runtime(tmdb_context) -> str:
    """Calcule la duree moyenne d'un episode (pour saisons / integrales).

    Source preferee : moyenne des runtimes des episodes de la saison TMDB.
    Fallback : runtime general de la serie.
    """
    if not tmdb_context:
        return ""
    eps = tmdb_context.get("season_episodes") or []
    runtimes = [e.get("runtime") for e in eps if e.get("runtime")]
    if runtimes:
        avg = round(sum(runtimes) / len(runtimes))
        return _format_runtime(avg).replace("⏱ ", "")
    runtime = tmdb_context.get("runtime")
    if runtime:
        return _format_runtime(runtime).replace("⏱ ", "")
    return ""


def _normalize_container(container: str) -> str:
    """'Matroska' -> 'MKV', 'MPEG-4' -> 'MP4', etc."""
    c = (container or "").upper()
    if "MATROSKA" in c or c == "MKV":
        return "MKV"
    if "MPEG-4" in c or "MP4" in c:
        return "MP4"
    if "AVI" in c:
        return "AVI"
    return container or "?"


def _format_rating(value, vote_count=None) -> str:
    """8.012 -> '8.0', 7.5 -> '7.5'. Vide si invalide."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return f"{v:.1f}"


def _format_vote_count(count) -> str:
    """32100 -> '32k', 1234567 -> '1.2M', 158 -> '158'. Vide si 0/None."""
    if not count:
        return ""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1_000_000:.1f}M"


def _format_stars(rating10, assets: dict) -> str:
    """Convertit une note /10 en BBCode d'etoiles /5 (arrondi au 0.5).

    8.5/10 -> 4.25/5 -> arrondi a 4.5 -> 4 pleines + 1 demi + 0 vide
    7.0/10 -> 3.5/5 -> 3 pleines + 1 demi + 1 vide
    9.0/10 -> 4.5/5 -> 4 pleines + 1 demi + 0 vide

    Taille fixe [img=15] pour les etoiles.
    """
    if rating10 is None:
        return ""
    try:
        v = float(rating10)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""

    stars5 = v / 2.0
    rounded = round(stars5 * 2) / 2
    full = int(rounded)
    half = 1 if (rounded - full) >= 0.5 else 0
    empty = 5 - full - half

    full_url = assets.get("star_full_url", "")
    half_url = assets.get("star_half_url", "")
    empty_url = assets.get("star_empty_url", "")

    parts = []
    parts.extend([f"[img=15]{full_url}[/img]"] * full)
    if half:
        parts.append(f"[img=15]{half_url}[/img]")
    parts.extend([f"[img=15]{empty_url}[/img]"] * empty)
    return "".join(parts)


def _tmdb_url_for(tmdb_context, media_type) -> str:
    """Retourne l'URL TMDB pour le media (tv/<id> ou movie/<id>)."""
    if not tmdb_context:
        return ""
    tv_id = tmdb_context.get("tv_id")
    movie_id = tmdb_context.get("movie_id")
    from .media_type import MediaType
    is_tv = media_type in {
        MediaType.TV_EPISODE, MediaType.TV_SEASON, MediaType.TV_INTEGRALE,
    } if media_type else False
    if is_tv and tv_id:
        return f"https://www.themoviedb.org/tv/{tv_id}"
    if movie_id:
        return f"https://www.themoviedb.org/movie/{movie_id}"
    return ""


def _imdb_url_for(tmdb_context) -> str:
    if not tmdb_context:
        return ""
    imdb_id = (tmdb_context.get("imdb_id") or "").strip()
    return f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else ""


def _youtube_url_for(tmdb_context) -> str:
    if not tmdb_context:
        return ""
    yt_key = (tmdb_context.get("trailer_yt_key") or "").strip()
    return f"https://www.youtube.com/watch?v={yt_key}" if yt_key else ""


def _format_youtube_link(tmdb_context, assets: dict) -> str:
    """Logo YouTube clickable taille 50, sur sa propre ligne."""
    yt_url = _youtube_url_for(tmdb_context)
    if not yt_url:
        return ""
    yt_logo = assets.get("youtube_logo_url", "")
    if not yt_logo:
        return ""
    return f"[url={yt_url}][img=50]{yt_logo}[/img][/url]"


def _format_full_date_fr(release_date: str) -> str:
    """'2025-03-13' -> '13 mars 2025'."""
    if not release_date or len(release_date) < 10:
        return release_date or ""
    months = {
        "01": "janvier", "02": "février", "03": "mars", "04": "avril",
        "05": "mai", "06": "juin", "07": "juillet", "08": "août",
        "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
    }
    try:
        y, m, d = release_date[:4], release_date[5:7], release_date[8:10]
        return f"{int(d)} {months.get(m, m)} {y}"
    except Exception:
        return release_date


# ============================================================
# CONSTRUCTION DES BLOCS
# ============================================================

def _build_poster_section(poster_url: str) -> str:
    """Bloc poster ou vide."""
    if not poster_url:
        return ""
    return f"\n[img=300x0]{poster_url}[/img]\n"


def _build_header_line(
    lang_label: str,
    resolution: str,
    hdr: str,
    source: str,
    video_codec: str,
    audio_main: str,
) -> str:
    """LANGUE | RESOLUTION | HDR | SOURCE | CODEC | AUDIO."""
    parts = [
        p
        for p in [lang_label, resolution, hdr, source, video_codec, audio_main]
        if p
    ]
    return " | ".join(parts)


def _lang_label_from_release_name(release_name: str) -> str:
    """Extrait le tag langue principal du release name pour l'en-tête.

    Ex: '...MULTi.VFF.2160p...' -> 'MULTi VFF'
    """
    name = release_name.upper()
    for tag in ["MULTI.VFF", "MULTI.VFQ", "MULTI.VFB", "MULTI.VF2"]:
        if tag in name:
            return tag.replace(".", " ").replace("MULTI", "MULTi")
    for tag in ["VFF", "VFQ", "VFB", "VF2", "VOSTFR", "VOF", "VOQ", "VOB"]:
        if f".{tag}." in f".{name}." or name.endswith(f".{tag}"):
            return tag
    if "MULTI" in name:
        return "MULTi"
    if "FRENCH" in name:
        return "FRENCH"
    return ""


def _audio_codec_compact(codec: str, channels: str) -> str:
    """'DDP' + '7.1' -> 'DDP 7.1'. Pour l'en-tête."""
    if codec and channels:
        return f"{codec} {channels}"
    return codec or channels or ""


def _build_video_codec_compact(video: dict) -> str:
    """'HEVC / x265' (pour codec compact dans header)."""
    codec_full = video.get("codec", "")
    # 'HEVC / x265' -> 'x265', 'AVC / x264' -> 'x264'
    if "x265" in codec_full:
        return "x265"
    if "x264" in codec_full:
        return "x264"
    if "HEVC" in codec_full:
        return "HEVC"
    if "AVC" in codec_full:
        return "AVC"
    return codec_full


def _hdr_compact(hdr: str) -> str:
    """SDR -> 'SDR', HDR10/HDR10+/DoVi -> 'HDR' (l'en-tête est synthétique)."""
    if hdr in {"HDR10", "HDR10+", "DoVi", "HDR", "HLG"}:
        return "HDR"
    if hdr == "SDR":
        return "SDR"
    return ""


def _build_ratings_section(
    tmdb_rating: str, imdb_rating: str,
    tmdb_rating_raw=None, tmdb_vote_count=None,
    imdb_vote_count=None,
    tmdb_context=None, media_type=None,
    assets: dict | None = None,
) -> str:
    """Bloc des notes : logos TMDB/IMDb a gauche (clickables), note, etoiles, votes.

    Pas de titre/header : les etoiles + logos suffisent a identifier la section.
    """
    lines = []
    assets = assets or {}
    tmdb_logo = assets.get("tmdb_logo_url", "")
    imdb_logo = assets.get("imdb_logo_url", "")

    if tmdb_rating:
        votes = _format_vote_count(tmdb_vote_count)
        votes_part = f" [color=#FFFFFF]({votes})[/color]" if votes else ""
        stars = _format_stars(tmdb_rating_raw, assets)
        # Logo clickable a gauche (remplace 'TMDB :')
        tmdb_url = _tmdb_url_for(tmdb_context, media_type)
        if tmdb_logo and tmdb_url:
            logo_part = f"[url={tmdb_url}][img=30]{tmdb_logo}[/img][/url]"
        elif tmdb_logo:
            logo_part = f"[img=30]{tmdb_logo}[/img]"
        else:
            logo_part = "TMDB"
        lines.append(
            f"{logo_part} [b] {tmdb_rating} [/b] {stars}{votes_part}"
        )
    if imdb_rating:
        rating_clean = imdb_rating.replace("/10", "").strip()
        try:
            imdb_raw = float(rating_clean)
        except (TypeError, ValueError):
            imdb_raw = None
        stars = _format_stars(imdb_raw, assets)
        votes = _format_vote_count(imdb_vote_count)
        votes_part = f" [color=#FFFFFF]({votes})[/color]" if votes else ""
        imdb_url = _imdb_url_for(tmdb_context)
        if imdb_logo and imdb_url:
            logo_part = f"[url={imdb_url}][img=30]{imdb_logo}[/img][/url]"
        elif imdb_logo:
            logo_part = f"[img=30]{imdb_logo}[/img]"
        else:
            logo_part = "IMDb"
        lines.append(
            f"{logo_part} [b] {rating_clean} [/b] {stars}{votes_part}"
        )

    if not lines:
        return ""

    return "\n".join(lines)


def _build_movie_info_block(
    tmdb_context: dict | None, fallback_year: str, include_runtime: bool = True,
    is_tv: bool = False,
) -> str:
    """Lignes 'Titre original / Année / Réalisateur / etc.' ou bloc vide."""
    if not tmdb_context:
        if fallback_year:
            return f"[color={COLOR_TAUPE}]Année :[/color] {fallback_year}"
        return ""

    lines: list[str] = []

    original_title = tmdb_context.get("original_title") or ""
    title = tmdb_context.get("title") or ""
    if original_title and original_title != title:
        lines.append(
            f"[color={COLOR_TAUPE}]Titre original :[/color] {original_title}"
        )

    # Date complete au lieu de juste l'annee si dispo
    full_date = _format_full_date_fr(tmdb_context.get("release_date") or "")
    if full_date:
        label = "Première diffusion" if is_tv else "Sortie"
        lines.append(f"[color={COLOR_TAUPE}]{label} :[/color] {full_date}")
    else:
        year = fallback_year
        if year:
            lines.append(f"[color={COLOR_TAUPE}]Année :[/color] {year}")

    director = tmdb_context.get("director") or ""
    if director:
        # Pour les series : "Createur" plutot que "Realisateur"
        label = "Créateur" if is_tv else "Réalisateur"
        lines.append(f"[color={COLOR_TAUPE}]{label} :[/color] {director}")

    writers = tmdb_context.get("writers") or []
    if writers:
        lines.append(
            f"[color={COLOR_TAUPE}]Scénario :[/color] {', '.join(writers)}"
        )

    genres = tmdb_context.get("genres") or []
    if genres:
        lines.append(f"[color={COLOR_TAUPE}]Genre :[/color] {_format_genres(genres)}")

    countries = tmdb_context.get("production_countries") or []
    if countries:
        # Premier pays principal avec drapeau
        lines.append(
            f"[color={COLOR_TAUPE}]Pays :[/color] "
            f"{_format_country_with_flag(countries[0])}"
        )

    runtime = tmdb_context.get("runtime")
    if runtime and include_runtime:
        lines.append(f"[color={COLOR_TAUPE}]Durée :[/color] {_format_runtime(runtime)}")

    return "\n".join(lines)


def _build_cast_section(tmdb_context: dict | None) -> str:
    if not tmdb_context:
        return ""
    cast = tmdb_context.get("cast") or []
    if not cast:
        return ""

    lines = [f"\n[color={COLOR_GOLD}][b][size=20]🎭 Casting 🎭[/size][/b][/color]"]

    # Bloc photos : on prend les profile_path TMDB des 5 acteurs principaux
    # qui en ont une (les autres restent dans la liste textuelle).
    photo_urls = []
    for item in cast[:5]:
        path = (item.get("profile_path") or "").strip()
        if path:
            photo_urls.append(f"https://image.tmdb.org/t/p/w185{path}")
    if photo_urls:
        photos_line = " ".join(f"[img=110x0]{u}[/img]" for u in photo_urls)
        lines.append("")
        lines.append(photos_line)
        lines.append("")

    # Liste textuelle classique (toujours, meme si photos presentes)
    for item in cast[:5]:
        name = (item.get("name") or "").strip()
        character = (item.get("character") or "").strip()
        if name and character:
            lines.append(f"• {name} — {character}")
        elif name:
            lines.append(f"• {name}")

    return "\n".join(lines)


def _build_awards_section(awards_text: str) -> str:
    """OMDb retourne par ex. 'Won 4 Oscars. 86 wins & 158 nominations total'."""
    if not awards_text or awards_text.strip().upper() in {"N/A", "NONE"}:
        return ""
    return (
        f"\n[color={COLOR_GOLD}][b][size=20]🏆 Récompenses 🏆[/size][/b][/color]\n"
        f"{awards_text.strip()}"
    )


def _build_synopsis_section(tmdb_overview: str, omdb_plot: str) -> str:
    text = (tmdb_overview or "").strip() or (omdb_plot or "").strip()
    if not text:
        return ""
    return (
        f"\n[color={COLOR_GOLD}][b][size=20]📝 Synopsis 📝[/size][/b][/color]\n\n"
        f"{text}"
    )


def _build_video_block(video: dict) -> str:
    lines: list[str] = []
    codec = video.get("codec") or ""
    if codec:
        lines.append(f"• Codec : {codec}")

    width = video.get("width")
    height = video.get("height")
    res_label = video.get("resolution_label") or ""
    if width and height:
        lines.append(
            f"• Résolution : {width}x{height} ({res_label})"
            if res_label
            else f"• Résolution : {width}x{height}"
        )
    elif res_label:
        lines.append(f"• Résolution : {res_label}")

    hdr = video.get("hdr") or ""
    if hdr and hdr != "SDR":
        lines.append(f"• HDR : {hdr}")

    bitrate = video.get("bitrate_pretty") or ""
    if bitrate:
        lines.append(f"• Bitrate : {bitrate}")

    bit_depth = video.get("bit_depth") or ""
    if bit_depth:
        lines.append(f"• Bit depth : {bit_depth}")

    framerate = video.get("framerate") or ""
    if framerate:
        lines.append(f"• Framerate : {framerate}")

    return "\n".join(lines)


def _build_audio_block(
    audio_tracks: list[dict],
    production_countries: list[str],
    original_language: str = "",
    release_fr_variant: str = "",
) -> str:
    """Construit le bloc audio du BBCode.

    `release_fr_variant` (NOTES round 6 B1) : variant FR extrait du
    release_name (VFF/VFQ/VFB/VOF/VOQ/VOB). Si la piste FR n'a pas
    de region/title explicite, on utilise ce hint comme source de
    verite plutot que de fallback sur "VFF" par defaut. Bug reel :
    "La.Deesse.Des.Mouches.A.Feu.2020.VOQ..." -> piste FR sans tag
    -> on affichait "VFF" au lieu de "VOQ".
    """
    if not audio_tracks:
        return "(aucune piste audio détectée)"
    orig_iso = (original_language or "").strip().lower()
    variant_hint = (release_fr_variant or "").upper()
    # Pour le drapeau : VFQ/VOQ -> CA, VFB/VOB -> BE, VFF/VOF -> FR
    variant_to_region = {
        "VFQ": "CA", "VOQ": "CA",
        "VFB": "BE", "VOB": "BE",
        "VFF": "FR", "VOF": "FR", "VF2": "FR",
    }
    inferred_region = variant_to_region.get(variant_hint, "")
    lines: list[str] = []
    for t in audio_tracks:
        if t.get("is_commentary") or t.get("is_audio_description"):
            continue

        lang_iso = t.get("language") or ""
        region = (t.get("region") or "").upper()
        # Si pas de region MediaInfo MAIS variant connu via release_name
        # ET piste FR : on utilise la region inferee pour le drapeau ET le label.
        effective_region = region
        if not region and lang_iso == "fr" and inferred_region:
            effective_region = inferred_region

        # Drapeau
        flag = ""
        if effective_region:
            flag = flag_for_country(effective_region) or ""
        if not flag:
            flag = flag_for_language_with_context(lang_iso, production_countries) or ""

        title = (t.get("title") or "").strip()
        is_vo = (
            bool(orig_iso)
            and lang_iso == orig_iso
            and lang_iso != "fr"
        )
        # Pour FR sans title/region explicite, on injecte le variant hint
        # dans le title pour que _language_label le pick up via sa regle #1.
        label_title = title
        if not title and lang_iso == "fr" and variant_hint:
            label_title = variant_hint
        lang_label = _language_label(lang_iso, label_title, region=effective_region, is_vo=is_vo)

        codec = t.get("codec") or "?"
        channels = t.get("channels") or ""
        bitrate = t.get("bitrate_pretty") or ""
        codec_compact = f"{codec} {channels}".strip() if channels else codec

        bullet_parts = [p for p in [flag, lang_label] if p]
        line = "• " + " ".join(bullet_parts)
        if codec_compact:
            line += f" — {codec_compact}"
        if bitrate:
            line += f" — {bitrate}"
        lines.append(line)

    return "\n".join(lines) if lines else "(aucune piste audio détectée)"


def _build_subtitle_block(
    subtitle_tracks: list[dict],
    production_countries: list[str],
    original_language: str = "",
) -> str:
    if not subtitle_tracks:
        return "(aucun sous-titre)"

    # Fusion : (langue, region, kind) -> [formats]
    # On inclut la region dans la cle pour distinguer un sub FR-FR Forced
    # d'un sub FR-CA Forced (sinon ils etaient fusionnes a tort en une ligne).
    grouped: dict = {}
    order: list = []
    for t in subtitle_tracks:
        lang = t.get("language") or ""
        region = (t.get("region") or "").upper()
        kind = t.get("kind") or "Complet"
        key = (lang, region, kind)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        fmt = t.get("format") or ""
        if fmt and fmt not in grouped[key]:
            grouped[key].append(fmt)

    orig_iso = (original_language or "").strip().lower()
    lines: list[str] = []
    for key in order:
        lang_iso, region, kind = key
        # Drapeau : region prioritaire sinon langue
        flag = ""
        if region:
            flag = flag_for_country(region) or ""
        if not flag:
            flag = flag_for_language_with_context(lang_iso, production_countries) or ""

        is_vo = bool(orig_iso) and lang_iso == orig_iso and lang_iso != "fr"
        lang_label = _language_label(lang_iso, "", region=region, is_vo=is_vo)

        bullet_parts = [p for p in [flag, lang_label] if p]
        line = "• " + " ".join(bullet_parts)
        if kind:
            line += f" {kind}"
        formats = grouped[key]
        if formats:
            line += " — " + " + ".join(formats)
        lines.append(line)

    return "\n".join(lines) if lines else "(aucun sous-titre)"


# Mapping ISO 639 -> nom francais affiche dans la fiche
_ISO_TO_LABEL = {
    "fr": "Français",
    "en": "Anglais",
    "es": "Espagnol",
    "de": "Allemand",
    "it": "Italien",
    "pt": "Portugais",
    "ja": "Japonais",
    "ko": "Coréen",
    "zh": "Chinois",
    "ru": "Russe",
    "ar": "Arabe",
    "hi": "Hindi",
    "tr": "Turc",
    "pl": "Polonais",
    "nl": "Néerlandais",
    "sv": "Suédois",
    "no": "Norvégien",
    "da": "Danois",
    "fi": "Finnois",
    "cs": "Tchèque",
    "sk": "Slovaque",
    "hu": "Hongrois",
    "ro": "Roumain",
    "bg": "Bulgare",
    "el": "Grec",
    "uk": "Ukrainien",
    "he": "Hébreu",
    "th": "Thaï",
    "vi": "Vietnamien",
    "id": "Indonésien",
    "ms": "Malais",
    "fa": "Persan",
    "ur": "Ourdou",
    "bn": "Bengali",
    "ta": "Tamoul",
    "te": "Télougou",
}

# Tri-letter codes (ISO 639-2) -> 2-letter (ISO 639-1) pour normalisation
_ISO3_TO_ISO2 = {
    "fra": "fr", "fre": "fr",
    "eng": "en",
    "spa": "es",
    "deu": "de", "ger": "de",
    "ita": "it",
    "por": "pt",
    "jpn": "ja",
    "kor": "ko",
    "zho": "zh", "chi": "zh",
    "rus": "ru",
    "ara": "ar",
    "hin": "hi",
    "tur": "tr",
    "pol": "pl",
    "nld": "nl", "dut": "nl",
    "swe": "sv",
    "nor": "no", "nob": "no", "nno": "no",
    "dan": "da",
    "fin": "fi",
    "ces": "cs", "cze": "cs",
    "slk": "sk", "slo": "sk",
    "hun": "hu",
    "ron": "ro", "rum": "ro",
    "bul": "bg",
    "ell": "el", "gre": "el",
    "ukr": "uk",
    "heb": "he",
    "tha": "th",
    "vie": "vi",
    "ind": "id",
    "msa": "ms", "may": "ms",
    "fas": "fa", "per": "fa",
    "urd": "ur",
    "ben": "bn",
    "tam": "ta",
    "tel": "te",
}


def _language_label(
    iso: str,
    title: str = "",
    region: str = "",
    is_vo: bool = False,
) -> str:
    """Retourne 'Français VFF', 'Anglais VO', etc.

    Variantes derivees :
    - Tag explicite dans le title (VFF/VFQ/VFB/VF2/VOF/VOQ/VOB/VO) : prioritaire
    - Sinon, pour le francais : region CA -> VFQ, BE -> VFB, CH -> VFF
      (la suisse romande est consideree comme VFF par convention),
      sinon VFF par defaut
    - Pour les autres langues : si is_vo (= la piste est la VO du film d'apres
      tmdb_context.original_language) on suffixe ' VO'
    """
    if not iso:
        return "Inconnue"
    key = iso.strip().lower()
    if len(key) == 3:
        key = _ISO3_TO_ISO2.get(key, key)
    label = _ISO_TO_LABEL.get(key)
    if not label:
        return iso.upper() if iso else "Inconnue"

    # 1. Tag explicite dans le title : prioritaire
    title_upper = (title or "").upper()
    for variant in ["VFF", "VFQ", "VFB", "VF2", "VOF", "VOQ", "VOB"]:
        if variant in title_upper:
            return f"{label} {variant}"

    # 2. Francais : on derive depuis la region
    if key == "fr":
        region_to_variant = {"CA": "VFQ", "BE": "VFB", "CH": "VFF", "FR": "VFF"}
        variant = region_to_variant.get((region or "").upper(), "VFF")
        return f"{label} {variant}"

    # 3. Autres langues : marquer VO si c'est la langue d'origine du film
    if is_vo:
        return f"{label} VO"

    return label


# ============================================================
# RENDERER PRINCIPAL
# ============================================================

def render_bbcode(
    tracker: "Tracker",
    video_path: Path,
    release_name: str,
    mediainfo_data: dict,
    tmdb_context: dict | None,
    poster_url: str,
    awards_text: str,
    omdb_plot: str,
    release_type: str,
    release_source: str,
    media_info=None,
) -> str:
    """Rend la fiche BBCode finale en utilisant le template du tracker."""
    template_path = (
        Path(tracker.__class__.__module__.replace(".", "/")).parent  # noqa: not used
    )
    # On retrouve le template via le dossier du tracker. Plus simple :
    # on charge depuis le path connu via load_tracker_assets ou similaire.
    # Ici, on utilise une convention : trackers/<key>/template.bbcode
    from ..trackers import gemini  # default
    # Recharge proprement via le module du tracker
    media_type = media_info.media_type if media_info is not None else None
    template_text = _load_template_for(tracker.key, media_type)

    video = mediainfo_data.get("video", {}) or {}
    audio_tracks = mediainfo_data.get("audio_tracks", []) or []
    subtitle_tracks = mediainfo_data.get("subtitle_tracks", []) or []
    production_countries = (
        (tmdb_context or {}).get("production_countries", []) or []
    )

    # Header
    lang_label = _lang_label_from_release_name(release_name)
    main_audio = audio_tracks[0] if audio_tracks else {}
    main_audio_str = _audio_codec_compact(
        main_audio.get("codec", ""), main_audio.get("channels", "")
    )
    header_line = _build_header_line(
        lang_label,
        video.get("resolution_label", ""),
        _hdr_compact(video.get("hdr", "")),
        release_source,
        _build_video_codec_compact(video),
        main_audio_str,
    )

    # Titre + année
    title = ((tmdb_context or {}).get("title") or "").strip()
    if not title:
        # Fallback intelligent : tous les tokens avant l'annee, espaces au lieu de points
        import re as _re
        m = _re.search(r"^(.+?)\.((?:19|20)\d{2})\b", release_name)
        if m:
            title = m.group(1).replace(".", " ")
        else:
            title = release_name.replace(".", " ")
    year = ""
    if tmdb_context:
        year = _format_iso_date_year(tmdb_context.get("release_date") or "")
    if not year:
        # Fallback : extraire l'annee du release_name
        import re as _re
        m = _re.search(r"\.((?:19|20)\d{2})\.", release_name)
        if m:
            year = m.group(1)

    # Notes + liens externes
    tmdb_rating_raw = (tmdb_context or {}).get("tmdb_rating")
    tmdb_rating_str = _format_rating(tmdb_rating_raw)
    tmdb_vote_count = (tmdb_context or {}).get("tmdb_vote_count")
    imdb_rating_str = (tmdb_context or {}).get("imdb_rating") or ""
    imdb_vote_count = (tmdb_context or {}).get("imdb_vote_count") or 0
    assets = (tracker.rules.get("presentation_assets") or {})
    ratings_section = _build_ratings_section(
        tmdb_rating_str, imdb_rating_str,
        tmdb_rating_raw=tmdb_rating_raw,
        tmdb_vote_count=tmdb_vote_count,
        imdb_vote_count=imdb_vote_count,
        tmdb_context=tmdb_context,
        media_type=media_type,
        assets=assets,
    )
    external_links = _format_youtube_link(tmdb_context, assets)

    # Pour les series : pas de duree (variable selon les episodes)
    include_runtime = True
    if media_info is not None:
        from .media_type import MediaType as _MT
        if media_info.media_type in {
            _MT.TV_EPISODE, _MT.TV_SEASON, _MT.TV_INTEGRALE,
        }:
            include_runtime = False
    is_tv_for_label = not include_runtime
    movie_info_block = _build_movie_info_block(
        tmdb_context, year, include_runtime, is_tv=is_tv_for_label,
    )
    cast_section = _build_cast_section(tmdb_context)
    awards_section = _build_awards_section(awards_text)
    synopsis_section = _build_synopsis_section(
        (tmdb_context or {}).get("overview", ""), omdb_plot
    )

    original_language = (tmdb_context or {}).get("original_language") or ""
    # NOTES round 6 B1 : extrait le variant FR du release_name pour que
    # les pistes audio FR sans region MediaInfo affichent le bon tag
    # (VOQ/VFQ -> 🇨🇦 + "Français VOQ" au lieu de 🇫🇷 + "Français VFF").
    rn_upper = (release_name or "").upper()
    _fr_variants = ("VFQ", "VOQ", "VFB", "VOB", "VFF", "VOF", "VF2")
    release_fr_variant = ""
    for _v in _fr_variants:
        if "." + _v + "." in rn_upper or rn_upper.startswith(_v + ".") or rn_upper.endswith("." + _v):
            release_fr_variant = _v
            break
    video_block = _build_video_block(video)
    audio_block = _build_audio_block(
        audio_tracks, production_countries, original_language,
        release_fr_variant=release_fr_variant,
    )
    subtitle_block = _build_subtitle_block(
        subtitle_tracks, production_countries, original_language,
    )

    poster_section = _build_poster_section(poster_url)

    context = {
        "poster_section": poster_section,
        "title": title,
        "year": year,
        "header_line": header_line,
        "ratings_section": ratings_section,
        "external_links": external_links,
        "movie_info_block": movie_info_block,
        "cast_section": cast_section,
        "awards_section": awards_section,
        "synopsis_section": synopsis_section,
        "release_title": release_name,
        "release_type": release_type,
        "release_source": release_source,
        "container": _normalize_container(mediainfo_data.get("container", "?")),
        "video_block": video_block,
        "audio_block": audio_block,
        "subtitle_block": subtitle_block,
        "file_size": mediainfo_data.get("size_pretty", ""),
        "episode_tag": _format_episode_tag_for_template(media_info),
        "episode_title_block": _format_episode_title_block(media_info, tmdb_context),
        "season_number": media_info.season if (media_info and media_info.season) else "",
        "episode_count": (
            len(media_info.all_videos) if media_info else 0
        ),
        "seasons_total": (
            (tmdb_context or {}).get("number_of_seasons")
            or (len(media_info.seasons_found) if (media_info and media_info.seasons_found) else "?")
        ),
        "episodes_total": (
            (tmdb_context or {}).get("number_of_episodes")
            or (len(media_info.all_videos) if media_info else "?")
        ),
        "episode_list_block": _format_episode_list(media_info, tmdb_context),
        "seasons_list_block": _format_seasons_list(tmdb_context),
        "avg_episode_runtime": _format_avg_episode_runtime(tmdb_context),
    }

    rendered = template_text.format(**context)

    import re as _re
    rendered = _re.sub(r"\n{3,}", "\n\n", rendered)
    sep_jaune = r"\[img=500\]https://i\.imgur\.com/jOSyeDp\.png\[/img\]"
    sep_brun = r"\[img=500\]https://i\.imgur\.com/ZHUrtS7\.png\[/img\]"
    for sep in [sep_jaune, sep_brun]:
        rendered = _re.sub(rf"({sep})\s*\n\s*({sep})", r"\1", rendered)
    rendered = _re.sub(rf"({sep_brun})\s*\n\s*({sep_jaune})", r"\1", rendered)
    rendered = _re.sub(r"\n{3,}", "\n\n", rendered).strip()
    return rendered


def _load_template_for(tracker_key, media_type=None):
    from ..trackers import TRACKER_LOADERS
    if tracker_key not in TRACKER_LOADERS:
        raise KeyError(f"Tracker inconnu : {tracker_key}")
    import importlib
    module = importlib.import_module(
        f"flox_uploader.trackers.{tracker_key}.tracker"
    )
    tracker_dir = Path(module.__file__).resolve().parent
    if media_type is not None:
        from .media_type import MediaType
        type_to_filename = {
            MediaType.MOVIE: "template_movie.bbcode",
            MediaType.TV_EPISODE: "template_episode.bbcode",
            MediaType.TV_SEASON: "template_season.bbcode",
            MediaType.TV_INTEGRALE: "template_integrale.bbcode",
        }
        filename = type_to_filename.get(media_type)
        if filename:
            specific = tracker_dir / filename
            if specific.exists():
                return specific.read_text(encoding="utf-8")
    template_path = tracker_dir / "template.bbcode"
    if not template_path.exists():
        raise FileNotFoundError(f"Template introuvable : {template_path}")
    return template_path.read_text(encoding="utf-8")
