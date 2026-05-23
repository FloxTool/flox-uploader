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


# ============================================================
# TYPES Jeux (16-24) — categorie 3
# ============================================================
# Source : doc PDF officielle G3MINI TR4CK3R - TORRENT API.
# Sprint A v0.5.0 (PLAN-MULTICAT §8.1) : ces IDs etaient manquants en v0.3.x,
# rendant impossible un upload jeu (l'API tracker refuse sans type_id valide).

TYPE_GAME_WINDOWS = 16          # Jeux\Windows
TYPE_GAME_OTHER = 17            # Jeux\Autre
TYPE_GAME_LINUX = 18            # Jeux\Linux
TYPE_GAME_MACOS = 19            # Jeux\MacOS
TYPE_GAME_XBOX = 20             # Jeux\Xbox
TYPE_GAME_NINTENDO = 21         # Jeux\Nintendo
TYPE_GAME_SMARTPHONE = 22       # Jeux\Smartphone
TYPE_GAME_SONY = 23             # Jeux\Sony
TYPE_GAME_TABLETTE = 24         # Jeux\Tablette


# ============================================================
# TYPES Livres (25-33) — categorie 12
# ============================================================

TYPE_BOOK_M4B = 25              # Livres\M4B (audio M4B)
TYPE_BOOK_MP3 = 26              # Livres\MP3 (audio MP3)
TYPE_BOOK_EBOOK = 27            # Livres (generique EPUB/PDF/MOBI/AZW3/DJVU)
TYPE_BOOK_BD = 28               # Livres\BD
TYPE_BOOK_COMICS = 29           # Livres\Comics
TYPE_BOOK_MANGAS = 30           # Livres\Mangas
TYPE_BOOK_MAGAZINE = 31         # Livres\Magazine
TYPE_BOOK_PRESSE = 32           # Livres\Presse
TYPE_BOOK_AUDIO = 33            # Livres\Audio (generique audio)


# ============================================================
# TYPES Logiciels (34-37) — categorie 17
# ============================================================

TYPE_SOFTWARE_WINDOWS = 34      # Logiciels\Windows
TYPE_SOFTWARE_MACOS = 35        # Logiciels\MacOS
TYPE_SOFTWARE_LINUX = 36        # Logiciels\Linux
TYPE_SOFTWARE_OTHER = 37        # Logiciels\Autres


# ============================================================
# Mappings plateforme/format -> type_id pour les strategies non-video
# ============================================================
# Consommes par les pipelines Sprint D (Livre), E (Jeu), H (Logiciel /
# Formation). Exposes ici pour la coherence des sources de verite : un seul
# fichier qui consolide les IDs Gemini officiels.
#
# Lookup case-insensitive : les helpers consommateurs doivent normaliser la
# cle via `.strip().lower()` avant d'interroger ces dicts.

GAME_TYPE_BY_PLATFORM: dict[str, int] = {
    # Windows / PC
    "windows": TYPE_GAME_WINDOWS,
    "win": TYPE_GAME_WINDOWS,
    "win64": TYPE_GAME_WINDOWS,
    "pc": TYPE_GAME_WINDOWS,
    # Linux
    "linux": TYPE_GAME_LINUX,
    # MacOS
    "mac": TYPE_GAME_MACOS,
    "macos": TYPE_GAME_MACOS,
    "osx": TYPE_GAME_MACOS,
    # Microsoft consoles
    "xbox": TYPE_GAME_XBOX,
    "xbox360": TYPE_GAME_XBOX,
    "xboxone": TYPE_GAME_XBOX,
    "xsx": TYPE_GAME_XBOX,
    # Nintendo consoles & handhelds
    "nintendo": TYPE_GAME_NINTENDO,
    "switch": TYPE_GAME_NINTENDO,
    "nsw": TYPE_GAME_NINTENDO,
    "wii": TYPE_GAME_NINTENDO,
    "wiiu": TYPE_GAME_NINTENDO,
    "3ds": TYPE_GAME_NINTENDO,
    "ds": TYPE_GAME_NINTENDO,
    "n64": TYPE_GAME_NINTENDO,
    "gba": TYPE_GAME_NINTENDO,
    "gameboy": TYPE_GAME_NINTENDO,
    "snes": TYPE_GAME_NINTENDO,
    "nes": TYPE_GAME_NINTENDO,
    # Sony consoles & handhelds
    "ps1": TYPE_GAME_SONY,
    "ps2": TYPE_GAME_SONY,
    "ps3": TYPE_GAME_SONY,
    "ps4": TYPE_GAME_SONY,
    "ps5": TYPE_GAME_SONY,
    "psp": TYPE_GAME_SONY,
    "psvita": TYPE_GAME_SONY,
    "vita": TYPE_GAME_SONY,
    # Smartphone
    "android": TYPE_GAME_SMARTPHONE,
    "ios": TYPE_GAME_SMARTPHONE,
    "iphone": TYPE_GAME_SMARTPHONE,
    # Tablette
    "tablet": TYPE_GAME_TABLETTE,
    "tablette": TYPE_GAME_TABLETTE,
    "ipad": TYPE_GAME_TABLETTE,
}

