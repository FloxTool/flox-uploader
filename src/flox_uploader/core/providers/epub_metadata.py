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


def extract_epub_cover(epub_path: Path, output_path: Path) -> bool:
    """Extrait la couverture embarquee dans un EPUB vers `output_path`.

    Strategies essayees (par ordre de fiabilite) :
    1. <meta name="cover" content="<idref>"/> + <item id="idref" href="..."/>
       dans l'OPF.
    2. <item properties="cover-image" href="..."/> (EPUB 3).
    3. Fallback heuristique : 1re image trouvee dans le ZIP avec un nom qui
       contient "cover" ou "couv".

    Sprint D.7 v0.5.0 — pour augmenter le taux de cover (0% sur 33 tests).

    Args:
        epub_path : chemin du EPUB source.
        output_path : path de sortie pour la cover (.jpg/.png/.webp selon source).

    Returns:
        True si la cover a ete extraite, False sinon.
    """
    if not epub_path.is_file():
        return False
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            opf_path = _find_opf_path(zf)
            if not opf_path:
                return _fallback_cover_by_name(zf, output_path)
            try:
                opf_data = zf.read(opf_path)
            except (KeyError, OSError):
                return _fallback_cover_by_name(zf, output_path)
            try:
                opf_root = ET.fromstring(opf_data)
            except ET.ParseError:
                return _fallback_cover_by_name(zf, output_path)

            cover_href = _find_cover_href_in_opf(opf_root)
            if not cover_href:
                return _fallback_cover_by_name(zf, output_path)

            # Le href est relatif au dossier de l'OPF
            opf_dir = "/".join(opf_path.split("/")[:-1])
            full_href = f"{opf_dir}/{cover_href}" if opf_dir else cover_href
            full_href = full_href.lstrip("/")

            # Certains EPUB normalisent avec ./ ; on normalise
            full_href = full_href.replace("/./", "/")

            try:
                data = zf.read(full_href)
            except KeyError:
                # Fallback : chercher par basename
                basename = cover_href.split("/")[-1]
                candidates = [n for n in zf.namelist() if n.endswith(basename)]
                if not candidates:
                    return _fallback_cover_by_name(zf, output_path)
                data = zf.read(candidates[0])

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
            return True
    except (zipfile.BadZipFile, OSError) as e:
        print(f"[WARN] EPUB cover extraction echec : {type(e).__name__} {e}")
        return False


def _find_cover_href_in_opf(opf_root: ET.Element) -> str:
    """Cherche le href de la couverture dans l'OPF.

    Strategies :
    1. EPUB 2 : <meta name="cover" content="<idref>"/> + <item id="idref" href="..."/>
    2. EPUB 3 : <item properties="cover-image" href="..."/>
    """
    # Strategy 1 : meta name="cover" pointe vers un item id
    cover_id = ""
    metadata_elem = opf_root.find("opf:metadata", _NS)
    if metadata_elem is None:
        metadata_elem = opf_root.find("{*}metadata")
    if metadata_elem is not None:
        for meta_elem in metadata_elem.iter():
            if not meta_elem.tag.endswith("}meta") and meta_elem.tag != "meta":
                continue
            if meta_elem.get("name") == "cover":
                cover_id = meta_elem.get("content", "")
                break

    manifest = opf_root.find("opf:manifest", _NS)
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        return ""

    if cover_id:
        for item in manifest:
            if item.get("id") == cover_id:
                return item.get("href", "")

    # Strategy 2 : properties="cover-image" (EPUB 3)
    for item in manifest:
        props = (item.get("properties") or "").lower()
        if "cover-image" in props:
            return item.get("href", "")

    # Fallback : 1er item de manifest avec mediatype image et "cover" dans href
    for item in manifest:
        href = (item.get("href") or "").lower()
        media = (item.get("media-type") or "").lower()
        if media.startswith("image/") and "cover" in href:
            return item.get("href", "")

    return ""


def _fallback_cover_by_name(zf: zipfile.ZipFile, output_path: Path) -> bool:
    """Fallback : cherche dans le ZIP une image dont le nom contient 'cover' ou 'couv'."""
    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    candidates = []
    for name in zf.namelist():
        lower = name.lower()
        if any(lower.endswith(ext) for ext in image_exts):
            if "cover" in lower or "couv" in lower:
                candidates.append(name)
    if not candidates:
        return False
    try:
        data = zf.read(sorted(candidates)[0])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return True
    except (KeyError, OSError):
        return False


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
