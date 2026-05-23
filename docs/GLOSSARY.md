# Glossaire — Flox Uploader

> Vocabulaire métier ↔ code ↔ source de vérité Gemini. Consulté quand une
> session Claude rencontre un terme inconnu dans le code ou la doc.
>
> **Source de vérité ultime** pour tout terme lié à la charte Gemini : les
> 7 PDFs dans `gemini/` (voir [ONBOARDING.md](ONBOARDING.md) §3).

---

## 1. Termes Gemini officiels

### Langues (variantes audio FR)

| Terme | Signification | Source |
|---|---|---|
| `VFF` | Version Française France | `gemini/RÈGLES DE NOMMAGE.pdf` p.3 |
| `VFQ` | Version Française Québécoise | idem |
| `VFB` | Version Française Belge | idem |
| `VF2` | Multi-piste FR (France + Québec, 1 piste chacun) | idem |
| `VOF` | Version Originale Française (= film FR doublé en français) | idem |
| `VOQ` | Version Originale Québécoise | idem |
| `VOB` | Version Originale Belge | idem |
| `VOSTFR` | Version Originale Sous-Titrée Français | idem |
| `MULTi` | Plusieurs langues audio incluses (VO obligatoire) — **doit être suivi de VFF/VFQ/VFB/VF2** | idem |
| `FRENCH` | **Rejeté** par Gemini — trop générique, doit être remplacé par VFF/VFQ/VFB | idem |
| `FR` | **Rejeté** par Gemini — idem | idem |
| `VFi` | **Rejeté** par Gemini — signale juste "1 seul doublage", non informatif | idem |

### Sources vidéo

| Terme | Signification | Source |
|---|---|---|
| `FULL DISC` / `FULL` / `COMPLETE BDMV` | Copie complète du disque Blu-ray (menus, bonus, 25-100 Go) | `gemini/FULL, REMUX, BDRIP, ...COMMENT CHOISIR.pdf` |
| `REMUX` | Blu-ray remuxé sans menus/bonus, audio/vidéo non recompressés (20-40 Go) | idem |
| `BDRip` / `BluRay` | Blu-ray réencodé (x264/x265/AV1) — bon ratio poids/qualité | idem |
| `BRRip` | Réencodage d'un BDRip — autorisé **seulement en SD** (< 720p) | idem |
| `WEB-DL` / `WEB` | Flux web non recompressé (Netflix, Amazon, Apple TV, Disney+, etc.) | idem |
| `WEBRip` | Flux web réencodé ou capturé/enregistré | idem |
| `HDTV` | Capture directe TV numérique (TNT, satellite, câble) | idem |
| `TVRip` | Réencodage d'un HDTV — qualité variable | idem |
| `DVD` / `DVD9` / `DVD5` | Copie complète d'un disque DVD (SD, 4.7 ou 8.5 Go) | idem |
| `DVDRip` | DVD réencodé (XviD, DivX, x264) | idem |

### Codecs vidéo

| Token | Pour | Source |
|---|---|---|
| `x264`, `x265`, `AV1` | Encodes (BDRip, WEBRip, TVRip) | `gemini/Regle d'encodage.pdf` |
| `H.264`, `H.265`, `VP9`, `MPEG-2` | Flux untouched (WEB-DL, HDTV) | idem |
| `AVC`, `HEVC`, `VC-1` | Disques (FULL, REMUX) | idem |

### Codecs audio

| Token | Signification | Source |
|---|---|---|
| `DTS`, `DTS-HD`, `DTS-HDMA`, `DTS-HDHRA` | Variantes DTS (avec Atmos possible) | `gemini/RÈGLES D'UPLOAD.pdf` |
| `DD` (= `AC-3`), `DDP` (= `E-AC-3`) | Dolby Digital / Dolby Digital Plus | idem |
| `TrueHD` | Dolby TrueHD (avec Atmos possible) | idem |
| `AAC`, `AAC-LC`, `HE-AAC` | AAC variants | idem |
| `FLAC` | Autorisé **uniquement** en mono/stéréo | idem |
| `Opus` | Autorisé | idem |
| `MP3` | **Interdit** sauf pour pistes mono/stéréo | idem |

