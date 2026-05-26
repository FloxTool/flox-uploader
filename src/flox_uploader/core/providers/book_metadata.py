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

    # Sprint D.37 v0.5.0 : flag explicite "aucune correspondance fiable
    # trouvee". Setter quand TOUS les providers ratent ou retournent
    # wrong-volume. Le confidence score deduit ce flag pour deguerader le
    # score (au lieu de pretendre que c'est OK). UI affiche un badge
    # ⚠️ "Pas de correspondance fiable" sur le package.
    # Cas typiques : fanscans (One Piece chapitres), auto-publies non
    # indexes (Historica Cosmos), mauvais volume malgre fixes.
    no_canonical_match: bool = False

    # Sprint D.38 v0.5.0 (feedback Louis) : cover WEB (BnF/Google Books)
    # conservee separement pour permettre une comparaison visuelle dans
    # la page detail. La cover_url ci-dessus contient toujours la VRAIE
    # cover utilisee (locale prioritaire). Cette web_cover_url affiche
    # une vignette secondaire pour confirmer visuellement que la
    # correspondance trouvee est bien le bon livre.
    web_cover_url: str = ""

    @property
    def isbn(self) -> str:
        """Retourne le meilleur ISBN dispo : isbn_13 prioritaire, sinon isbn_10."""
        return self.isbn_13 or self.isbn_10

    def sanitize_cover_url(self) -> None:
        """Clear cover_url s'il pointe vers un placeholder / logo (Sprint D.31).

        Pattern detectes : 'logo-*', 'placeholder', 'no-image', 'default.*'.
        Cas Louis Tomoji : chasse-aux-livres met son LOGO comme og:image
        quand la couverture est absente. Sans ca, on stockait
        'logo-chasse-aux-livres-square.png' comme cover_url, recupere
        ensuite du cache meme apres fix du parser. Cette methode peut etre
        appelee a l'init OU apres book_from_dict (cache load) pour
        invalider les entries pourries.
        """
        if not self.cover_url:
            return
        url_lower = self.cover_url.lower()
        last_seg = url_lower.rsplit("/", 1)[-1] if "/" in url_lower else url_lower
        if (
            "/logo-" in url_lower
            or "/logo." in url_lower
            or last_seg.startswith("logo")
            or "placeholder" in url_lower
            or "no-image" in url_lower
            or last_seg.startswith("default.")
            or last_seg.startswith("default-")
        ):
            self.cover_url = ""

    @property
    def primary_author(self) -> str:
        """Premier auteur de la liste, ou vide si pas d'auteur."""
        return self.authors[0] if self.authors else ""

    def has_essential_fields(self) -> bool:
        """Vrai si on a au moins titre + auteur (= naming possible)."""
        return bool(self.title and self.authors)

    def merge_from(
        self, other: "BookMetadata", source_name: str = "",
        *, authoritative: bool = False,
    ) -> None:
        """Enrichit self avec les champs de `other`, sans ecraser les non-vides.

        Convention : extraction locale = autoritaire. Donc on n'ecrase pas
        un champ deja rempli. Mais on COMPLETE :
        - Champs strings vides : remplit avec `other.<field>`
        - Listes vides : remplit avec `other.<field>`
        - Nombres = 0 : remplit avec `other.<field>` si > 0
        - sources : append `source_name` si fourni et non-deja-present

        Sprint D.31 v0.5.0 : parametre `authoritative=True` permet d'OVERRIDE
        les champs title/authors/publisher/publication_year/cover_url avec
        ceux de `other`. A utiliser SEULEMENT quand `other` vient d'un match
        haute-confiance (ISBN match BnF/Google, ou title+author+year_match).
        Cas Louis Petit Fute : local EPUB title 'POITIERS 2026 (avec photos)'
        doit etre ecrase par le canonique Google 'Guide Poitiers 2026 Petit
        Fute Escapades dans la Vienne'.

        Args:
            other : BookMetadata source d'enrichissement.
            source_name : libelle du provider ("bnf", "google_books", ...).
            authoritative : si True, override title/authors/cover/etc.
        """
        # Sprint D.31 : champs override-ables en mode authoritative
        # Sprint D.38 : cover_url retiree de la liste (la cover locale a
        # priorite). Le web_cover est capture separement plus bas pour
        # affichage comparaison.
        _AUTHORITATIVE_FIELDS = (
            "title", "subtitle", "publisher", "language",
            "isbn_13", "isbn_10",
        )

        # Sprint D.38 v0.5.0 (feedback Louis) : capture web_cover_url AVANT
        # le merge. La cover_url locale (extraite du fichier) DOIT toujours
        # gagner pour la presentation. On garde la web cover dans un champ
        # separe pour la vignette de comparaison sur la page detail.
        other_cover = getattr(other, "cover_url", "")
        if other_cover and other_cover.startswith(("http://", "https://")):
            # Web cover BnF/Google -> stocker dans web_cover_url si vide
            if not self.web_cover_url:
                self.web_cover_url = other_cover

        # Strings : on remplit si vide, OU override si authoritative.
        # cover_url retiree : on ne remplace pas une cover deja presente
        # (qui est typiquement locale = prio).
        for str_field in ("title", "subtitle", "publisher", "language",
                          "description", "isbn_13", "isbn_10",
                          "series", "series_index_range", "file_format",
                          "google_books_id", "bnf_ark"):
            other_val = getattr(other, str_field)
            if not other_val:
                continue
            self_val = getattr(self, str_field)
            if not self_val:
                setattr(self, str_field, other_val)
            elif authoritative and str_field in _AUTHORITATIVE_FIELDS:
                setattr(self, str_field, other_val)
            # Sprint D.39 v0.5.0 (feedback Louis) : description courte
            # BnF (souvent juste code-barres "EAN 9782...") -> remplacer
            # par la description Google Books si plus longue. Cas Louis :
            # 8 packages avec description = 44 chars (code-barres BnF).
            # Heuristique : si self.description < 100 chars ET other a
            # une description >= 100 chars, on override.
            elif (
                str_field == "description"
                and len(self_val) < 100
                and len(other_val) >= 100
            ):
                setattr(self, str_field, other_val)

        # Sprint D.38 : cover_url avec strict prio local. On ne setter
        # cover_url depuis other QUE si self.cover_url est completement
        # vide (= aucune cover locale extraite). Sinon on garde local.
        if not self.cover_url and other_cover:
            self.cover_url = other_cover

        # Listes : remplit si vide, override authors si authoritative
        for list_field in ("authors", "genres", "preview_urls"):
            other_list = getattr(other, list_field)
            if not other_list:
                continue
            self_list = getattr(self, list_field)
            if not self_list:
                setattr(self, list_field, list(other_list))
            elif authoritative and list_field == "authors":
                setattr(self, list_field, list(other_list))

        # Nombres : on remplit si 0, override publication_year si authoritative
        for num_field in ("publication_year", "page_count"):
            other_val = getattr(other, num_field)
            if other_val <= 0:
                continue
            self_val = getattr(self, num_field)
            if self_val == 0:
                setattr(self, num_field, other_val)
            elif authoritative and num_field == "publication_year":
                setattr(self, num_field, other_val)
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
        # Sprint D.37 : flag no-canonical-match (penalite score + UI badge)
        "no_canonical_match": meta.no_canonical_match,
        # Sprint D.38 : cover web (BnF/Google) pour comparaison visuelle.
        "web_cover_url": meta.web_cover_url,
        # Note : on ne cache PAS file_path (chemin local utilisateur) ni
        # cover_local_path (regenerable). Le cache est partage entre runs / users.
    }


def book_from_dict(d: dict) -> BookMetadata:
    """Reconstruit un BookMetadata depuis un dict cache. Tolerant aux types.

    Sprint D.31 v0.5.0 : applique sanitize_cover_url() pour invalider les
    cover_url pourries (logos, placeholders) qui ont pu etre cachees avant
    le fix D.30. Les entries cache stale sont ainsi auto-nettoyees au load.
    """
    if not isinstance(d, dict):
        return BookMetadata()
    meta = BookMetadata(
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
        # Sprint D.37 : flag no-canonical (lecture cache)
        no_canonical_match=bool(d.get("no_canonical_match", False)),
        # Sprint D.38 : cover web (BnF/Google) pour comparaison.
        web_cover_url=str(d.get("web_cover_url", "") or ""),
    )
    # Sprint D.31 : auto-invalidation des cover_url pourries au load
    meta.sanitize_cover_url()
    return meta
