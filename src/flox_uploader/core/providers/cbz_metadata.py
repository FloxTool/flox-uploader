"""Extraction de metadonnees depuis un fichier .cbz / .cbr local (BD, comics, manga).

Sprint D.7 v0.5.0 (PLAN-MULTICAT §7.4). Les CBZ sont juste des ZIP d'images
JPG/PNG (1 image = 1 page). Les CBR sont des RAR ; on tente unrar si dispo
sinon on degrade gracieusement.

Aucune metadata standard n'est garantie. Les seuls signaux sont :
- Le nom du fichier (heuristique : "Auteur - Serie Tx - Titre.cbz")
- Un fichier ComicInfo.xml optionnel (format ComicRack, parfois present)
- La premiere image (cover) qu'on peut extraire pour la fiche

Ce qu'on extrait :
- file_format = "cbz" / "cbr"
- page_count = nombre d'images
- title + author + series + series_index depuis le nom de fichier
- cover_local_path = premiere image trouvee (extraite via extract_cbz_cover)
- title/author/serie depuis ComicInfo.xml si present
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .book_metadata import BookMetadata


# Extensions d'images considerees comme pages
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def extract_cbz_metadata(cbz_path: Path) -> BookMetadata:
    """Extrait les metadonnees d'un fichier .cbz.

    Strategie :
    1. Lit le ComicInfo.xml interne si present (norme ComicRack)
    2. Compte le nombre d'images = nombre de pages
    3. Parse le nom de fichier pour series/tome/title/author si pas dans XML

    Args:
        cbz_path : chemin du fichier .cbz (ou .cbr, voir extract_cbr_metadata).

    Returns:
        BookMetadata avec `sources=["local_cbz"]` si extraction reussie,
        sources=[] sinon. Ne plante jamais sur fichier corrompu.
    """
    meta = BookMetadata(
        file_path=cbz_path,
        file_format=cbz_path.suffix.lower().lstrip("."),
    )

    if not cbz_path.is_file():
        return meta

    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            names = zf.namelist()
            image_names = sorted([
                n for n in names
                if Path(n).suffix.lower() in _IMAGE_EXTS
                and not n.startswith("__MACOSX/")
            ])
            meta.page_count = len(image_names)

            # 1. ComicInfo.xml si present
            comicinfo_name = next(
                (n for n in names if n.lower().endswith("comicinfo.xml")),
                None,
            )
            if comicinfo_name:
                try:
                    xml_data = zf.read(comicinfo_name)
                    _parse_comicinfo_xml(xml_data, meta)
                except (KeyError, OSError, ET.ParseError) as e:
                    print(f"[WARN] CBZ ComicInfo.xml parse echec : {type(e).__name__} {e}")
    except (zipfile.BadZipFile, OSError) as e:
        print(f"[WARN] CBZ lecture echec ({cbz_path.name}) : {type(e).__name__} {e}")
        return meta

    # 2. Fallback : parser le nom de fichier si XML absent ou incomplet
    if not meta.title or not meta.authors or not meta.series:
        parsed = _parse_cbz_filename(cbz_path.stem)
        if not meta.title and parsed["title"]:
            meta.title = parsed["title"]
        if not meta.authors and parsed["author"]:
            meta.authors = [parsed["author"]]
        if not meta.series and parsed["series"]:
            meta.series = parsed["series"]
        if meta.series_index == 0.0 and parsed["volume"] > 0:
            meta.series_index = float(parsed["volume"])

    if meta.title or meta.authors or meta.series:
        meta.sources.append("local_cbz")

    return meta


def extract_cbr_metadata(cbr_path: Path) -> BookMetadata:
    """Extracteur CBR (RAR). Limite a parser du nom de fichier (pas d'unrar).

    Le format RAR est proprietaire. Sans unrar (binaire externe), on ne peut
    pas lire le contenu. On retourne donc juste les heuristiques du nom de
    fichier + file_format.
    """
    meta = BookMetadata(
        file_path=cbr_path,
        file_format="cbr",
    )
    if not cbr_path.is_file():
        return meta

    parsed = _parse_cbz_filename(cbr_path.stem)
    if parsed["title"]:
        meta.title = parsed["title"]
    if parsed["author"]:
        meta.authors = [parsed["author"]]
    if parsed["series"]:
        meta.series = parsed["series"]
    if parsed["volume"] > 0:
        meta.series_index = float(parsed["volume"])

    if meta.title or meta.authors or meta.series:
        meta.sources.append("local_cbr")
    return meta


# ============================================================
# ComicInfo.xml parser
# ============================================================

def _parse_comicinfo_xml(xml_data: bytes, meta: BookMetadata) -> None:
    """Parse un ComicInfo.xml (norme ComicRack) et remplit `meta` in-place.

    Reference schema : https://anansi-project.github.io/docs/comicinfo/intro

    Champs lus :
    - Title, Series, Number (tome), Volume
    - Writer / Penciller / Artist (regroupes en authors)
    - Publisher, Year, LanguageISO
    - Summary -> description
    - Genre -> genres
    - PageCount
    """
    root = ET.fromstring(xml_data)

    def _text(tag: str) -> str:
        elem = root.find(tag)
        return (elem.text or "").strip() if elem is not None and elem.text else ""

    title = _text("Title")
    if title:
        meta.title = title

    series = _text("Series")
    if series:
        meta.series = series

    number = _text("Number")
    if number:
        try:
            meta.series_index = float(number)
        except ValueError:
            pass

    # Auteurs : Writer prioritaire, puis Penciller, puis Artist.
    authors_set: list[str] = []
    for role in ("Writer", "Penciller", "Inker", "Artist"):
        val = _text(role)
        for name in re.split(r"[,;]", val):
            name = name.strip()
            if name and name not in authors_set:
                authors_set.append(name)
    if authors_set:
        meta.authors = authors_set

    publisher = _text("Publisher")
    if publisher:
        meta.publisher = publisher

    year = _text("Year")
    if year:
        try:
            meta.publication_year = int(year)
        except ValueError:
            pass

    lang = _text("LanguageISO")
    if lang:
        meta.language = lang.lower()[:2]

    summary = _text("Summary")
    if summary:
        # Sprint D.22 : nettoyage HTML eventuel (ComicInfo.xml peut contenir
        # du HTML dans le Summary).
        from ._html import strip_html
        meta.description = strip_html(summary)

    page_count = _text("PageCount")
    if page_count:
        try:
            meta.page_count = int(page_count)
        except ValueError:
            pass

    genres = _text("Genre")
    if genres:
        for g in re.split(r"[,;]", genres):
            g = g.strip()
            if g and g not in meta.genres:
                meta.genres.append(g)


# ============================================================
# Parser du nom de fichier CBZ/CBR
# ============================================================

# Patterns frequents :
# - "Largo Winch - 01 - L'Heritier.cbz"
# - "Tintin T07 - L'Ile Noire.cbz"
# - "[Hergé] Tintin T07 L'Ile Noire.cbz"
# - "One Piece - 042.cbz"
# - "Asterix.T01.Asterix.le.Gaulois.cbz"
_VOLUME_PATTERNS = [
    re.compile(r"[\s.\-_]T0*(\d{1,4})(?:[\s.\-_]|$)", re.IGNORECASE),
    re.compile(r"[\s.\-_]Tome\s*0*(\d{1,4})(?:[\s.\-_]|$)", re.IGNORECASE),
    re.compile(r"[\s.\-_]Vol\.?\s*0*(\d{1,4})(?:[\s.\-_]|$)", re.IGNORECASE),
    re.compile(r"[\s.\-_-]0*(\d{1,4})(?:[\s.\-_]|$)"),  # "Largo Winch - 01"
]


_SCENE_TOKENS_HINT = frozenset({
    "FRENCH", "ENGLISH", "MULTI", "EPUB", "PDF", "CBZ", "CBR", "MOBI",
    "NOTAG", "VFF", "VFQ", "VFB", "VOSTFR", "VF", "VO",
})


def _looks_scene_style(stem: str) -> bool:
    """Detecte un nom de fichier scene-style : dots + tech tokens.

    Cas Louis Tomoji : 'Elle.s.appelait.Tomoji.FR.NoTag' -> True (dots +
    FR + NoTag). Sans ce check, le fallback "_parse_cbz_filename" assigne
    le stem brut comme title, polluant la query Google Books.
    """
    if "." not in stem:
        return False
    upper_tokens = {t.upper() for t in re.split(r"[._\-]", stem) if t}
    return bool(upper_tokens & _SCENE_TOKENS_HINT)


def _parse_cbz_filename(stem: str) -> dict:
    """Parse un nom de fichier CBZ/CBR pour extraire title/series/volume/author.

    Retourne un dict {title, series, volume, author} (vides si non-detectes).
    Conservateur : retourne le minimum sur, et le caller decide quoi faire.

    Sprint D.30 v0.5.0 : si le stem est manifestement scene-style (dots +
    tokens techniques FR/NoTag/etc.), on retourne TOUT vide pour laisser
    le scene parser (BookNamingStrategy) faire le boulot proprement.
    Evite de stocker 'Elle.s.appelait.Tomoji.FR.NoTag' comme title.
    """
    result = {"title": "", "series": "", "volume": 0, "author": ""}

    # Sprint D.30 : skip si scene-style (laisse le scene parser gerer)
    if _looks_scene_style(stem):
        return result

    # Normaliser separateurs (underscore -> espace, garder dots pour T1.5)
    clean = stem.replace("_", " ").strip()
    # Retirer annee finale (1234) ou [Annee]
    clean = re.sub(r"\s*\(\s*(?:19|20)\d{2}\s*\)\s*$", "", clean)

    # 1. Extraire auteur entre crochets [Auteur] Titre
    bracket_match = re.match(r"^\[([^\]]+)\]\s*(.+)$", clean)
    if bracket_match:
        result["author"] = bracket_match.group(1).strip()
        clean = bracket_match.group(2).strip()

    # 2. Detecter tome
    for pattern in _VOLUME_PATTERNS:
        m = pattern.search(clean)
        if m:
            try:
                vol = int(m.group(1))
                # Anti-faux-positif : un nombre > 9999 est probable un id, pas un tome
                if 1 <= vol <= 9999:
                    result["volume"] = vol
                    # Split sur le tome pour separer serie et titre du tome
                    before = clean[:m.start()].strip(" .-_")
                    after = clean[m.end():].strip(" .-_")
                    if before:
                        result["series"] = before
                    if after:
                        result["title"] = after
                    break
            except ValueError:
                pass

    # 3. Pas de tome detecte : le tout est le titre (ou serie si on a deja un auteur)
    if not result["volume"]:
        if " - " in clean:
            parts = [p.strip() for p in clean.split(" - ", 1)]
            if len(parts) == 2:
                # "Auteur - Titre" ou "Serie - Titre"
                # Sprint D.39 v0.5.0 (feedback Louis #17 LARGO.WINCH.INTEGRALE) :
                # si la partie gauche est "HS" / "Hors-Serie" / "H.S.", c'est
                # un marqueur scene Hors-Serie, PAS un nom d'auteur. On le
                # garde dans le title et on traite comme "non-author" pattern.
                left_upper = parts[0].upper().replace(".", "").replace(" ", "")
                if left_upper in {"HS", "HORSSERIE", "HORSSÉRIE"}:
                    # Toute la chaine devient le titre
                    result["title"] = clean
                elif not result["author"]:
                    result["author"] = parts[0]
                    result["title"] = parts[1]
                else:
                    result["title"] = clean
        else:
            result["title"] = clean

    # Si on a une serie mais pas de titre (cas "Naruto T01"), on copie la
    # serie comme titre pour eviter title vide.
    if result["series"] and not result["title"]:
        result["title"] = result["series"]

    return result


# ============================================================
# Extraction de la couverture (premiere image du CBZ)
# ============================================================

def extract_cbz_cover(cbz_path: Path, output_path: Path) -> bool:
    """Extrait la premiere image d'un CBZ vers `output_path`.

    Args:
        cbz_path : path du CBZ source.
        output_path : path de sortie (extension de l'image source preservee).

    Returns:
        True si la cover a ete extraite, False sinon.
    """
    if not cbz_path.is_file():
        return False
    try:
        with zipfile.ZipFile(cbz_path, "r") as zf:
            image_names = sorted([
                n for n in zf.namelist()
                if Path(n).suffix.lower() in _IMAGE_EXTS
                and not n.startswith("__MACOSX/")
            ])
            if not image_names:
                return False
            # La 1re image triee alphabetiquement est generalement la cover
            # (convention 001.jpg, page001.jpg, cover.jpg, etc.).
            first = image_names[0]
            data = zf.read(first)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
            return True
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        print(f"[WARN] CBZ cover extraction echec : {type(e).__name__} {e}")
        return False
