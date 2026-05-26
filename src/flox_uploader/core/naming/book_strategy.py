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
    detect_volume_range_from_files, find_primary_ebook,
    merge_book_dir_hints, parse_book_dir_name,
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


# Sprint D.33 v0.5.0 : detection des periodiques (magazines / journaux).
# Ces publications NE sont PAS dans Google Books / BnF (sauf reliures
# annuelles rares). Inutile de lancer une recherche qui matchera un livre
# random et polluera le titre.
#
# Heuristiques :
#  1. Noms de publications connus (insensible casse)
#  2. Pattern date dans le filename (mois+annee : "Mai 2026", "23 Mai 2026")
import re as _re
_KNOWN_PERIODICALS = frozenset({
    # Magazines FR
    "rolling stone", "le temps magazine", "diverto", "telerama", "le point",
    "l'obs", "le nouvel obs", "courrier international", "valeurs actuelles",
    "marianne", "society", "geo", "national geographic", "science et vie",
    "ca m'interesse", "60 millions", "que choisir",
    # Journaux quotidiens FR
    "ouest-france", "ouest france", "le monde", "le figaro", "liberation",
    "le parisien", "la croix", "l'humanite", "la depeche", "sud ouest",
    "la voix du nord", "le progres", "nice matin", "var matin", "midi libre",
    "20 minutes", "metro",
    # Sport
    "l'equipe", "lequipe", "france football", "auto plus", "moto magazine",
    "auto moto",
    # Eco/Tech
    "les echos", "challenges", "capital", "01 net", "01net", "micro hebdo",
    "stuff", "geek mag",
    # International EN
    "the economist", "time magazine", "newsweek", "vanity fair", "vogue",
    "wired", "forbes", "fortune",
})
# Pattern date dans filename : "23 Mai 2026", "Mai 2026", "23-24 Mai 2026"
_PERIODICAL_DATE_RE = _re.compile(
    r"\b(?:\d{1,2}[-\s]+)?\d{0,2}\s*"
    r"(?:janv|f[eé]v|mars|avril|mai|juin|juil|ao[uû]t|sept|oct|nov|d[eé]c)"
    r"[a-z]*\s+\d{4}\b",
    _re.IGNORECASE,
)
# Pattern "MAG NN" (numero de magazine)
_PERIODICAL_NUM_RE = _re.compile(r"\bN[°ºo]?\s*\d{2,4}\b", _re.IGNORECASE)


