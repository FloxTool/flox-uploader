"""BookNamingStrategy : génère le release_name pour les categories Livre / BD / Manga.

Sprint D.3 v0.5.0 (PLAN-MULTICAT §5.5 + §7.4). Implémente le Protocol
NamingStrategy pour produire un release_name au format Gemini officiel :

    Auteur.Titre.Date.Langue.Format-TEAM

Exemples :
    J.R.R.Tolkien.Le.Seigneur.Des.Anneaux.1954.FRENCH.EPUB-Flox
    Herge.Tintin.T1.Au.Pays.Des.Soviets.1930.FRENCH.CBZ-Flox
    Stephen.King.La.Tour.Sombre.T3.Terres.Perdues.1991.FRENCH.PDF-Flox

Pour les séries (BD, Manga, sagas), on insère le numéro de tome après le
titre principal via le marqueur Tx (T1, T2, T3, …).

Stratégie d'enrichissement (D.1 + D.2) :
1. Extraction locale via `extract_epub_metadata` si .epub
2. Pour .cbz/.cbr/.pdf/.mobi/.azw3 : on n'a pas d'extracteur local — on
   se contente du file_format
3. Lookup en ligne via `lookup_book_metadata` (BnF + Google Books + OpenLibrary)
4. `merge_from()` préserve l'extraction locale (autoritaire) tout en
   complétant les champs vides depuis les providers

Sprint D.3 limite : la strategy est autonome et testable, mais l'intégration
pipeline (lever la Brique 1 die() et router via `get_strategy()`) viendra en
Sprint D.4 avec la compliance ebook. En l'état, BookNamingStrategy peut être
appelée par les tests mais le pipeline normal die() toujours sur un .epub.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._helpers import ascii_fold, collapse_dots
from ..providers.book_metadata import BookMetadata, book_to_dict
from ..providers.book_lookup import lookup_book_metadata
from ..providers.epub_metadata import extract_epub_metadata
from ..providers.pdf_metadata import extract_pdf_metadata
from ..providers.cbz_metadata import extract_cbz_metadata, extract_cbr_metadata
from ..providers.dir_parser import (
    find_primary_ebook, merge_book_dir_hints, parse_book_dir_name,
)

if TYPE_CHECKING:
    from ...trackers.base import Tracker
    from ..debug import Debug


# Mapping code ISO 639-1 -> token langue Gemini (charte ebook PDF).
# Source : PLAN-MULTICAT §7.4 + convention Gemini observée sur le tracker.
# Pour les langues non listées, on retombe sur le code ISO en majuscule.
_LANG_TOKENS: dict[str, str] = {
    "fr": "FRENCH",
    "en": "ENGLISH",
    "es": "SPANISH",
    "de": "GERMAN",
    "it": "ITALIAN",
    "pt": "PORTUGUESE",
    "ja": "JAPANESE",
    "zh": "CHINESE",
    "ru": "RUSSIAN",
    "ar": "ARABIC",
    "ko": "KOREAN",
    "nl": "DUTCH",
    "sv": "SWEDISH",
}


class BookNamingStrategy:
    """Strategy de naming pour Livres / BD / Manga (cat Gemini 12)."""

    name: str = "book"

    def build_release_name(
        self,
        video_path: Path,
        tracker: "Tracker",
        nfo_text: str,
        debug: "Debug",
        *,
        force_fr: str | None = None,
        tmdb_resolver: Any | None = None,
        media_info: Any | None = None,
        mediainfo_data: dict | None = None,
        # Sprint D.3 specific : permet d'injecter un orchestrateur custom pour
        # les tests (sans avoir a mocker http_get + cache_dir + env vars).
        _book_lookup=None,
    ) -> tuple[str, dict | None]:
        """Construit le release_name livre. Retourne `(release_name, None)`.

        `video_path` est en realite le path du fichier ebook (le naming est
        partage avec la signature NamingStrategy.build_release_name).

        Le `tmdb_context` retourne est `None` (TMDB n'est pas applicable aux
        livres). Le caller pipeline doit verifier ce cas.
        """
        # === 1. Extraction locale ===
        # Sprint D.7 v0.5.0 : route vers l'extracteur adapte au format.
        # Sprint D.10 v0.5.0 : si l'input est un DOSSIER, on cherche le
        # fichier ebook a l'interieur et on l'analyse, puis on parse le
        # nom du dossier pour extraire format/serie/tome/range, et on
        # MERGE intelligemment (decision Louis : merge avec warning si
        # conflit). Sans ca, les torrents type
        # `[EPUB].Series.Tome.13.Titre/` se retrouvaient avec book_metadata
        # vide car video_path = dossier (suffix = "").
        dir_warnings: list[str] = []
        dir_hints = None
        analysis_target = video_path

        if video_path.is_dir():
            # Trouver le fichier ebook principal dedans
            primary = find_primary_ebook(video_path)
            if primary is not None:
                analysis_target = primary
                debug.set("book_inner_file", str(primary.relative_to(video_path)))
            # Parser le nom du dossier (TOUJOURS, meme si pas de fichier interne)
            dir_hints = parse_book_dir_name(video_path.name)
            if dir_hints.notes:
                debug.set("dir_parse_notes", dir_hints.notes)

        # Sprint D.10 fix : un dossier nomme `[PDF].Foo.Titre.2024` a
        # `Path.suffix = ".2024"` car Path ignore is_dir(). On force ext=""
        # pour les dossiers afin de ne pas creer un file_format pourri.
        if analysis_target.is_dir():
            ext = ""
        else:
            ext = analysis_target.suffix.lower()

        if ext == ".epub":
            meta = extract_epub_metadata(analysis_target)
        elif ext == ".pdf":
            meta = extract_pdf_metadata(analysis_target)
        elif ext == ".cbz":
            meta = extract_cbz_metadata(analysis_target)
        elif ext == ".cbr":
            meta = extract_cbr_metadata(analysis_target)
        else:
            meta = BookMetadata(
                file_path=analysis_target,
                file_format=ext.lstrip(".") if ext else "",
            )

        # Sprint D.10 : merger les hints du nom de dossier avec l'extraction
        # du fichier interne. Le dossier prime sur les conflits (decision
        # Louis : c'est l'organisation utilisateur qui compte).
        if dir_hints is not None:
            meta, conflicts = merge_book_dir_hints(
                meta, dir_hints, dir_priority=True,
            )
            if conflicts:
                debug.set("dir_merge_conflicts", conflicts)
                dir_warnings.extend(conflicts)

        # === 1bis. Parsing scene name (Sprint D.20) ===
        # On parse le nom du fichier source via le parser scene livre.
        # Le parser identifie authors / title / year / format / team /
        # series + tome / lang en filtrant les tokens techniques (MP3,
        # 128kbps, FRENCH, NoTAG, [Digital-XXXX], etc.).
        # Le resultat enrichit le meta : on prend les valeurs scene
        # SEULEMENT si l'extraction local + dir_hints n'a rien trouve.
        # Convention : extraction locale > dir_hints > parser scene name.
        # Le parser scene est la SECURITE quand tout le reste rate.
        from ..providers._scene_parser import parse_book_filename
        source_name = video_path.name
        # Pour un fichier, on prend le stem (sans extension). Pour un dossier,
        # on prend le nom complet (qui peut avoir des "extensions" comme
        # [EPUB].Foo qui ne sont pas vraies extensions).
        if video_path.is_file():
            source_stem = video_path.stem
        else:
            source_stem = source_name
        scene_parsed = parse_book_filename(
            source_stem,
            file_format_hint=meta.file_format,
        )
        debug.set("scene_parsed", {
            "authors": scene_parsed.authors,
            "title": scene_parsed.title,
            "year": scene_parsed.year,
            "language": scene_parsed.language,
            "file_format": scene_parsed.file_format,
            "team": scene_parsed.team,
            "series_index": scene_parsed.series_index,
            "series_index_range": scene_parsed.series_index_range,
            "is_integrale": scene_parsed.is_integrale,
        })
        # Fallback intelligent : on remplit les champs meta vides depuis
        # le parser scene (ne SURCHARGE pas une extraction reussie).
        if not meta.title and scene_parsed.title:
            meta.title = scene_parsed.title
        if not meta.authors and scene_parsed.authors:
            meta.authors = list(scene_parsed.authors)
        if not meta.publication_year and scene_parsed.year:
            meta.publication_year = scene_parsed.year
        if not meta.language and scene_parsed.language:
            meta.language = scene_parsed.language
        if not meta.file_format and scene_parsed.file_format:
            meta.file_format = scene_parsed.file_format
        if meta.series_index == 0.0 and scene_parsed.series_index:
            meta.series_index = scene_parsed.series_index
        if not meta.series_index_range and scene_parsed.series_index_range:
            meta.series_index_range = scene_parsed.series_index_range

        # === 2. Enrichissement online (BnF + Google Books + OpenLibrary) ===
        # Sprint D.29 v0.5.0 : si le scene parser a un titre DIFFERENT du
        # titre meta (typiquement metadata EPUB embarquee tronquee comme
        # 'POITIERS 2026 (avec photos)' vs filename 'Guide Poitiers Petit
        # Fute'), on passe le titre scene comme candidat alternatif aux
        # providers. Permet de retrouver des cas ou le filename est PLUS
        # canonique que la metadata embarquee.
        extra_titles: list[str] = []
        if scene_parsed.title and scene_parsed.title.strip().lower() != (meta.title or "").strip().lower():
            extra_titles.append(scene_parsed.title)

        # Sprint D.30 v0.5.0 : trace diagnostique. Chaque provider note ses
        # tentatives (queries, http_status, items_returned, errors) dans
        # cette liste. Persiste dans debug.json pour debug post-mortem.
        lookup_trace: list[dict] = []

        # Lookup configure depuis la config app si pas injecte (tests).
        if _book_lookup is not None:
            meta = _book_lookup(meta)
        else:
            from ... import config
            google_key = config.get_optional_env("GOOGLE_BOOKS_API_KEY", "")
            cache_dir = config.data_dir()
            meta = lookup_book_metadata(
                meta,
                cache_dir=cache_dir,
                google_api_key=google_key,
                extra_titles=extra_titles,
                trace=lookup_trace,
            )
        # Persiste le trace (memo de toutes les queries provider) dans debug
        try:
            debug.set("lookup_trace", lookup_trace)
        except Exception:
            pass

        # === 3. Persister les metadonnees dans debug pour la page detail ===
        try:
            debug.set("book_metadata", book_to_dict(meta))
        except Exception:
            pass  # debug est best-effort

        # === 4. Construire le release_name au format Gemini ===
        # Sprint D.20 : si le parser scene a detecte une team explicite et
        # non-generique (ex: "COZY" pour les audiobooks Sapkowski), on la
        # respecte. Sinon on prend le default tracker (typiquement "Flox").
        # Generic teams (NoTAG / Anonymous) sont skipees ici car egales au
        # default scene (NoTAG = pas de team) — autant prendre la team
        # default tracker qui est plus explicite (Flox).
        team = (tracker.default_team or "NoTAG").strip()
        scene_team = scene_parsed.team or ""
        if scene_team and scene_team.upper() not in {"NOTAG", "NO-TAG", "NO_TAG", "ANON", "ANONYMOUS"}:
            team = scene_team
        release_name = self._build_book_release_name(meta, team)

        # tmdb_context = None pour les livres (TMDB pas applicable)
        return release_name, None

    def compliance_profile(self) -> str:
        """Aligne avec compliance._profile_for_category qui retourne 'book'
        pour CATEGORY_BOOKS.
        """
        return "book"

    def build_extra_payload(self, state_data: Any) -> dict:
        """Sprint D.5 : ajoutera les champs livre dans le payload Gemini
        (isbn, etc.). Pour l'instant rien."""
        return {}

    # ============================================================
    # Construction du release_name
    # ============================================================

    def _build_book_release_name(self, meta: BookMetadata, team: str) -> str:
        """Assemble les tokens scene-compliant :
        `Auteur.Titre.Date.Langue.Format-TEAM`.

        Pour les séries / BD / Manga, on insère T<num> après le titre :
        `Auteur.Titre.T<num>.Sous-titre.Date.Langue.Format-TEAM`.
        """
        parts: list[str] = []

        # 1. Auteur principal (J.R.R. Tolkien -> J.R.R.Tolkien)
        author_token = self._tokenize_author(meta.primary_author)
        if author_token:
            parts.append(author_token)

        # 2. Titre principal (le nom du livre)
        # Sprint D.10 v0.5.0 : 3 cas de figure :
        # (a) Range tomes (intégrale partielle) : Serie.T01-T06
        # (b) Serie + tome unique : Serie.T<num>.Sous-titre
        # (c) Tome unique sans serie : juste le titre
        if meta.series and meta.series_index_range:
            # (a) Intégrale partielle : on padd les numeros sur 2 chiffres
            # (convention scene : T01-T06 plutot que T1-T6)
            series_token = self._tokenize_title(meta.series)
            if series_token:
                parts.append(series_token)
            try:
                lo, hi = meta.series_index_range.split("-")
                lo_i, hi_i = int(lo), int(hi)
                width = max(2, len(str(hi_i)))
                parts.append(f"T{lo_i:0{width}d}-T{hi_i:0{width}d}")
            except (ValueError, IndexError):
                # Fallback : utiliser la string brute
                parts.append(f"T{meta.series_index_range}")
        elif meta.series and meta.series_index > 0:
            # (b) Serie + tome unique
            series_token = self._tokenize_title(meta.series)
            if series_token:
                parts.append(series_token)
            # T<num> : on prend l'int si entier, sinon on garde le float (T2.5)
            if meta.series_index == int(meta.series_index):
                parts.append(f"T{int(meta.series_index)}")
            else:
                parts.append(f"T{meta.series_index}")
            # Le titre du livre devient un sous-titre apres T<num>
            if meta.title and meta.title != meta.series:
                subtitle_token = self._tokenize_title(meta.title)
                if subtitle_token:
                    parts.append(subtitle_token)
        else:
            # (c) Pas de serie : juste le titre
            if meta.title:
                title_token = self._tokenize_title(meta.title)
                if title_token:
                    parts.append(title_token)

        # Si on n'a ni auteur ni titre, on utilise le stem du fichier en
        # fallback (mieux que de retourner juste "EPUB-Team" sans nom).
        # Doit etre fait AVANT l'ajout de l'annee/langue/format pour que ces
        # tokens viennent APRES le stem fallback dans le release_name final.
        if not parts:
            stem = meta.file_path.stem if meta.file_path else "Unknown"
            stem_token = self._tokenize_title(stem)
            if stem_token:
                parts.append(stem_token)

        # 3. Annee de publication
        if meta.publication_year > 0:
            parts.append(str(meta.publication_year))

        # 4. Langue (FRENCH / ENGLISH / JAPANESE...)
        lang_token = self._tokenize_language(meta.language)
        if lang_token:
            parts.append(lang_token)

        # 5. Format (EPUB / PDF / CBZ / MOBI / AZW3 / DJVU)
        if meta.file_format:
            parts.append(meta.file_format.upper())

        base = collapse_dots(".".join(parts))
        # Nettoyer la team du caractere `-` (qui casserait le split scene)
        clean_team = team.replace("-", "").strip(" .") or "NoTAG"
        return f"{base}-{clean_team}"

    # ----- helpers tokenisation -----

    def _tokenize_author(self, raw: str) -> str:
        """Nettoie un nom d'auteur pour le format scene.

        "J.R.R. Tolkien" -> "J.R.R.Tolkien"
        "Hergé" -> "Herge"
        "Stephen King" -> "Stephen.King"
        """
        if not raw:
            return ""
        token = ascii_fold(raw.strip())
        # Espaces -> points
        token = ".".join(p for p in token.split() if p)
        # Nettoyer caracteres non scene-safe (garde lettres, chiffres, points, tirets)
        import re
        token = re.sub(r"[^A-Za-z0-9.\-]+", "", token)
        return collapse_dots(token)

    def _tokenize_title(self, raw: str) -> str:
        """Nettoie un titre pour le format scene.

        "Le Seigneur des Anneaux" -> "Le.Seigneur.Des.Anneaux"
        "Tintin au pays des Soviets" -> "Tintin.Au.Pays.Des.Soviets"
        """
        if not raw:
            return ""
        import re
        token = ascii_fold(raw.strip())
        # Apostrophes : retirer sans espace (l'homme -> lhomme)
        for ch in "'’‘`":
            token = token.replace(ch, "")
        # Ponctuation -> espace puis dots
        for ch in "()[]{},:;!?":
            token = token.replace(ch, " ")
        token = token.replace("_", ".")
        # Espaces -> points + capitalize chaque mot
        words = [w for w in re.split(r"[\s.]+", token) if w]
        words = [self._capitalize_word(w) for w in words]
        token = ".".join(words)
        # Nettoyer caracteres non scene
        token = re.sub(r"[^A-Za-z0-9.\-]+", "", token)
        return collapse_dots(token)

    def _capitalize_word(self, w: str) -> str:
        """Capitalise un mot du titre (sauf les nombres et acronymes).

        "le" -> "Le", "DES" -> "Des", "1984" -> "1984", "JRR" -> "JRR"
        Heuristique simple : si all upper et len > 1 -> garder. Sinon
        capitalize standard.
        """
        if not w:
            return w
        if w.isdigit():
            return w
        # Acronymes >= 2 lettres tous en majuscules : on garde
        if w.isupper() and len(w) >= 2 and not any(c.isdigit() for c in w):
            return w
        return w[0].upper() + w[1:].lower()

    def _tokenize_language(self, lang_code: str) -> str:
        """Convertit un code ISO 639-1 en token Gemini (FRENCH/ENGLISH/...).

        Fallback : si langue non listee, on retourne le code en majuscule
        (FR pour un code "fr" sans mapping). Si vide, on retourne "".
        """
        if not lang_code:
            return ""
        code = lang_code.strip().lower()[:2]
        return _LANG_TOKENS.get(code, code.upper())
