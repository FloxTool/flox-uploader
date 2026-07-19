"""Helpers utilitaires purs pour la construction de noms de release.

Sprint B.1 v0.5.0 (PLAN-MULTICAT §5.5) — extraction depuis `release_name.py`.

Ces helpers etaient historiquement definis dans `core/release_name.py`. Ils
sont deplaces ici pour etre reutilisables par les futures strategies non-video
(BookNamingStrategy, GameNamingStrategy, etc. — Sprints D/E/H).

NO-OP cote comportement : `release_name.py` les re-importe et re-expose, donc
tout caller historique (`from flox_uploader.core.release_name import split_team`)
continue de fonctionner sans modification.

Aucune dependance metier ici — uniquement `re` et `unicodedata` de la stdlib.
"""
from __future__ import annotations

import re
import unicodedata


# ============================================================
# TOKENS "TECHNIQUES" (vocabulaire scene unifie)
# ============================================================
# Tokens reconnus dans les noms de release scene. Source unique de verite,
# utilisee par :
# - split_team : rejet des candidates qui contiennent un de ces tokens
#   (evite que "AC3-Amen" donne "AC3" comme team)
# - split_team fallback "...x264.TEAM" : rejet de "x264" / "1080p" comme team
# - _looks_minimal : detection des noms sans aucun marqueur technique
#   (declenche le fallback "filename" depuis le dossier minimaliste)
_TECH_TOKENS: set[str] = {
    # Resolutions
    "480p", "576p", "720p", "1080p", "2160p", "1080i", "576i", "480i",
    "4K", "UHD",
    # Sources
    "BluRay", "BDRip", "BRRip", "WEB", "WEBRip", "WEB-DL", "WEBDL",
    "HDTV", "DVD", "DVDRip", "REMUX", "HDLight", "HDRip", "TVRip",
    # Codecs video
    "x264", "x265", "H.264", "H.265", "H264", "H265",
    "HEVC", "AVC", "AV1", "VC-1", "DivX", "XviD",
    # Codecs audio
    "DTS", "AC3", "AAC", "DDP", "DD", "FLAC", "OPUS", "TrueHD", "Atmos",
    "AC-3", "EAC3", "E-AC3", "DTS-HD", "DTS-HDMA",
    # Langues
    "MULTi", "MULTI", "FRENCH", "FR", "VOSTFR", "VFF", "VFQ", "VFB",
    "VOF", "VOQ", "VOB", "VF2", "TRUEFRENCH", "SUBFRENCH",
    # HDR / bit
    "HDR", "HDR10", "HDR10P", "DV", "DoVi", "SDR", "HLG",
    "10bit", "8bit", "10Bit", "8Bit",
    # Editions
    "EXTENDED", "REMASTERED", "REPACK", "PROPER", "DIRECTORS", "UNCUT",
    "UNRATED", "INTERNAL", "LIMITED", "IMAX", "AD", "COMPLETE",
    # Channels
    "2CH", "6CH", "8CH",
}
_TECH_UPPER: frozenset[str] = frozenset(t.upper() for t in _TECH_TOKENS)

# Regex compose pour _looks_minimal (compile une seule fois). Match :
# - n'importe quel token de _TECH_TOKENS (case-insensitive, longest-first
#   pour que "WEB-DL" soit teste avant "WEB")
# - resolution nue type "1080" sans p (rare mais possible)
_LOOKS_MINIMAL_TECH_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(
        re.escape(t) for t in sorted(_TECH_UPPER, key=len, reverse=True)
    )
    + r")\b|\b\d{3,4}p\b",
    re.IGNORECASE,
)