def _looks_like_periodical(filename: str, title: str = "", publisher: str = "") -> bool:
    """Heuristique : ce fichier est-il un periodique (magazine/journal) ?

    Si oui, on skip la lookup Google Books/BnF qui matchera un livre random.
    Cas Louis : Diverto, Rolling Stone, Le Temps Magazine, Ouest-France,
    L'Equipe.
    """
    # Normaliser separateurs scene -> espaces pour faciliter le match des
    # noms de publications avec espaces.
    combined = f"{filename} {title} {publisher}".lower()
    combined_normalized = combined.replace("_", " ").replace(".", " ").replace("-", " ")
    combined_normalized = _re.sub(r"\s+", " ", combined_normalized)
    # Test 1 : nom de publication connu
    for known in _KNOWN_PERIODICALS:
        if known in combined or known in combined_normalized:
            return True
    # Test 2 : pattern date + mot 'magazine' / 'journal' / 'hebdo'
    has_date = bool(_PERIODICAL_DATE_RE.search(filename))
    has_periodical_marker = any(
        m in combined_normalized for m in (
            "magazine", " mag ", "journal", "hebdo", "mensuel",
            "quotidien", "weekly", "monthly",
        )
    )
    if has_date and has_periodical_marker:
        return True
    return False


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

        # Sprint D.39 v0.5.0 (feedback Louis #20 #24) : si on est sur un
        # DOSSIER ET que le range n'est pas explicite dans le nom du
        # dossier, on scanne les fichiers pour detecter T01-T0N implicite.
        # Cas Louis :
        #   - Tokyo Alien Bros. (01-03)/T01,T02,T03.cbz -> range "01-03"
        #     (deja detecte par parse_book_dir_name via "(01-03)" mais on
        #     confirme via les fichiers).
        #   - Star Wars Rebellion/ avec T01..T06.cbz -> range "01-06"
        #     (PAS detecte par parse_book_dir_name car nom dossier brut
        #     sans range explicite).
        if video_path.is_dir() and not meta.series_index_range:
            detected_range = detect_volume_range_from_files(video_path)
            if detected_range:
                meta.series_index_range = detected_range
                try:
                    debug.set("series_index_range_inferred_from_files",
                              detected_range)
                except Exception:
                    pass

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

        # Sprint D.33 v0.5.0 : detecter les periodiques (Diverto, Rolling
        # Stone, L'Equipe, Ouest-France, Le Temps Magazine, etc.) qui ne
        # sont PAS dans Google Books / BnF et qui produisent des matchs
        # foireux ("Rolling Stone Juin 2026" -> matched "Les Rolling Stones").
        # On skip le lookup et on marque dans trace.
        is_periodical = _looks_like_periodical(
            video_path.name, meta.title, meta.publisher,
        )
        if is_periodical:
            lookup_trace.append({
                "provider": "periodical_detector",
                "outcome": "skipped_lookup",
                "reason": "periodique detecte (magazine/journal) - skip BnF/Google Books pour eviter faux match",
                "filename": video_path.name,
                "title": meta.title,
            })
            debug.set("is_periodical", True)

        # Lookup configure depuis la config app si pas injecte (tests).
        if _book_lookup is not None:
            meta = _book_lookup(meta)
        elif is_periodical:
            # Pas de lookup en ligne pour les periodiques - on garde meta tel quel.
            pass
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

        # Sprint D.37 v0.5.0 : detection "aucune correspondance fiable".
        # Si ce n'est pas un periodique (skip intentionnel) ET qu'on n'a
        # aucun ID externe (Google Books / BnF) ET pas d'ISBN apres lookup,
        # on marque no_canonical_match=True. Le confidence score deduit
        # ce flag pour deguerader. UI affiche badge ⚠️.
        if not is_periodical:
            has_match = bool(meta.google_books_id or meta.bnf_ark or meta.isbn_13)
            if not has_match:
                meta.no_canonical_match = True
                try:
                    debug.set("no_canonical_match", True)
                    debug.set("no_canonical_reason",
                              "Aucun provider (BnF / Google Books / OpenLibrary) "
                              "n'a renvoye d'ID externe ni d'ISBN. Le release_name "
                              "est construit depuis la metadata locale uniquement.")
                except Exception:
                    pass

        # Sprint D.39 v0.5.0 (feedback Louis) : detection FANSCAN chapitre
        # individuel (pattern "C\d{3,4}" dans le filename SANS tome/Volume).
        # Cas Louis One Piece #12/#13 : `Eiichiro.Oda.2026.One.Piece.C1180.FRENCH.cbz`
        # Google Books n'indexe pas les chapitres individuels avant edition
        # volume. On force no_canonical_match (avec metadata locale uniquement)
        # pour eviter de retomber sur la fiche d'un AUTRE chapitre random.
        # Le match Google Books obtenu est forcement faux dans ces cas.
        import re as _re_fs
        if not is_periodical:
            stem_lower = video_path.stem.lower() if video_path.is_file() else video_path.name.lower()
            is_fanscan = bool(
                _re_fs.search(r"\bc\d{3,4}\b", stem_lower)
                and not _re_fs.search(r"\b(?:t|tome|vol)\.?\s*\d{1,3}\b", stem_lower)
            )
            if is_fanscan:
                # On force no_canonical_match meme si on a un Google Books ID :
                # ces matches sur "C1180" sont aleatoires (autre chapitre).
                meta.no_canonical_match = True
                # Et on RETIRE les IDs externes obtenus (faux match)
                meta.google_books_id = ""
                meta.bnf_ark = ""
                try:
                    debug.set("no_canonical_match", True)
                    debug.set("no_canonical_reason",
                              "Fanscan chapitre individuel (pattern C\\d{3,4}) "
                              "detecte : Google Books / BnF n'indexent pas les "
                              "chapitres pre-publication. Le match obtenu serait "
                              "aleatoire (autre chapitre). On garde la metadata "
                              "locale uniquement.")
                    debug.set("is_fanscan", True)
                except Exception:
                    pass

        # Sprint D.34 v0.5.0 : sanitize le title final (apres lookup) pour
        # retirer toute pollution scene/BD residuelle dans le stored title.
        # Cas Louis :
        # - Marc Levy MP3 : title="Marc Levy Sept Jours ... FRENCH 128kbps-NOTAG"
        # - Dawnrunner CBZ : title="Dawnrunner (One Shot) (HiComics...) [Digital-2880] (TCH)"
        # - Space Brothers : title="2020.FR" (filename tronque)
        # Le sanitize preserve casse + accents (contrairement a normalize
        # pour query).
        from ..providers._query_normalize import sanitize_book_title
        if meta.title:
            original_title = meta.title
            meta.title = sanitize_book_title(meta.title)
            if meta.title != original_title:
                try:
                    debug.set("title_sanitized", {
                        "before": original_title,
                        "after": meta.title,
                    })
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

        Sprint D.36 v0.5.0 (feedback Louis) : detection + suppression des
        DOUBLONS auteur/serie/titre dans le release_name. Cas typiques :
        - Sapkowski Witcher : auteur="Andrzej Sapkowski", serie polluee
          "Andrzej Sapkowski The Witcher" -> on retire le prefix auteur.
        - Space Brothers : serie="Space Brothers", title="Space Brothers"
          identiques -> on skip le subtitle.
        - Marc Levy MP3 : auteur="Marc Levy", title="Marc Levy Sept Jours..."
          -> on retire le prefix auteur du title.
        """
        parts: list[str] = []

        # 1. Auteur principal (J.R.R. Tolkien -> J.R.R.Tolkien)
        author_token = self._tokenize_author(meta.primary_author)
        if author_token:
            parts.append(author_token)

        # 2. Titre principal — Sprint D.36 v0.5.0 (refonte feedback Louis)
        # Etape 1 : nettoyer la serie. Si polluee par l'auteur, on dedup.
        # Si elle est mono-mot ET deja contenue dans le title AVEC au
        # moins 3 autres mots distincts -> on drop. Cas Sapkowski :
        # serie="Andrzej Sapkowski The Witcher" -> dedup auteur -> "Witcher"
        # (1 mot), title="Sorceleur (Witcher) : La Croisee des corbeaux"
        # qui a 6 autres mots -> drop la serie.
        # Mais cas Raja : serie="Raja", title="RAJA - Tome 2 - RAJA" qui
        # a juste 2 autres mots distincts -> on garde la serie.
        clean_series_token = ""
        if meta.series:
            s = self._tokenize_title(meta.series)
            s = self._dedup_prefix(s, author_token)
            if s:
                s_words = [w.lower() for w in s.split(".") if w]
                covered = False
                if len(s_words) == 1 and meta.title:
                    series_word = s_words[0]
                    if series_word in meta.title.lower():
                        # Mots distincts du title - mots de la serie
                        from collections import Counter
                        title_words = [
                            w.lower() for w in self._tokenize_title(meta.title).split(".") if w
                        ]
                        distinct = set(title_words) - set(s_words)
                        if len(distinct) >= 3:
                            covered = True
                if not covered:
                    clean_series_token = s

        # T<num> string (entier/float)
        tnum_str = ""
        if meta.series_index > 0:
            if meta.series_index == int(meta.series_index):
                tnum_str = f"T{int(meta.series_index)}"
            else:
                tnum_str = f"T{meta.series_index}"

        # Helper : title tokenized contient deja T<num>/Tome.N/Vol.N ?
        def _title_has_volume_marker(title_tok: str, vol_idx: float) -> bool:
            if not title_tok or vol_idx <= 0:
                return False
            vol_int = int(vol_idx) if vol_idx == int(vol_idx) else None
            if vol_int is None:
                return False
            import re as _re2
            tokens = set(title_tok.split("."))
            for pat in (f"T{vol_int}", f"T{vol_int:02d}",
                        f"Tome.{vol_int}", f"Tome.{vol_int:02d}"):
                # Verifier comme token entier
                if pat.split(".")[0] in tokens:
                    return True
            return False

        # Etape 2 : decider la branche
        if clean_series_token and meta.series_index_range:
            # (a) Range tomes (integrale T01-T06)
            parts.append(clean_series_token)
            try:
                lo, hi = meta.series_index_range.split("-")
                lo_i, hi_i = int(lo), int(hi)
                width = max(2, len(str(hi_i)))
                parts.append(f"T{lo_i:0{width}d}-T{hi_i:0{width}d}")
            except (ValueError, IndexError):
                parts.append(f"T{meta.series_index_range}")
        elif (
            clean_series_token and meta.series_index > 0
            and meta.title and meta.title.strip().lower() == meta.series.strip().lower()
        ):
            # (b) title == series : on emet juste series + T<num> (Space Brothers T30)
            parts.append(clean_series_token)
            parts.append(tnum_str)
        elif clean_series_token and meta.series_index > 0:
            # (b') series + T<num> + subtitle dedup
            parts.append(clean_series_token)
            parts.append(tnum_str)
            if meta.title:
                subtitle_token = self._tokenize_title(meta.title)
                subtitle_token = self._dedup_prefix(subtitle_token, clean_series_token)
                subtitle_token = self._dedup_prefix(subtitle_token, author_token)
                # Strip T<num> prefix du subtitle (cas Mercedes
                # ou subtitle commence par "T3.Les.Vents.Furieux").
                import re as _re
                vol_int = int(meta.series_index) if meta.series_index == int(meta.series_index) else None
                if vol_int is not None and subtitle_token:
                    for pat in (
                        rf"^T0*{vol_int}\.",
                        rf"^Tome\.0*{vol_int}\.",
                        rf"^Vol\.0*{vol_int}\.",
                    ):
                        subtitle_token = _re.sub(pat, "", subtitle_token, flags=_re.IGNORECASE)
                # Sprint D.39 v0.5.0 (feedback Louis) : si le subtitle SE
                # TERMINE par la serie (cas Raja "RAJA - Tome 2 - RAJA"
                # title BnF qui repete la serie en suffix), on strippe le
                # suffix. Cas typique editeurs qui font des fiches title
                # symetriques. NB : on accepte aussi le suffix avec dot.
                if subtitle_token and clean_series_token:
                    serie_low = clean_series_token.lower()
                    sub_low = subtitle_token.lower()
                    if sub_low.endswith("." + serie_low):
                        subtitle_token = subtitle_token[: -(len(clean_series_token) + 1)]
                    elif sub_low == serie_low:
                        subtitle_token = ""
                # Sprint D.39 v0.5.0 (feedback Louis) : aussi si subtitle ==
                # series (cas Space Brothers T33 ou title BnF = "Space Brothers"
                # et series = "Space Brothers" -> doublon "Space.Brothers.T33.Space.Brothers")
                if subtitle_token:
                    parts.append(subtitle_token)
        else:
            # (c) Pas de serie utilisable : juste le titre (peut contenir T<num>)
            if meta.title:
                title_token = self._tokenize_title(meta.title)
                title_token = self._dedup_prefix(title_token, author_token)
                if title_token:
                    parts.append(title_token)
                # Si le title NE contient PAS deja T<num> mais qu'on a un
                # series_index, on l'ajoute en suffix (cas Sapkowski T8 ou
                # title n'a pas "T8" embedded -> on NE l'ajoute pas, Louis
                # prefere sans).
                # Decision Louis : si serie est juste covered, on ne tente
                # PAS d'ajouter le T<num> au release_name.

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
        # Sprint D.39 v0.5.0 (feedback Louis) : strip le doublon year si le
        # title termine deja par cette annee. Cas Louis :
        #   - "POITOU.2024" + year=2024 -> "POITOU.2024.2024" (doublon)
        #   - "Marc.Levy.Sept.Jours.Pour.Une.Eternite.2024" + year=2024
        #     -> "...Eternite.2024.2024" (doublon)
        # Solution : si le dernier token du title == publication_year, on
        # ne re-ajoute pas le year.
        year_already_in_title = False
        if meta.publication_year > 0 and parts:
            year_str = str(meta.publication_year)
            last_token = parts[-1].split(".")[-1] if parts[-1] else ""
            if last_token == year_str:
                year_already_in_title = True
        if meta.publication_year > 0 and not year_already_in_title:
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

    def _dedup_prefix(self, token: str, prefix: str) -> str:
        """Sprint D.36 : retire le `prefix` du debut de `token` si present.

        Compare insensible-casse. Strip aussi `The` immediatement apres le
        prefix (cas anglais "Author The Series" -> Author est strippe, et
        "The" devient orphelin si on garde la chaine apres -> on le strip
        aussi). On NE strip PAS les articles francais (Le/La/L') car ils
        peuvent etre la 1re partie du titre (ex "La Trilogie des Vents").
        """
        if not token or not prefix:
            return token
        if token.lower() == prefix.lower():
            return ""
        prefix_lower = prefix.lower()
        token_lower = token.lower()
        if token_lower.startswith(prefix_lower + "."):
            remainder = token[len(prefix) + 1:]
            # Strip "The." en anglais (cas Sapkowski "Author.The.Witcher")
            # PAS les articles francais (peuvent etre dans le titre).
            if remainder.lower().startswith("the."):
                remainder = remainder[4:]
            return remainder
        return token

    def _tokenize_author(self, raw: str) -> str:
        """Nettoie un nom d'auteur pour le format scene.

        "J.R.R. Tolkien" -> "J.R.R.Tolkien"
        "Hergé" -> "Herge"
        "Stephen King" -> "Stephen.King"

        Sprint D.39 v0.5.0 (feedback Louis) : gere le format BnF
        "Lastname, Firstname" en INVERSANT vers "Firstname Lastname"
        avant tokenisation. Cas Louis :
          - "White, T. H." (BnF) -> "T.H.White"
          - "Tolkien, J.R.R." -> "J.R.R.Tolkien"
        Aussi : strip les fragments scene "HS" (Hors-Serie) qui se
        retrouvent en pseudo-auteur quand le filename interne commence
        par "HS - ...".
        """
        if not raw:
            return ""
        s = raw.strip()
        # Sprint D.39 : strip "HS" / "H.S." / "Hors-Serie" comme pseudo-auteur
        # (cas Louis #17 LARGO.WINCH.INTEGRALE ou le fichier interne est
        # "HS - La methode Largo Winch.cbz" et "HS" devient l'auteur).
        normalized = s.upper().replace(".", "").replace(" ", "").replace("-", "").replace("_", "")
        if normalized in {"HS", "HORSSERIE", "HORSSÉRIE"}:
            return ""
        # Sprint D.39 : format BnF "Lastname, Firstname" -> inverser
        # Heuristique : un seul comma + partie droite contient au moins 1 lettre
        # + partie gauche pas trop longue (single lastname/composed-name).
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                lastname = parts[0]
                firstname = parts[1]
                # Verifier que c'est plausiblement un nom inverse :
                # - lastname : 1-4 mots, contient au moins une lettre
                # - firstname : initiales (T. H.) ou prenom court
                lastname_words = lastname.split()
                if (1 <= len(lastname_words) <= 4
                        and any(c.isalpha() for c in lastname)
                        and any(c.isalpha() for c in firstname)):
                    s = f"{firstname} {lastname}"
        token = ascii_fold(s)
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

        Sprint D.36 v0.5.0 (feedback Louis) : les tirets `-` deviennent
        des dots, plus de "Le.Mythe.de.l.Ossuaire.-.Le.Passage" mais
        "Le.Mythe.De.L.Ossuaire.Le.Passage". Convention scene : les
        dashes dans un release_name n'existent QUE pour `-TEAM` final.
        Cas Louis : Clos.De.Bourgogne.Tome.02, 1942.44 (au lieu de 1942-44),
        Le.Mythe.De.L.Ossuaire.Le.Passage.
        """
        if not raw:
            return ""
        import re
        token = ascii_fold(raw.strip())
        # Apostrophes : retirer sans espace (l'homme -> lhomme)
        for ch in "'’‘`":
            token = token.replace(ch, "")
        # Ponctuation -> espace puis dots (Sprint D.36 : `-` aussi)
        for ch in "()[]{},:;!?-":
            token = token.replace(ch, " ")
        token = token.replace("_", ".")
        # Espaces -> points + capitalize chaque mot
        words = [w for w in re.split(r"[\s.]+", token) if w]
        words = [self._capitalize_word(w) for w in words]
        token = ".".join(words)
        # Nettoyer caracteres non scene (Sprint D.36 : on accepte plus le `-`)
        token = re.sub(r"[^A-Za-z0-9.]+", "", token)
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
