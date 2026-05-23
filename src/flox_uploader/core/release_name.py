"""Construction et normalisation du nom de release.

Le builder principal `build_release_name` est générique : il prend un set de
règles (par tracker) en entrée et produit un nom standardisé. La logique de
parsing des tokens est entièrement pilotée par le `rules.json` du tracker.

Sprint B.1 v0.5.0 (PLAN-MULTICAT §5.5) — les helpers utilitaires purs
(`split_team`, `normalize_separators`, `collapse_dots`, `ascii_fold`,
`_normalize_token_case`, `_looks_minimal`, `dedupe_keep_order`) ont ete
deplaces dans `core/naming/_helpers.py` pour etre reutilisables par les
strategies non-video (Sprints D/E/H). Ils sont re-exportes ci-dessous pour
preserver la retrocompat 100% des callers historiques.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from .debug import Debug
from .errors import die

# Re-exports Sprint B.1 — helpers extraits dans naming/_helpers.py.
# Garantit que `from flox_uploader.core.release_name import split_team`
# continue de fonctionner pour tous les callers historiques (tests, web/app,
# CLI, etc.).
from .naming._helpers import (  # noqa: F401  (re-export)
    _CANONICAL_CASE,
    _LOOKS_MINIMAL_TECH_PATTERN,
    _TECH_TOKENS,
    _TECH_UPPER,
    _looks_minimal,
    _normalize_token_case,
    ascii_fold,
    collapse_dots,
    dedupe_keep_order,
    normalize_separators,
    split_team,
)

if TYPE_CHECKING:
    from ..trackers.base import Tracker


ALLOWED_FORCE_FR = {"VFF", "VFQ", "VFB", "VF2", "VOF", "VOQ", "VOB"}


def apply_replacements(text: str, replace_tokens: dict[str, str]) -> str:
    parts = [p for p in text.split(".") if p]
    return ".".join(replace_tokens.get(p.upper(), p) for p in parts)


# Lot O.3 — Tokens AMBIGUS qui peuvent etre des mots du titre. On ne les
# drop QUE s'ils apparaissent APRES l'annee (= tag technique, pas mot du
# titre). Sinon le titre "Mad Max" perd son "Max" (drop service streaming
# HBO Max), "Furiosa: A Mad Max Saga" devient "Furiosa Saga", recherche
# TMDB rate.
#
# Tous les autres drop_tokens (4KLight, mHD, HDLight, NoTAG, 10bit, etc.)
# restent supprimes globalement parce qu'ils ne sont jamais des mots de
# titre.
_AMBIGUOUS_DROP_TOKENS_UPPER: set[str] = {
    # Services streaming qui peuvent ressembler a des mots du titre
    "NF", "NFLX", "AMZN", "DSNP", "ATVP", "HMAX", "MAX", "PCOK", "PMTP",
    "STAN", "SHO", "HULU",
    # Atmos peut etre dans le titre d'un docu (rare mais possible)
    "ATMOS",
}


def _find_year_position(parts: list[str]) -> int:
    """Retourne l'index de l'annee dans `parts`, ou -1 si pas trouvee.

    Annee = pattern strict 19xx ou 20xx, 4 chiffres seulement.
    """
    for i, p in enumerate(parts):
        if re.fullmatch(r"(19|20)\d{2}", p):
            return i
    return -1


def remove_tokens(text: str, tokens_to_remove: list[str]) -> str:
    """Supprime les tokens techniques du release name.

    Lot O.3 : les tokens AMBIGUS (streaming services, Atmos) ne sont
    supprimes que s'ils apparaissent APRES l'annee. Avant l'annee, ce
    sont des mots du titre (ex: "Mad Max" -> ne pas dropper "Max").
    """
    parts = [p for p in text.split(".") if p]
    if not parts:
        return text
    remove_upper = {t.upper() for t in tokens_to_remove}
    year_idx = _find_year_position(parts)

    kept: list[str] = []
    for i, p in enumerate(parts):
        upper = p.upper()
        if upper not in remove_upper:
            kept.append(p)
            continue
        # Token marque pour suppression — verifier la position
        if upper in _AMBIGUOUS_DROP_TOKENS_UPPER and 0 <= year_idx and i < year_idx:
            # Avant l'annee + ambigu : c'est un mot du titre, on garde.
            kept.append(p)
            continue
        # Drop confirme.
    return ".".join(kept)


def split_glued_tokens(text: str) -> str:
    """Insere un point entre une source et un codec audio quand ils sont colles.

    Ex (typique chez certaines teams comme TyHD) :
      WEBripEAC3 -> WEBrip.EAC3
      BluRayDDP  -> BluRay.DDP
      BDRipAAC   -> BDRip.AAC
      WEB-DLAC3  -> WEB-DL.AC3

    On gere les patterns source+codec uniquement (le cas le plus frequent).
    """
    sources = "WEBRIP|BLURAY|BDRIP|HDRIP|WEBDL|WEB-DL|HDTV|DVDRIP|REMUX|WEB"
    codecs = "EAC3|E-AC3|DDP|DTS-HD|DTS|TRUEHD|AAC|AC3|FLAC|OPUS|MP3|DD"

    pattern = re.compile(
        rf"\b({sources})({codecs})\b", flags=re.IGNORECASE
    )
    return pattern.sub(r"\1.\2", text)


def split_compound_specs(text: str) -> str:
    """Split les compose `<source>-<channels>-<codec>` (et variantes).

    Cas reel rapporte : `L'Arracheuse.De.Temps.2021.FRENCH.1080p.WEBDL-5.1-H264`
    -> le token compose `WEBDL-5.1-H264` n'etait dans AUCUNE map (sources,
    audio_channel, video_codec) et finissait `dropped_unknown_after_year`,
    perdant 3 specs critiques d'un coup.

    On reconnait les patterns suivants et on remplace les tirets par des
    points pour que la tokenisation suivante les capte individuellement :

      WEBDL-5.1-H264         -> WEBDL.5.1.H264
      BluRay-DDP5.1-x265     -> BluRay.DDP5.1.x265
      WEB-DL-7.1-HEVC        -> WEB-DL.7.1.HEVC  (preserve le tiret de WEB-DL)
      WEBDL-x264             -> WEBDL.x264       (sans channels)
      WEBDL-5.1              -> WEBDL.5.1        (sans codec)

    Le tiret de `WEB-DL` doit etre preserve : on remplace seulement les
    tirets ENTRE les groupes spec, pas a l'interieur.
    """
    sources = "(?:WEB-DL|WEBDL|WEBRIP|BLURAY|BDRIP|HDRIP|HDTV|DVDRIP|REMUX|WEB)"
    channels = r"\d\.\d"
    # Codecs video et audio (tous separes par |). On utilise re.escape pour
    # les codecs avec tiret deja interne (E-AC3, DTS-HD).
    codec_alternatives = [
        "H[.]?264", "H[.]?265", "HEVC", "AVC", "x264", "x265", "AV1", "VC-1",
        "EAC3", "E-AC3", "DDP", "DTS-HD", "DTS", "TrueHD", "AAC", "AC3",
        "FLAC", "OPUS", "MP3", "DD",
    ]
    codecs = "(?:" + "|".join(codec_alternatives) + ")"

    # 1. SRC-CHANNELS-CODEC : WEBDL-5.1-H264, BluRay-7.1-x265
    p1 = re.compile(
        rf"\b({sources})-({channels})-({codecs})\b", flags=re.IGNORECASE,
    )
    text = p1.sub(r"\1.\2.\3", text)

    # 2. SRC-CODEC : WEBDL-x264, BluRay-HEVC
    p2 = re.compile(rf"\b({sources})-({codecs})\b", flags=re.IGNORECASE)
    text = p2.sub(r"\1.\2", text)

    # 3. SRC-CHANNELS : WEBDL-5.1
    p3 = re.compile(rf"\b({sources})-({channels})\b", flags=re.IGNORECASE)
    text = p3.sub(r"\1.\2", text)

    # 4. CHANNELS-CODEC : 5.1-H264 (au cas ou la source manque)
    p4 = re.compile(rf"\b({channels})-({codecs})\b", flags=re.IGNORECASE)
    text = p4.sub(r"\1.\2", text)

    return text


def normalize_multi_language(text: str) -> str:
    # Uniformise MULTI (toutes casses) en MULTi. Les patterns composés type
    # MULTi.VFF sont préservés puisque seul le sous-token MULTI est réécrit.
    return re.sub(r"\bMULTI\b", "MULTi", text, flags=re.IGNORECASE)


def normalize_channels(text: str) -> str:
    return re.sub(
        r"\b(DDP|DD|DTS|AAC|AC3|E-AC3)\.?([124567]\.0|[567]\.1)\b",
        r"\1.\2",
        text,
        flags=re.IGNORECASE,
    )


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.upper()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def merge_video_codec_tokens(parts: list[str]) -> list[str]:
    """Recolle H + 264/265 cassés par split('.')."""
    merged = []
    i = 0
    while i < len(parts):
        current = parts[i]
        if i + 1 < len(parts) and current.upper() == "H" and parts[i + 1] in {"264", "265"}:
            merged.append(f"H.{parts[i + 1]}")
            i += 2
            continue
        merged.append(current)
        i += 1
    return merged


def merge_compound_audio_codecs(parts: list[str]) -> list[str]:
    """Recolle les codecs audio composes casses par split('.').

    Transformations :
    - ['DTS', 'HDMA']     -> ['DTS-HDMA']
    - ['DTS', 'HD', 'MA'] -> ['DTS-HD']  (le MA est mange car forme finale 'DTS-HD MA' pas standard ici)
    - ['DTS', 'HD']       -> ['DTS-HD']
    - ['DTS', 'X']        -> ['DTS-X']
    - ['DTS', 'ES']       -> ['DTS-ES']
    - ['E', 'AC3']        -> ['E-AC3']  (au cas ou EAC3 ne serait pas dans replace_tokens)
    """
    out = []
    i = 0
    while i < len(parts):
        cur = parts[i].upper()
        nxt = parts[i + 1].upper() if i + 1 < len(parts) else ""
        nxt2 = parts[i + 2].upper() if i + 2 < len(parts) else ""

        # DTS + HD + MA -> DTS-HD (forme la plus repandue)
        if cur == "DTS" and nxt == "HD" and nxt2 == "MA":
            out.append("DTS-HD")
            i += 3
            continue
        # DTS + HDMA / DTS + HD / DTS + X / DTS + ES
        if cur == "DTS" and nxt in {"HDMA", "HD", "X", "ES"}:
            mapping = {"HDMA": "DTS-HDMA", "HD": "DTS-HD", "X": "DTS-X", "ES": "DTS-ES"}
            out.append(mapping[nxt])
            i += 2
            continue
        # E + AC3 -> E-AC3 (filet de securite si pas dans replace_tokens)
        if cur == "E" and nxt == "AC3":
            out.append("E-AC3")
            i += 2
            continue
        out.append(parts[i])
        i += 1
    return out


def merge_audio_channel_tokens(parts: list[str]) -> list[str]:
    """Recolle les channel tokens 5.1, 7.1, 2.0 casses par split('.').

    'EAC3' '5' '1' -> 'EAC3' '5.1'
    'DDP' '7' '1' -> 'DDP' '7.1'
    Ou standalone : '5' '1' tout seuls -> '5.1'
    """
    out = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        # X.Y avec X dans {1,2,4,5,6,7} et Y dans {0,1}
        if (cur in {"1", "2", "4", "5", "6", "7"}
                and i + 1 < len(parts)
                and parts[i + 1] in {"0", "1"}):
            out.append(f"{cur}.{parts[i + 1]}")
            i += 2
            continue
        out.append(cur)
        i += 1
    return out


# ============================================================
# INFÉRENCE VARIANTE FR (depuis TMDB)
# ============================================================

def infer_fr_variant_from_tmdb(tmdb_context: dict | None) -> str | None:
    """Détermine la variante FR à partir du contexte TMDB.

    Regle : la France domine pour les coproductions. On retourne :
    - original_language='fr' + France parmi les pays   -> VOF
      (peu importe si Belgique/Canada/Suisse aussi co-producteurs)
    - original_language='fr' + uniquement Canada       -> VOQ
    - original_language='fr' + uniquement Belgique     -> VOB
    - original_language='fr' (autre cas, ex Suisse)    -> VOF (defaut FR)
    - original_language != 'fr'                        -> VFF (doublage)

    Exemple : "Delicieux" (2021) = co-prod France+Belgique -> VOF (pas VOB).
    """
    if not tmdb_context:
        return None

    orig_lang = (tmdb_context.get("original_language") or "").strip().lower()
    countries = [
        c.lower() for c in tmdb_context.get("production_countries", []) if c
    ]

    is_france = any("france" in c for c in countries)
    is_canada = any(
        "canada" in c or "québec" in c or "quebec" in c for c in countries
    )
    is_belgium = any("belg" in c for c in countries)

    if orig_lang == "fr":
        # France presente (meme en coprod) -> VOF (la France domine)
        if is_france:
            return "VOF"
        # Production purement quebecoise
        if is_canada:
            return "VOQ"
        # Production purement belge
        if is_belgium:
            return "VOB"
        # Suisse romande, Luxembourg, etc. -> on retombe sur VOF par defaut
        return "VOF"

    if orig_lang:
        return "VFF"

    return None


def merge_multi_language(
    lang_tokens: list[str],
    rules: dict,
    nfo_variant: str | None = None,
    force_fr: str | None = None,
    tmdb_context: dict | None = None,
    is_vostfr_from_nfo: bool = False,
    french_audio_count: int = 0,
    is_tv_series: bool = False,
    out_warnings: list[str] | None = None,
) -> list[str]:
    # Cas spécial : aucun tag langue dans le nom mais le NFO montre
    # audio non-FR + sous-titres FR → VOSTFR
    if not lang_tokens:
        if is_vostfr_from_nfo:
            return ["VOSTFR"]
        return []

    upper = [x.upper() for x in lang_tokens]
    require_precise = bool(rules.get("require_precise_multi_language", True))

    def _warn(msg: str) -> None:
        """Note l'ambiguite + log. Permet a la UI de signaler 'a choisir'."""
        print(f"[WARN] {msg}")
        if out_warnings is not None:
            out_warnings.append(msg)

    precise_variants = {"VFF", "VFQ", "VFB", "VF2", "VOF", "VOQ", "VOB"}
    has_multi = "MULTI" in upper or any(x.startswith("MULTI.") for x in upper)

    # CAS 1 : MULTI
    if has_multi:
        if force_fr in ALLOWED_FORCE_FR:
            return [f"MULTi.{force_fr}"]

        for combined in ["MULTI.VFF", "MULTI.VFQ", "MULTI.VFB", "MULTI.VF2"]:
            if combined in upper:
                return [combined.replace("MULTI", "MULTi")]

        for variant in ["VFF", "VFQ", "VFB", "VF2"]:
            if variant in upper:
                return [f"MULTi.{variant}"]

        if nfo_variant in {"VFF", "VFQ", "VFB", "VF2"}:
            return [f"MULTi.{nfo_variant}"]

        # TMDB ne peut trancher QUE si le film est d'origine française.
        # Pour un film étranger (en/ja/ko/etc.) un "MULTi" générique peut aussi bien
        # désigner un doublage VFF qu'un doublage VFQ. On NE DEVINE PAS : on bloque.
        tmdb_variant = infer_fr_variant_from_tmdb(tmdb_context)
        if tmdb_variant in {"VOF", "VOQ", "VOB"}:
            vo_to_vf = {"VOF": "VFF", "VOQ": "VFQ", "VOB": "VFB"}
            return [f"MULTi.{vo_to_vf[tmdb_variant]}"]

        # Pas de tag explicite, pas de variante NFO claire, pas de signal TMDB :
        # - Series (99% des distrib FR-FRA) : assume VFF par defaut
        # - Films : on ne devine PAS, on demande a l'utilisateur (--force-fr)
        if french_audio_count >= 1 and is_tv_series:
            print(
                "[INFO] MULTi sans precision (serie) : "
                f"{french_audio_count} piste(s) FR principale(s) detectee(s) "
                "-> assume VFF par defaut (regle series). Si quebecois, "
                "utiliser --force-fr VFQ ; si VFF + VFQ reels, --force-fr VF2."
            )
            return ["MULTi.VFF"]
        if french_audio_count >= 1 and not is_tv_series:
            _warn(
                "MULTi sans precision (film) : "
                f"{french_audio_count} piste(s) FR detectee(s) sans tag distinctif. "
                "Choisir VFF / VFQ / VFB / VF2 via la page detail puis re-preparer."
            )
            return ["MULTi"]

        if require_precise:
            _warn(
                "MULTi sans precision et aucune piste FR detectee dans le NFO. "
                "Choisir VFF / VFQ / VFB / VF2 via la page detail puis re-preparer."
            )
        return ["MULTi"]

    # CAS 2 : variante précise déjà présente
    has_precise = any(v in upper for v in precise_variants)
    if has_precise:
        cleaned = [t for t in lang_tokens if t.upper() not in {"FRENCH", "FR"}]
        cleaned = dedupe_keep_order(cleaned) if cleaned else lang_tokens

        if force_fr in ALLOWED_FORCE_FR:
            return [force_fr]

        # TMDB = fr-original → piste FR est la VO, pas un doublage
        tmdb_variant = infer_fr_variant_from_tmdb(tmdb_context)
        if tmdb_variant in {"VOF", "VOQ", "VOB"}:
            vf_to_vo = {"VFF": "VOF", "VFQ": "VOQ", "VFB": "VOB"}
            upgraded = []
            converted_any = False
            for t in cleaned:
                if t.upper() in vf_to_vo:
                    upgraded.append(tmdb_variant)
                    converted_any = True
                else:
                    upgraded.append(t)
            if converted_any:
                return dedupe_keep_order(upgraded)

        return cleaned

    # CAS 3 : VOSTFR seul
    if "VOSTFR" in upper and not any(u in {"FRENCH", "FR"} for u in upper):
        return lang_tokens

    # CAS 4 : FRENCH ou FR générique
    has_french_generic = any(u in {"FRENCH", "FR"} for u in upper)
    if has_french_generic:
        if force_fr in ALLOWED_FORCE_FR:
            return [force_fr]

        # TMDB en priorite sur le NFO : seul TMDB peut trancher VO vs doublage.
        # Le NFO ne sait que dire "il y a du francais" (titre de piste), il ne
        # peut pas savoir si c'est l'original ou un doublage.
        # Exemple : un film francais ("L'Art d'etre heureux", original_language=fr,
        # production France) avec piste FR principale -> VOF. Le NFO inferera
        # VFF (doublage) ce qui est faux.
        tmdb_variant = infer_fr_variant_from_tmdb(tmdb_context)
        if tmdb_variant in {"VOF", "VOQ", "VOB"}:
            return [tmdb_variant]

        # NFO en fallback quand TMDB ne peut pas conclure (orig non-fr, ou
        # pas de match TMDB). Le NFO peut distinguer VFF / VFQ / VFB grace
        # aux titres de piste "French (CA)" etc.
        if nfo_variant in {"VFF", "VFQ", "VFB", "VF2"}:
            return [nfo_variant]

        # Series : VFF par defaut. Films : strict, on demande --force-fr.
        if french_audio_count >= 1 and is_tv_series:
            print(
                "[INFO] FRENCH/FR sans precision (serie) : "
                f"{french_audio_count} piste(s) FR principale(s) detectee(s) "
                "-> assume VFF par defaut (regle series). Si quebecois, "
                "utiliser --force-fr VFQ ; si VFF + VFQ reels, --force-fr VF2."
            )
            return ["VFF"]
        if french_audio_count >= 1 and not is_tv_series:
            _warn(
                "FRENCH/FR generique (film) : "
                f"{french_audio_count} piste(s) FR detectee(s) sans tag distinctif. "
                "Choisir VFF / VFQ / VFB / VF2 via la page detail puis re-preparer."
            )
            return lang_tokens

        if require_precise:
            _warn(
                "FRENCH/FR generique et aucune piste FR detectee. "
                "Choisir VFF / VFQ / VFB / VF2 via la page detail puis re-preparer."
            )
        return lang_tokens

    return lang_tokens


