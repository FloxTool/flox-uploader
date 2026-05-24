"""Extraction de metadonnees depuis un fichier .epub local.

Sprint D v0.5.0 — premier provider du pipeline Livre. Lit le `metadata.opf`
encapsule dans le ZIP du .epub (format OEBPS / EPUB 2 et 3) et extrait les
champs Dublin Core (dc:title, dc:creator, dc:identifier, dc:language, etc.).

C'est la source AUTORITAIRE pour ce qui est dans le fichier : ce que l'auteur
ou l'editeur a code dans son ebook. Les providers en ligne (BnF, Google Books,
OpenLibrary) viendront ENRICHIR (couverture, resume, editeur canonique) mais
ne devraient pas remplacer ces metadata locales.

Specifications EPUB :
- EPUB 2.0 : http://idpf.org/epub/20/spec/OPF_2.0.1_draft.htm
- EPUB 3.x : https://www.w3.org/TR/epub-33/

L'OPF est un fichier XML pointe depuis META-INF/container.xml a la racine du ZIP.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .book_metadata import BookMetadata


# Namespaces XML utilises dans l'OPF EPUB
_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def extract_epub_metadata(epub_path: Path) -> BookMetadata:
    """Extrait les metadonnees d'un fichier .epub.

    Retourne un `BookMetadata` au moins partiel (au pire avec juste file_path
    + file_format remplis). Ne plante jamais sur un .epub corrompu ou
    inaccessible : retourne le BookMetadata minimal.

    Args:
        epub_path : chemin du fichier .epub.

    Returns:
        BookMetadata avec `sources=["local_epub"]` si extraction reussie,
        sources=[] sinon.
    """
    meta = BookMetadata(
        file_path=epub_path,
        file_format="epub",
    )

    if not epub_path.is_file():
        return meta

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            opf_path = _find_opf_path(zf)
            if not opf_path:
                return meta
            opf_data = zf.read(opf_path)
    except (zipfile.BadZipFile, OSError, KeyError):
        return meta

    try:
        root = ET.fromstring(opf_data)
    except ET.ParseError:
        return meta

    # Le metadata block est sous <package>/<metadata>
    metadata_elem = root.find("opf:metadata", _NS)
    if metadata_elem is None:
        # Certains EPUB 2 utilisent le namespace par defaut sur <metadata>
        metadata_elem = root.find("{*}metadata")
        if metadata_elem is None:
            return meta

    _extract_dublin_core(metadata_elem, meta)
    _extract_series_info(metadata_elem, meta)

    if meta.title or meta.authors:
        meta.sources.append("local_epub")

    return meta


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    """Trouve le chemin du fichier OPF dans le ZIP.

    Le chemin est specifie dans META-INF/container.xml. Si absent, on tente
    un fallback en cherchant content.opf ou *.opf a la racine.

    Returns:
        Chemin relatif du fichier OPF, ou "" si introuvable.
    """
    try:
        container_data = zf.read("META-INF/container.xml")
    except KeyError:
        # Fallback : chercher un .opf a la racine
        for name in zf.namelist():
            if name.endswith(".opf"):
                return name
        return ""

    try:
        root = ET.fromstring(container_data)
    except ET.ParseError:
        return ""

    # container.xml : <rootfiles><rootfile full-path="OPS/content.opf" .../>
    for rootfile in root.iter():
        # Le tag est namespace-prefixed : {urn:oasis:...}rootfile
        if rootfile.tag.endswith("}rootfile"):
            full_path = rootfile.get("full-path")
            if full_path:
                return full_path
    return ""


def _extract_dublin_core(metadata_elem: ET.Element, meta: BookMetadata) -> None:
    """Extrait les champs Dublin Core standards (dc:title, dc:creator, etc.).

    Modifie `meta` in-place.
    """
    # Title
    title_elem = metadata_elem.find("dc:title", _NS)
    if title_elem is None:
        title_elem = metadata_elem.find("{*}title")
    if title_elem is not None and title_elem.text:
        meta.title = title_elem.text.strip()

    # Authors (peut y en avoir plusieurs : creator + contributor parfois)
    for creator_elem in metadata_elem.findall("dc:creator", _NS):
        if creator_elem.text:
            name = creator_elem.text.strip()
            if name and name not in meta.authors:
                meta.authors.append(name)
    if not meta.authors:
        # Fallback namespace
        for creator_elem in metadata_elem.findall("{*}creator"):
            if creator_elem.text:
                name = creator_elem.text.strip()
                if name and name not in meta.authors:
                    meta.authors.append(name)

    # Publisher
    pub_elem = metadata_elem.find("dc:publisher", _NS)
    if pub_elem is None:
        pub_elem = metadata_elem.find("{*}publisher")
    if pub_elem is not None and pub_elem.text:
        meta.publisher = pub_elem.text.strip()

    # Language (code ISO court ou long, on garde ce qu'on trouve)
    lang_elem = metadata_elem.find("dc:language", _NS)
    if lang_elem is None:
        lang_elem = metadata_elem.find("{*}language")
    if lang_elem is not None and lang_elem.text:
        # Normaliser : "fr-FR" -> "fr", "eng" -> "en" (basique)
        raw = lang_elem.text.strip().lower()
        if "-" in raw:
            raw = raw.split("-")[0]
        if raw == "eng":
            raw = "en"
        elif raw == "fre" or raw == "fra":
            raw = "fr"
        elif raw == "jpn":
            raw = "ja"
        meta.language = raw[:2] if len(raw) >= 2 else raw

    # Publication date -> annee
    date_elem = metadata_elem.find("dc:date", _NS)
    if date_elem is None:
        date_elem = metadata_elem.find("{*}date")
    if date_elem is not None and date_elem.text:
        # Format ISO ou annee seule
        match = re.search(r"\b(19|20)\d{2}\b", date_elem.text)
        if match:
            try:
                meta.publication_year = int(match.group())
            except ValueError:
                pass

    # ISBN (dc:identifier avec scheme="ISBN" ou opf:scheme="ISBN")
    for ident_elem in metadata_elem.findall("dc:identifier", _NS):
        _extract_isbn_from_identifier(ident_elem, meta)
    if not meta.isbn_13 and not meta.isbn_10:
        for ident_elem in metadata_elem.findall("{*}identifier"):
            _extract_isbn_from_identifier(ident_elem, meta)

    # Description (resume)
    desc_elem = metadata_elem.find("dc:description", _NS)
    if desc_elem is None:
        desc_elem = metadata_elem.find("{*}description")
    if desc_elem is not None and desc_elem.text:
        meta.description = desc_elem.text.strip()

    # Subject = genre / tags
    for subj_elem in metadata_elem.findall("dc:subject", _NS):
        if subj_elem.text:
            tag = subj_elem.text.strip()
            if tag and tag not in meta.genres:
                meta.genres.append(tag)


def _extract_isbn_from_identifier(ident_elem: ET.Element, meta: BookMetadata) -> None:
    """Extrait un ISBN-10/13 depuis un element <dc:identifier>.

    L'attribut `scheme` (ou `opf:scheme`) indique le type. On accepte aussi
    les ISBN inferes par regex dans le texte (cas urn:isbn:...).
    """
    if ident_elem.text is None:
        return
    text = ident_elem.text.strip()

    # Recupere le scheme via different namespaces possibles
    scheme = (
        ident_elem.get("scheme")
        or ident_elem.get("{http://www.idpf.org/2007/opf}scheme")
        or ""
    ).strip().upper()

    # Nettoyer le texte : retirer urn:isbn:, isbn:, tirets, espaces
    clean = re.sub(r"^(urn:)?isbn[:-]?", "", text, flags=re.IGNORECASE)
    clean = re.sub(r"[^\d Xx]", "", clean).replace(" ", "")

    is_isbn = scheme == "ISBN" or "isbn" in text.lower()
    if not is_isbn:
        return

    if len(clean) == 13 and clean.isdigit() and not meta.isbn_13:
        meta.isbn_13 = clean
    elif len(clean) == 10 and (clean[:-1].isdigit() and (clean[-1].isdigit() or clean[-1] in "Xx")) and not meta.isbn_10:
        meta.isbn_10 = clean.upper()


def _extract_series_info(metadata_elem: ET.Element, meta: BookMetadata) -> None:
    """Extrait les infos de serie (Calibre extension EPUB).

    Calibre stocke la serie via <meta name="calibre:series" content="..."/> +
    <meta name="calibre:series_index" content="X"/>. C'est une extension non-
    standard mais ultra repandue. EPUB 3 a aussi <meta property="belongs-to-collection">.
    """
    for meta_elem in metadata_elem.iter():
        if not meta_elem.tag.endswith("}meta") and meta_elem.tag != "meta":
            continue
        name = meta_elem.get("name", "")
        content = meta_elem.get("content", "")
        if name == "calibre:series" and content and not meta.series:
            meta.series = content.strip()
        elif name == "calibre:series_index" and content and meta.series_index == 0:
            try:
                meta.series_index = float(content)
            except ValueError:
                pass
