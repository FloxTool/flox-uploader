"""Extraction de metadonnees depuis un fichier .pdf local.

Sprint D.7 v0.5.0 (PLAN-MULTICAT §7.4). Apres l'extracteur EPUB (D.1), c'est
le 2e extracteur local. Les PDF embarquent souvent un dictionnaire d'info
standard (Author, Title, Subject, Producer, CreationDate) et parfois des
metadonnees XMP plus riches. On ne fait pas l'XMP pour rester simple :
pypdf retourne /Info de toute facon dans `reader.metadata`.

On essaie aussi d'extraire la premiere page comme couverture (image PNG
generee via le rendu interne pypdf si Pillow + pypdf-extras dispo, sinon
on laisse cover_local_path vide et c'est BnF/Google Books qui fournira).

Comportement :
- PDF chiffre / corrompu / pas de metadata : retourne BookMetadata minimal
  avec juste file_format='pdf' (jamais de plantage).
- Pas d'ISBN dans le /Info (jamais), donc le lookup BnF/Google par texte
  est crucial. C'est pour ca qu'on extrait title + author meme imparfaits.
- ISBN est parfois cache dans Title/Subject (regex sur les 13/10 chiffres).
"""
from __future__ import annotations

import re
from pathlib import Path

from .book_metadata import BookMetadata


# Regex ISBN-13 (978/979 prefix) et ISBN-10 dans des champs texte libres.
_ISBN13_RE = re.compile(r"\b(97[89])(\d{10})\b")
_ISBN10_RE = re.compile(r"\b(\d{9}[\dXx])\b")


def extract_pdf_metadata(pdf_path: Path) -> BookMetadata:
    """Extrait les metadonnees d'un fichier .pdf.

    Retourne un `BookMetadata` au moins partiel (file_format='pdf' garanti).
    Ne plante jamais sur un PDF corrompu ou chiffre : retourne le minimum.

    Args:
        pdf_path : chemin du fichier .pdf.

    Returns:
        BookMetadata avec `sources=["local_pdf"]` si extraction reussie,
        sources=[] sinon.
    """
    meta = BookMetadata(
        file_path=pdf_path,
        file_format="pdf",
    )

    if not pdf_path.is_file():
        return meta

    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        print("[WARN] pypdf non installe, extraction PDF skip.")
        return meta

    try:
        reader = PdfReader(str(pdf_path), strict=False)
    except (OSError, PdfReadError, Exception) as e:
        print(f"[WARN] PDF lecture echec ({pdf_path.name}) : {type(e).__name__} {e}")
        return meta

    # Nombre de pages : tres fiable, on l'extrait meme sans /Info.
    try:
        meta.page_count = len(reader.pages)
    except Exception:
        pass

    # /Info dictionary
    try:
        info = reader.metadata or {}
    except Exception:
        info = {}

    if info:
        # Title
        title = _clean_pdf_string(info.get("/Title"))
        if title and not _looks_like_filename(title):
            meta.title = title

        # Author
        author = _clean_pdf_string(info.get("/Author"))
        if author:
            # Certains PDF mettent plusieurs auteurs en un seul string ;
            # heuristique : split sur ", " ou " and " ou " ; ".
            for separator in (";", "&", " and "):
                if separator in author:
                    parts = [p.strip() for p in author.split(separator) if p.strip()]
                    meta.authors = parts
                    break
            else:
                # Pas de separateur : 1 seul auteur
                meta.authors = [author]

        # Subject : peut contenir ISBN ou description. On scanne pour ISBN.
        subject = _clean_pdf_string(info.get("/Subject"))
        if subject:
            # Si subject ressemble a une description (texte long) -> description
            if len(subject) > 50:
                # Sprint D.22 : nettoyage HTML eventuel (PDF /Subject peut
                # contenir du HTML dans certains cas rares).
                from ._html import strip_html
                meta.description = strip_html(subject)
            _extract_isbn_from_text(subject, meta)

        # Producer / Creator : on n'utilise pas (souvent juste le logiciel).
        # Mais on scanne les ISBN dans le Title aussi.
        if title:
            _extract_isbn_from_text(title, meta)

        # Keywords -> genres
        keywords = _clean_pdf_string(info.get("/Keywords"))
        if keywords:
            for kw in re.split(r"[,;]", keywords):
                kw = kw.strip()
                if kw and kw not in meta.genres:
                    meta.genres.append(kw)

    # Fallback titre/auteur depuis le nom de fichier si /Info vide.
    # Format courant : "Auteur - Titre.pdf" ou "Titre (Auteur).pdf"
    if not meta.title:
        meta.title, parsed_author = _parse_title_author_from_filename(pdf_path.stem)
        if parsed_author and not meta.authors:
            meta.authors = [parsed_author]

    if meta.title or meta.authors or meta.isbn_13 or meta.isbn_10:
        meta.sources.append("local_pdf")

    return meta