def is_silent_film(mediainfo_data: dict | None) -> bool:
    """Vrai si MediaInfo indique un film muet (toutes pistes audio en `zxx`).

    `zxx` est le code ISO 639-2 pour "No linguistic content" (= musique de
    fosse, bruitage, mais pas de dialogue). C'est le marqueur standard pour
    les films muets dans MediaInfo.

    Aligne sur _is_silent_from_mediainfo de Unit3Dup-G3MINI/release_normalizer.py.

    Cas d'usage : un film muet uploade avec ce flag aurait son release_name
    avec `MUET` comme tag de langue (a la place de VFF/VOSTFR/etc.) et sans
    codec audio dans le nom. Helper exporte pour integration future ou pour
    detection cote orchestrator.
    """
    if not isinstance(mediainfo_data, dict):
        return False
    tracks = mediainfo_data.get("audio_tracks")
    if not isinstance(tracks, list) or not tracks:
        # Pas d'audio detecte != film muet : pourrait etre une erreur de parse,
        # mieux vaut retourner False et laisser la logique normale.
        return False
    return all(
        isinstance(t, dict) and (t.get("language") or "").lower() == "zxx"
        for t in tracks
    )


def _has_encode_library(mediainfo_data: dict | None) -> bool:
    """Vrai si MediaInfo indique un encode confirme (writing library x264/x265).

    Format typique du parser : `mediainfo_data["video"]["codec"] = "HEVC / x265"`.
    La presence de "x264" ou "x265" apres le slash signe un re-encode confirme
    (par opposition a un codec natif comme HEVC pur d'un BluRay UHD ou WEB-DL).
    """
    if not mediainfo_data:
        return False
    video = mediainfo_data.get("video") if isinstance(mediainfo_data, dict) else None
    if not isinstance(video, dict):
        return False
    codec = (video.get("codec") or "").lower()
    return "x264" in codec or "x265" in codec


