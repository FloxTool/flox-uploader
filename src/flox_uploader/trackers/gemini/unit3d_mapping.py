"""Mapping des IDs Unit3D pour le tracker Gemini.

Source : documentation officielle G3MINI TR4CK3R API (PDF transmis par Louis,
2026-05-07). Les IDs ci-dessous sont la VERITE TERRAIN, plus fiables que le
mapping Unit3Dup-G3MINI/common/trackers/gemini.py qui contenait plusieurs
erreurs (BDRip=25 wrong → vraiment 3, DVDRip=24 wrong → vraiment 13, types
WEBMux=26/DLMux=27/BDMux=29/3D=32 qui n'existent pas dans Gemini reel).

Important — categories qui demandent quoi (cf. doc) :
- Categories Films (TMDB=oui)  : 1 (Films), 7 (Films Animations), 13 (Films Documentaires)
- Categories Series (TMDB=oui) : 2 (Series), 6 (Series Animations), 14 (Series Documentaires), 15 (Emission TV)
- Categorie Jeu (IGDB=oui)     : 3 (Jeux)
- Categories sans meta TMDB    : 10 (Sports), 12 (Livres), 17 (Logiciels), 18 (Formations)
- MediaInfo obligatoire pour   : 1, 2, 6, 7, 10, 13, 14, 15
- resolution_id requis pour    : toutes les categories Film/Serie TMDB
- season_number/episode_number : requis pour les categories Serie TMDB (2, 6, 14, 15)
"""
from __future__ import annotations

from ...core.media_type import MediaType


# ============================================================
# CATEGORIES (CATEGORY)
# ============================================================
# Source : doc PDF officielle G3MINI TR4CK3R, page 4, tableau Catégories.

CATEGORY_MOVIE = 1               # Films
CATEGORY_TV = 2                  # Séries
CATEGORY_GAME = 3                # Jeux
CATEGORY_TV_ANIME = 6            # Séries Animations
CATEGORY_MOVIE_ANIME = 7         # Films Animations
CATEGORY_SPORTS = 10             # Sports
CATEGORY_BOOKS = 12              # Livres
CATEGORY_MOVIE_DOC = 13          # Films Documentaires
CATEGORY_TV_DOC = 14             # Séries Documentaires
CATEGORY_TV_SHOW = 15            # Émission TV
CATEGORY_SOFTWARE = 17           # Logiciels
CATEGORY_TRAINING = 18           # Formations

# Alias retro-compat : ancien CATEGORY_EDICOLA (= 6 dans Unit3Dup-G3MINI mais
# c'etait FAUX et collision avec CATEGORY_TV_ANIME). Plus utilise — on garde
# uniquement pour ne pas casser des imports historiques.
CATEGORY_EDICOLA = CATEGORY_BOOKS  # ID 12 (Livres) dans la doc officielle


# Categories qui demandent un TMDB ID Film
TMDB_MOVIE_CATEGORIES = {CATEGORY_MOVIE, CATEGORY_MOVIE_ANIME, CATEGORY_MOVIE_DOC}
# Categories qui demandent un TMDB ID Série
TMDB_TV_CATEGORIES = {
    CATEGORY_TV, CATEGORY_TV_ANIME, CATEGORY_TV_DOC, CATEGORY_TV_SHOW,
}
# Categories qui demandent season_number/episode_number
SERIES_META_CATEGORIES = TMDB_TV_CATEGORIES
# Categories ou MediaInfo est OBLIGATOIRE
MEDIAINFO_REQUIRED_CATEGORIES = (
    TMDB_MOVIE_CATEGORIES | TMDB_TV_CATEGORIES | {CATEGORY_SPORTS}
)
# Categories ou resolution_id est REQUIS (Film ou Serie TMDB)
RESOLUTION_REQUIRED_CATEGORIES = TMDB_MOVIE_CATEGORIES | TMDB_TV_CATEGORIES


# ============================================================
# Lot N.1 : keywords pour detecter les uploads Sports.
# ============================================================
# TMDB n'a quasiment pas d'entrees pour les events sportifs (UFC 300, F1
# Monaco GP, Tour de France, Super Bowl). Quand TMDB ne matche pas, on
# tombe en fallback sur ces keywords — c'est tres fiable parce que les
# release names sportifs contiennent quasi-toujours le nom de la ligue,
# de la competition ou de l'event en token isole.
#
# IMPORTANT : ces keywords ne sont CONSULTES QUE quand TMDB n'a rien
# trouve (tmdb_context vide ou pas de genres). Si TMDB a matche un film
# normal contenant "F1" (le film Brad Pitt 2025) ou "Le.Mans" (Le Mans
# 66), TMDB gagne et on classe en Films — la liste de keywords sport
# n'est jamais consultee dans ce cas. Cf. category_id_for ci-dessous.