def _clean_pdf_string(value) -> str:
    """Nettoie un champ /Info PDF (peut etre str, IndirectObject, bytes)."""
    if value is None:
        return ""
    try:
        s = str(value).strip()
    except Exception:
        return ""
    # Filtrer les valeurs poubelle frequentes
    if not s or s.lower() in {"untitled", "no title", "unknown", "anonymous"}:
        return ""
    # Limite anti-pavé : si > 500 chars, c'est suspect (mais on tronque pas
    # ici, le caller decidera).
    return s


def _looks_like_filename(title: str) -> bool:
    """Heuristique : un titre qui ressemble a un chemin/filename est suspect.

    Beaucoup de PDF generes par scan ou logiciel mettent le path complet ou
    le hash dans /Title. On filtre.
    """
    if "\\" in title or "/" in title:
        return True
    if title.lower().endswith((".pdf", ".doc", ".docx", ".tex")):
        return True
    # Hash-like (32+ chars hex)
    if re.fullmatch(r"[a-fA-F0-9]{16,}", title):
        return True
    return False


def _extract_isbn_from_text(text: str, meta: BookMetadata) -> None:
    """Cherche un ISBN-13/ISBN-10 dans un texte libre et le remplit dans meta."""
    if meta.isbn_13:
        return
    # ISBN-13 prioritaire
    m13 = _ISBN13_RE.search(text)
    if m13:
        candidate = m13.group(1) + m13.group(2)
        if len(candidate) == 13 and candidate.isdigit():
            meta.isbn_13 = candidate
            return
    # Sinon ISBN-10
    if not meta.isbn_10:
        m10 = _ISBN10_RE.search(text)
        if m10:
            candidate = m10.group(1).upper()
            if len(candidate) == 10 and candidate[:-1].isdigit():
                meta.isbn_10 = candidate


# ============================================================
# Parsing nom de fichier (heuristiques)
# ============================================================

# Patterns courants dans les noms de fichier ebook :
# - "Auteur - Titre (Annee).pdf"
# - "Titre - Auteur.pdf"
# - "[Auteur] Titre.pdf"
# - "Auteur_Titre.pdf"
_FILENAME_AUTHOR_DASH_TITLE = re.compile(
    r"^(?P<author>[A-Z][A-Za-zÀ-ÿ' .-]{2,40})\s*-\s*(?P<title>.+?)$"
)
_FILENAME_BRACKETED_AUTHOR = re.compile(
    r"^\[(?P<author>[^\]]+)\]\s*(?P<title>.+?)$"
)


def _parse_title_author_from_filename(stem: str) -> tuple[str, str]:
    """Extrait titre + auteur d'un nom de fichier (sans extension).

    Heuristiques :
    - "Hergé - Tintin au Tibet" -> ("Tintin au Tibet", "Hergé")
    - "[Tolkien] Le Hobbit" -> ("Le Hobbit", "Tolkien")
    - "Le Hobbit" -> ("Le Hobbit", "")

    Retourne (title, author). Vides si impossible a parser.
    """
    # Nettoyer les annees / underscores
    clean = stem.replace("_", " ").strip()
    # Retirer (1234) en fin de stem (annees)
    clean = re.sub(r"\s*\(\s*(?:19|20)\d{2}\s*\)\s*$", "", clean)

    # 1. [Auteur] Titre
    m = _FILENAME_BRACKETED_AUTHOR.match(clean)
    if m:
        return m.group("title").strip(), m.group("author").strip()

    # 2. Auteur - Titre  (heuristique : auteur a 2-3 mots majoritairement en capitale)
    if " - " in clean:
        left, right = clean.split(" - ", 1)
        left = left.strip()
        right = right.strip()
        # Si gauche est court (~3 mots max) et capitalize -> probable auteur
        words = left.split()
        if 1 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            return right, left
        # Sinon, on suppose Titre - Auteur (cas inverse)
        words_r = right.split()
        if 1 <= len(words_r) <= 4 and all(w[0].isupper() for w in words_r if w):
            return left, right

    # 3. Fallback : tout est le titre
    return clean, ""


# ============================================================
# Extraction de la couverture (premiere page rendue en PNG)
# ============================================================

def extract_pdf_cover(pdf_path: Path, output_path: Path) -> bool:
    """Extrait la premiere page d'un PDF en image PNG/JPG.

    pypdf seul ne peut PAS rendre du PDF en image. Il faut pdf2image
    (poppler) ou PyMuPDF (fitz). Comme on ne veut pas ajouter de dep lourde,
    on tente PyMuPDF en optionnel et on echoue silencieusement sinon.

    Args:
        pdf_path : path du PDF source.
        output_path : path de sortie (.jpg ou .png recommande).

    Returns:
        True si la cover a ete extraite, False sinon.
    """
    if not pdf_path.is_file():
        return False
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # PyMuPDF non installe : on n'extrait pas la cover.
        return False

    try:
        doc = fitz.open(str(pdf_path))
        if doc.page_count == 0:
            doc.close()
            return False
        page = doc.load_page(0)
        # Rendu en pixmap (image bitmap) avec resolution raisonnable (~600px wide)
        zoom = 2.0  # ~144 dpi
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(output_path))
        doc.close()
        return True
    except Exception as e:
        print(f"[WARN] PDF cover extraction echec : {type(e).__name__} {e}")
        return False