def infer_video_codec(
    codec: str | None,
    source: str | None,
    has_encode_library: bool = False,
) -> str | None:
    """Adapte le codec video selon la source (convention G3MINI / Unit3Dup).

    Logique alignee sur le release_normalizer.py du fork Unit3Dup-G3MINI :
    - REMUX  : codec = HEVC / AVC (codec natif, pas de re-encode)
    - WEB    : codec = H.265 / H.264 (capture WEB native, pas re-encodee)
               sauf si MediaInfo confirme un encode (writing library x264/x265)
               -> on garde alors x265 / x264
    - WEBRip : codec = x265 / x264 (capture + re-encode)
    - BDRip  : codec = x265 / x264
    - HDTV/TVRip : codec = x265 / x264
    - BluRay encode : codec = x265 / x264 (rip d'un BluRay)
    - Tous autres cas : codec inchange

    Retourne le codec adapte (ou inchange si aucune regle ne s'applique).
    `codec` et `source` peuvent etre None : on retourne dans ce cas le codec tel quel.
    """
    if not codec:
        return codec

    codec_upper = codec.upper().replace(".", "")  # "H.265" -> "H265"
    is_265 = codec_upper in {"X265", "HEVC", "H265"}
    is_264 = codec_upper in {"X264", "AVC", "H264"}
    if not (is_265 or is_264):
        return codec  # autres codecs (AV1, VP9, MPEG-2, VC-1, etc.) inchanges

    src = (source or "").upper()
    # Cas 1 : REMUX prioritaire
    if src == "REMUX":
        return "HEVC" if is_265 else "AVC"
    # Cas 2 : WEB-DL = capture native non re-encodee
    if src in ("WEB-DL", "WEB"):
        if has_encode_library:
            # MediaInfo confirme un encode malgre le tag "WEB" -> on garde x265/x264
            return "x265" if is_265 else "x264"
        return "H.265" if is_265 else "H.264"
    # Cas 3 : sources qui sont par definition des re-encodes
    if src in ("WEBRIP", "BDRIP", "DVDRIP", "HDRIP", "HDTV", "TVRIP"):
        return "x265" if is_265 else "x264"
    # Cas 4 : BluRay = soit untouched (HEVC) soit encode (x265). MediaInfo decide.
    if src == "BLURAY":
        if has_encode_library:
            return "x265" if is_265 else "x264"
        # Pas d'info MediaInfo -> on garde tel quel (par defaut on a x265 si
        # le release_name le dit, sinon HEVC).
        return codec
    # Defaut : inchange
    return codec