SPORTS_KEYWORDS: tuple[str, ...] = (
    # MMA / Boxe / arts martiaux
    "UFC", "MMA", "Bellator", "PFL", "ONE.Championship", "ONE.FC",
    "Boxing", "Boxe", "WBC", "WBA", "IBF", "WBO",
    # US sports
    "NFL", "NBA", "NHL", "MLB", "MLS", "NCAA",
    "Super.Bowl", "Stanley.Cup", "World.Series", "NBA.Finals",
    "NFL.Draft", "All.Star",
    # Football / Soccer
    "FIFA", "UEFA", "Coupe.du.Monde", "World.Cup",
    "Champions.League", "Ligue.des.Champions",
    "Premier.League", "Ligue.1", "La.Liga", "Bundesliga", "Serie.A",
    "Euro.20", "Copa.America", "AFCON", "CAN.20",
    "Coupe.de.France", "FA.Cup", "Coppa.Italia",
    # Motorsport
    "F1", "Formula.1", "Formula1", "MotoGP", "NASCAR", "WRC", "IndyCar",
    "Le.Mans", "24.Heures", "24h.Le.Mans", "Dakar",
    "Grand.Prix",
    # Cyclisme
    "Tour.de.France", "Tour.d.Italie", "Giro.d.Italia",
    "Vuelta", "Vuelta.a.Espana",
    "Paris.Roubaix", "Liege.Bastogne", "Milan.San.Remo",
    # Tennis / Golf
    "Wimbledon", "Roland.Garros", "Roland-Garros",
    "US.Open", "Australian.Open",
    "PGA", "Masters.Tournament", "Ryder.Cup",
    # Olympiques / multi-sports
    "Olympics", "Olympiques", "Paralympics", "JO.20", "JO.Paris",
    "Commonwealth.Games", "Asian.Games",
    # Catch / Wrestling
    "WWE", "AEW", "WrestleMania", "SmackDown", "RAW", "NXT",
    "SummerSlam", "Royal.Rumble",
    # Rugby / autres
    "Six.Nations", "Top.14", "World.Rugby",
    # Eurosport / generique
    "Eurosport",
)


# Pre-tri des keywords par longueur decroissante : un release qui contient
# "NBA.Finals" doit matcher "NBA.Finals" et pas "NBA" (plus specifique gagne).
# Idem "Super.Bowl" doit matcher avant "NFL". Tri unique au niveau module.
_SPORTS_KEYWORDS_SORTED: tuple[str, ...] = tuple(
    sorted(SPORTS_KEYWORDS, key=lambda k: -len(k))
)


def _has_sports_keyword(release_name: str) -> str:
    """Si un keyword sport est present dans le release_name, le retourne.

    Matching :
    - case-insensitive
    - keyword doit etre un TOKEN ISOLE (entoure de `.`, `-`, `_`, espace ou
      bord de chaine), pour eviter qu'un substring matche par hasard
      ("F1" dans "CONFINEMENT" ne doit PAS matcher)
    - les keywords plus longs gagnent (NBA.Finals avant NBA) grace au pre-tri

    Retourne le keyword matche, ou "" si aucun.
    """
    import re as _re
    for kw in _SPORTS_KEYWORDS_SORTED:
        # Le keyword peut contenir des points (ex: "F1", "Tour.de.France"),
        # qu'on echappe pour les traiter comme litteraux.
        pattern = r"(?:^|[._\-\s])" + _re.escape(kw) + r"(?:[._\-\s]|$)"
        if _re.search(pattern, release_name, _re.IGNORECASE):
            return kw
    return ""


