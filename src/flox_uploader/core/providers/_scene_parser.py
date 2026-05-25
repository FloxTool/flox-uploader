"""Decompose un nom de release scene livre en tokens semantiques.

Sprint D.20 v0.5.0 (notes Louis N-R1 a N-R12). Le probleme racine :
nos noms de fichier scene contiennent dots-separated tokens entremeles
(authors + title + year + lang + format + team + tome). Sans parsing
structure, on prenait tout comme title -> queries Google Books / BnF
rataient + release_name reconstruit etait pollue (duplications,
tokens techniques dans le titre, team mal detectee).

Ce module fait l'equivalent du release_name.py video mais pour les
livres. Il identifie chaque token et retourne un ParsedBookRelease.

Stratégie multi-pass :
  1. Extraire le team suffix (-TEAM / [TEAM] / -COZY etc.)
  2. Extraire le format (EPUB/PDF/CBZ/CBR/MOBI/AZW3/M4B/MP3/...)
  3. Extraire la langue (FRENCH/ENGLISH/MULTi/FR/EN/...)
  4. Extraire l'annee (1900-2099)
  5. Extraire les marqueurs audio (VBR/CBR/128kbps/320kbps/...)
  6. Extraire le prefixe HS (Hors-Serie)
  7. Extraire le tome (T01/T03/Tome.X/Vol.X) et range (T01-T06)
  8. Extraire les marqueurs digitaux ([Digital-XXXX], (TCH), (10354)...)
  9. Identifier les auteurs en debut (1-3 mots commencant par majuscule)
 10. Le reste = titre, dots->espaces, ponctuation propre

Concu pour etre injectable dans BookNamingStrategy ET dans _parse_*_filename
des extracteurs (pdf_metadata, cbz_metadata).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ============================================================
# Tokens reconnus (uppercase pour comparaison case-insensitive)
# ============================================================

# Formats fichier (livre + audiobook)
_FORMAT_TOKENS: dict[str, str] = {
    "EPUB": "epub", "PDF": "pdf", "CBZ": "cbz", "CBR": "cbr",
    "MOBI": "mobi", "AZW3": "azw3", "AZW": "azw", "DJVU": "djvu",
    "M4B": "m4b", "MP3": "mp3", "FB2": "fb2", "TXT": "txt",
    "EBOOK": "",  # juste un marqueur scene generique, on l'absorbe
    "E-BOOK": "",
}

# Langues : token scene -> code ISO 639-1.
# Sprint D.20 : on N'INCLUT PAS les codes 2-lettres qui sont aussi des mots
# courants en français/anglais : EN ("en" preposition), DE ("de" prep),
# DU/LA/LE/UN. Si l'utilisateur veut indiquer la langue dans son release,
# il utilisera la forme explicite (FRENCH/ENGLISH/...). Last-wins logic
# pour les conflits (cf. _classify_tokens).
_LANG_TOKENS: dict[str, str] = {
    "FRENCH": "fr", "FR": "fr", "FRA": "fr", "VFF": "fr",
    "MULTI": "fr",  # MULTi sur un livre = generique FR par defaut
    "MULTI.VFF": "fr",
    "ENGLISH": "en", "ENG": "en",
    "SPANISH": "es",
    "GERMAN": "de",
    "ITALIAN": "it",
    "PORTUGUESE": "pt",
    "JAPANESE": "ja", "JAP": "ja",
    "CHINESE": "zh",
    "RUSSIAN": "ru",
    "KOREAN": "ko",
    "DUTCH": "nl",
    "VOSTFR": "fr",
}

# Tokens audio (audiobook). On les CAPTURE pour les metadata mais
# on les retire du titre pour la query.
_AUDIO_QUALITY_TOKENS = {"VBR", "CBR"}
# Patterns kbps : 128kbps, 192kbps, 320kbps, ...
_KBPS_RE = re.compile(r"^\d{2,4}KBPS$", re.IGNORECASE)
# Pattern kHz : 44.1kHz, 48kHz (moins frequent mais possible)
_KHZ_RE = re.compile(r"^\d{2,3}(?:\.\d)?KHZ$", re.IGNORECASE)

# Marqueurs scene generiques a retirer purement (pas d'info utile).
# NOTE Sprint D.20 : NoTAG/NoTag est volontairement ABSENT car c'est une
# team valide (default scene "pas de team explicite"). Si on le mettait
# en noise, _extract_team rejetterait "NoTAG" comme candidate team et le
# laisserait dans le titre brut.
_SCENE_NOISE = {
    "RETAIL", "PROPER", "REPACK", "INTERNAL",
    "HD", "ED", "OCR", "OCRED",
    # Edition markers (rare mais existe)
    "EDITION", "VERSION",
    # Tags douteux
    "TCH",  # tag scene comics
}

# Teams "generiques" reconnues comme team scene valide.
# Utilise par _is_plausible_team pour valider ces noms communs.
_GENERIC_TEAMS = {"NOTAG", "NO-TAG", "NO_TAG", "ANON", "ANONYMOUS"}

# Tokens digitaux : [Digital-XXXX], (10354), [Webrip], etc.
# Regex qui matche TOUT pattern parenthese ou crochet avec contenu.
_BRACKETED_RE = re.compile(r"[\[\(]([^\]\)]*)[\]\)]")

# Annee 1900-2099
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

# Tome : T01, T03, T08, T.01, T 01, Tome01, Tome.1, Tome 1, T1, Vol01, Vol.1
_TOME_RE = re.compile(r"^(?:T|TOME|VOL)\.?[\s]?0*(\d{1,4})$", re.IGNORECASE)
# Range : T01-T06, T1-T8, T01.T06 (point au lieu de tiret rare)
_TOME_RANGE_RE = re.compile(
    r"^(?:T|TOME|VOL)\.?0*(\d{1,4})[\.\-–—](?:T|TOME|VOL)?\.?0*(\d{1,4})$",
    re.IGNORECASE,
)
# "Knockemout.1" : pattern <word>.<digit> ou le digit est un tome implicite
# (sans prefixe T). On detecte seulement si le digit est <= 99 pour eviter
# faux positifs avec "[Digital-2984]" ou annees.
_IMPLICIT_TOME_RE = re.compile(r"^([0-9]{1,2})$")  # 1 a 99 seul

# Sprint D.27 v0.5.0 : IDs numeriques internes (tracker, digital, ref).
# Pattern : 4+ digits SEULS, qui ne sont pas une annee (1900-2099 deja
# capturee par _YEAR_RE). Ex : "10354", "29384", "100123".
# On les absorbe (pas dans le title) car ce sont des identifiants
# internes : numero tracker, ID digital, reference editoriale, etc.
# Cas reel Louis : "Zep.Decoupe.En.Tranches.10354.PDF" -> 10354 est
# un ID tracker, pas une partie du titre.
_NUMERIC_ID_RE = re.compile(r"^[0-9]{4,}$")

# Integrale / Compilation / Coffret
_INTEGRALE_TOKENS = {
    "INTEGRALE", "INTÉGRALE", "INTEGRAL",
    "COMPILATION", "COMPLET", "COMPLETE",
    "COFFRET", "BOX", "BOXSET", "COMPILE",
}

# Prefixes HS (Hors-Serie)
_HS_TOKENS = {"HS", "H.S", "HORS-SERIE", "HORS.SERIE", "HORSSERIE"}

# Particules de noms de famille a NE PAS considerer comme un nouveau mot
# d'auteur quand on detecte des chaines majuscule a la suite.
# "Andrzej Sapkowski" : "Andrzej" Cap, "Sapkowski" Cap -> 2 mots auteur OK
# "Jean-Paul Labourdette" : tirets internes preserves
_AUTHOR_PARTICLE = {"DE", "DU", "LA", "LE", "VAN", "VON", "AL", "AND"}


# ============================================================
# Dataclass de retour
# ============================================================

@dataclass
class ParsedBookRelease:
    """Resultat de la decomposition d'un nom de release livre.

    Tous les champs sont optionnels. Le caller decide quoi en faire :
    - BookNamingStrategy : reconstruit Authors.Title.Tx.Year.Lang.Format-Team
    - _query_normalize : utilise title + authors[0] pour Google Books / BnF
    - extracteurs (pdf/cbz) : fallback quand les metadonnees fichier sont
      vides
    """
    authors: list[str] = field(default_factory=list)
    title: str = ""
    year: int = 0
    language: str = ""           # iso 639-1 ("fr"/"en"/...)
    file_format: str = ""        # "epub"/"pdf"/"cbz"/...
    team: str = ""
    series: str = ""             # nom de la serie si detecte
    series_index: float = 0.0    # 3.0 pour T03
    series_index_range: str = ""  # "01-06" pour T01-T06
    is_integrale: bool = False
    is_hors_serie: bool = False
    audio_quality: str = ""      # "VBR"/"CBR"/"128kbps"/...

    # Debug : tokens originaux et tokens "absorbés" (techniques)
    raw_tokens: list[str] = field(default_factory=list)
    absorbed_tokens: list[str] = field(default_factory=list)


# ============================================================
# Fonction principale
# ============================================================

def parse_book_filename(
    stem_or_release: str,
    file_format_hint: str = "",
) -> ParsedBookRelease:
    """Parse un nom de release scene livre.

    Args:
        stem_or_release : nom de fichier sans extension OU release_name
            complet. Le parser tolere les 2 formats (avec/sans extension
            terminale).
        file_format_hint : extension du fichier source (ex: "epub", "pdf").
            Utilisee si le release_name lui-meme ne contient pas le format.

    Returns:
        ParsedBookRelease avec les champs detectes (vides si non identifies).
        Ne plante jamais. Pour une chaine non-parsable, retourne un
        ParsedBookRelease avec juste `title = chaine brute` et team = "NoTAG".
    """
    if not stem_or_release:
        return ParsedBookRelease(team="NoTAG")

    parsed = ParsedBookRelease()

    # Etape 1 : pre-traiter les marqueurs entre [] ou ().
    # ORDRE D.20 : on fait ça AVANT _extract_team car les bracketed
    # peuvent contenir un tiret interne (ex: [Digital-2984]) qui ferait
    # confondre _extract_team avec un team marker.
    # MAIS attention : `[EPUB]`, `[FRENCH]`, `[MP3]` sont des marqueurs
    # de format/lang/audio connus qu'il faut PRESERVER (les sortir du
    # bracket). Pour le reste (Digital-XXXX, scan tags, etc.), on absorb.
    base_after_brackets, bracketed_unknown = _preprocess_brackets(stem_or_release)
    parsed.absorbed_tokens.extend(bracketed_unknown)

    # Etape 2 : extraire le team suffix (-TEAM ou - TEAM ou [TEAM])
    # On fait ça AVANT de splitter en tokens pour preserver la team
    # multi-cap (ex: "Punisher694", "COZY", "Flox").
    base, team = _extract_team(base_after_brackets)
    parsed.team = team

    # Etape 3 : tokenize sur dots + spaces + underscores
    # On garde les tirets internes (Jean-Paul, E-Book).
    raw_tokens = [
        t for t in re.split(r"[\.\s_]+", base) if t
    ]
    parsed.raw_tokens = list(raw_tokens)

    # Etape 4 : classifier chaque token et retirer les techniques
    title_tokens, classified = _classify_tokens(raw_tokens, parsed)
    # Sprint D.27 : on persiste les tokens absorbes (langue, format, year,
    # tome, ID numerique, etc.) dans parsed.absorbed_tokens pour traceabilite
    # debug + tests.
    parsed.absorbed_tokens.extend(classified)

    # Etape 5 : detecter les auteurs en debut des title_tokens
    title_tokens = _extract_authors(title_tokens, parsed)

    # Etape 6 : reconstruire le titre proprement (espaces, capitalisation)
    parsed.title = _build_title(title_tokens, parsed)

    # Etape 7 : appliquer le file_format_hint si rien detecte dans le nom
    if not parsed.file_format and file_format_hint:
        parsed.file_format = file_format_hint.lower().lstrip(".")

    # Etape 8 : team default si toujours vide
    if not parsed.team:
        parsed.team = "NoTAG"

    return parsed


# ============================================================
# Helpers - extraction par étapes
# ============================================================

def _preprocess_brackets(s: str) -> tuple[str, list[str]]:
    """Pre-traite les marqueurs [bracketed] et (parens) :
    - Si le contenu est un token connu (FORMAT/LANG/AUDIO/HS/INTEGRALE),
      on retire juste les crochets, le token reste dans le flux.
    - Sinon (Digital-XXXX, scan tags, ID interne), on absorb completement.

    Retourne (string_propre, list_des_absorbes).

    Exemple : `Title.[EPUB]-NoTAG (Delcourt) [Digital-2984]`
      -> ("Title. EPUB -NoTAG", ["Delcourt", "Digital-2984"])
    """
    absorbed: list[str] = []

    def replace_match(m):
        content = m.group(1).strip()
        upper = content.upper()
        # Token connu : on retire juste les crochets, on garde le contenu
        if (upper in _FORMAT_TOKENS
                or upper in _LANG_TOKENS
                or upper in _AUDIO_QUALITY_TOKENS
                or upper in _HS_TOKENS
                or upper in _INTEGRALE_TOKENS
                or _KBPS_RE.match(content)
                or _KHZ_RE.match(content)
                or _YEAR_RE.match(content)
                or _TOME_RE.match(content)
                or _TOME_RANGE_RE.match(content)):
            return f" {content} "
        # Sinon : on absorb et on remplace par espace
        absorbed.append(content)
        return " "

    cleaned = _BRACKETED_RE.sub(replace_match, s).strip()
    # Compacter les espaces multiples (cosmetique)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned, absorbed


# Regex team : tolérante aux patterns scene + bracketed.
# Captures (en ordre de priorité) :
# 1. Suffix `-TEAM` ou `-TEAM.ext` (le plus courant)
# 2. Suffix ` - TEAM` (espaces autour, jamais sur les livres mais possible)
# 3. Wrapping `[TEAM]` ou `(TEAM)` en fin de chaine
_TEAM_SUFFIX_DASH_RE = re.compile(
    r"^(.+?)[-]\s*([A-Za-z][A-Za-z0-9._-]{1,30}?)\s*$"
)
_TEAM_BRACKETED_END_RE = re.compile(
    r"^(.+?)\s*[\[\(]\s*([A-Za-z][A-Za-z0-9.-]{1,30})\s*[\]\)]\s*$"
)


def _extract_team(release: str) -> tuple[str, str]:
    """Extrait le team suffix d'un release name. Retourne (base, team).

    Strategies (par ordre de priorité) :
    1. Suffix -TEAM avec scene-like name (NoTAG / Flox / COZY / Punisher694)
       MAIS attention : "Tintin-T07" a un tiret qui n'est PAS un team marker
    2. Wrapping [TEAM] ou (TEAM) en fin

    Le tiret PEUT etre un tokenizer normal dans certains noms ; on accepte
    le team-suffix SEULEMENT si ce qui suit le dernier `-` est un mot
    plausible (non un format/lang/year/tome).
    """
    s = release.strip()

    # 1. Pattern bracketed en fin : "Foo [TEAM]" ou "Foo (TEAM)"
    m = _TEAM_BRACKETED_END_RE.match(s)
    if m:
        candidate = m.group(2).strip().rstrip(".")
        if _is_plausible_team(candidate):
            return m.group(1).strip().rstrip(" -."), candidate

    # 2. Pattern -TEAM en fin (le plus courant). On prend le DERNIER `-`
    # car certains noms ont des tirets internes (Jean-Paul, T01-T06, etc.).
    last_dash = s.rfind("-")
    if last_dash > 0:
        candidate = s[last_dash + 1:].strip().rstrip(".")
        if _is_plausible_team(candidate):
            return s[:last_dash].strip().rstrip(" ."), candidate
        # Sprint D.29 v0.5.0 : si le candidat post-dash a des espaces ou si
        # le dash est entoure d'espaces, c'est un subtitle separator
        # editorial (ex: "Guide Petit Fute- Escapades dans la Vienne"),
        # PAS un scene team marker. On TRONQUE le titre au dash (le
        # sous-titre apres est drop, la partie avant est plus
        # canonique pour la recherche).
        has_space_adjacent = (
            (last_dash > 0 and s[last_dash - 1].isspace())
            or (last_dash + 1 < len(s) and s[last_dash + 1].isspace())
        )
        candidate_has_spaces = candidate and any(c.isspace() for c in candidate)
        if has_space_adjacent or candidate_has_spaces:
            return s[:last_dash].strip().rstrip(" ."), ""

    return s, ""


def _is_plausible_team(s: str) -> bool:
    """Heuristique : est-ce que `s` ressemble a un nom de team scene ?

    Critères :
    - Longueur 2-30 caracteres
    - Au moins 1 lettre
    - PAS d'espaces internes (les teams scene sont des blobs alphanum :
      'NoTAG', 'Frosties', 'Punisher694', 'PopHD'). Sprint D.29 v0.5.0
      (cas Louis 'Guide Poitiers 2026 Petit Fute- Escapades dans la
      Vienne.epub' qui captait 'Escapades dans la Vienne' comme team).
    - PAS un token connu (format/lang/audio/scene noise/HS/integrale/year/tome)
    """
    if not s or len(s) < 2 or len(s) > 30:
        return False
    if not any(c.isalpha() for c in s):
        return False
    # Sprint D.29 : un team scene n'a JAMAIS d'espace. Une sequence comme
    # "Escapades dans la Vienne" est un sous-titre (separe par "- " typique
    # editorial), pas une team.
    if any(c.isspace() for c in s):
        return False
    upper = s.upper()
    if upper in _FORMAT_TOKENS:
        return False
    if upper in _LANG_TOKENS:
        return False
    if upper in _AUDIO_QUALITY_TOKENS:
        return False
    if upper in _SCENE_NOISE:
        return False
    if upper in _INTEGRALE_TOKENS:
        return False
    if upper in _HS_TOKENS:
        return False
    if _YEAR_RE.match(s):
        return False
    if _TOME_RE.match(s) or _TOME_RANGE_RE.match(s):
        return False
    if _KBPS_RE.match(s) or _KHZ_RE.match(s):
        return False
    return True


def _classify_tokens(
    tokens: list[str], parsed: ParsedBookRelease,
) -> tuple[list[str], list[str]]:
    """Identifie les tokens techniques et les retire du flux titre.

    Modifie parsed in-place (year/language/file_format/series/etc.).
    Retourne (title_tokens, absorbed_tokens).
    """
    title_tokens: list[str] = []
    absorbed: list[str] = []
    skip_next = 0

    for i, tok in enumerate(tokens):
        if skip_next > 0:
            skip_next -= 1
            absorbed.append(tok)
            continue

        upper = tok.upper()

        # Year
        if not parsed.year and _YEAR_RE.match(tok):
            try:
                parsed.year = int(tok)
                absorbed.append(tok)
                continue
            except ValueError:
                pass

        # Format
        if upper in _FORMAT_TOKENS:
            fmt = _FORMAT_TOKENS[upper]
            if fmt and not parsed.file_format:
                parsed.file_format = fmt
            absorbed.append(tok)
            continue

        # Language : Sprint D.20 last-wins pour gérer les collisions
        # avec les prépositions françaises ("De", "Du", "La") qui ressemblent
        # à des codes 2-lettres (DE, DU, LA). Si on voit "DE" puis "FRENCH",
        # FRENCH gagne. Si on voit juste "FR" (NR12 Tomoji), FR gagne par défaut.
        if upper in _LANG_TOKENS:
            # On préfère un token explicite (>= 3 chars) sur un code 2-lettres
            # ambigu si on en avait déjà un.
            new_lang = _LANG_TOKENS[upper]
            if not parsed.language or len(upper) >= 3:
                parsed.language = new_lang
            absorbed.append(tok)
            continue

        # Audio quality
        if upper in _AUDIO_QUALITY_TOKENS:
            if not parsed.audio_quality:
                parsed.audio_quality = upper
            absorbed.append(tok)
            continue
        if _KBPS_RE.match(tok) or _KHZ_RE.match(tok):
            if not parsed.audio_quality:
                parsed.audio_quality = tok
            absorbed.append(tok)
            continue

        # HS prefix
        if upper in _HS_TOKENS:
            parsed.is_hors_serie = True
            absorbed.append(tok)
            continue

        # Integrale
        if upper in _INTEGRALE_TOKENS:
            parsed.is_integrale = True
            absorbed.append(tok)
            continue

        # Scene noise
        if upper in _SCENE_NOISE:
            absorbed.append(tok)
            continue

        # Sprint D.20 : "NoTag" / "NoTAG" / "NO-TAG" en token isole
        # (pas precede d'un tiret de team marker) -> on les absorbe ET on
        # set la team si elle est vide. Cas Tomoji : "...FR.NoTag" sans
        # tiret final, _extract_team n'aurait rien capture.
        if upper in _GENERIC_TEAMS:
            if not parsed.team:
                parsed.team = tok
            absorbed.append(tok)
            continue

        # Sprint D.20 : "Et Autres" / "And Others" pattern multi-tokens.
        # On detecte "Et" suivi de "Autres" (et variations) et absorbe les 2.
        if (upper in {"ET", "AND"} and i + 1 < len(tokens)
                and tokens[i + 1].upper() in {"AUTRES", "AL", "OTHERS"}):
            absorbed.append(tok)
            skip_next = 1  # absorber aussi le mot suivant
            continue

        # Tome range (T01-T06) : doit etre teste AVANT _TOME_RE
        m_range = _TOME_RANGE_RE.match(tok)
        if m_range:
            parsed.series_index_range = f"{int(m_range.group(1)):02d}-{int(m_range.group(2)):02d}"
            absorbed.append(tok)
            continue

        # Tome simple : T03
        m_tome = _TOME_RE.match(tok)
        if m_tome:
            try:
                parsed.series_index = float(m_tome.group(1))
                absorbed.append(tok)
                continue
            except ValueError:
                pass

        # Sprint D.20 : "Tome" / "Vol" / "T" tout seul suivi d'un nombre
        # (`Tome.1.Title` -> Tome puis 1 dans tokens separes). On absorbe
        # le marker ET le nombre suivant.
        if upper in {"TOME", "VOL", "VOLUME", "T"} and i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if _IMPLICIT_TOME_RE.match(next_tok):
                try:
                    val = int(next_tok)
                    if 1 <= val <= 9999 and not parsed.series_index:
                        parsed.series_index = float(val)
                        absorbed.append(tok)
                        skip_next = 1  # absorber aussi le nombre suivant
                        continue
                except ValueError:
                    pass

        # Tome implicite : un digit 1-99 ENTRE le titre serie et le titre tome
        # Ex : Knockemout.1.Ces.Choses -> "1" est tome implicite
        # Heuristique : si le token precedent est CAP et le suivant est CAP
        # ET on a deja capturé des mots de titre.
        if _IMPLICIT_TOME_RE.match(tok) and title_tokens:
            try:
                val = int(tok)
                if (1 <= val <= 99 and not parsed.series_index
                        and i + 1 < len(tokens)
                        and tokens[i + 1][:1].isalpha()
                        and tokens[i + 1][:1].isupper()):
                    parsed.series_index = float(val)
                    absorbed.append(tok)
                    continue
            except ValueError:
                pass

        # Sprint D.27 v0.5.0 : ID numerique 4+ digits qui n'est pas une
        # annee (deja gere plus haut par _YEAR_RE). Typiquement des IDs
        # tracker / digital / reference editoriale. On absorbe.
        # Cas Louis "Zep.Decoupe.En.Tranches.10354.PDF" : 10354 est un
        # ID tracker, pas une partie du titre.
        if _NUMERIC_ID_RE.match(tok):
            absorbed.append(tok)
            continue

        # Token de titre / auteur : on garde
        title_tokens.append(tok)

    return title_tokens, absorbed


def _extract_authors(
    title_tokens: list[str], parsed: ParsedBookRelease,
) -> list[str]:
    """Detecte les auteurs en debut de title_tokens.

    Heuristique :
    - On collecte les mots qui commencent par une majuscule en debut.
    - Un "auteur" = 1 a 3 mots consecutifs Cap.
    - On separe les auteurs par detection d'un "petit mot" (la/le/du/etc.)
      qui marque la transition titre, OU par un mot tres long (>15c) car
      les noms sont rares > 15c (sauf composes).
    - Pratiquement : on prend les 2-3 premiers mots cap si la suite est
      "scene-titre-pattern" (mots cap avec petits mots intercales).

    Retourne les title_tokens sans les auteurs detectes.
    """
    if not title_tokens:
        return title_tokens

    # Heuristique simple : on prend les N premiers mots CAP jusqu'a ce
    # qu'on trouve un petit mot (de/du/la/le/the) OU un mot tout-minuscule.
    # MAIS attention : si tous les tokens sont CAP (ex: "TINTIN.AU.PAYS.DES"),
    # on doit etre conservateur (probablement pas d'auteur).
    is_first_token_cap = title_tokens[0][:1].isalpha() and title_tokens[0][:1].isupper()
    if not is_first_token_cap:
        return title_tokens

    # Strategy : on prend des mots cap consecutifs jusqu'a 5 max, en se
    # limitant a "1-3 noms d'auteur" (typiquement 2-3 mots par auteur).
    # On s'arrete sur :
    # - un mot all-uppercase de plus de 3 lettres (acronyme/title)
    # - un petit mot (LE/LA/DU/DES/UN/UNE/THE/...)
    # - un mot avec digit
    # - un mot tres court (1-2 lettres, sauf initiales J./R./H./S.)

    small_words = {"LE", "LA", "LES", "DE", "DU", "DES", "UN", "UNE",
                   "L", "D", "DAN", "DANS",
                   "THE", "A", "AN", "OF", "AND",
                   "EL", "LO", "LOS", "LAS",
                   "AU", "AUX"}

    # Sprint D.20 fix NR5 : si le 1er token est un small_word (Le, La, Les,
    # Un, Une, The, ...), le release commence par un titre, pas par un auteur.
    # Ex : "Le.Massacre.De.Crac.H.Pierre.Bertin" -> le titre est en debut,
    # les auteurs sont au milieu/fin (non auto-detectables sans dictionnaire).
    if title_tokens[0].upper() in small_words:
        return title_tokens

    n_taken = 0
    for i, tok in enumerate(title_tokens[:6]):
        if not tok:
            break
        first = tok[:1]
        if not first.isalpha():
            break
        upper = tok.upper()
        if upper in small_words and i > 0:
            # On est entre dans le titre (ex: "Andrzej Sapkowski The Witcher" -> stop at "The")
            break
        if any(c.isdigit() for c in tok):
            break
        # All upper et plus de 3 lettres : probablement un titre (THE WITCHER)
        if tok.isupper() and len(tok) > 3 and not _looks_like_initial(tok):
            break
        # On accepte ce token comme partie auteur
        if first.isupper():
            n_taken += 1
        else:
            break
        # Limiter a 5 tokens en mode prudent (typiquement 2 auteurs)
        if n_taken >= 5:
            break

    # Sprint D.27 v0.5.0 : detection pseudonyme 1-mot (Zep, Hergé, Loisel,
    # Mœbius, Tintin, Goscinny, etc.). Avant on demandait >= 2 tokens cap
    # consecutifs, ce qui ratait les auteurs BD/manga 1-mot tres communs.
    #
    # Heuristique pour 1 token seul :
    # - Le 1er token est Cap court (3-15 chars typique pseudo)
    # - PAS un mot tout-uppercase de plus de 3 lettres (= title style genre TINTIN)
    # - Au moins 2 tokens restants apres (pour avoir un titre plausible)
    # - Le 2e token est aussi cap (sinon "Zep mange" en lower, pas un release)
    # - Cas Louis "Zep.Decoupe.En.Tranches.10354" : Zep + Decoupe (cap)
    if n_taken == 1 and len(title_tokens) >= 3:
        first_tok = title_tokens[0]
        second_tok = title_tokens[1]
        if (len(first_tok) <= 15
                and not (first_tok.isupper() and len(first_tok) > 3)
                and second_tok[:1].isupper()):
            # On accepte le 1er token seul comme pseudo auteur
            parsed.authors = [first_tok]
            return title_tokens[1:]

    # Sprint D.27 v0.5.0 : detection de pattern de titre francais.
    # Si on a n_taken >= 3 (chaine longue cap), on cherche dans la SUITE
    # une preposition francaise (En, De, Des, Du, La, Le, Les, Et, Au,
    # Aux, L', D'...). Si trouvee, c'est probablement un TITRE qui contient
    # cette preposition, pas une suite de noms d'auteur.
    #
    # On limite ce check a n_taken >= 3 pour preserver les co-auteurs
    # type "Lemire Sorrentino" (n_taken=2) qui ne contient pas de
    # preposition au milieu.
    #
    # Cas Louis "Zep.Decoupe.En.Tranches" : n_taken=4, "En" detectee a
    # position 2 -> reculer a 1 (auteur = Zep seul, titre = Decoupe En Tranches).
    french_prepositions = {
        "EN", "DE", "DU", "DES", "LA", "LE", "LES",
        "UN", "UNE", "AU", "AUX", "ET", "OU",
        "L", "D",  # apostrophes scene-style : L'Ile -> "L"
    }
    was_reculed_by_french_prep = False
    if n_taken >= 3:
        for j in range(1, min(n_taken, len(title_tokens))):
            if title_tokens[j].upper() in french_prepositions:
                # On recule a j-1 : la preposition fait partie d'un titre
                # francais qui inclut le mot juste AVANT (cas "X En Y" :
                # "X En Y" est le titre, l'auteur est ce qui precede X).
                # Cas Louis "Zep Decoupe En Tranches" :
                #   j=2 (position de "En") -> new_n_taken=1
                #   -> author = [Zep], title = [Decoupe, En, Tranches] ✓
                new_n_taken = max(1, j - 1)
                # Au minimum 1 token auteur, et au minimum 2 tokens de
                # titre restants pour considerer ce decoupage valide.
                if len(title_tokens) - new_n_taken >= 2:
                    n_taken = new_n_taken
                    was_reculed_by_french_prep = True
                    break

    # Apres recul french_prep, si on a 1 token seul, on bascule sur pseudo
    # 1-mot avec confiance (le recul a deja valide le contexte).
    # On ne touche PAS au cas n_taken=1 initial qui n'a pas pris le recul
    # (cas Tomoji "Elle.s.appelait..." ou 'Elle' est le titre, pas un auteur).
    if (was_reculed_by_french_prep and n_taken == 1
            and len(title_tokens) >= 3):
        first_tok = title_tokens[0]
        if len(first_tok) <= 15 and not (first_tok.isupper() and len(first_tok) > 3):
            parsed.authors = [first_tok]
            return title_tokens[1:]

    # Si on a pris 0 ou 1 token : pas assez pour un auteur (un nom seul
    # est ambigu : pourrait etre un titre 1-mot). On laisse tout en titre.
    if n_taken < 2:
        return title_tokens

    author_tokens = title_tokens[:n_taken]
    rest = title_tokens[n_taken:]

    # Si on a pris des mots et qu'il ne RESTE RIEN, c'etait un titre court,
    # pas un auteur. On annule.
    if not rest:
        return title_tokens

    # Reconstruction des auteurs : on split par "et" ou par detection
    # de pattern Prenom1.Nom1.Prenom2.Nom2
    parsed.authors = _split_authors(author_tokens)
    return rest


def _looks_like_initial(tok: str) -> bool:
    """True si tok ressemble a une initiale (J/R/H ou JR ou JRR)."""
    if len(tok) <= 3 and tok.isupper() and tok.isalpha():
        return True
    return False


def _split_authors(tokens: list[str]) -> list[str]:
    """Split des tokens auteurs en N auteurs distincts.

    Heuristique :
    - 2 tokens : 1 seul auteur "Prenom Nom"
    - 3 tokens : peut etre 1 auteur "Prenom Prenom2 Nom" ou 2 auteurs
      "Prenom1.Nom1.Prenom2" (pas terminé)
    - 4 tokens : probablement 2 auteurs "Prenom1.Nom1.Prenom2.Nom2"
    - 5+ tokens : 2-3 auteurs

    Pour simplifier et eviter les erreurs : on retourne le 1er groupe
    de 2 tokens comme auteur principal, le reste comme contributors.
    Convention : on retourne juste le 1er auteur (le plus important
    pour le naming). Le `meta.authors[0]` est utilise comme auteur
    principal pour la query.
    """
    if not tokens:
        return []
    if len(tokens) == 1:
        return [tokens[0]]
    if len(tokens) == 2:
        # 1 auteur : "Prenom Nom"
        return [" ".join(tokens)]
    # 3+ tokens : on suppose 2 auteurs, chacun 2 mots
    # ou 1 auteur 3 mots (J.R.R. Tolkien -> 4 tokens "J", "R", "R", "Tolkien")
    # Cas J.R.R. : si 3 premiers sont 1-2 lettres each, c'est un seul auteur
    if all(_looks_like_initial(t) for t in tokens[:-1]):
        return [" ".join(tokens)]
    # Sinon : on split en groupes de 2
    authors = []
    for i in range(0, len(tokens) - 1, 2):
        authors.append(" ".join(tokens[i:i + 2]))
    # Restant impair : ajouter au dernier
    if len(tokens) % 2 == 1:
        authors[-1] = authors[-1] + " " + tokens[-1]
    return authors


def _build_title(tokens: list[str], parsed: ParsedBookRelease) -> str:
    """Reconstruit un titre lisible depuis les tokens.

    - Joint avec espaces
    - Capitalize en gardant le mot tel quel si deja propre
    - Sprint D.28 v0.5.0 (cas Louis Tomoji) : reconstruit les apostrophes
      francaises. Les particules elididees (s/l/d/n/t/m/c/qu/j) qui sont
      isolees dans le scene name (.s. .l. .d. etc.) sont collees au mot
      suivant avec apostrophe + lowercase.
      Ex: ['Elle', 'S', 'Appelait', 'Tomoji'] -> "Elle s'Appelait Tomoji"
    """
    if not tokens:
        return ""

    cleaned: list[str] = []
    for tok in tokens:
        # Si tout en majuscules et len > 1 : on garde (acronyme/titre scene)
        if tok.isupper() and len(tok) > 1 and not tok.isdigit():
            cleaned.append(tok)
        elif tok.islower():
            cleaned.append(tok[:1].upper() + tok[1:])
        else:
            # Deja mixte ou capitalize : on garde
            cleaned.append(tok)

    # Sprint D.28 : reconstruire les apostrophes francaises elidees.
    # Pour chaque mot court particule (s/l/d/n/t/m/c/qu/j) suivi d'un
    # autre mot, on colle au mot suivant : "S Appelait" -> "s'Appelait".
    apostrophe_particles = {"s", "l", "d", "n", "t", "m", "c", "qu", "j"}
    result: list[str] = []
    i = 0
    while i < len(cleaned):
        word = cleaned[i]
        word_lower = word.lower()
        if (word_lower in apostrophe_particles
                and i + 1 < len(cleaned)
                and cleaned[i + 1][:1].isalpha()):
            # Coller la particule au mot suivant avec apostrophe
            # Ex : "S" + "Appelait" -> "s'Appelait"
            result.append(f"{word_lower}'{cleaned[i + 1]}")
            i += 2
        else:
            result.append(word)
            i += 1

    title = " ".join(result)
    # Compacter espaces multiples
    title = re.sub(r"\s+", " ", title).strip()
    return title