# Mapping extension -> type_id pour les livres.
# Note : `.cbr/.cbz` -> BD par defaut. Comics/Manga sont determines par
# heuristique additionnelle (ISBN 978-1 = comics US/UK, 978-4 = manga JP,
# 978-2 = BD FR) qui sera implementee dans BookNamingStrategy (Sprint D).
BOOK_TYPE_BY_FORMAT: dict[str, int] = {
    # Ebooks generiques
    "epub": TYPE_BOOK_EBOOK,
    "pdf": TYPE_BOOK_EBOOK,
    "mobi": TYPE_BOOK_EBOOK,
    "azw3": TYPE_BOOK_EBOOK,
    "azw": TYPE_BOOK_EBOOK,
    "djvu": TYPE_BOOK_EBOOK,
    # BD / Comics / Manga (defaut BD ; sous-classement Sprint D)
    "cbr": TYPE_BOOK_BD,
    "cbz": TYPE_BOOK_BD,
    # Livre audio
    "m4b": TYPE_BOOK_M4B,
    "mp3": TYPE_BOOK_MP3,
}

SOFTWARE_TYPE_BY_PLATFORM: dict[str, int] = {
    "windows": TYPE_SOFTWARE_WINDOWS,
    "win": TYPE_SOFTWARE_WINDOWS,
    "win64": TYPE_SOFTWARE_WINDOWS,
    "macos": TYPE_SOFTWARE_MACOS,
    "mac": TYPE_SOFTWARE_MACOS,
    "osx": TYPE_SOFTWARE_MACOS,
    "linux": TYPE_SOFTWARE_LINUX,
}


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

# Options UI pour les categories non-video. Consommees par les templates
# `_detail_<profile>.html` (Sprint C). Ne pas merger dans TYPE_OPTIONS : un
# upload Film n'a aucune raison d'exposer "Jeux\Xbox" dans son select.
GAME_TYPE_OPTIONS: list[tuple[int, str]] = [
    (TYPE_GAME_WINDOWS, "Windows / PC"),
    (TYPE_GAME_LINUX, "Linux"),
    (TYPE_GAME_MACOS, "MacOS"),
    (TYPE_GAME_XBOX, "Xbox"),
    (TYPE_GAME_NINTENDO, "Nintendo"),
    (TYPE_GAME_SONY, "Sony / PlayStation"),
    (TYPE_GAME_SMARTPHONE, "Smartphone"),
    (TYPE_GAME_TABLETTE, "Tablette"),
    (TYPE_GAME_OTHER, "Autre"),
]

BOOK_TYPE_OPTIONS: list[tuple[int, str]] = [
    (TYPE_BOOK_EBOOK, "Livre (EPUB/PDF/MOBI/AZW3/DJVU)"),
    (TYPE_BOOK_BD, "BD"),
    (TYPE_BOOK_COMICS, "Comics"),
    (TYPE_BOOK_MANGAS, "Mangas"),
    (TYPE_BOOK_AUDIO, "Livre audio (generique)"),
    (TYPE_BOOK_M4B, "Livre audio M4B"),
    (TYPE_BOOK_MP3, "Livre audio MP3"),
    (TYPE_BOOK_MAGAZINE, "Magazine"),
    (TYPE_BOOK_PRESSE, "Presse"),
]

SOFTWARE_TYPE_OPTIONS: list[tuple[int, str]] = [
    (TYPE_SOFTWARE_WINDOWS, "Windows"),
    (TYPE_SOFTWARE_MACOS, "MacOS"),
    (TYPE_SOFTWARE_LINUX, "Linux"),
    (TYPE_SOFTWARE_OTHER, "Autre"),
]

# Pool de tous les types Gemini connus, par categorie. Permet a
# `type_label()` de retrouver un libelle peu importe la categorie d'origine
# d'un type_id (pratique pour les logs et l'admin).
_ALL_TYPE_OPTIONS: list[tuple[int, str]] = (
    TYPE_OPTIONS + GAME_TYPE_OPTIONS + BOOK_TYPE_OPTIONS + SOFTWARE_TYPE_OPTIONS
)

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


