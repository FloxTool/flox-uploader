"""Client API BnF (Bibliotheque nationale de France) — SRU XML.

Sprint D.2 v0.5.0 (PLAN-MULTICAT §7.4). Pivot FR pour les metadonnees livres.
La BnF expose son catalogue via le standard SRU (Search/Retrieve via URL) qui
retourne du XML Dublin Core. Gratuit, aucune cle requise (institution publique).

Endpoint : http://catalogue.bnf.fr/api/SRU

Documentation : https://api.bnf.fr/catalogue-general-de-la-bnf

Strategie :
- Recherche par ISBN-13 d'abord (le plus precis)
- Fallback recherche par titre + auteur si pas d'ISBN
- Cache atomique par ISBN dans data/.bnf_cache.json
- Cache aussi les misses (404 / pas trouve) pour eviter de re-frapper l'API

Champs SRU consommes (Dublin Core / DCMES / MARC) :
- dc:title          -> BookMetadata.title
- dc:creator        -> BookMetadata.authors (premier element)
- dc:contributor    -> BookMetadata.authors (suivants)
- dc:date           -> BookMetadata.publication_year (extract annee)
- dc:publisher      -> BookMetadata.publisher
- dc:language       -> BookMetadata.language (normalise ISO 639-1)
- dc:description    -> BookMetadata.description
- dc:subject        -> BookMetadata.genres
- dcterms:extent    -> BookMetadata.page_count

NOTE : la BnF peut renvoyer du XML namespace-prefixe variable selon les
records. On utilise des XPath tolerants (`{*}tagname`).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..http import http_get_with_retry as _default_http_get
from .book_metadata import BookMetadata, book_from_dict, book_to_dict
from ._cache import (
    cache_key_isbn, is_miss, load_cache, make_miss, save_cache,
)


# Endpoint officiel BnF SRU
BNF_SRU_URL = "http://catalogue.bnf.fr/api/SRU"

# Schema retour : Dublin Core simple (le plus stable pour notre usage)
_DEFAULT_PARAMS = {
    "version": "1.2",
    "operation": "searchRetrieve",
    "recordSchema": "dublincore",
    "maximumRecords": "1",
}


def lookup_bnf(
    isbn: str = "",
    title: str = "",
    author: str = "",
    cache_file: Path | None = None,
    http_get=None,
    trace: list | None = None,
    extra_titles: list[str] | None = None,
) -> BookMetadata | None:
    """Cherche un livre dans le catalogue BnF.

    Args:
        isbn : ISBN-13 ou ISBN-10. Si fourni, recherche directe par identifiant.
        title : utilise en fallback si pas d'ISBN.
        author : optionnel, refine la recherche par titre.
        cache_file : path du cache JSON. Si None, pas de cache.
        http_get : fonction HTTP injectable (pour les tests).

    Returns:
        BookMetadata avec source='bnf' si trouve, None sinon (cache aussi
        les misses). Ne plante jamais sur erreur reseau.
    """
    http = http_get or _default_http_get
    cache = load_cache(cache_file) if cache_file else {}

    # Sprint D.30 : trace diagnostique
    entry: dict | None = None
    if trace is not None:
        entry = {
            "provider": "bnf",
            "isbn": isbn,
            "title": title,
            "author": author,
            "queries": [],
            "outcome": "no_match",
        }
        trace.append(entry)

    def _set(name: str, **extra):
        if entry is not None:
            entry["outcome"] = name
            for k, v in extra.items():
                entry[k] = v

    # === Strategie 1 : ISBN prioritaire ===
    key = cache_key_isbn(isbn)
    if key:
        if key in cache:
            cached = cache[key]
            if is_miss(cached):
                _set("cached_miss")
                # Sprint D.17 v0.5.0 : fallback titre si ISBN MISS en cache.
                if title:
                    return _query_bnf_by_title(title, author, http=http, trace_entry=entry)
                return None
            _set("cached_hit", matched_id=cached.get("bnf_ark", ""))
            return book_from_dict(cached)

        meta = _query_bnf_by_isbn(key, http=http, trace_entry=entry)
        if cache_file is not None:
            cache[key] = book_to_dict(meta) if meta else make_miss()
            save_cache(cache_file, cache)
        if meta is not None:
            _set("matched_isbn", matched_id=meta.bnf_ark or "", matched_title=meta.title)
            return meta
        # Sprint D.17 : ISBN ne match pas a la BnF -> fallback titre.
        if title:
            return _query_bnf_by_title(title, author, http=http, trace_entry=entry)
        return None

    # === Strategie 2 : titre + auteur (pas de cache pour ce type de query) ===
    if title:
        result = _query_bnf_by_title(
            title, author, http=http, trace_entry=entry, extra_titles=extra_titles,
        )
        if result:
            return result
    return None


def _query_bnf_by_isbn(
    isbn: str, http,
    trace_entry: dict | None = None,
) -> BookMetadata | None:
    """Recherche BnF par ISBN. Retourne None si pas trouve ou erreur."""
    import time
    cql_query = f'bib.isbn adj "{isbn}"'
    params = {**_DEFAULT_PARAMS, "query": cql_query}
    t0 = time.monotonic()
    q_entry = {"q": cql_query, "phase": "isbn"}
    try:
        resp = http(BNF_SRU_URL, params=params)
    except Exception as e:
        q_entry.update({
            "error": f"{type(e).__name__}: {e}",
            "ms": int((time.monotonic() - t0) * 1000),
        })
        if trace_entry is not None:
            trace_entry["queries"].append(q_entry)
        print(f"[WARN] BnF lookup ISBN {isbn} : {type(e).__name__} {e}")
        return None
    q_entry.update({
        "http_status": getattr(resp, "status_code", 200),
        "ms": int((time.monotonic() - t0) * 1000),
    })
    if trace_entry is not None:
        trace_entry["queries"].append(q_entry)
    return _parse_first_record(resp.text)


def _query_bnf_by_title(
    title: str, author: str, http,
    trace_entry: dict | None = None,
    extra_titles: list[str] | None = None,
) -> BookMetadata | None:
    """Recherche BnF par titre + auteur optionnel.

    Sprint D.16 v0.5.0 : multi-strategies via _query_normalize. La BnF SRU
    (protocole CQL) est moins permissive que Google Books — on essaye
    plusieurs variantes du plus strict au plus large jusqu'a un match.

    Sprint D.33 v0.5.0 : `extra_titles` (scene parsed title etc.) sont
    aussi essayes comme variantes additionnelles pour augmenter les chances.
    """
    import time
    from ._query_normalize import build_query_variants, normalize_title_for_query
    variants = build_query_variants(title, author)
    if extra_titles:
        seen_norm = {normalize_title_for_query(title).lower()}
        for extra in extra_titles:
            norm = normalize_title_for_query(extra).lower()
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            variants.extend(build_query_variants(extra, author))
    if not variants:
        return None

    for variant in variants:
        # Pour BnF on garde toujours les quotes CQL (la syntaxe adj le requiert)
        parts = [f'bib.title adj "{variant.title}"']
        if variant.author:
            parts.append(f'bib.author adj "{variant.author}"')
        cql_query = " AND ".join(parts)
        params = {**_DEFAULT_PARAMS, "query": cql_query}
        t0 = time.monotonic()
        q_entry = {"q": cql_query, "phase": "title_author", "label": variant.label}
        try:
            resp = http(BNF_SRU_URL, params=params)
        except Exception as e:
            q_entry.update({
                "error": f"{type(e).__name__}: {e}",
                "ms": int((time.monotonic() - t0) * 1000),
            })
            if trace_entry is not None:
                trace_entry["queries"].append(q_entry)
            print(f"[WARN] BnF variant {variant.label!r} : {type(e).__name__} {e}")
            continue
        q_entry.update({
            "http_status": getattr(resp, "status_code", 200),
            "ms": int((time.monotonic() - t0) * 1000),
        })
        result = _parse_first_record(resp.text)
        if result is not None:
            q_entry["matched"] = True
            if trace_entry is not None:
                trace_entry["queries"].append(q_entry)
                trace_entry["outcome"] = "matched_title"
                trace_entry["matched_id"] = result.bnf_ark or ""
                trace_entry["matched_title"] = result.title
                trace_entry["matched_via_variant"] = variant.label
            return result
        q_entry["matched"] = False
        if trace_entry is not None:
            trace_entry["queries"].append(q_entry)
    return None


def _parse_first_record(xml_text: str) -> BookMetadata | None:
    """Parse la reponse SRU XML et extrait le premier record en BookMetadata.

    Retourne None si numberOfRecords=0 ou XML mal forme.
    """
    if not xml_text or not xml_text.strip():
        return None

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # Verifier numberOfRecords (tag SRU standard, namespace variable)
    num_elem = _find_first(root, "numberOfRecords")
    if num_elem is not None and num_elem.text:
        try:
            if int(num_elem.text.strip()) == 0:
                return None
        except ValueError:
            pass

    # Trouver le premier <record> -> <recordData> -> <oai_dc:dc> ou equivalent
    record = _find_first(root, "record")
    if record is None:
        return None
    record_data = _find_first(record, "recordData")
    # Le bloc Dublin Core est dans record_data, tag varie selon le serveur
    # (oai_dc:dc, dc, etc). On itere sur le contenu.
    dc_block = record_data if record_data is not None else record
    return _extract_dc_fields(dc_block)


def _find_first(parent: ET.Element, local_name: str) -> ET.Element | None:
    """Trouve le premier descendant avec ce local-name, peu importe le namespace."""
    for elem in parent.iter():
        # elem.tag peut etre "{ns}name" ou "name"
        if elem.tag == local_name or elem.tag.endswith("}" + local_name):
            return elem
    return None


def _findall_dc(parent: ET.Element, local_name: str) -> list[ET.Element]:
    """Trouve tous les descendants <dc:local_name>."""
    out: list[ET.Element] = []
    for elem in parent.iter():
        # On accepte {http://purl.org/dc/elements/1.1/}local_name ou {dc}local_name
        tag = elem.tag
        if tag.endswith("}" + local_name) and ("dc" in tag.lower() or "dublincore" in tag.lower() or "purl.org/dc/" in tag):
            out.append(elem)
    return out


def _extract_dc_fields(dc_block: ET.Element) -> BookMetadata:
    """Parse les champs Dublin Core dans un bloc et retourne un BookMetadata."""
    meta = BookMetadata()
    meta.sources.append("bnf")

    # Titre — Sprint D.33 : strip le suffix BnF " / Auteur ; traduit..."
    # qui apparait dans dc:title. Sans ca, le titre stocke est
    #   "Les vents furieux / Mercedes Lackey ; traduit de l'anglais..."
    # au lieu de juste "Les vents furieux".
    titles = _findall_dc(dc_block, "title")
    if titles and titles[0].text:
        raw_title = titles[0].text.strip()
        # Strip "/ ..." (auteurs/traducteurs ajoutes par la BnF)
        clean_title = re.sub(r"\s+/\s+.+$", "", raw_title).strip()
        # Strip ";" terminal au cas ou
        clean_title = clean_title.rstrip(" ;,.").strip()
        meta.title = clean_title or raw_title

    # Auteurs : dc:creator (1er) + dc:contributor (suivants)
    for creator in _findall_dc(dc_block, "creator"):
        if creator.text:
            name = _clean_author_name(creator.text)
            if name and name not in meta.authors:
                meta.authors.append(name)
    for contrib in _findall_dc(dc_block, "contributor"):
        if contrib.text:
            name = _clean_author_name(contrib.text)
            if name and name not in meta.authors:
                meta.authors.append(name)

    # Editeur
    publishers = _findall_dc(dc_block, "publisher")
    if publishers and publishers[0].text:
        meta.publisher = _clean_publisher(publishers[0].text)

    # Date -> annee
    dates = _findall_dc(dc_block, "date")
    if dates and dates[0].text:
        m = re.search(r"\b(1[89]|20)\d{2}\b", dates[0].text)
        if m:
            try:
                meta.publication_year = int(m.group())
            except ValueError:
                pass

    # Langue -> ISO 639-1 court
    languages = _findall_dc(dc_block, "language")
    if languages and languages[0].text:
        raw = languages[0].text.strip().lower()
        # BnF code souvent en 3 lettres : "fre", "eng", "spa"...
        mapping_3_to_2 = {
            "fre": "fr", "fra": "fr", "eng": "en", "spa": "es",
            "ger": "de", "deu": "de", "ita": "it", "jpn": "ja",
            "chi": "zh", "zho": "zh", "rus": "ru", "por": "pt",
        }
        if raw in mapping_3_to_2:
            meta.language = mapping_3_to_2[raw]
        elif len(raw) >= 2:
            meta.language = raw[:2]

    # Description : BnF retourne parfois du HTML (<div>, <b>, etc.) qu'on
    # nettoie pour avoir du plain text propre dans la fiche BBCode et la
    # page detail web (Sprint D.10 v0.5.0).
    descriptions = _findall_dc(dc_block, "description")
    if descriptions and descriptions[0].text:
        from ._html import strip_html
        meta.description = strip_html(descriptions[0].text)

    # Subjects -> genres
    for subj in _findall_dc(dc_block, "subject"):
        if subj.text:
            tag = subj.text.strip()
            if tag and tag not in meta.genres:
                meta.genres.append(tag)

    # ISBN (identifier scheme=ISBN ou texte contient ISBN)
    for ident in _findall_dc(dc_block, "identifier"):
        if ident.text and "isbn" in (ident.text + ident.get("scheme", "") + ident.get("xsi:type", "")).lower():
            clean = re.sub(r"[^\dXx]", "", ident.text.upper())
            if len(clean) == 13 and clean.isdigit() and not meta.isbn_13:
                meta.isbn_13 = clean
            elif len(clean) == 10 and not meta.isbn_10:
                meta.isbn_10 = clean

    # Sprint D.15 v0.5.0 : capturer l'ARK BnF pour generer un lien direct
    # vers la fiche catalogue (https://catalogue.bnf.fr/ark:/12148/{ark}).
    # Format typique : "ark:/12148/cb12345678p" trouve dans dc:identifier ou
    # n'importe quel descendant de l'XML.
    if not meta.bnf_ark:
        ark_regex = re.compile(r"ark:/12148/(cb[a-zA-Z0-9]+)")
        for elem in dc_block.iter():
            if elem.text:
                m = ark_regex.search(elem.text)
                if m:
                    meta.bnf_ark = m.group(1)
                    break
            # Verifier aussi les attributs (parfois l'ARK est dans rdf:about)
            for attr_val in (elem.attrib or {}).values():
                if attr_val and "ark:/12148/" in str(attr_val):
                    m = ark_regex.search(str(attr_val))
                    if m:
                        meta.bnf_ark = m.group(1)
                        break
            if meta.bnf_ark:
                break

    # Pages (dcterms:extent)
    for elem in dc_block.iter():
        if elem.tag.endswith("}extent") and elem.text:
            m = re.search(r"(\d+)\s*p", elem.text)
            if m:
                try:
                    meta.page_count = int(m.group(1))
                    break
                except ValueError:
                    pass

    # Si on n'a rien recupere, on retourne None implicitement (caller vide)
    if not meta.title and not meta.authors and not meta.isbn_13:
        return None  # type: ignore[return-value]
    return meta


_BNF_ROLE_ANNOTATIONS = (
    "Auteur du texte",
    "Auteur",
    "Illustrateur",
    "Illustratrice",
    "Traducteur",
    "Traductrice",
    "Préfacier",
    "Préfacière",
    "Editeur scientifique",
    "Éditeur scientifique",
    "Editrice scientifique",
    "Éditrice scientifique",
    "Adaptateur",
    "Adaptatrice",
    "Postfacier",
    "Annotateur",
    "Compilateur",
    "Photographe",
    "Cartographe",
    # Sprint D.33 v0.5.0 : roles BD/jeux video (LucasArts, etc.)
    "Developpeur",
    "Développeur",
    "Producteur",
    "Productrice",
    "Scenariste",
    "Scénariste",
    "Dessinateur",
    "Dessinatrice",
    "Coloriste",
    "Lettreur",
)


def _clean_author_name(raw: str) -> str:
    """Nettoie un nom d'auteur BnF (souvent format 'Nom, Prenom (dates)').

    Exemple : "Tolkien, John Ronald Reuel (1892-1973)" -> "John Ronald Reuel Tolkien"

    Sprint D.30 v0.5.0 (cas Louis Tomoji) : la BnF ajoute SOUVENT le ROLE
    de l'auteur dans le champ creator/contributor, ex:
    'Ogihara, Miwako. Auteur du texte' (sequence Nom, Prenom. Role).
    Sans retirer ce role, l'inversion comma donne le bouilli
    'Miwako. Auteur du texte Ogihara'. On strip donc les role annotations
    BnF d'abord, puis on inverse.
    """
    name = raw.strip()
    # Sprint D.33 v0.5.0 : retirer la parenthese de DATES (n'importe ou
    # dans le nom). Cas Mercedes Lackey :
    #   "Mercedes (1950-....). Auteur du texte Lackey"
    # On retire "(1950-....)" partout. On garde ".  Role" pour le strip
    # role suivant.
    name = re.sub(r"\s*\(\s*\d{4}\s*-[^)]*\)\s*", " ", name)
    name = re.sub(r"\s*\(\s*\d{4}\s*\)\s*", " ", name)  # juste (1950)
    # Sprint D.30+D.33 : retirer les annotations de role BnF.
    # 3 positions possibles :
    #   - fin de chaine "Foo, Bar. Auteur du texte" -> end-strip
    #   - milieu apres dot "Foo. Auteur du texte Bar" -> mid-dot-strip
    #   - milieu nu (dot retire avec dates) "Foo Auteur du texte Bar"
    #     -> mid-bare-strip
    for role in _BNF_ROLE_ANNOTATIONS:
        # Position 1 : ". Role" en fin
        name = re.sub(
            rf"\s*[\.,]\s*{re.escape(role)}\s*$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        # Position 2 : ". Role" au milieu (avant Lastname)
        name = re.sub(
            rf"\s*[\.,]\s+{re.escape(role)}\s+",
            " ",
            name,
            flags=re.IGNORECASE,
        )
        # Position 3 : "Role" nu au milieu (la dot a ete retiree par strip dates)
        name = re.sub(
            rf"\s+{re.escape(role)}\s+",
            " ",
            name,
            flags=re.IGNORECASE,
        )
    name = name.strip().rstrip(",.")
    # Compacter espaces multiples
    name = re.sub(r"\s+", " ", name)
    # Retirer parenthese restante en fin (au cas ou)
    name = re.sub(r"\s*\([^)]+\)\s*$", "", name)
    name = name.strip().rstrip(",.")
    # Inverser "Nom, Prenom" -> "Prenom Nom"
    if "," in name:
        parts = name.split(",", 1)
        if len(parts) == 2:
            last, first = parts[0].strip(), parts[1].strip()
            if first and last:
                return f"{first} {last}"
    return name.strip()


def _clean_publisher(raw: str) -> str:
    """Nettoie un nom d'editeur (retirer ville, dates entre crochets, etc.)."""
    pub = raw.strip()
    # Format BnF typique : "Paris : Gallimard , DL 2010"
    if ":" in pub:
        pub = pub.split(":", 1)[1]
    if "," in pub:
        pub = pub.split(",", 1)[0]
    return pub.strip()


# ============================================================
# Cache serialisation : factorise dans book_metadata.py
# (book_to_dict / book_from_dict reutilises par google_books.py et openlibrary.py)
# ============================================================
