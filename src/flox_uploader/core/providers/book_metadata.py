"""Structure de donnees pour les metadonnees livre.

Sprint D v0.5.0 (PLAN-MULTICAT §7.4). Source de verite unique pour toutes
les sources de metadonnees livre : extraction EPUB locale, BnF SRU, Google
Books, OpenLibrary, ComicVine, AniList. Tous les providers retournent ou
enrichissent un objet `BookMetadata`.

Strategie de remplissage :
1. Extraction locale du fichier (.epub, .cbz, .pdf si possible) -> remplit
   ce qui est dans le fichier (titre, auteur, ISBN parfois).
2. Lookup BnF par ISBN -> enrichit (auteur canonique, editeur, annee, pages).
3. Lookup Google Books par ISBN ou titre -> enrichit (resume FR, couverture).
4. Fallback OpenLibrary si BnF + Google ratent.

Chaque enrichissement *complete* les champs vides, mais ne remplace JAMAIS
un champ deja peuple (extraction locale = source autoritaire pour ce qui
est dans le fichier).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BookMetadata:
    """Metadonnees consolidees d'un livre / BD / Manga.

    Tous les champs sont optionnels et peuvent etre vides. Les providers
    remplissent ce qu'ils peuvent ; le release_name est genere meme avec
    des champs partiels (penalites confidence si trop incomplet).

    Attributs core :
        file_path : chemin du fichier source (ou dossier pour multi-fichier).
        file_format : extension lowercase sans le point ("epub", "cbz", "pdf"...).
        title : titre principal du livre.
        subtitle : sous-titre eventuel.
        authors : liste des auteurs (ordre = ordre du livre).
        isbn_13 : ISBN-13 sans tirets (13 chiffres).
        isbn_10 : ISBN-10 sans tirets (10 chiffres).
        publisher : editeur (Gallimard, Glenat, etc.).
        publication_year : annee de publication (int).
        language : code langue ISO 639-1 ("fr", "en", "ja"...).
        page_count : nombre de pages.

    Attributs serie (BD/Manga tomes) :
        series : nom de la serie ("Largo Winch", "One Piece", "Le Seigneur des Anneaux").
        series_index : numero du tome (int ou float pour les tomes hs ex "0.5").

    Attributs UI / fiche :
        description : resume du livre (peut etre long, plain text).
        cover_url : URL d'une image de couverture (BnF / Google Books / OpenLibrary).
        cover_local_path : chemin local d'une couverture extraite (pour les BD/.cbz).
        genres : tags genres ("Fantasy", "Romance", "Polar", "Aventure").

    Source tracking :
        sources : liste des providers qui ont contribue ("local_epub", "bnf",
                  "google_books", "openlibrary", "comicvine", "anilist").
    """

    # Source fichier (toujours rempli)
    file_path: Path | None = None
    file_format: str = ""

    # Identifiants livre
    title: str = ""
    subtitle: str = ""
    authors: list[str] = field(default_factory=list)
    isbn_13: str = ""
    isbn_10: str = ""

    # Publication
    publisher: str = ""
    publication_year: int = 0
    language: str = ""
    page_count: int = 0

    # Serie (BD/Manga)
    series: str = ""
    series_index: float = 0.0  # 0 = pas de numero, sinon int ou float
    # Sprint D.10 v0.5.0 : range tomes pour les multi-volumes / integrales
    # partielles. Format string "1-6" pour T01-T06 (decision Louis : pas
    # de token INTEGRALE car incertain). Vide = pas de range detecte.
    series_index_range: str = ""

    # UI / fiche
    description: str = ""
    cover_url: str = ""
    cover_local_path: Path | None = None
    genres: list[str] = field(default_factory=list)

    # Trace des providers qui ont enrichi
    sources: list[str] = field(default_factory=list)

    # Sprint D.15 v0.5.0 : identifiants externes pour generer des liens
    # DIRECTS vers les fiches (pas des liens de recherche).
    # - google_books_id : volumeId Google Books, ex "Nw2eEQAAQBAJ" ->
    #   https://books.google.com/books?id={volumeId}
    # - bnf_ark : identifiant ARK BnF, ex "cb12345678p" ->
    #   https://catalogue.bnf.fr/ark:/12148/{ark}
    # Vides si le provider n'a pas matche.
    google_books_id: str = ""
    bnf_ark: str = ""

    # Sprint D.19 v0.5.0 : previews uploadees sur host externe (imgbb).
    # URLs publiques https://i.ibb.co/... utilisables dans le BBCode tracker.
    # 4 previews random par defaut (cf. note Louis Q3).
    preview_urls: list[str] = field(default_factory=list)

    @property
    def isbn(self) -> str:
        """Retourne le meilleur ISBN dispo : isbn_13 prioritaire, sinon isbn_10."""
        return self.isbn_13 or self.isbn_10

    @property
    def primary_author(self) -> str:
        """Premier auteur de la liste, ou vide si pas d'auteur."""
        return self.authors[0] if self.authors else ""

    def has_essential_fields(self) -> bool:
        """Vrai si on a au moins titre + auteur (= naming possible)."""
        return bool(self.title and self.authors)

    def merge_from(self, other: "BookMetadata", source_name: str = "") -> None:
        """Enrichit self avec les champs de `other`, sans ecraser les non-vides.

        Convention : extraction locale = autoritaire. Donc on n'ecrase pas
        un champ deja rempli. Mais on COMPLETE :
        - Champs strings vides : remplit avec `other.<field>`
        - Listes vides : remplit avec `other.<field>`
        - Nombres = 0 : remplit avec `other.<field>` si > 0
        - sources : append `source_name` si fourni et non-deja-present

        Args:
            other : BookMetadata source d'enrichissement.
            source_name : libelle du provider ("bnf", "google_books", ...).
        """
        # Strings : on remplit si vide
        for str_field in ("title", "subtitle", "publisher", "language",
                          "description", "cover_url", "isbn_13", "isbn_10",
                          "series", "series_index_range", "file_format",
                          "google_books_id", "bnf_ark"):
            if not getattr(self, str_field) and getattr(other, str_field):
                setattr(self, str_field, getattr(other, str_field))

        # Listes : on remplit si vide
        for list_field in ("authors", "genres", "preview_urls"):
            if not getattr(self, list_field) and getattr(other, list_field):
                setattr(self, list_field, list(getattr(other, list_field)))

        # Nombres : on remplit si 0
        for num_field in ("publication_year", "page_count"):
            if getattr(self, num_field) == 0 and getattr(other, num_field) > 0:
                setattr(self, num_field, getattr(other, num_field))
        if self.series_index == 0.0 and other.series_index > 0:
            self.series_index = other.series_index

        # Path : on remplit si None
        if self.file_path is None and other.file_path is not None:
            self.file_path = other.file_path
        if self.cover_local_path is None and other.cover_local_path is not None:
            self.cover_local_path = other.cover_local_path

        # Tracker la source
        if source_name and source_name not in self.sources:
            self.sources.append(source_name)


