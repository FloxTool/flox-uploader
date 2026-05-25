"""Parser le nom d'un dossier ebook pour extraire format / serie / tome / range / titre.

Sprint D.10 v0.5.0 (PLAN-MULTICAT §7.4). Beaucoup de torrents ebook sont
livres en DOSSIER : `[EPUB].Historica.Cosmos.Tome.13.Legendes.et.contes/`
contenant 1 ou plusieurs fichiers. Le nom du dossier porte les vrais
metadata (organisation utilisateur) alors que les fichiers internes ont
souvent des noms moins parlants.

Ce module extrait des HINTS depuis le nom de dossier :
- Format : `[EPUB]`, `[PDF]`, `[CBZ]`, `(EPUB)`, suffix `.EPUB-...`
- Série / Titre / Tome : `Naruto T01`, `Tintin - 07 - L'Ile Noire`,
  `Star Wars Rebellion T01-T06`, `Le Hobbit (1937)`
- Range tomes (intégrale partielle) : `T01-T06`, `T01 a T06`, `Tomes 1 a 6`,
  `T1.a.6`. Stocké comme `series_index_range = "1-6"` (string).
- Annee de publication : `(1999)`, `.1999.`, `2024 -`

Ces hints sont MERGEABLES avec l'extraction du fichier ebook interne via
`merge_book_dir_hints()` : le caller decide de la strategie (dossier
prioritaire, fichier prioritaire, ou merge avec warnings).

Convention : on retourne TOUJOURS un BookMetadata partiel + une liste
de `notes` pour traçabilité (utilisé par BookConfidenceStrategy pour
émettre des signaux 'extraction depuis nom de dossier').
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .book_metadata import BookMetadata


# ============================================================
# Constantes regex
# ============================================================

# Format en prefix/suffix : `[EPUB]`, `(EPUB)`, `.EPUB-`, `[EPUB +PDF]`.
# On accepte les formats Gemini autorises + ceux qu'on peut traduire.
_FORMAT_KEYWORDS = frozenset({
    "EPUB", "PDF", "CBZ", "CBR", "MOBI", "AZW3", "AZW", "DJVU", "M4B",
    "MP3", "TXT",
})

_FORMAT_BRACKET_RE = re.compile(
    r"[\[\(]\s*((?:EPUB|PDF|CBZ|CBR|MOBI|AZW3|AZW|DJVU|M4B|MP3|TXT)"
    r"(?:\s*[+,/&]\s*(?:EPUB|PDF|CBZ|CBR|MOBI|AZW3|AZW|DJVU|M4B|MP3|TXT))*)"
    r"\s*[\]\)]",
    re.IGNORECASE,
)

# Format en suffix scene : `.EPUB-NoTAG`, `.PDF-TEAM`, ou format en fin
# de string (`...EPUB$` ou `...EPUB-...`)
_FORMAT_SUFFIX_RE = re.compile(
    r"[\s._]((?:EPUB|PDF|CBZ|CBR|MOBI|AZW3|AZW|DJVU|M4B|MP3|TXT))"
    r"(?=[\s._-]|$)",
    re.IGNORECASE,
)

# Range tomes : T01-T06, T1-T6, T01.-.T06, Tomes 1 a 6, T1 a T6, T1.a.6
# Note Sprint D.10 : utiliser [\s._-] au lieu de \s* pour gerer les
# separateurs scene (dots, underscores).
_RANGE_PATTERNS = [
    # Forme courte : T01-T06 / T1-T6 (avec dots ou tirets autour)
    re.compile(
        r"\bT\.?0*(\d{1,4})[\s._]*[-–—][\s._]*T?\.?0*(\d{1,4})\b",
        re.IGNORECASE,
    ),
    # Forme longue : Tomes 1 a 6 / Tome 1 au 6
    re.compile(
        r"\bTomes?[\s._]+0*(\d{1,4})[\s._]+(?:a|à|au|to)[\s._]+0*(\d{1,4})\b",
        re.IGNORECASE,
    ),
    # Forme avec 'a' : T1.a.T6, T1.a.6
    re.compile(
        r"\bT\.?0*(\d{1,4})[\s._]+a[\s._]+T?\.?0*(\d{1,4})\b",
        re.IGNORECASE,
    ),
]

# Tome unique : T01, Tome 1, Vol.1, V1 — accepte dots/underscores comme
# separateurs (cas scene `Tome.13`, `T.07`, `Vol_3`).
_VOLUME_PATTERNS = [
    re.compile(r"\bT\.?0*(\d{1,4})\b(?![\s._]*[-–—][\s._]*T)", re.IGNORECASE),
    re.compile(r"\bTome[\s._]*0*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\bVol\.?[\s._]*0*(\d{1,4})\b", re.IGNORECASE),
]

# Annee : (1999), .1999., 1999 (en fin), entre 1900 et 2099
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Auteur entre crochets : `[Tolkien] Le Hobbit`
_BRACKETED_AUTHOR_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.+)$")


# ============================================================
# Dataclass de retour
# ============================================================

@dataclass
class DirParseResult:
    """Resultat du parsing d'un nom de dossier ebook.

    Tous les champs sont optionnels (vides si non-detectes).
    `notes` trace les decisions prises (pour debug + UI transparency).
    """
    format_hint: str = ""        # "EPUB" / "PDF" / "CBZ" / etc.
    multi_formats: list[str] = None  # ex: ["EPUB", "PDF"] si "[EPUB+PDF]"
    series: str = ""             # nom de la serie
    title: str = ""              # titre du livre (si different de serie)
    author: str = ""             # auteur si extrait depuis [Auteur] ...
    volume: int = 0              # tome unique (0 si pas detecte)
    volume_range: str = ""       # ex: "1-6" si T01-T06 detecte
    year: int = 0                # annee de publication
    notes: list[str] = None      # log des decisions

    def __post_init__(self):
        if self.multi_formats is None:
            self.multi_formats = []
        if self.notes is None:
            self.notes = []

    @property
    def has_any_data(self) -> bool:
        return bool(
            self.format_hint or self.series or self.title or self.author
            or self.volume or self.volume_range or self.year
        )


# ============================================================
# Parser principal
# ============================================================

def parse_book_dir_name(name: str) -> DirParseResult:
    """Parse un nom de dossier ebook et retourne les hints extraits.

    Args:
        name : nom du dossier (sans le path, sans extension).

    Returns:
        DirParseResult avec les champs detectes + notes de trace.

    Exemples :
        >>> r = parse_book_dir_name("[EPUB].Historica.Cosmos.Tome.13.Legendes.et.contes.de.Bretagne")
        >>> r.format_hint
        'EPUB'
        >>> r.volume
        13
        >>> r.title
        'Historica Cosmos Legendes et contes de Bretagne'

        >>> r = parse_book_dir_name("Star.Wars.Rebellion.T01-T06.FRENCH.EPUB-NoTAG")
        >>> r.volume_range
        '1-6'
        >>> r.format_hint
        'EPUB'

        >>> r = parse_book_dir_name("[Hergé] Tintin T07 - L'Ile Noire (1958)")
        >>> r.author
        'Hergé'
        >>> r.series
        'Tintin'
        >>> r.volume
        7
        >>> r.year
        1958
    """
    result = DirParseResult()
    if not name:
        return result

    # Normaliser : underscores -> espace ; on garde les dots pour l'instant
    clean = name.replace("_", " ").strip()

    # 1. Extraire format(s) entre crochets/parentheses
    fmt_match = _FORMAT_BRACKET_RE.search(clean)
    if fmt_match:
        raw_formats = fmt_match.group(1)
        formats = [
            f.strip().upper()
            for f in re.split(r"[+,/&]", raw_formats)
            if f.strip().upper() in _FORMAT_KEYWORDS
        ]
        if formats:
            result.multi_formats = formats
            result.format_hint = formats[0]
            result.notes.append(
                f"Format extrait du nom de dossier : [{', '.join(formats)}]"
            )
        # On retire le bracket pour la suite du parsing
        clean = (clean[:fmt_match.start()] + " " + clean[fmt_match.end():]).strip()
    else:
        # 1bis. Fallback : format en suffix scene (`.EPUB-TEAM` ou `...EPUB`).
        # On itere pour trouver le DERNIER match (le format est generalement
        # en fin de release_name pour les scene-style).
        all_matches = list(_FORMAT_SUFFIX_RE.finditer(clean))
        if all_matches:
            last = all_matches[-1]
            fmt = last.group(1).upper()
            if fmt in _FORMAT_KEYWORDS:
                result.format_hint = fmt
                result.multi_formats = [fmt]
                result.notes.append(
                    f"Format extrait du suffix : {fmt}"
                )
                # On retire ce token pour ne pas le confondre avec un titre
                clean = (clean[:last.start()] + " " + clean[last.end():]).strip(" ._-")

    # 2. Extraire auteur entre crochets [Auteur] Titre
    bracket_auth = _BRACKETED_AUTHOR_RE.match(clean)
    if bracket_auth:
        candidate_author = bracket_auth.group(1).strip()
        # Anti-faux-positif : si entre les crochets c'est un format deja
        # consomme, on ignore (cas geres au-dessus normalement).
        if candidate_author.upper() not in _FORMAT_KEYWORDS:
            result.author = candidate_author
            clean = bracket_auth.group(2).strip()
            result.notes.append(f"Auteur extrait : '{candidate_author}'")

    # 3. Extraire annee (avant le parsing des tomes pour eviter T1999)
    year_match = _YEAR_RE.search(clean)
    if year_match:
        try:
            year = int(year_match.group(1))
            if 1900 <= year <= 2099:
                result.year = year
                result.notes.append(f"Annee : {year}")
                # On NE retire PAS l'annee du clean : elle peut faire partie
                # du titre (ex: '1984' de Orwell). Mais on note la position
                # pour ne pas la prendre comme tome.
        except ValueError:
            pass

    # 4. Extraire RANGE de tomes (priorite sur tome unique)
    for pattern in _RANGE_PATTERNS:
        m = pattern.search(clean)
        if m:
            try:
                start = int(m.group(1))
                end = int(m.group(2))
                if 1 <= start <= 9999 and 1 <= end <= 9999 and start < end:
                    result.volume_range = f"{start}-{end}"
                    result.notes.append(
                        f"Range de tomes : T{start}-T{end} ({end - start + 1} tomes)"
                    )
                    # On split le clean autour du range pour extraire serie + titre
                    before = clean[:m.start()].strip(" .-_")
                    after = clean[m.end():].strip(" .-_")
                    if before:
                        result.series = _normalize_dots(before)
                    if after:
                        result.title = _normalize_dots(after)
                    return _finalize(result)
            except (ValueError, IndexError):
                continue

    # 5. Extraire tome unique
    for pattern in _VOLUME_PATTERNS:
        m = pattern.search(clean)
        if m:
            try:
                vol = int(m.group(1))
                if 1 <= vol <= 9999:
                    result.volume = vol
                    result.notes.append(f"Tome : T{vol}")
                    before = clean[:m.start()].strip(" .-_")
                    after = clean[m.end():].strip(" .-_")
                    if before:
                        result.series = _normalize_dots(before)
                    if after:
                        result.title = _normalize_dots(after)
                    return _finalize(result)
            except (ValueError, IndexError):
                continue

    # 6. Pas de tome detecte : tout le reste = titre
    if " - " in clean:
        # "Auteur - Titre" ou "Titre - sous-titre"
        parts = [p.strip() for p in clean.split(" - ", 1)]
        if len(parts) == 2 and not result.author:
            left, right = parts
            # Heuristique : si gauche court (~3 mots) et capitalize -> auteur
            words = left.split()
            if 1 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                result.author = left
                result.title = _normalize_dots(right)
                result.notes.append(f"Auteur (heuristique '-') : '{left}'")
            else:
                result.title = _normalize_dots(clean)
        else:
            result.title = _normalize_dots(clean)
    else:
        result.title = _normalize_dots(clean)

    return _finalize(result)


def _normalize_dots(s: str) -> str:
    """Convertit les points en espaces et nettoie les espaces multiples."""
    s = s.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def _finalize(result: DirParseResult) -> DirParseResult:
    """Post-traitement : nettoyer les champs serie/titre si needed."""
    # Si on a serie mais pas titre, c'est OK (Tome 13 sans sous-titre).
    # Si on a titre mais pas serie + un volume_range -> le titre est en
    # fait probablement la serie.
    if result.volume_range and result.title and not result.series:
        result.series = result.title
        result.title = ""
    return result


# ============================================================
# Merger dir hints + extraction fichier interne
# ============================================================

def merge_book_dir_hints(
    file_meta: BookMetadata,
    dir_hints: DirParseResult,
    *,
    dir_priority: bool = True,
) -> tuple[BookMetadata, list[str]]:
    """Merge un BookMetadata extrait du fichier avec les hints du nom de dossier.

    Sprint D.10 v0.5.0 — strategie "merge intelligent avec warning si conflit"
    (choisie par Louis).

    - On COMPLETE les champs vides du fichier avec ceux du dossier.
    - Si conflit (les deux ont une valeur differente) :
        - `dir_priority=True` (defaut) : le dossier gagne, warning emis.
        - `dir_priority=False` : le fichier gagne, warning emis.
    - Les hints volume_range / multi_formats du dossier sont TOUJOURS injectes
      car ils ne sont pas extractibles depuis 1 fichier ebook (concerne le
      multi-fichier).

    Args:
        file_meta : BookMetadata extrait du fichier ebook (peut etre vide).
        dir_hints : DirParseResult extrait du nom de dossier.
        dir_priority : si True, le dossier ecrase les conflits ; sinon
            c'est le fichier qui gagne.

    Returns:
        Tuple (BookMetadata enrichi, list[str] warnings de conflit).
    """
    warnings: list[str] = []

    if not dir_hints.has_any_data:
        return file_meta, warnings

    def _merge_field(field_name: str, dir_value, label: str):
        """Helper pour merge avec detection de conflit."""
        file_value = getattr(file_meta, field_name)
        if not dir_value:
            return
        if not file_value:
            # Le fichier n'a pas, le dossier oui -> on complete
            setattr(file_meta, field_name, dir_value)
            return
        # Les deux ont une valeur : conflit potentiel
        if _values_match(file_value, dir_value):
            return
        if dir_priority:
            warnings.append(
                f"Conflit {label} : dossier='{dir_value}' vs fichier='{file_value}' "
                f"-> dossier prioritaire."
            )
            setattr(file_meta, field_name, dir_value)
        else:
            warnings.append(
                f"Conflit {label} : dossier='{dir_value}' vs fichier='{file_value}' "
                f"-> fichier prioritaire."
            )

    # title (le titre du dossier peut etre la serie ou le titre)
    _merge_field("title", dir_hints.title, "titre")

    # series
    _merge_field("series", dir_hints.series, "serie")

    # author
    if dir_hints.author:
        if not file_meta.authors:
            file_meta.authors = [dir_hints.author]
        elif dir_hints.author.lower() not in [a.lower() for a in file_meta.authors]:
            # Conflit auteur
            if dir_priority:
                warnings.append(
                    f"Conflit auteur : dossier='{dir_hints.author}' vs "
                    f"fichier={file_meta.authors} -> dossier prioritaire."
                )
                file_meta.authors = [dir_hints.author]
            else:
                warnings.append(
                    f"Conflit auteur : dossier='{dir_hints.author}' vs "
                    f"fichier={file_meta.authors} -> fichier prioritaire."
                )

    # volume single
    if dir_hints.volume > 0:
        if file_meta.series_index == 0.0:
            file_meta.series_index = float(dir_hints.volume)
        elif int(file_meta.series_index) != dir_hints.volume:
            if dir_priority:
                warnings.append(
                    f"Conflit tome : dossier=T{dir_hints.volume} vs "
                    f"fichier=T{int(file_meta.series_index)} -> dossier prioritaire."
                )
                file_meta.series_index = float(dir_hints.volume)
            else:
                warnings.append(
                    f"Conflit tome : dossier=T{dir_hints.volume} vs "
                    f"fichier=T{int(file_meta.series_index)} -> fichier prioritaire."
                )

    # volume_range : TOUJOURS injecte depuis le dossier (le fichier individuel
    # ne peut pas savoir qu'il fait partie d'une intégrale).
    if dir_hints.volume_range and not getattr(file_meta, "series_index_range", ""):
        file_meta.series_index_range = dir_hints.volume_range

    # year
    if dir_hints.year > 0:
        if file_meta.publication_year == 0:
            file_meta.publication_year = dir_hints.year
        elif file_meta.publication_year != dir_hints.year:
            # Petite difference (réédition vs édition originale) -> WARN
            # mais on prefere le fichier (souvent date du EPUB exact).
            if abs(file_meta.publication_year - dir_hints.year) > 1:
                if dir_priority:
                    warnings.append(
                        f"Conflit annee : dossier={dir_hints.year} vs "
                        f"fichier={file_meta.publication_year} -> dossier prioritaire."
                    )
                    file_meta.publication_year = dir_hints.year
                else:
                    warnings.append(
                        f"Conflit annee : dossier={dir_hints.year} vs "
                        f"fichier={file_meta.publication_year}."
                    )

    # format_hint : TOUJOURS injecte si fichier vide
    if dir_hints.format_hint and not file_meta.file_format:
        file_meta.file_format = dir_hints.format_hint.lower()

    return file_meta, warnings


def _values_match(a, b) -> bool:
    """Compare 2 valeurs string en mode tolerant (case + dots + spaces)."""
    if a is None or b is None:
        return False
    sa = str(a).lower().replace(".", " ").replace("_", " ")
    sb = str(b).lower().replace(".", " ").replace("_", " ")
    sa = re.sub(r"\s+", " ", sa).strip()
    sb = re.sub(r"\s+", " ", sb).strip()
    return sa == sb


# ============================================================
# Find ebook file inside a directory
# ============================================================

_EBOOK_EXTENSIONS = frozenset({
    ".epub", ".pdf", ".cbz", ".cbr", ".mobi", ".azw3", ".azw",
    ".djvu", ".m4b", ".mp3",
})


def find_primary_ebook(folder: Path) -> Path | None:
    """Trouve le fichier ebook 'principal' dans un dossier.

    Sprint D.10 v0.5.0 — quand `torrent_target` est un dossier (cas
    frequent : `[EPUB].Historica.../book.epub`), il faut extraire les
    metadata du fichier ebook A L'INTERIEUR, pas juste du nom du dossier.

    Strategie :
    1. Scanne le dossier recursivement (sorted, deterministe).
    2. Filtre les fichiers caches (.DS_Store, etc.) et satellites
       (cover.jpg, .nfo, .opf, .url, .txt-cover).
    3. Retourne le PREMIER ebook avec extension dans `_EBOOK_EXTENSIONS`.
    4. Si plusieurs ebooks (intégrale multi-EPUB), retourne le 1er
       alphabetique (= souvent T01 ou Tome 1).
    5. Si aucun ebook : retourne None.

    Ne plante jamais sur erreur filesystem.
    """
    if not folder.is_dir():
        return None
    try:
        all_files = sorted([p for p in folder.rglob("*") if p.is_file()])
    except (OSError, PermissionError):
        return None

    for p in all_files:
        if p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in _EBOOK_EXTENSIONS:
            return p
    return None