# Casse canonique pour les tokens scene reconnus.
# Cle = forme uppercase, valeur = casse a appliquer dans le release_name.
# Pour les tokens non listes, on garde la casse du fichier source mais on
# capitalize la premiere lettre (utile pour les mots du titre : 'delicieux'
# -> 'Delicieux', 'matrix' -> 'Matrix').
_CANONICAL_CASE: dict[str, str] = {
    # Langues
    "MULTI": "MULTi",
    "MULTI.VFF": "MULTi.VFF", "MULTI.VFQ": "MULTi.VFQ",
    "MULTI.VFB": "MULTi.VFB", "MULTI.VF2": "MULTi.VF2",
    "VFF": "VFF", "VFQ": "VFQ", "VFB": "VFB", "VF2": "VF2",
    "VOF": "VOF", "VOQ": "VOQ", "VOB": "VOB",
    "VOSTFR": "VOSTFR", "FRENCH": "FRENCH", "FR": "FR",
    "TRUEFRENCH": "TRUEFRENCH", "SUBFRENCH": "SUBFRENCH",
    # Sources
    "BLURAY": "BluRay", "BDRIP": "BDRip", "DVDRIP": "DVDRip",
    "HDRIP": "HDRip", "WEBRIP": "WEBRip", "WEB-DL": "WEB-DL",
    "WEB": "WEB", "HDTV": "HDTV", "DVD": "DVD", "REMUX": "REMUX",
    # Resolutions
    "480P": "480p", "576P": "576p", "720P": "720p", "1080P": "1080p",
    "2160P": "2160p", "1080I": "1080i", "576I": "576i", "480I": "480i",
    # Codecs video
    "X264": "x264", "X265": "x265", "H.264": "H.264", "H.265": "H.265",
    "HEVC": "HEVC", "AVC": "AVC", "AV1": "AV1", "VC-1": "VC-1",
    # Codecs audio
    "DD": "DD", "DDP": "DDP", "AAC": "AAC", "AC3": "AC3",
    # NOTES Sprint 8 hotfix : HE-AAC + AAC-LC explicitement listes pour preserver
    # leur casse (sinon `He-aac` apres capitalize). Les 3 sont valides selon
    # rules.json (audio_codec_tokens).
    "HE-AAC": "HE-AAC", "AAC-LC": "AAC-LC",
    "E-AC3": "E-AC3", "DTS": "DTS", "DTS-HD": "DTS-HD",
    "DTS-HDMA": "DTS-HDMA", "DTS-HD.HRA": "DTS-HD.HRA",
    "TRUEHD": "TrueHD", "OPUS": "OPUS", "FLAC": "FLAC",
    "ATMOS": "Atmos",
    # HDR (convention Gemini : forme courte DV/HDR10P, pas DoVi/HDR10+)
    "DV": "DV", "DOVI": "DV", "DOLBYVISION": "DV",
    "HDR": "HDR", "HDR10": "HDR10",
    "HDR10P": "HDR10P", "HDR10PLUS": "HDR10P", "HDR10+": "HDR10P",
    "SDR": "SDR", "HLG": "HLG", "PQ10": "PQ10",
    "10BIT": "10Bit", "8BIT": "8Bit", "12BIT": "12Bit",
    # Editions / cuts (vocabulaire FR + EN)
    "IMAX": "IMAX", "IMAX.EDITION": "IMAX.EDITION",
    # Optional
    "REPACK": "REPACK", "PROPER": "PROPER", "EXTENDED": "EXTENDED",
    "DIRECTORS": "DIRECTORS", "CUT": "CUT", "THEATRICAL": "THEATRICAL",
    "UNRATED": "UNRATED", "UNCUT": "UNCUT", "REMASTERED": "REMASTERED",
    "LIMITED": "LIMITED", "INTERNAL": "INTERNAL",
    "AD": "AD", "FORCED": "Forced",
    # TV
    "COMPLETE": "COMPLETE", "INTEGRALE": "iNTEGRALE",
    # Channels (norme Gemini : MAJUSCULES)
    "2CH": "2CH", "6CH": "6CH", "8CH": "8CH",
    # Chiffres romains (suites de films : Visiteurs II, Star Wars V, etc.)
    "II": "II", "III": "III", "IV": "IV", "V": "V",
    "VI": "VI", "VII": "VII", "VIII": "VIII", "IX": "IX",
    "X": "X", "XI": "XI", "XII": "XII", "XIII": "XIII",
}


# ============================================================
# NORMALISATION TOKEN / CASSE
# ============================================================