# ============================================================
# Serialisation cache (utilisee par bnf.py / google_books.py / openlibrary.py)
# ============================================================
# Pattern : BookMetadata.to_dict() pour la sauvegarde JSON du cache,
# book_from_dict(d) pour reconstruire. Plus simple qu'asdict() pour gerer
# Path (file_path / cover_local_path -> str -> Path), int safe, list copy.

def book_to_dict(meta: BookMetadata) -> dict:
    """Serialise un BookMetadata en dict JSON-able pour le cache."""
    return {
        "title": meta.title,
        "subtitle": meta.subtitle,
        "authors": list(meta.authors),
        "isbn_13": meta.isbn_13,
        "isbn_10": meta.isbn_10,
        "publisher": meta.publisher,
        "publication_year": meta.publication_year,
        "language": meta.language,
        "page_count": meta.page_count,
        "series": meta.series,
        "series_index": meta.series_index,
        # Sprint D.10 : range tomes pour les multi-volumes
        "series_index_range": meta.series_index_range,
        "description": meta.description,
        "cover_url": meta.cover_url,
        # Sprint D.14 fix : file_format DOIT etre serialise — sinon le
        # warning 'Format manquant' apparait alors qu'on a bien
        # l'extension du fichier source (cf. note Louis N-Log-1, N-Log-3).
        "file_format": meta.file_format,
        # Sprint D.15 : ids externes pour liens directs vers fiches.
        "google_books_id": meta.google_books_id,
        "bnf_ark": meta.bnf_ark,
        # Sprint D.19 : previews uploadees externe (imgbb).
        "preview_urls": list(meta.preview_urls),
        "genres": list(meta.genres),
        "sources": list(meta.sources),
        # Note : on ne cache PAS file_path (chemin local utilisateur) ni
        # cover_local_path (regenerable). Le cache est partage entre runs / users.
    }


def book_from_dict(d: dict) -> BookMetadata:
    """Reconstruit un BookMetadata depuis un dict cache. Tolerant aux types."""
    if not isinstance(d, dict):
        return BookMetadata()
    return BookMetadata(
        title=str(d.get("title", "") or ""),
        subtitle=str(d.get("subtitle", "") or ""),
        authors=[str(a) for a in (d.get("authors") or []) if a],
        isbn_13=str(d.get("isbn_13", "") or ""),
        isbn_10=str(d.get("isbn_10", "") or ""),
        publisher=str(d.get("publisher", "") or ""),
        publication_year=int(d.get("publication_year") or 0),
        language=str(d.get("language", "") or ""),
        page_count=int(d.get("page_count") or 0),
        series=str(d.get("series", "") or ""),
        series_index=float(d.get("series_index") or 0.0),
        series_index_range=str(d.get("series_index_range", "") or ""),
        description=str(d.get("description", "") or ""),
        cover_url=str(d.get("cover_url", "") or ""),
        # Sprint D.14 fix : file_format aussi rechargee depuis le cache.
        file_format=str(d.get("file_format", "") or ""),
        # Sprint D.15 : ids externes (liens directs fiches).
        google_books_id=str(d.get("google_books_id", "") or ""),
        bnf_ark=str(d.get("bnf_ark", "") or ""),
        # Sprint D.19 : previews imgbb (URLs externes).
        preview_urls=[str(u) for u in (d.get("preview_urls") or []) if u],
        genres=[str(g) for g in (d.get("genres") or []) if g],
        sources=[str(s) for s in (d.get("sources") or []) if s],
    )