# ============================================================
# UI METADATA (Sprint C v0.5.0)
# ============================================================
# Source de verite des metadonnees UI par categorie : libelle, icone Lucide,
# couleur Tailwind, extensions associees. Consomme par :
# - L'endpoint /api/categories (modal selecteur Inbox)
# - Les badges couleur sur Queue / Page detail / History (Sprint C.2)
# - L'auto-detection cote frontend (mapping extension -> suggestion)
#
# Charte UI : pas d'emoji (CHARTE.md §15) -> icones Lucide SVG.
# https://lucide.dev/icons/
#
# Couleurs : palette Tailwind standard. primary = couleur historique de l'app
# pour les categories video (Films/Series/Doc/Anime), autres palettes pour
# differencier visuellement les nouvelles categories.

# SVG paths inline pour chaque icone Lucide utilisee par les categories.
# Source : https://lucide.dev (MIT license). Format = innerHTML d'un <svg
# viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none"
# stroke-linecap="round" stroke-linejoin="round">. Consomme par l'endpoint
# /api/categories pour que le frontend puisse injecter les SVG dans la modal
# sans dependre du sprite Jinja (qui n'expose pas les icones cote JS).
_CATEGORY_ICON_SVG: dict[str, str] = {
    "clapperboard": (
        '<path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3Z"/>'
        '<path d="m6.2 5.3 3.1 3.9"/>'
        '<path d="m12.4 3.4 3.1 4"/>'
        '<path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>'
    ),
    "tv": (
        '<rect width="20" height="15" x="2" y="7" rx="2" ry="2"/>'
        '<polyline points="17 2 12 7 7 2"/>'
    ),
    "sparkles": (
        '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>'
        '<path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/>'
    ),
    "radio-tower": (
        '<path d="M4.9 16.1C1 12.2 1 5.8 4.9 1.9"/>'
        '<path d="M7.8 4.7a6.14 6.14 0 0 0-.8 7.5"/>'
        '<circle cx="12" cy="9" r="2"/>'
        '<path d="M16.2 4.8c2 2 2.26 5.11.8 7.47"/>'
        '<path d="M19.1 1.9a9.96 9.96 0 0 1 0 14.1"/>'
        '<path d="M9.5 18h5"/>'
        '<path d="m8 22 4-11 4 11"/>'
    ),
    "mic-vocal": (
        '<path d="M16 8.99V5a3 3 0 0 0-6 0v6a3 3 0 0 0 4.18 2.76"/>'
        '<path d="M11.7 13.99a8 8 0 0 0 8.3 8.85"/>'
        '<path d="M16 14a4 4 0 0 1-4-4"/>'
        '<path d="M22 14h-4"/>'
    ),
    "trophy": (
        '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>'
        '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
        '<path d="M4 22h16"/>'
        '<path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
        '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
        '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'
    ),
    "book-open": (
        '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
        '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'
    ),
    "gamepad-2": (
        '<line x1="6" x2="10" y1="11" y2="11"/>'
        '<line x1="8" x2="8" y1="9" y2="13"/>'
        '<line x1="15" x2="15.01" y1="12" y2="12"/>'
        '<line x1="18" x2="18.01" y1="10" y2="10"/>'
        '<path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/>'
    ),
    "monitor-cog": (
        '<path d="M12 17v4"/>'
        '<path d="m15.2 4.9-.9-.4"/>'
        '<path d="m15.2 7.1-.9.4"/>'
        '<path d="m16.9 3.2-.4-.9"/>'
        '<path d="m16.9 8.8-.4.9"/>'
        '<path d="m19.5 2.3-.4.9"/>'
        '<path d="m19.5 9.7-.4-.9"/>'
        '<path d="m21.7 4.5-.9.4"/>'
        '<path d="m21.7 7.5-.9-.4"/>'
        '<path d="M22 13v2a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9"/>'
        '<path d="M8 21h8"/>'
        '<circle cx="18" cy="6" r="3"/>'
    ),
    "graduation-cap": (
        '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/>'
        '<path d="M22 10v6"/>'
        '<path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>'
    ),
    "layers": (
        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.65 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
        '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>'
    ),
}