def category_id_for(
    media_type: MediaType,
    tmdb_context: dict | None = None,
    release_name: str = "",
) -> int:
    """Retourne le category_id selon le media_type, les genres TMDB et le nom.

    Priorite stricte :

      1. TMDB a matche ET genre 'Animation'      -> Films/Series Anime
      2. TMDB a matche ET genre 'Documentary'    -> Films/Series Doc
      3. TMDB a matche (autres genres)           -> Films / Series classiques
      4. TMDB n'a PAS matche -> on regarde les SPORTS_KEYWORDS dans le
         release_name :
            a. Match keyword sport -> CATEGORY_SPORTS (10)
            b. Sinon               -> Films / Series par defaut

    Cette priorite garantit que :
    - Le film "F1" (TMDB id 911430, Brad Pitt) reste classe en Films, meme
      s'il contient le keyword "F1" — TMDB a matche, donc TMDB gagne.
    - Une course F1 reelle ("F1.2024.05.Miami.GP-TEAM") qui n'a pas de
      fiche TMDB tombe en Sports via le keyword.
    - Un docu-serie comme "F1.Drive.to.Survive" garde sa categorie Series
      Documentaires (TMDB renvoie genre Documentary, qui prime).

    L'utilisateur peut toujours overrider via la page detail
    (manual_category_id) pour les cas que l'auto-detect rate (ex: emission
    TV, talk-show qui doit aller en cat 15).

    Args:
        media_type   : MediaType detecte (MOVIE / TV_EPISODE / TV_SEASON /
                       TV_INTEGRALE).
        tmdb_context : dict TMDB enrichi (titre, genres, ids), ou None/{}
                       si TMDB n'a rien trouve.
        release_name : nom du release final (utilise pour les keywords sport
                       quand TMDB n'a pas matche). Optionnel pour la
                       compat tests existants.
    """
    is_tv = media_type in {
        MediaType.TV_EPISODE, MediaType.TV_SEASON, MediaType.TV_INTEGRALE,
    }
    ctx = tmdb_context or {}
    genres = ctx.get("genres") or []
    genres_lower = [(g or "").strip().lower() for g in genres]
    has_tmdb_match = bool(
        ctx.get("movie_id") or ctx.get("tv_id") or ctx.get("tmdb_id")
        or ctx.get("title") or genres
    )

    is_animation = any("animation" in g for g in genres_lower)
    is_documentary = any(
        "documentary" in g or "documentaire" in g for g in genres_lower
    )

    # 1-2-3 : TMDB a matche -> on respecte TMDB.
    if has_tmdb_match:
        if is_tv:
            if is_animation:
                return CATEGORY_TV_ANIME
            if is_documentary:
                return CATEGORY_TV_DOC
            return CATEGORY_TV
        # Film
        if is_animation:
            return CATEGORY_MOVIE_ANIME
        if is_documentary:
            return CATEGORY_MOVIE_DOC
        return CATEGORY_MOVIE

    # 4 : TMDB n'a rien trouve -> fallback keywords sport.
    if release_name and _has_sports_keyword(release_name):
        return CATEGORY_SPORTS

    # Defaut : Films / Series.
    return CATEGORY_TV if is_tv else CATEGORY_MOVIE


def category_guess_source(
    media_type: MediaType,
    tmdb_context: dict | None = None,
    release_name: str = "",
) -> str:
    """Retourne un libelle humain expliquant POURQUOI on a choisi cette categorie.

    Permet a l'UI de montrer la source du guess sous la dropdown Categorie,
    pour aider l'utilisateur a comprendre et catch les erreurs sans avoir a
    deviner ce que fait l'algo.

    Exemples de retour :
    - "TMDB : genre 'Animation' detecte"
    - "TMDB : genres Action, Drama"
    - "Keyword sport detecte : 'F1'"
    - "Defaut Films (TMDB n'a pas matche, aucun keyword sport)"
    """
    ctx = tmdb_context or {}
    genres = [(g or "").strip() for g in (ctx.get("genres") or []) if g]
    genres_lower = [g.lower() for g in genres]
    has_tmdb_match = bool(
        ctx.get("movie_id") or ctx.get("tv_id") or ctx.get("tmdb_id")
        or ctx.get("title") or genres
    )

    if has_tmdb_match:
        if any("animation" in g for g in genres_lower):
            return "TMDB : genre 'Animation' detecte"
        if any(
            "documentary" in g or "documentaire" in g for g in genres_lower
        ):
            return "TMDB : genre 'Documentaire' detecte"
        if genres:
            sample = ", ".join(genres[:3])
            return f"TMDB : genres {sample}"
        return "TMDB : titre matche (sans genre)"

    # TMDB n'a pas matche
    kw = _has_sports_keyword(release_name) if release_name else ""
    if kw:
        return f"Keyword sport detecte : '{kw}'"

    is_tv = media_type in {
        MediaType.TV_EPISODE, MediaType.TV_SEASON, MediaType.TV_INTEGRALE,
    }
    fallback = "Series" if is_tv else "Films"
    return f"Defaut {fallback} (TMDB n'a pas matche, aucun keyword sport)"


# ============================================================
# TYPES (TYPE_ID)
# ============================================================
# Source : doc PDF officielle G3MINI TR4CK3R, page 4-5, tableau Types.

