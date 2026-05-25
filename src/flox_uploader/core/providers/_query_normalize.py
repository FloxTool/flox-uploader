"""Normalisation des queries titre/auteur pour les lookups BnF / Google Books.

Sprint D.16 v0.5.0 (notes Louis N-Rel-1 à N-Rel-6). Le probleme :
nos titres extraits viennent souvent du nom de fichier scene
(`Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF`)
et contiennent :
- des dots qui séparent les mots
- des tokens techniques (FRENCH, EPUB, PDF, MULTi, NoTag, FR, etc.)
- des marqueurs de tome (Tome.X, T01, Vol., etc.)
- l'annee de publication
- éventuellement plusieurs auteurs collés (Dominique.Auzias.Jean-Paul.Labourdette.et.autres)

Si on envoie ça brut a Google Books, on obtient soit aucun match soit
des résultats parasites. Ce module fournit des helpers pour produire
des queries propres :

- `normalize_title_for_query()` : nettoie le titre des tokens techniques
- `normalize_author_for_query()` : extrait le 1er auteur signifiant
- `build_query_variants()` : produit 3-4 variantes de query, du plus
  strict au plus permissif, à essayer dans l'ordre.

Architecture : le caller (google_books, bnf) appelle `build_query_variants`,
itère sur les variantes, et retourne le 1er match non vide.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ============================================================
# Constantes
# ============================================================

# Tokens techniques scene à retirer (en MAJUSCULES pour la comparaison
# case-insensitive). Ne JAMAIS retirer ces tokens s'ils font partie
# d'un mot plus long ("FRENCH" oui, "FRENCHIE" non).
_TECH_TOKENS = frozenset({
    # Formats fichier
    "EPUB", "PDF", "CBZ", "CBR", "MOBI", "AZW3", "AZW", "DJVU",
    "M4B", "MP3", "TXT",
    # Langues / variantes
    "FRENCH", "ENGLISH", "MULTI", "VF", "VOSTFR", "VFF", "VOF", "VFQ",
    "VOQ", "VFB", "VOB", "FR", "EN",
    # Marqueurs scene
    "NOTAG", "INTEGRALE",
    # Autres
    "HD", "REMUX", "X264", "X265",
})

# Tokens série/tome à retirer pour la recherche (on garde la série mais
# on retire le marqueur T01/Tome.X/Vol.).
_VOLUME_PATTERNS_FOR_REMOVAL = [
    re.compile(r"\bT\.?0*\d{1,4}\b", re.IGNORECASE),
    re.compile(r"\bTome\.?\s*0*\d{1,4}\b", re.IGNORECASE),
    re.compile(r"\bVol\.?\s*0*\d{1,4}\b", re.IGNORECASE),
    # Range tomes
    re.compile(r"\bT\.?0*\d{1,4}\s*[-.–—]\s*T?\.?0*\d{1,4}\b", re.IGNORECASE),
]

# Année 1900-2099
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Séparateurs "X et autres", "et al.", etc.
_MULTI_AUTHOR_SUFFIX_RE = re.compile(
    r"\b(?:et\s+(?:autres|al\.?)|&\s*autres)\s*$",
    re.IGNORECASE,
)


# ============================================================
# Dataclass de retour
# ============================================================

@dataclass
class QueryVariant:
    """Une variante de query à tenter, du plus strict au plus permissif."""
    title: str          # titre à inclure (peut être tronqué)
    author: str         # auteur à inclure (peut être vide)
    use_quotes: bool    # True = intitle:"..." inauthor:"..." ; False = sans quotes
    label: str          # description pour log/debug


# ============================================================
# Normalisation titre
# ============================================================

def normalize_title_for_query(raw: str) -> str:
    """Nettoie un titre pour le rendre cherchable sur Google Books / BnF.

    Étapes :
    1. Points et underscores -> espaces
    2. Retire les tokens techniques (FRENCH, EPUB, MULTi, NoTag, etc.)
    3. Retire les marqueurs de tome (Tome.X, T01, Vol., range T01-T06)
    4. Retire l'année 1900-2099
    5. Retire la ponctuation poubelle, garde les apostrophes utiles
    6. Compacte les espaces multiples
    7. Trim

    Exemples :
        "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag"
        -> "Lemire Sorrentino Le mythe de l Ossuaire Le passage"

        "Star Wars Rebellion T01-T06 FRENCH EPUB"
        -> "Star Wars Rebellion"

        "Tintin T07 - L'Ile Noire (1958)"
        -> "Tintin L'Ile Noire"
    """
    if not raw:
        return ""

    # Étape 0 (Sprint D.28) : reconstruction des apostrophes scene.
    # Pattern : ".X." où X est une particule française élidée
    # (s/l/d/n/t/m/c/qu/j) qui était initialement attachée par apostrophe
    # au mot suivant. Le format scene perd les apostrophes, on les
    # reconstruit pour que les queries Google Books / BnF matchent
    # les vrais titres.
    # Exemples :
    #   "Elle.s.appelait.Tomoji" -> "Elle s'appelait Tomoji"
    #   "Le.mythe.de.l.Ossuaire" -> "Le mythe de l'Ossuaire"
    #   "Aujourd.hui.je.t.aime" -> "Aujourd'hui je t'aime"
    #
    # On utilise re.sub avec lambda pour reconstruire " <particule>'"
    # qui colle au mot suivant. Important : on ne touche PAS les
    # particules 2-lettres (qu, sf) si elles sont précédées par un
    # tiret (vrais titres composés "Qu-on-savait", rare mais possible).
    _APOSTROPHE_PARTICLES_RE = re.compile(
        r"\.(s|l|d|n|t|m|c|qu|j)\.",
        re.IGNORECASE,
    )
    raw = _APOSTROPHE_PARTICLES_RE.sub(
        lambda m: f" {m.group(1).lower()}'",
        raw,
    )

    # Étape 1 : séparateurs scene -> espaces
    s = raw.replace(".", " ").replace("_", " ").replace("-", " ")

    # Étape 2 : retire les tokens techniques (mot complet uniquement)
    words = s.split()
    cleaned_words: list[str] = []
    for w in words:
        # On compare en uppercase mais on garde la casse originale
        if w.upper() in _TECH_TOKENS:
            continue
        cleaned_words.append(w)
    s = " ".join(cleaned_words)

    # Étape 3 : retire les marqueurs de tome / range
    for pattern in _VOLUME_PATTERNS_FOR_REMOVAL:
        s = pattern.sub(" ", s)

    # Étape 4 : retire l'année
    s = _YEAR_RE.sub(" ", s)

    # Étape 5 : ponctuation - on garde apostrophes (L'Ile, l'Ossuaire), tirets internes
    # On retire parentheses, crochets, accolades, virgules, points-virgules
    s = re.sub(r"[\(\)\[\]\{\},;:!?]", " ", s)

    # Étape 6 : compacter espaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ============================================================
# Normalisation auteur
# ============================================================

def normalize_author_for_query(raw: str) -> str:
    """Nettoie un nom d'auteur pour la recherche.

    - Points / underscores -> espaces
    - Si "et autres" / "et al." en fin -> garde seulement le 1er auteur
      (split sur le 2e nom de famille majuscule, heuristique)
    - Retire les marqueurs techniques au cas où

    Exemples :
        "Dominique Auzias, Jean-Paul Labourdette et autres"
        -> "Dominique Auzias"
        "J.R.R.Tolkien" -> "J.R.R. Tolkien" -> "J R R Tolkien" (Google le tolere)
        "[Tolkien]" -> "Tolkien"
    """
    if not raw:
        return ""
    s = raw.replace("_", " ").strip()
    # Retire les crochets
    s = re.sub(r"[\[\]]", "", s)
    # Retire le suffix "et autres" / "et al."
    s = _MULTI_AUTHOR_SUFFIX_RE.sub("", s).strip().rstrip(",").strip()
    # Points internes (J.R.R.Tolkien) -> espace (J R R Tolkien)
    # mais on preserve les espaces existants
    s = s.replace(".", " ")
    # Compacter espaces
    s = re.sub(r"\s+", " ", s).strip()

    # Si on a une virgule avec plusieurs auteurs : "Dominique Auzias, Jean-Paul Labourdette"
    # on garde le 1er (jusqu'à la 1re virgule).
    if "," in s:
        s = s.split(",", 1)[0].strip()

    return s


# ============================================================
# Construction des variantes de query
# ============================================================

def build_query_variants(
    title: str,
    author: str = "",
    max_title_words: int = 8,
) -> list[QueryVariant]:
    """Construit une liste de variantes de query à essayer dans l'ordre.

    Stratégies générées :
    1. Title complet normalisé + author complet, AVEC quotes (strict)
    2. Title complet normalisé + author complet, SANS quotes (souple)
    3. Title tronqué (4-5 premiers mots) + author, SANS quotes (large)
    4. Title premier-mot-significatif + author, SANS quotes (très large)
    5. Si pas d'auteur : title seul (3 variantes : strict, souple, tronqué)

    Args:
        title : titre brut (sera normalisé)
        author : auteur brut (sera normalisé, peut être vide)
        max_title_words : max de mots pour la variante "tronquée"

    Returns:
        Liste de QueryVariant à tenter dans l'ordre. Vide si title vide.
    """
    norm_title = normalize_title_for_query(title)
    norm_author = normalize_author_for_query(author)

    if not norm_title:
        return []

    variants: list[QueryVariant] = []

    if norm_author:
        # Avec auteur : 4 variantes du plus strict au plus large
        variants.append(QueryVariant(
            title=norm_title, author=norm_author,
            use_quotes=True,
            label=f"strict (avec quotes) : '{norm_title}' + '{norm_author}'",
        ))
        variants.append(QueryVariant(
            title=norm_title, author=norm_author,
            use_quotes=False,
            label=f"souple (sans quotes) : {norm_title} + {norm_author}",
        ))

        # Title tronqué
        words = norm_title.split()
        if len(words) > max_title_words:
            short_title = " ".join(words[:max_title_words])
            variants.append(QueryVariant(
                title=short_title, author=norm_author,
                use_quotes=False,
                label=f"titre tronqué ({max_title_words} mots) : {short_title} + {norm_author}",
            ))

        # Title juste les 2-3 premiers mots significatifs
        significant = [w for w in words if len(w) >= 3]
        if len(significant) >= 2:
            head_title = " ".join(significant[:3])
            if head_title != norm_title:
                variants.append(QueryVariant(
                    title=head_title, author=norm_author,
                    use_quotes=False,
                    label=f"titre court (3 mots significatifs) : {head_title} + {norm_author}",
                ))
    else:
        # Sans auteur : 3 variantes
        variants.append(QueryVariant(
            title=norm_title, author="",
            use_quotes=True,
            label=f"strict titre seul : '{norm_title}'",
        ))
        variants.append(QueryVariant(
            title=norm_title, author="",
            use_quotes=False,
            label=f"souple titre seul : {norm_title}",
        ))
        words = norm_title.split()
        if len(words) > max_title_words:
            short_title = " ".join(words[:max_title_words])
            variants.append(QueryVariant(
                title=short_title, author="",
                use_quotes=False,
                label=f"titre tronqué seul : {short_title}",
            ))

    # Dedupe par (title, author, use_quotes)
    seen: set[tuple[str, str, bool]] = set()
    unique: list[QueryVariant] = []
    for v in variants:
        key = (v.title.lower(), v.author.lower(), v.use_quotes)
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)
    return unique