CATEGORY_UI_METADATA: list[dict] = [
    {
        "id": CATEGORY_MOVIE,
        "label": "Film",
        "icon": "clapperboard",
        "icon_svg_path": _CATEGORY_ICON_SVG["clapperboard"],
        "color": "primary",  # violet/indigo (couleur historique)
        "extensions": [".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".iso", ".wmv", ".flv"],
        "hint": "Films cinéma, films TV (1 fichier vidéo principal)",
    },
    {
        "id": CATEGORY_TV,
        "label": "Série",
        "icon": "tv",
        "icon_svg_path": _CATEGORY_ICON_SVG["tv"],
        "color": "primary",
        "extensions": [],  # heuristique S01E01 plus parlante que extension
        "hint": "Séries TV (1 épisode, 1 saison, ou intégrale)",
    },
    {
        "id": CATEGORY_MOVIE_ANIME,
        "label": "Film d'animation",
        "icon": "sparkles",
        "icon_svg_path": _CATEGORY_ICON_SVG["sparkles"],
        "color": "primary",
        "extensions": [],
        "hint": "Films d'animation (auto-détecté si TMDB genre = Animation)",
    },
    {
        "id": CATEGORY_TV_ANIME,
        "label": "Série d'animation",
        "icon": "sparkles",
        "icon_svg_path": _CATEGORY_ICON_SVG["sparkles"],
        "color": "primary",
        "extensions": [],
        "hint": "Séries d'animation",
    },
    {
        "id": CATEGORY_MOVIE_DOC,
        "label": "Film documentaire",
        "icon": "radio-tower",
        "icon_svg_path": _CATEGORY_ICON_SVG["radio-tower"],
        "color": "primary",
        "extensions": [],
        "hint": "Documentaires (auto-détecté si TMDB genre = Documentary)",
    },
    {
        "id": CATEGORY_TV_DOC,
        "label": "Série documentaire",
        "icon": "radio-tower",
        "icon_svg_path": _CATEGORY_ICON_SVG["radio-tower"],
        "color": "primary",
        "extensions": [],
        "hint": "Séries documentaires",
    },
    {
        "id": CATEGORY_TV_SHOW,
        "label": "Émission TV",
        "icon": "mic-vocal",
        "icon_svg_path": _CATEGORY_ICON_SVG["mic-vocal"],
        "color": "pink",
        "extensions": [],
        "hint": "Talk-show, jeu télé, télé-réalité (Quotidien, TPMP, Koh-Lanta...)",
    },
    {
        "id": CATEGORY_SPORTS,
        "label": "Sport",
        "icon": "trophy",
        "icon_svg_path": _CATEGORY_ICON_SVG["trophy"],
        "color": "warning",  # orange
        "extensions": [],
        "hint": "Sport en direct ou différé (UFC, F1, Tour de France...)",
    },
    {
        "id": CATEGORY_BOOKS,
        "label": "Livre / BD / Manga",
        "icon": "book-open",
        "icon_svg_path": _CATEGORY_ICON_SVG["book-open"],
        "color": "success",  # emeraude
        "extensions": [".epub", ".pdf", ".mobi", ".azw3", ".azw", ".djvu", ".cbr", ".cbz", ".m4b"],
        "hint": "Livres numériques, BD, comics, mangas, livres audio",
    },
    {
        "id": CATEGORY_GAME,
        "label": "Jeu vidéo",
        "icon": "gamepad-2",
        "icon_svg_path": _CATEGORY_ICON_SVG["gamepad-2"],
        "color": "cyan",
        "extensions": [],  # extensions trop variees (.iso PS3, .bin/.cue, dossiers PC)
        "hint": "Jeux PC, consoles, mobile",
    },
    {
        "id": CATEGORY_SOFTWARE,
        "label": "Logiciel",
        "icon": "monitor-cog",
        "icon_svg_path": _CATEGORY_ICON_SVG["monitor-cog"],
        "color": "slate",
        "extensions": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"],
        "hint": "Logiciels Windows / macOS / Linux",
    },
    {
        "id": CATEGORY_TRAINING,
        "label": "Formation",
        "icon": "graduation-cap",
        "icon_svg_path": _CATEGORY_ICON_SVG["graduation-cap"],
        "color": "amber",  # jaune
        "extensions": [],
        "hint": "Tutoriels, cours vidéo, MOOC (Udemy, OpenClassrooms...)",
    },
]


def category_ui_metadata(category_id: int) -> dict | None:
    """Retourne le dict metadata UI pour une categorie, ou None si inconnue."""
    for meta in CATEGORY_UI_METADATA:
        if meta["id"] == category_id:
            return meta
    return None


def type_label(type_id: int) -> str:
    """Retourne le libelle humain d'un type_id, ou '?' si inconnu.

    Cherche dans le pool unifie tous-types (video + jeux + livres + logiciels)
    pour pouvoir retrouver le libelle d'un type_id non-video aussi (utile pour
    les logs et l'admin). En cas de collision (qui ne se produit pas dans la
    nomenclature Gemini : video 1-15, jeux 16-24, livres 25-33, logiciels
    34-37), la premiere entree gagne (= video).
    """
    for tid, label in _ALL_TYPE_OPTIONS:
        if tid == type_id:
            return label
    return f"? (id={type_id})"


def resolution_label(resolution_id: int) -> str:
    """Retourne le libelle humain d'un resolution_id, ou '?' si inconnu."""
    for rid, label in RESOLUTION_OPTIONS:
        if rid == resolution_id:
            return label
    return f"? (id={resolution_id})"