### Layouts audio (channels)

| Token | Signification |
|---|---|
| `1.0` | Mono |
| `2.0` | Stéréo |
| `2.1` | Stéréo + LFE |
| `4.0`, `5.1`, `6.1`, `7.1` | Multi-canal |
| `2CH`, `6CH`, `8CH` | Variante en nb de canaux (uppercase) |

⚠ Cf. `KNOWN_ISSUES.md` : `3.5`, `2.2`, etc. **ne sont pas des layouts valides** —
le code filtre via `_VALID_AUDIO_LAYOUTS` pour éviter les faux positifs sur
les codecs finissant par un chiffre (E-AC**3**.5.1).

### Tags techniques

| Token | Signification |
|---|---|
| `HDR10`, `HDR10P`, `DV`, `DoVi`, `HLG`, `PQ10` | Métadonnées HDR |
| `10Bit` | Profondeur couleur 10 bits |
| `Atmos` | Dolby Atmos object-based |
| `REPACK` | Corrige un défaut technique majeur d'une release antérieure |
| `PROPER` | Corrige une erreur d'une autre release |
| `DiRFiX` | Corrige une faute de frappe dans le nom |
| `EXTENDED`, `DIRECTORS.CUT`, `THEATRICAL`, `UNCUT`, `UNRATED`, `UNCENSORED` | Versions spécifiques |
| `CUSTOM` | Piste audio ajoutée d'une autre source |
| `INTERNAL` | Release non destinée à la scène publique |
| `READ.NFO` | Infos supplémentaires dans le NFO |
| `LEAK` | Contenu ayant fuité |
| `SUBFRENCH` | Sous-titres FR incrustés dans la vidéo (hardsubs) |
| `SUBFORCED` | Sous-titres FR "forcés" (passages langues étrangères) incrustés |

### Formats ebooks

| Token | Signification | Source |
|---|---|---|
| `EPUB` | Format standard ebook (recommandé) | `gemini/RÈGLES D'UPLOAD EBOOK.pdf` |
| `PDF` | PDF standard | idem |
| `MOBI`, `AZW3` | Formats Kindle | idem |
| `DJVU` | Format scan haute qualité | idem |
| `CBR`, `CBZ` | Comic Book RAR / ZIP (BD/Comics/Manga) | idem |

### Plateformes jeux

| Token | Signification | Source |
|---|---|---|
| `Windows`, `Mac`, `Linux` | PC | `gemini/RÈGLES DE NOMMAGE.pdf` p.2 |
| `PS1`, `PS2`, `PS3`, `PS4`, `PS5` | PlayStation | idem |
| `XBOX` (générique), `360`, `One`, `Series` (post-fix) | Xbox | idem |
| `NSW`, `SWITCH` | Nintendo Switch | idem |
| `NDS`, `PSP`, `WII` | Consoles plus anciennes | idem |

### Types 3D (films)

| Token | Signification | Source |
|---|---|---|
| `SBS` | Side By Side | `gemini/RÈGLES DE NOMMAGE.pdf` p.2 |
| `HSBS` | Half-SBS | idem |
| `TAB` | Top And Bottom | idem |
| `HTAB` | Half-TAB | idem |
| `MVC` | BluRay 3D natif | idem |

---

## 2. Termes Flox internes (code)

### États et workflow

| Terme code | Dans | Signification |
|---|---|---|
| `release_name` | `core/release_name.py::build_release_name` | Nom de release final scene-compliant (`Titre.Annee.MULTi.VFF.1080p.BluRay.x265-TEAM`) |
| `PackageState` (enum) | `core/package_state.py` | États : `PREPARED`, `VALIDATED`, `UPLOADING`, `UPLOADED`, `ABORTED_DUPLICATE`, `FAILED` |
| `package_state.json` | `<package_dir>/` | Persistance atomique de l'état d'un package |
| `dedup_confidence` | `core/upload_orchestrator.py` | Niveau de confiance sur un doublon : `CERTAIN`, `VERY_LIKELY`, `AMBIGUOUS`, `NONE` |
| `naming_signals` | `core/naming_signals.py::SIGNAL_METADATA` | Signaux de fallback émis par le pipeline (TMDB raccourci, langue inférée, etc.) |
| `confidence_score` | `core/confidence.py::compute_confidence_score` | Score 0-100, avec **6 buckets** : `parfait` (=100), `perfect` (95-99), `ready` (90-94), `good` (80-89), `review` (60-79), `blocked` (<60) |
| `tmdb_context` | `debug.json["tmdb_context"]` | Résultat enrichi du resolver TMDB (id, title, genres, etc.) |
| `force_fr` | CLI `--force-fr`, UI radio | Override manuel de la variante FR (VFF/VFQ/VFB/VF2/VOF/VOQ/VOB) |
| `manual_release_name` | `core/package_state.py::PackageStateData` | Release name forcé par l'user (verrouille le pipeline naming) |
| `personal_release` | upload payload | Flag Gemini : release perso (= taggable spécifiquement) |
| `anonymous` | upload payload | Flag Gemini : upload anonyme |