def _normalize_token_case(token: str) -> str:
    """Applique la casse canonique d'un token scene.

    Si le token est dans `_CANONICAL_CASE`, on retourne la valeur. Sinon, on
    capitalize la premiere lettre (cas typique des mots du titre : 'matrix'
    -> 'Matrix', 'delicieux' -> 'Delicieux'). Les tokens deja en mixed case
    explicite (ex 'iNTEGRALE') passent par la table.

    Sxx / SxxEyy / 5.1 / 7.1 / annee : on les retourne tels quels.

    CAS SPECIAL codec audio compose (DTS2.0, DDP5.1, E-AC3.5.1, TrueHD7.1, etc.) :
    on detecte le pattern `<codec><sep?><X.Y>` et on applique la casse canonique
    au codec sans toucher aux channels. Sinon le fallback "Capitalize" donne
    `Dts2.0`/`E-ac3.5.1` ce qui est faux.
    """
    if not token:
        return token
    key = token.upper()
    if key in _CANONICAL_CASE:
        return _CANONICAL_CASE[key]
    # SxxEyy, Sxx (laisses tels quels en uppercase)
    if re.match(r"^S\d{1,2}(E\d{1,3})?$", key):
        return key
    # Annee 4 chiffres / channels (5.1, 7.1, etc.) / nombres -> tel quel
    if re.match(r"^\d+(\.\d+)?$", token):
        return token

    # Codec audio compose : codec + (sep optionnel) + channels.
    # Deux familles de channels selon la charte Gemini :
    #   - Numerical : 1.0, 2.0, 4.0, 5.1, 6.1, 7.1
    #     Exemples : DDP5.1, E-AC3.5.1, TrueHD7.1, DTS2.0
    #   - CH-suffix : 2CH, 6CH, 8CH (toujours en MAJUSCULES)
    #     Exemples : AAC6CH, DDP8CH, AC32CH
    # Le codec peut contenir des tirets (E-AC3, DTS-HD), des chiffres (AC3, MP3),
    # mais doit commencer par une lettre.
    audio_match = re.match(
        r"^([A-Za-z][A-Za-z0-9-]*?)(\.?)(\d\.\d|\d{1,2}CH)$",
        token,
        re.IGNORECASE,
    )
    if audio_match:
        codec_part, sep, channels = audio_match.groups()
        codec_canonical = _CANONICAL_CASE.get(
            codec_part.upper(), codec_part.upper()
        )
        # Channels : numerical garde sa forme (5.1 reste 5.1), CH-suffix
        # forcement en MAJUSCULES selon la charte (6ch -> 6CH).
        return f"{codec_canonical}{sep}{channels.upper()}"

    # Mots du titre : capitalize la premiere lettre, garde le reste lowercase
    return token[0].upper() + token[1:].lower()


# ============================================================
# NORMALISATION STRINGS
# ============================================================

def collapse_dots(text: str) -> str:
    return re.sub(r"\.+", ".", text).strip(".")


def ascii_fold(text: str) -> str:
    """Capharnaüm -> Capharnaum, Dìdi -> Didi."""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _looks_minimal(name: str) -> bool:
    """Determine si un nom de dossier/fichier est "minimaliste" (sans tags
    techniques scene). Vrai si on n'y trouve aucun token technique connu
    (resolution, codec, source, langue) -> on prefere le nom du fichier au
    nom du dossier dans ce cas.

    Utilise _LOOKS_MINIMAL_TECH_PATTERN (compose a partir de _TECH_TOKENS,
    source unique de verite du vocabulaire scene).
    """
    if not name:
        return True
    return _LOOKS_MINIMAL_TECH_PATTERN.search(name) is None


def normalize_separators(text: str) -> str:
    text = ascii_fold(text)
    # Apostrophes : supprimer sans espace (colle les mots)
    # Don't -> Dont, l'homme -> lhomme, Coupez ! -> Coupez
    for ch in "'’‘`":
        text = text.replace(ch, "")
    # Ponctuation sans valeur dans un release name : remplacer par espace
    for ch in "()[]{},:;!?":
        text = text.replace(ch, " ")
    text = text.replace("_", ".")
    text = re.sub(r"\s+", ".", text)
    # Tirets de titre (entourés de points après conversion) : supprimer
    # "OSS.117.-.Rio" → "OSS.117.Rio"
    # Préserve les tirets collés type WEB-DL, DTS-HD, E-AC3 (pas de points autour)
    text = re.sub(r"\.-\.", ".", text)
    # Nettoyage final des caractères restants non autorisés
    text = re.sub(r"[^A-Za-z0-9.\-+]+", ".", text)
    return collapse_dots(text)


# ============================================================
# SPLIT TEAM (5 strategies, vocabulaire commun via _TECH_UPPER)
# ============================================================