# Types video
TYPE_FULL_DISC = 1               # FULL DISC (BD/UHD ISO)
TYPE_REMUX = 2                   # REMUX
TYPE_BDRIP = 3                   # BDRip (et Encode generique BluRay)
TYPE_WEB = 4                     # WEB (anciennement WEB-DL dans Unit3Dup)
TYPE_WEBRIP = 5                  # WEBRip
TYPE_HDTV = 6                    # HDTV
TYPE_ISO = 7                     # ISO
TYPE_DVD = 11                    # DVD
TYPE_TVRIP = 12                  # TVRip
TYPE_DVDRIP = 13                 # DVDRip
TYPE_VHSRIP = 38                 # VHSRip

# Alias retro-compat (anciens noms qui pointaient vers d'autres IDs)
TYPE_ENCODE = TYPE_BDRIP         # Encode generique (BluRay rip) -> id 3
TYPE_BLURAY = TYPE_BDRIP
TYPE_WEB_DL = TYPE_WEB           # Anciennement 4 (idem dans la doc)


# Mapping textuel -> id pour le type_id_for(release_name)
TYPE_ID_TABLE: dict[str, int] = {
    # Full disc / ISO
    "full-disc": TYPE_FULL_DISC,
    "fulldisc": TYPE_FULL_DISC,
    "iso": TYPE_ISO,
    # Remux
    "remux": TYPE_REMUX,
    "bdremux": TYPE_REMUX,
    # BDRip / encode
    "bdrip": TYPE_BDRIP,
    "encode": TYPE_BDRIP,
    "bluray": TYPE_BDRIP,
    "fullhd": TYPE_BDRIP,
    "hevc": TYPE_BDRIP,
    "hdrip": TYPE_BDRIP,
    # WEB / WEBRip
    "web": TYPE_WEB,
    "webdl": TYPE_WEB,
    "web-dl": TYPE_WEB,
    "webrip": TYPE_WEBRIP,
    # HDTV / TV captures
    "hdtv": TYPE_HDTV,
    "tvrip": TYPE_TVRIP,
    # DVD
    "dvd": TYPE_DVD,
    "dvdrip": TYPE_DVDRIP,
    # VHS
    "vhsrip": TYPE_VHSRIP,
}


def type_id_for(release_name: str) -> int:
    """Devine le type_id depuis le release_name.

    Ordre de detection : du plus specifique (REMUX, FULL DISC, ISO) au plus
    generique (BluRay = encode = BDRip).
    """
    upper = release_name.upper()

    # Full disc / ISO
    if "FULL DISC" in upper or ".FULL." in upper:
        return TYPE_FULL_DISC
    if "ISO" in upper.split("."):
        return TYPE_ISO

    # Remux : prioritaire car peut coexister avec BluRay
    if "REMUX" in upper:
        return TYPE_REMUX

    # WEB-DL vs WEBRip vs WEB
    if "WEBRIP" in upper or "WEB.RIP" in upper:
        return TYPE_WEBRIP
    if "WEB-DL" in upper or "WEB.DL" in upper or "WEBDL" in upper:
        return TYPE_WEB
    if ".WEB." in upper or upper.endswith(".WEB"):
        # WEB seul (sans -DL ni Rip) -> WEB
        return TYPE_WEB

    # HDTV / TV captures
    if "HDTV" in upper:
        return TYPE_HDTV
    if "TVRIP" in upper or "TV.RIP" in upper:
        return TYPE_TVRIP

    # DVD
    if "DVDRIP" in upper:
        return TYPE_DVDRIP
    if "DVD" in upper.split("."):
        return TYPE_DVD

    # VHS
    if "VHSRIP" in upper or "VHS.RIP" in upper:
        return TYPE_VHSRIP

    # BDRip / BluRay encode generique
    if "BDRIP" in upper or "BLURAY" in upper or "BDREMUX" in upper:
        return TYPE_BDRIP

    # Defaut : BDRip (couvre HEVC, x265, etc. sans source claire). C'est le
    # type le plus probable pour un release scene non-WEB.
    return TYPE_BDRIP


# ============================================================
# RESOLUTIONS
# ============================================================
# Source : doc PDF officielle G3MINI TR4CK3R, page 5, tableau Résolutions.
# Conforme au mapping Unit3Dup-G3MINI (verifie identique).

RESOLUTION_TABLE: dict[str, int] = {
    "4320p": 1,
    "2160p": 2,
    "1080p": 3,
    "1080i": 4,
    "720p": 5,
    "576p": 6,
    "576i": 7,
    "480p": 8,
    "480i": 9,
    "altro": 10,    # autre / inconnu
    "other": 10,    # alias EN
}