def merge_audio_tokens(audio_tokens: list[str]) -> list[str]:
    if not audio_tokens:
        return []

    codec = None
    channels = None
    extras = []

    codec_candidates = {
        "DD", "DDP", "TRUEHD", "DTS", "DTS-HD", "DTS-HDMA",
        "DTS-HD.HRA", "AAC", "AC3", "E-AC3", "OPUS",
    }
    channel_candidates = {
        "1.0", "2.0", "4.0", "5.1", "6.1", "7.1", "2CH", "6CH", "8CH",
    }

    for token in audio_tokens:
        u = token.upper()
        if u in codec_candidates and codec is None:
            codec = token
        elif u in channel_candidates and channels is None:
            channels = token
        else:
            extras.append(token)

    out = []
    if codec and channels:
        # Charte Gemini : codec colle aux channels (DDP5.1, AC35.1).
        # Exception : si le codec contient un tiret (E-AC3, DTS-HD), on garde
        # le point separateur pour lisibilite (sinon E-AC35.1 est illisible).
        if "-" in codec:
            out.append(f"{codec}.{channels}")
        else:
            out.append(f"{codec}{channels}")
    else:
        if codec:
            out.append(codec)
        if channels:
            out.append(channels)
    out.extend(extras)
    return out


def classify_parts(parts: list[str], rules: dict) -> dict:
    # MAPS upper -> forme canonique pour s'assurer que les valeurs sortent
    # toujours dans la bonne casse : "1080P" -> "1080p", "BLURAY" -> "BluRay", etc.
    lang_map = {x.upper(): x for x in rules.get("language_tokens", [])}
    res_map = {x.upper(): x for x in rules.get("resolution_tokens", [])}
    source_map = {x.upper(): x for x in rules.get("source_tokens", [])}
    audio_codec_map = {x.upper(): x for x in rules.get("audio_codec_tokens", [])}
    audio_channel_map = {
        x.upper(): x for x in rules.get("audio_channel_tokens", [])
    }

    # Résolutions nues (sans p/i) -> canonique avec "p" par défaut
    bare_res_map: dict[str, str] = {}
    for canonical in rules.get("resolution_tokens", []):
        bare = canonical.rstrip("pi")
        if bare.isdigit() and bare not in bare_res_map:
            bare_res_map[bare] = canonical  # "1080" -> "1080p" (pas "1080i")

    video_codec_map = {x.upper(): x for x in rules.get("video_codec_tokens", [])}
    optional_map = {
        x.upper(): x for x in rules.get("allowed_optional_tokens", [])
    }
    strict_mode = bool(rules.get("strict_mode", True))

    title_parts, lang, audio, optional, dropped = [], [], [], [], []
    year = resolution = source = vcodec = None

    # Patterns de tags TV qui seront re-inseres par media_info -> on les drop
    # pour eviter les doublons type 'Breaking.Bad.S01E01.S01E01.MULTi...'
    tv_tag_patterns = [
        re.compile(r"^S\d{1,2}E\d{1,3}$", re.IGNORECASE),  # S01E01
        re.compile(r"^\d{1,2}x\d{1,3}$"),                  # 1x01
        re.compile(r"^S\d{1,2}$", re.IGNORECASE),          # S01 (saison)
        re.compile(r"^iNTEGRALE$", re.IGNORECASE),
        re.compile(r"^INTEGRALE$", re.IGNORECASE),
        re.compile(r"^COMPLETE$", re.IGNORECASE),
    ]

    for part in parts:
        u = part.upper()

        # Drop des tags TV (re-inseres par build_release_name via media_info)
        if any(p.match(part) for p in tv_tag_patterns):
            continue

        if year is None and re.fullmatch(r"(19|20)\d{2}", part):
            year = part
            continue
        if u in lang_map:
            lang.append(lang_map[u])
            continue
        if u in res_map:
            resolution = res_map[u]
            continue
        if part in bare_res_map:
            resolution = bare_res_map[part]
            continue
        if u in source_map:
            source = source_map[u]
            continue
        if u in audio_codec_map:
            audio.append(audio_codec_map[u])
            continue
        if u in audio_channel_map:
            audio.append(audio_channel_map[u])
            continue
        if u in video_codec_map:
            vcodec = video_codec_map[u]
            continue
        if u in optional_map:
            optional.append(optional_map[u])
            continue

        if year is None:
            title_parts.append(part)
        else:
            if strict_mode:
                dropped.append(part)
            else:
                optional.append(part)

    # Edge case : le titre est un nombre ressemblant à une année.
    # Ex: "1987 (2014)" → "1987" capté comme année, titre vide, "2014" droppé.
    if not title_parts and year and dropped:
        for i, d in enumerate(dropped):
            if re.fullmatch(r"(19|20)\d{2}", d):
                title_parts = [year]
                year = d
                dropped = dropped[:i] + dropped[i + 1 :]
                break

    return {
        "title_parts": title_parts,
        "year": year,
        "lang": lang,
        "resolution": resolution,
        "source": source,
        "audio": audio,
        "vcodec": vcodec,
        "optional": optional,
        "dropped_unknown_after_year": dropped,
    }