### Tokens techniques (naming)

| Terme code | Dans | Signification |
|---|---|---|
| `_TECH_TOKENS` | `core/release_name.py` | Liste mutualisée des tokens techniques (codecs, sources, résolutions...) utilisée par `split_team` ET `_looks_minimal` — **modifier l'un = vérifier l'autre** |
| `_TECH_UPPER` | idem | Version uppercase de `_TECH_TOKENS` pour comparaisons case-insensitive |
| `_NEVER_TEAM` | idem | Mots qui ne peuvent JAMAIS être une team (codecs, dates, etc.) |
| `_VALID_AUDIO_LAYOUTS` | `core/compliance.py` | `frozenset({"1.0","2.0","2.1","4.0","5.1","6.1","7.1"})` — anti-faux positif `3.5`/`2.2` |
| `_CANONICAL_CASE` | `core/release_name.py` | Table dict `{"BLURAY": "BluRay", "X265": "x265", ...}` — casse de sortie pour les tokens scene (**JAMAIS appliqué à la team** : casse signature préservée) |
| `ALLOWED_FORCE_FR` | `core/release_name.py` | Set des valeurs valides pour `--force-fr` |
| `SPORTS_KEYWORDS` | `trackers/gemini/unit3d_mapping.py` | ~70 keywords pour auto-détecter la catégorie Sport (UFC, F1, NFL, Tour de France, etc.) |
| `DEFAULT_BANNED_TEAMS` | `core/compliance.py` | Tuple des teams interdites par défaut (`k0RE`, `Slay3R`) — additif avec `BANNED_TEAMS` env var |

### Catégories Gemini (mapping)

| Constante | ID | Description |
|---|---|---|
| `CATEGORY_MOVIE` | 1 | Films |
| `CATEGORY_TV` | 2 | Séries |
| `CATEGORY_GAME` | 3 | Jeux |
| `CATEGORY_TV_ANIME` | 6 | Séries Animations |
| `CATEGORY_MOVIE_ANIME` | 7 | Films Animations |
| `CATEGORY_SPORTS` | 10 | Sports |
| `CATEGORY_BOOKS` | 12 | Livres |
| `CATEGORY_MOVIE_DOC` | 13 | Films Documentaires |
| `CATEGORY_TV_DOC` | 14 | Séries Documentaires |
| `CATEGORY_TV_SHOW` | 15 | Émission TV |
| `CATEGORY_SOFTWARE` | 17 | Logiciels |
| `CATEGORY_TRAINING` | 18 | Formations |

⚠ **TYPE_IDs 16-37** (Jeux\Windows, Livres\BD, Logiciels\Linux, etc.) sont
**manquants** dans `unit3d_mapping.py` actuel — à ajouter en Sprint A v0.5.0
(cf. `PLAN-MULTICAT.md` §8.1).

### Sécurité / logs

| Terme code | Dans | Signification |
|---|---|---|
| `ScrubbingWriter` | `web/jobs_runner.py` | Wrapper qui regex-replace les secrets connus (clés API, passkeys) dans les logs avant écriture |
| `BANNED_TEAMS` | `.env` | Variable d'environnement pour étendre `DEFAULT_BANNED_TEAMS` (séparateurs `,;\n`) |

---

## 3. Acronymes