RESOLUTION_4320P = RESOLUTION_TABLE["4320p"]
RESOLUTION_2160P = RESOLUTION_TABLE["2160p"]
RESOLUTION_1080P = RESOLUTION_TABLE["1080p"]
RESOLUTION_1080I = RESOLUTION_TABLE["1080i"]
RESOLUTION_720P = RESOLUTION_TABLE["720p"]
RESOLUTION_576P = RESOLUTION_TABLE["576p"]
RESOLUTION_480P = RESOLUTION_TABLE["480p"]
RESOLUTION_OTHER = RESOLUTION_TABLE["altro"]


def resolution_id_for(release_name: str) -> int:
    """Devine la resolution_id depuis le release_name."""
    upper = release_name.upper()
    if "4320P" in upper or "8K" in upper.split("."):
        return RESOLUTION_4320P
    if "2160P" in upper or ".4K." in upper or upper.endswith(".4K") or "UHD" in upper:
        return RESOLUTION_2160P
    if "1080P" in upper:
        return RESOLUTION_1080P
    if "1080I" in upper:
        return RESOLUTION_1080I
    if "720P" in upper:
        return RESOLUTION_720P
    if "576P" in upper:
        return RESOLUTION_576P
    if "480P" in upper:
        return RESOLUTION_480P
    return RESOLUTION_OTHER


# ============================================================
# OPTIONS POUR LA UI : (id, label) tries pour selects
# ============================================================
# Utilises par la page detail du package (F3 NOTES.md) pour permettre
# l'override des champs envoyes au tracker. Ordre = ordre du formulaire
# upload sur le site Gemini (cf. doc PDF).

CATEGORY_OPTIONS: list[tuple[int, str]] = [
    (CATEGORY_MOVIE, "Film"),
    (CATEGORY_TV, "Série"),
    (CATEGORY_MOVIE_DOC, "Film documentaire"),
    (CATEGORY_TV_DOC, "Série documentaire"),
    (CATEGORY_MOVIE_ANIME, "Film d'animation"),
    (CATEGORY_TV_ANIME, "Série d'animation"),
    (CATEGORY_TV_SHOW, "Émission TV"),
    (CATEGORY_SPORTS, "Sports"),
    (CATEGORY_BOOKS, "Livre"),
    (CATEGORY_GAME, "Jeu"),
    (CATEGORY_SOFTWARE, "Logiciel"),
    (CATEGORY_TRAINING, "Formation"),
]

# Types — uniquement les types pertinents pour la video (les types Jeux,
# Livres, Logiciels sont specifiques a leur categorie et l'utilisateur ne
# choisit normalement pas un type video pour un upload de jeu).
TYPE_OPTIONS: list[tuple[int, str]] = [
    (TYPE_FULL_DISC, "Full Disc (BD/UHD ISO)"),
    (TYPE_REMUX, "Remux"),
    (TYPE_BDRIP, "BDRip / Encode BluRay"),
    (TYPE_WEB, "WEB / WEB-DL"),
    (TYPE_WEBRIP, "WEBRip"),
    (TYPE_HDTV, "HDTV"),
    (TYPE_TVRIP, "TVRip"),
    (TYPE_DVD, "DVD"),
    (TYPE_DVDRIP, "DVDRip"),
    (TYPE_VHSRIP, "VHSRip"),
    (TYPE_ISO, "ISO"),
]

RESOLUTION_OPTIONS: list[tuple[int, str]] = [
    (RESOLUTION_4320P, "4320p (8K)"),
    (RESOLUTION_2160P, "2160p (4K UHD)"),
    (RESOLUTION_1080P, "1080p"),
    (RESOLUTION_1080I, "1080i"),
    (RESOLUTION_720P, "720p"),
    (RESOLUTION_576P, "576p (PAL)"),
    (RESOLUTION_TABLE["576i"], "576i"),
    (RESOLUTION_480P, "480p (NTSC)"),
    (RESOLUTION_TABLE["480i"], "480i"),
    (RESOLUTION_OTHER, "Autre / Inconnue"),
]


def category_label(category_id: int) -> str:
    """Retourne le libelle humain d'un category_id, ou '?' si inconnu."""
    for cid, label in CATEGORY_OPTIONS:
        if cid == category_id:
            return label
    return f"? (id={category_id})"


def type_label(type_id: int) -> str:
    """Retourne le libelle humain d'un type_id, ou '?' si inconnu."""
    for tid, label in TYPE_OPTIONS:
        if tid == type_id:
            return label
    return f"? (id={type_id})"


def resolution_label(resolution_id: int) -> str:
    """Retourne le libelle humain d'un resolution_id, ou '?' si inconnu."""
    for rid, label in RESOLUTION_OPTIONS:
        if rid == resolution_id:
            return label
    return f"? (id={resolution_id})"