# ============================================================
# AUTO-ENRICHISSEMENT (helpers de build_release_name)
# ============================================================

def _enrich_language_from_nfo(
    lang: list[str],
    nfo_variant: str | None,
    force_fr: str | None,
    inferred_nfo: dict,
    mediainfo_data: dict | None,
    debug: Debug,
    tmdb_context: dict | None = None,
) -> list[str]:
    """Comble le tag langue quand le nom de release ne le contient pas (ou
    contient seulement le generique "FR"/"FRENCH" qui n'est pas valide en
    nomenclature Gemini).

    Logique :
    - Compte les pistes FR (depuis NFO) et non-FR (depuis NFO + MediaInfo)
    - Si on a au moins 1 piste FR :
        * variante FR = force_fr > nfo_variant > VFF par defaut
        * Si non-FR detecte -> MULTi.<variant>, sinon <variant>
    - NOTES round 7 : Si tmdb_context indique un film FR natif (original
      language=fr), la VFx inferee est en realite la VO du film, pas un
      doublage. On convertit VFx -> VOx :
        * Canada dans production_countries -> VOQ (cas Jusqu'au Declin)
        * Sinon (France / Belgique / Suisse / autre) -> VOF
    - Sinon : retourne lang inchange

    Emet les signaux SIG_LANG_INFERRED_FROM_NFO et SIG_LANG_DEFAULT_VFF_USED.
    """
    from . import naming_signals as ns

    fr_count = inferred_nfo.get("french_audio_count", 0)
    if fr_count < 1:
        return lang

    # Comptage des pistes audio totales : NFO en priorite, MediaInfo en secours.
    nfo_titles = inferred_nfo.get("audio_titles") or []
    if not nfo_titles and isinstance(mediainfo_data, dict):
        nfo_titles = mediainfo_data.get("audio_tracks") or []
    non_fr_count = max(0, len(nfo_titles) - fr_count)

    # "FR" / "FRENCH" seuls = pas valides en nomenclature Gemini, on les
    # traite comme equivalents a "lang absent" pour declencher l'enrichissement.
    lang_only_generic = bool(lang) and all(
        t.upper() in {"FR", "FRENCH"} for t in lang
    )
    if lang and not lang_only_generic:
        return lang  # Tag langue precis deja present, rien a faire

    # Choix de la variante FR
    used_default = False
    used_vfi_translation = False
    if force_fr in ALLOWED_FORCE_FR:
        inferred_variant = force_fr
    elif nfo_variant in {"VFF", "VFQ", "VFB", "VF2"}:
        inferred_variant = nfo_variant
        # Si la variante VFF a ete choisie SUITE A une detection VFi
        # explicite dans le NFO, on signale ca specifiquement (pas un
        # fallback par defaut, mais une traduction d'un tag scene legacy).
        if nfo_variant == "VFF" and inferred_nfo.get("vfi_detected"):
            used_vfi_translation = True
    elif inferred_nfo.get("vfi_detected"):
        # Cas edge : vfi_detected sans nfo_variant (ne devrait pas arriver
        # car infer_french_variant_from_nfo ajoute VFF a variants quand
        # vfi_detected, mais defensive).
        inferred_variant = "VFF"
        used_vfi_translation = True
    else:
        inferred_variant = "VFF"  # defaut serie / pas d'info NFO precise
        used_default = True

    # NOTES round 7 : conversion VFx -> VOx pour films FR natifs.
    # Sans cette regle, "Jusqu'au Declin" (film quebecois, audio FR-CA
    # "Canadian") etait tague VFQ comme s'il s'agissait d'un doublage.
    # Mais c'est la VO du film -> doit etre VOQ.
    # On reutilise `infer_fr_variant_from_tmdb` qui implemente deja la
    # logique fine (France domine en coprod, Canada-only -> VOQ, etc.).
    if tmdb_context and (tmdb_context.get("original_language") or "").lower() == "fr":
        if inferred_variant in {"VFF", "VFQ", "VFB", "VF2"}:
            vo_variant = infer_fr_variant_from_tmdb(tmdb_context)
            if vo_variant and vo_variant.startswith("VO"):
                print(
                    f"[INFO] Film FR natif (TMDB) : {inferred_variant} -> "
                    f"{vo_variant} (VO, pas VF). Pays : "
                    f"{tmdb_context.get('production_countries') or '?'}"
                )
                inferred_variant = vo_variant
                # On annule used_default : ce n'est plus un fallback aveugle
                used_default = False

    if non_fr_count >= 1:
        new_lang = [f"MULTi.{inferred_variant}"]
    else:
        new_lang = [inferred_variant]

    print(f"[INFO] Tag langue absent du nom : infere {new_lang[0]} depuis le NFO.")
    debug.set("lang_inferred_from_nfo", new_lang)  # retro-compat (champ existant)
    ns.emit_signal(debug, ns.SIG_LANG_INFERRED_FROM_NFO, True)
    if used_vfi_translation:
        # Signal specifique : VFi -> VFF (traduction explicite, pas defaut)
        ns.emit_signal(debug, ns.SIG_LANG_VFI_TO_VFF, True)
    elif used_default:
        ns.emit_signal(debug, ns.SIG_LANG_DEFAULT_VFF_USED, True)
    return new_lang