| Acronyme | Signification |
|---|---|
| **TMDB** | The Movie Database — source méta films/séries |
| **OMDb** | Open Movie Database — source note IMDb + récompenses (fallback) |
| **IGDB** | Internet Game Database — source méta jeux (planifié v0.5.0) |
| **IMDb** | Internet Movie Database — pas d'API officielle, accédé via OMDb |
| **TVDB** | TheTVDB — source méta séries (planifié v0.5.0 si nécessaire) |
| **MAL** | MyAnimeList — source méta anime/manga |
| **NFO** | Info file (`.nfo`) — texte descriptif accompagnant une release scene |
| **BBCode** | Bulletin Board Code — markup utilisé par les forums et les trackers Unit3D pour la fiche de présentation |
| **CLI** | Command-Line Interface (sous-commandes `prepare`, `upload`, `inspect`, `serve`) |
| **MULTi** | Plusieurs langues audio incluses (cf. §1) |
| **CRF** | Constant Rate Factor — mode d'encodage qualité-constante |
| **ABR** | Average Bit Rate — mode d'encodage bitrate-cible (2-pass recommandé) |
| **GOP** | Group Of Pictures (encodage vidéo) |
| **PGS** | Presentation Graphic Stream — sous-titres bitmap Blu-ray |
| **SDH** | Subtitles for the Deaf and Hard of hearing |
| **EAC3** | Enhanced AC-3 (= `E-AC-3` = Dolby Digital Plus) |
| **AC3** | Audio Codec 3 (= Dolby Digital) |
| **ISBN** | International Standard Book Number (livres) |
| **SRU** | Search/Retrieve via URL — protocole BnF |
| **ADR** | Architecture Decision Record (format de doc) |
| **DoD** | Definition of Done |
| **MVP** | Minimum Viable Product |

---

## 4. Faux-amis (termes qui ressemblent mais désignent autre chose)

| Terme | Ne pas confondre avec |
|---|---|
| `release_name` (str final) | `manual_release_name` (override user, peut être vide) |
| `tmdb_id` (movie/tv generic) | `tmdb_context["movie_id"]` ou `tmdb_context["tv_id"]` (typés) |
| `MULTi` (préfixe langue, info) | `multi_track` (concept audio générique) |
| `VOF` (FR original sans doublage) | `VFF` (FR doublé d'un film étranger) — **piège fréquent** |
| `_NEVER_TEAM` | `_TECH_TOKENS` (recouvrement partiel mais sémantique différente) |
| `package_state.json` (artefact disque) | `PackageState` enum (type Python) |
| `confidence_score` (0-100) | `dedup_confidence` (4 niveaux qualitatifs) |
| `category_id` (Gemini, int) | `MediaType` (enum interne : MOVIE / TV_EPISODE / TV_SEASON / TV_INTEGRALE) |
| `type_id` Gemini (FULL/REMUX/BDRip/etc.) | `MediaType` (orthogonal — `type_id` = source vidéo, `MediaType` = structure du contenu) |
| `Tracker` (dataclass) | `tracker` (le serveur Gemini lui-même) |
| `TRACKER_API_URL` (base URL `/api`) | `TRACKER_ANNOUNCE` (URL announce du `.torrent` avec passkey) |
| `naming_signals` (signaux fallback) | `compliance_issues` (issues conformité charte) |

---

## 5. Termes à venir (Sprint A→I v0.5.0)

À ajouter au fur et à mesure que les Sprints v0.5.0 sont livrés :

- `NamingStrategy` (Protocol) — strategy pattern par catégorie
- `MetadataProvider` (Protocol) — provider externe par univers (BnF, IGDB, TVmaze, etc.)
- `ConfidenceStrategy` (Protocol) — scoring par profil
- `BookProvider`, `GameProvider`, `ShowProvider`, `SportProvider` (implémentations)
- `category_id_early` (debug key) — précalcul catégorie tôt dans le pipeline
- `CHECKS_BY_PROFILE` (dict registre) — compliance par catégorie

Cf. `../PLAN-MULTICAT.md` §5 et §9 pour le détail.

---

*Maintenu manuellement. Si tu ajoutes un terme métier dans le code, pense à
l'ajouter ici (ou au moins le signaler dans la PR).*