def split_team(name: str, default_team: str) -> tuple[str, str]:
    # === Cleanup pre-split : enleve un eventuel "(titre alternatif)" final ===
    # Ex : "...QTZ (The Matrix)" / "...PopHD (The King's Speech)" / "...x265 (My Movie EN Title)"
    # Ces parentheses sont du bonus user et masquent souvent la team finale.
    name = re.sub(r"\s*\([^()]+\)\s*$", "", name).strip()

    # 1. Scene : -TEAM colle (pas d'espace avant le tiret).
    # Autorise les tirets INTERNES dans la team (ex: "mHDgz-Dread-Team")
    # MAIS on doit rejeter les matches greedy qui englobent un codec compose
    # comme "E-AC3" (donnerait "AC3.5.1.x265-Amen" au lieu de "Amen").
    # Strategie : on essaie chaque `-` de droite a gauche, on rejette le
    # candidat si la portion apres `-` contient un token technique connu
    # (vocabulaire centralise dans _TECH_UPPER, module-level).
    def _candidate_has_tech(c: str) -> bool:
        # Split sur . et - pour examiner chaque mot
        for tok in re.split(r"[.\-]+", c):
            if tok.upper() in _TECH_UPPER:
                return True
        return False

    # Left-to-right : on cherche le PREMIER `-` qui precede une portion
    # sans token technique. Donne "mHDgz-Dread-Team" (pas "Team") et
    # "Amen" (pas "AC3.5.1.x265-Amen") car on rejette les portions
    # qui contiennent x265/AC3/etc.
    dash_positions = [m.start() for m in re.finditer(r"(?<!\s)-", name)]
    for dash_pos in dash_positions:
        candidate = name[dash_pos + 1:].rstrip()
        if not candidate:
            continue
        # R1 (audit AUDIT_2026-07-19) : une team Gemini est un token UNIQUE
        # sans point (le point est le separateur de tokens de la charte).
        # Si le candidat contient un ".", c'est qu'on a coupe au milieu de
        # tokens techniques a tiret (ex. dash de "WEB-DL" -> candidat
        # "DL.DDP5.1.H.265-FLUX", ou dash de "DTS-HD" -> "HD.MA.5.1-AZAZE",
        # ou dash de "AC-3" -> "3.5.1-NoTag"). On rejette et on essaie le
        # dash suivant, qui donnera la vraie team (FLUX / AZAZE / NoTag).
        if "." in candidate:
            continue
        # Forme valide : alphanumerique + tirets/underscore/plus, pas double-tiret
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_+\-]*$", candidate):
            continue
        if "--" in candidate:
            continue
        # Si la portion contient un codec/resolution/lang -> on ne prend pas
        # ce dash comme separator team, on essaie le suivant.
        if _candidate_has_tech(candidate):
            continue
        team = candidate.strip(" ._-")
        base = name[:dash_pos].rstrip(" .")
        if team and base:
            return base, team

    # 2. [TEAM] entre crochets
    m = re.match(r"^(.*?)[\s._-]*\[(.+?)\]\s*$", name)
    if m:
        base = m.group(1).strip(" ._-")
        team = m.group(2).strip(" ._-")
        if team:
            return base, team

    # 3. Non-scene : "... 5.0 v2 -Punisher694" (espace AVANT le tiret, team
    # = un seul mot alphanumerique sans espace ni tiret interne).
    # On exige un team de 3+ caracteres pour eviter de matcher des titres
    # avec un suffixe "-A" ou "-2" en fin.
    m = re.search(r"\s-([A-Za-z0-9][A-Za-z0-9_+]{2,30})\s*$", name)
    if m:
        team = m.group(1).strip(" ._-")
        base = name[: m.start()].strip(" .")
        if team and base:
            return base, team

    # 4. Format non-scène avec espaces des deux cotes du tiret :
    # "Titre (Année) - specs TEAMNAME"
    # Cas fréquent avec contenu entre parenthèses APRÈS la team, ex :
    #   "Matrix (1999) MULTi ... - QTZ (The Matrix)"
    # On retire d'abord toute parenthèse finale (titre alternatif fourni en plus)
    # avant de chercher le dernier mot comme team.
    if " - " in name:
        name_cleaned = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()

        if " - " in name_cleaned:
            before, after = name_cleaned.rsplit(" - ", 1)
            tail_tokens = after.strip().split()
            if tail_tokens:
                team = tail_tokens[-1].strip(" ._-")
                rest = " ".join(tail_tokens[:-1])
                base = (before + " " + rest).strip(" .")
                if team and base:
                    return base, team

    # 5. Fallback : dernier token apres un point, si ce n'est pas un token
    # technique connu (codec / source / langue / resolution / channels).
    # Couvre le cas "...AC3.mHDgz" (point au lieu de tiret pour la team).
    # On utilise _TECH_UPPER (vocabulaire centralise) pour rejeter les
    # tokens techniques candidates.
    last_dot = name.rfind(".")
    if last_dot > 0:
        candidate = name[last_dot + 1:].strip()
        # Token alphanumerique de 3+ chars, pas un nombre pur, pas dans la liste
        if (candidate
                and len(candidate) >= 3
                and re.match(r"^[A-Za-z][A-Za-z0-9_+\-]*$", candidate)
                and candidate.upper() not in _TECH_UPPER):
            base = name[:last_dot].strip(" .")
            if base:
                return base, candidate

    return name.strip(" ."), default_team


# ============================================================
# UTILITAIRES LISTES
# ============================================================

def dedupe_keep_order(items: list[str]) -> list[str]:
    """Dedup case-insensitive en preservant l'ordre d'apparition."""
    seen = set()
    out = []
    for item in items:
        key = item.upper()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