def _enrich_audio_video_from_mediainfo(
    audio_tokens: list[str],
    vcodec: str | None,
    mediainfo_data: dict | None,
    rules: dict,
) -> tuple[list[str], str | None, list[str]]:
    """Lot P : enrichit les tokens audio + vcodec depuis MediaInfo.

    Quand le release_name source ne contient pas le codec audio principal
    (AAC, DDP, DD), le layout (5.1, 2.0) ou le codec video (x265, x264),
    on les insere automatiquement a partir des donnees MediaInfo. Resultat :
    le release_name produit reste conforme a la charte Gemini meme quand
    le nom source est minimaliste.

    Cas reels traites :
    - "Dragons.2.2014.MULTi.VFF.2160p.HDR.BluRay.5.1.x265-QTZ" (Lot P)
      -> "Dragons.2.2014.MULTi.VFF.2160p.HDR.BluRay.AAC.5.1.x265-QTZ"
      (codec audio AAC ajoute, layout 5.1 deja present, vcodec deja present)
    - "I.Am.Love.2009.MULTi.1080p.WEB.x264-FW" -> "I.Am.Love.2009.MULTi.1080p.WEB.DDP.2.0.x264-FW"
      (codec audio DDP + layout 2.0 ajoutes)

    On regarde la 1ere piste audio non-auxiliaire de MediaInfo (les
    commentaires / audio descriptions sont skipes). Pour le vcodec, on
    lit `mediainfo_data["video"]["codec"]` ("HEVC / x265" -> "x265").

    Retourne : (audio_enrichi, vcodec_enrichi, list[str] des signaux humains)
    pour traçabilité dans debug.json.
    """
    signals: list[str] = []
    if not isinstance(mediainfo_data, dict):
        return audio_tokens, vcodec, signals

    rules_audio_codecs = {t.upper() for t in rules.get("audio_codec_tokens", [])}
    rules_audio_channels = set(rules.get("audio_channel_tokens", []))

    # === Audio : codec + layout ===
    # On detecte ce qui est deja present dans audio_tokens. Ordre des checks :
    #  1. Layout direct ("5.1", "7.1", "2.0") — \d\.\d ou rules_audio_channels
    #  2. Codec direct ("DDP", "AAC", "FLAC")
    #  3. Compound ("DDP.5.1") — split en head + tail
    # IMPORTANT : "5.1" matche \d\.\d donc on le traite comme layout AVANT
    # de tester la branche compound (sinon head="5", tail="1" et la regex
    # \d\.\d ne matche pas "1" -> has_layout reste False -> on duplique 5.1).
    has_codec = False
    has_layout = False
    for tok in audio_tokens:
        upper = tok.upper()
        # Layout direct (5.1, 7.1, 2.0)
        if re.fullmatch(r"\d\.\d", tok) or tok in rules_audio_channels:
            has_layout = True
            continue
        # Codec direct (DDP, AAC, FLAC, etc.)
        if upper in rules_audio_codecs:
            has_codec = True
            continue
        # Compound type "DDP.5.1"
        if "." in tok:
            head, _, tail = tok.partition(".")
            if head.upper() in rules_audio_codecs:
                has_codec = True
            if tail in rules_audio_channels or re.fullmatch(r"\d\.\d", tail):
                has_layout = True

    audio_tracks = mediainfo_data.get("audio_tracks") or []
    main_track = None
    for t in audio_tracks:
        if t.get("is_commentary") or t.get("is_audio_description"):
            continue
        main_track = t
        break

    audio_enriched = list(audio_tokens)
    if main_track:
        # Codec : MediaInfo donne "DDP", "AAC", "DD", "DTS-HD MA", etc.
        # On normalise au token Gemini canonique.
        mi_codec = (main_track.get("codec") or "").upper()
        if not has_codec and mi_codec:
            # Mapping vers les tokens canoniques Gemini (rules.json)
            codec_token = _map_mediainfo_codec_to_token(mi_codec, rules_audio_codecs)
            if codec_token:
                # On insere AVANT le layout s'il existe deja, sinon en fin
                if has_layout:
                    # Trouve la position du layout pour inserer le codec juste avant
                    idx_layout = next(
                        (i for i, t in enumerate(audio_enriched)
                         if (t in rules_audio_channels
                             or re.fullmatch(r"\d\.\d", t))),
                        len(audio_enriched),
                    )
                    audio_enriched.insert(idx_layout, codec_token)
                else:
                    audio_enriched.append(codec_token)
                has_codec = True
                signals.append(f"audio_codec '{codec_token}' ajoute (MediaInfo)")

        # Layout : MediaInfo donne "5.1", "2.0", "7.1"
        mi_layout = (main_track.get("channels") or "").strip()
        if not has_layout and mi_layout and re.fullmatch(r"\d\.\d", mi_layout):
            audio_enriched.append(mi_layout)
            has_layout = True
            signals.append(f"audio_layout '{mi_layout}' ajoute (MediaInfo)")

    # === Codec video ===
    vcodec_enriched = vcodec
    if not vcodec_enriched:
        video = mediainfo_data.get("video") or {}
        mi_vcodec = (video.get("codec") or "").upper()
        # "HEVC / x265" -> "x265", "AVC / x264" -> "x264", "AV1" -> "AV1"
        if "X265" in mi_vcodec or "HEVC" in mi_vcodec or "H.265" in mi_vcodec:
            vcodec_enriched = "x265"
        elif "X264" in mi_vcodec or "AVC" in mi_vcodec or "H.264" in mi_vcodec:
            vcodec_enriched = "x264"
        elif "AV1" in mi_vcodec:
            vcodec_enriched = "AV1"
        elif "VP9" in mi_vcodec:
            vcodec_enriched = "VP9"
        if vcodec_enriched and vcodec_enriched != vcodec:
            signals.append(f"video_codec '{vcodec_enriched}' ajoute (MediaInfo)")

    return audio_enriched, vcodec_enriched, signals


# Mapping MediaInfo codec normalise (mediainfo_parser._normalize_audio_codec)
# vers les tokens Gemini canoniques (rules.json).
_MEDIAINFO_TO_GEMINI_AUDIO_CODEC: dict[str, str] = {
    "DDP": "DDP",
    "DD": "DD",
    "DTS": "DTS",
    "DTS-HD MA": "DTS-HDMA",
    "DTS-HD HRA": "DTS-HD.HRA",
    "DTS:X": "DTS",
    "DTS-ES": "DTS",
    "TRUEHD": "TrueHD",
    "TRUEHD ATMOS": "TrueHD",  # Atmos est dans drop_tokens, donc on garde TrueHD
    "AAC": "AAC",
    # NOTES Sprint 8 hotfix : MediaInfo distingue HE-AAC (high efficiency)
    # de AAC-LC (low complexity, standard) du AAC generique. Les 3 sont
    # valides dans rules.json donc on les preserve tels quels.
    "HE-AAC": "HE-AAC",
    "AAC LC": "AAC-LC",
    "AAC-LC": "AAC-LC",
    "OPUS": "OPUS",
    "FLAC": "FLAC",
    "PCM": "PCM",
}


def _map_mediainfo_codec_to_token(mi_codec: str, allowed_tokens: set[str]) -> str:
    """Mappe un codec MediaInfo vers un token Gemini canonique.

    Retourne un token autorise par rules.json.audio_codec_tokens, ou "" si
    aucun mapping trouve. Le mapping est insensible a la casse cote MI mais
    on retourne le token avec la casse exacte de rules.json.
    """
    canonical = _MEDIAINFO_TO_GEMINI_AUDIO_CODEC.get(mi_codec.strip().upper(), "")
    if not canonical:
        return ""
    # On verifie que le token est bien autorise
    if canonical.upper() in allowed_tokens:
        return canonical
    return ""


def _enrich_resolution_from_mediainfo(
    current_resolution: str | None,
    mediainfo_data: dict | None,
    debug: Debug,
) -> str | None:
    """Comble la resolution quand absente du nom, en lisant MediaInfo.video.resolution_label.
    Emet SIG_RESOLUTION_INFERRED si appliquee.
    """
    from . import naming_signals as ns

    if current_resolution:
        return current_resolution
    if not isinstance(mediainfo_data, dict):
        return current_resolution
    video = mediainfo_data.get("video") or {}
    if not isinstance(video, dict):
        return current_resolution
    inferred_res = (video.get("resolution_label") or "").strip()
    if not inferred_res:
        return current_resolution
    print(f"[INFO] Resolution absente du nom : infere {inferred_res} depuis MediaInfo.")
    debug.set("resolution_inferred", inferred_res)  # retro-compat
    ns.emit_signal(debug, ns.SIG_RESOLUTION_INFERRED, True)
    return inferred_res


# ============================================================
# BUILD RELEASE NAME (générique)
# ============================================================

def build_release_name(
    video_path: Path,
    tracker: "Tracker",
    nfo_text: str,
    debug: Debug,
    force_fr: str | None = None,
    tmdb_resolver=None,
    media_info=None,
    mediainfo_data: dict | None = None,
) -> tuple[str, dict | None]:
    """Construit le nom de release standardisé pour `tracker`.

    `tmdb_resolver` est une fonction `(title_parts, year, debug) -> (resolved_parts, ctx)`
    pour permettre l'injection (et le mock en test). En pratique, c'est
    `core.tmdb.resolve_tmdb_metadata`.
    """
    from .nfo import infer_french_variant_from_nfo  # éviter import circulaire

    rules = tracker.rules

    # Pour les saisons et integrales, on utilise le nom du DOSSIER source
    # plutot que le nom du fichier video d'episode. Raison : Sonarr renomme
    # les episodes en "Adolescence - S01E01 - Episode 1.mkv" (perte des specs
    # techniques et de la langue), alors que le nom du dossier source garde
    # "Adolescence.S01.MULTI.2160p.WEBRip.NF.DV.HDR.x265.EAC3.5.1.Atmos-Amen"
    # qui est ce qu'on veut pour build_release_name.
    if media_info is not None:
        from .media_type import MediaType
        # Pour les types TV ou le torrent_target est un dossier (saison,
        # integrale, episode unique pack avec NFO/extras) : on prend par
        # defaut le nom du DOSSIER source qui contient les specs scene,
        # plutot que le nom du fichier video (qui peut etre renomme par Sonarr).
        # MAIS si le nom du dossier est trop minimaliste (ex: "For All
        # Mankind - Saison 02"), on prefere le nom du 1er fichier video
        # qui contient probablement les vrais tokens techniques.
        target = media_info.torrent_target
        if target.is_dir() and media_info.media_type in {
            MediaType.TV_SEASON, MediaType.TV_INTEGRALE, MediaType.TV_EPISODE,
        }:
            folder_name = target.name.strip()
            if _looks_minimal(folder_name):
                file_name = video_path.stem.strip()
                if not _looks_minimal(file_name):
                    from . import naming_signals as ns
                    print(
                        f"[INFO] Nom de dossier minimaliste '{folder_name}' : "
                        f"on utilise le nom du 1er fichier '{file_name}' a la place."
                    )
                    ns.emit_signal(debug, ns.SIG_FOLDER_NAME_MINIMAL_FALLBACK, True)
                    original = file_name
                else:
                    original = folder_name
            else:
                original = folder_name
        else:
            original = video_path.stem.strip()
    else:
        original = video_path.stem.strip()

    inferred = infer_french_variant_from_nfo(nfo_text)
    nfo_variant = inferred["variant"]

    # Lot post-NOTES round 4 : pre-cleaning des crochets `[...]` qui sont
    # une convention scene pour les meta-infos hors-titre (ex: "[reprise 2011]"
    # dans "Metropolis [reprise 2011] (1927)"). Sans ce nettoyage, le
    # tokenizer inclut "reprise" dans le titre + prend 2011 comme annee au
    # lieu de 1927 -> TMDB cherche "Metropolis reprise" en 2011 et rate.
    # On les remplace par un espace pour preserver la separation entre tokens.
    original = re.sub(r"\[[^\]]*\]", " ", original)

    base, team = split_team(original, tracker.default_team)
    base = normalize_separators(base)
    base = split_glued_tokens(base)  # WEBripEAC3 -> WEBrip.EAC3 etc.
    base = split_compound_specs(base)  # WEBDL-5.1-H264 -> WEBDL.5.1.H264
    base = apply_replacements(base, rules.get("replace_tokens", {}))
    base = normalize_multi_language(base)
    base = normalize_channels(base)
    base = remove_tokens(base, rules.get("drop_tokens", []))
    base = collapse_dots(base)

    parts = [p for p in base.split(".") if p]
    parts = merge_video_codec_tokens(parts)
    parts = merge_compound_audio_codecs(parts)
    parts = merge_audio_channel_tokens(parts)

    data = classify_parts(parts, rules)

    if tmdb_resolver is not None:
        # Lot O.6 : detecte si le release est tagge FR-only (FRENCH/VFF/etc.
        # sans MULTi). Si oui, on transmet `release_lang_hint='fr'` au
        # resolver TMDB qui bonifiera les candidats de production
        # francophone — utile pour departager des homonymes EN vs FR
        # (cas reel : "La Maison" UK animation vs "La Maison" QC, year+title
        # exacts identiques, le bonus origine FR fait pencher vers le QC).
        from .tmdb import _detect_french_only_hint
        lang_hint = _detect_french_only_hint(data["lang"])
        try:
            resolved_title_parts, tmdb_context = tmdb_resolver(
                data["title_parts"], data["year"], debug,
                release_lang_hint=lang_hint,
            )
        except TypeError:
            # Backward-compat : resolver custom (forced_id) qui n'accepte
            # pas le kwarg. Fallback sans hint.
            resolved_title_parts, tmdb_context = tmdb_resolver(
                data["title_parts"], data["year"], debug,
            )
    else:
        resolved_title_parts, tmdb_context = data["title_parts"], None

    # Series = regle par defaut "assume VFF si on ne sait pas".
    # Film = strict (on demande --force-fr si ambigu).
    is_tv_series = False
    if media_info is not None:
        from .media_type import MediaType as _MT
        is_tv_series = media_info.media_type in {
            _MT.TV_EPISODE, _MT.TV_SEASON, _MT.TV_INTEGRALE,
        }

    lang_warnings: list[str] = []
    lang = merge_multi_language(
        dedupe_keep_order(data["lang"]),
        rules,
        nfo_variant=nfo_variant,
        force_fr=force_fr,
        tmdb_context=tmdb_context,
        is_vostfr_from_nfo=inferred.get("is_vostfr", False),
        french_audio_count=inferred.get("french_audio_count", 0),
        is_tv_series=is_tv_series,
        out_warnings=lang_warnings,
    )
    if lang_warnings:
        debug.set("lang_needs_choice", lang_warnings)

    # === Auto-enrichissement : combler les trous depuis NFO + MediaInfo ===
    # (cf. _enrich_language_from_nfo et _enrich_resolution_from_mediainfo)
    lang = _enrich_language_from_nfo(
        lang, nfo_variant, force_fr, inferred, mediainfo_data, debug,
        tmdb_context=tmdb_context,
    )
    data["resolution"] = _enrich_resolution_from_mediainfo(
        data.get("resolution"), mediainfo_data, debug,
    )

    # === Lot P : enrichissement audio/codec depuis MediaInfo ===
    # Si le nom source ne contient pas le codec audio principal (AAC, DDP),
    # le layout (5.1, 2.0) ou le codec video (x265, x264), on les ajoute
    # depuis MediaInfo. Resultat : le release name produit est conforme a
    # la charte Gemini meme quand le nom source est minimaliste.
    data["audio"], data["vcodec"], enrich_signals = _enrich_audio_video_from_mediainfo(
        data["audio"], data["vcodec"], mediainfo_data, rules,
    )
    if enrich_signals:
        debug.set("name_enrichment", enrich_signals)

    audio = merge_audio_tokens(dedupe_keep_order(data["audio"]))
    optional = dedupe_keep_order(data["optional"])

    if not resolved_title_parts:
        die("Impossible de détecter le titre pour le release_name")

    # Annee : obligatoire pour films, optionnelle pour series (les noms scene
    # type 'Breaking.Bad.S01E01.MULTi.VFF...' n'ont souvent pas d'annee).
    is_tv = False
    if media_info is not None:
        from .media_type import MediaType
        is_tv = media_info.media_type in {
            MediaType.TV_EPISODE, MediaType.TV_SEASON, MediaType.TV_INTEGRALE
        }
    # Si l'annee n'est pas dans le nom du fichier, on tente de la recuperer
    # depuis TMDB. Pour les films : release_date. Pour les series :
    # first_air_date (rapatrie sous release_date par _build_tv_context).
    # On veut TOUJOURS une annee dans le release_name, y compris pour les
    # series : "Battlestar.Galactica.2004.iNTEGRALE..." plutot que sans.
    if not data["year"] and tmdb_context:
        tmdb_release = (tmdb_context.get("release_date") or "").strip()
        if len(tmdb_release) >= 4 and tmdb_release[:4].isdigit():
            data["year"] = tmdb_release[:4]
            print(f"[INFO] Annee recuperee depuis TMDB : {data['year']}")

    if not data["year"]:
        # Sprint 8 hotfix v7 : avant on faisait die() ici pour les films,
        # ce qui plantait tout le pipeline et l'user voyait un job "failed"
        # sans package cree -> impossible d'override le TMDB ID. Maintenant
        # on emit un signal (penalite -20) et on continue. Le release_name
        # sortira sans annee (non conforme charte) mais le package est cree
        # et accessible via la page detail ou l'user peut override le TMDB ID
        # puis re-preparer pour avoir un release_name correct.
        from . import naming_signals as _ns_year
        _ns_year.emit_signal(debug, _ns_year.SIG_YEAR_MISSING, True)
        if is_tv:
            print(
                "[INFO] Pas d'annee detectee (ni nom ni TMDB) pour la serie. "
                "release_name sera genere sans annee."
            )
        else:
            print(
                "[AVERTISSEMENT] Pas d'annee detectee pour ce film (ni nom ni TMDB). "
                "release_name genere sans annee (non conforme charte Gemini). "
                "Override TMDB ID via la page detail puis re-prepare pour fixer."
            )

    for label, value in [
        ("Langue", lang),
        ("Résolution", data["resolution"]),
        ("Source", data["source"]),
        ("Codec vidéo", data["vcodec"]),
    ]:
        if not value:
            print(f"[AVERTISSEMENT] {label} non détecté(e) dans le nom")

    ordered = []
    ordered.extend(resolved_title_parts)
    if data["year"]:
        ordered.append(data["year"])

    # Insertion du tag de type media (charte Gemini) :
    # - Episode : SxxEyy juste apres l'annee
    # - Saison  : Sxx.COMPLETE
    # - Integrale : iNTEGRALE
    if media_info is not None:
        from .media_type import MediaType, format_episode_tag, format_season_tag
        if media_info.media_type == MediaType.TV_EPISODE:
            if media_info.season is not None and media_info.episode is not None:
                ordered.append(format_episode_tag(media_info.season, media_info.episode))
        elif media_info.media_type == MediaType.TV_SEASON:
            if media_info.season is not None:
                ordered.append(format_season_tag(media_info.season))
                ordered.append("COMPLETE")
        elif media_info.media_type == MediaType.TV_INTEGRALE:
            ordered.append("iNTEGRALE")

    ordered.extend(lang)
    if data["resolution"]:
        ordered.append(data["resolution"])
    ordered.extend(optional)
    if data["source"]:
        ordered.append(data["source"])
    ordered.extend(audio)

    # Inference codec ↔ source (convention G3MINI / Unit3Dup-G3MINI) :
    # REMUX → HEVC/AVC, WEB → H.265/H.264, WEBRip/BDRip → x265/x264.
    # MediaInfo arbitre quand le release_name est trompeur (ex: WEB-DL re-encode).
    has_encode_lib = _has_encode_library(mediainfo_data)
    inferred_vcodec = infer_video_codec(
        data["vcodec"], data["source"], has_encode_library=has_encode_lib,
    )
    if inferred_vcodec != data["vcodec"]:
        print(
            f"[INFO] Codec adapte selon source : {data['vcodec']} -> {inferred_vcodec} "
            f"(source={data['source']}, encode_library_detectee={has_encode_lib})"
        )
        data["vcodec"] = inferred_vcodec

    if data["vcodec"]:
        ordered.append(data["vcodec"])

    ordered = [x for x in ordered if x]
    ordered = [_normalize_token_case(t) for t in ordered]
    base_name = collapse_dots(".".join(ordered))

    # Conserve la casse d'origine de la team (Punisher694 / PopHD / mHDgz /
    # Amen / Frosties etc.). La doc Gemini n'impose pas l'uppercase et de
    # nombreuses teams ont une casse signature (camelCase, PascalCase, etc.).
    from . import naming_signals as ns
    cleaned_team = re.sub(r"[^A-Za-z0-9._-]+", "", team).strip(".-")
    if not cleaned_team:
        team = tracker.default_team
        ns.emit_signal(debug, ns.SIG_TEAM_DEFAULT_USED, True)
    else:
        team = cleaned_team
    release_name = f"{base_name}-{team}"

    # Signaux additionnels : tokens jetes apres l'annee
    if data.get("dropped_unknown_after_year"):
        ns.emit_signal(
            debug, ns.SIG_DROPPED_UNKNOWN_TOKENS,
            list(data["dropped_unknown_after_year"]),
        )

    # Signaux d'override utilisateur (Lot E NOTES.md / trust badge)
    if force_fr in ALLOWED_FORCE_FR:
        ns.emit_signal(debug, ns.SIG_USER_FORCE_FR_USED, force_fr)

    debug.update({
        "original_stem": original,
        "base_after_clean": base,
        "parts_after_codec_merge": parts,
        "title_parts_original": data["title_parts"],
        "title_parts_resolved": resolved_title_parts,
        "year": data["year"],
        "lang": lang,
        "resolution": data["resolution"],
        "optional": optional,
        "source": data["source"],
        "audio": audio,
        "vcodec": data["vcodec"],
        "dropped_unknown_after_year": data["dropped_unknown_after_year"],
        "inferred_nfo_variant": nfo_variant,
        "forced_fr_variant": force_fr,
        "nfo_found_variants": inferred["found_variants"],
        "nfo_audio_titles": inferred["audio_titles"],
        "nfo_has_french_audio": inferred.get("has_french_audio", False),
        "nfo_has_french_subtitle": inferred.get("has_french_subtitle", False),
        "nfo_is_vostfr": inferred.get("is_vostfr", False),
        "nfo_french_audio_count": inferred.get("french_audio_count", 0),
        "is_tv_series": is_tv_series,
        "tmdb_original_language": (
            tmdb_context.get("original_language") if tmdb_context else None
        ),
        "tmdb_production_countries": (
            tmdb_context.get("production_countries") if tmdb_context else None
        ),
        "team": team,
        "release_name": release_name,
    })

    return release_name, tmdb_context
