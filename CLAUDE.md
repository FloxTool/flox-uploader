# CLAUDE.md — Contexte du projet pour les sessions IA

> **Lecture obligatoire en début de session.** Ce fichier consolide tout l'historique
> du projet, les décisions architecturales prises, les pièges connus et la roadmap
> restante. Mis à jour à mesure que le projet évolue.

---

## 🧭 Index de navigation rapide

Pour trouver l'info en < 30 s, sache où chercher :

| Je veux... | Aller lire... |
|---|---|
| **Onboarder une nouvelle session Claude** (5 min) | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| **Comprendre le projet, l'architecture, les conventions** | Ce fichier (CLAUDE.md), TL;DR + §1-§17 |
| **Travailler concrètement (install, tests, PR, release)** | [`docs/WORKFLOW.md`](docs/WORKFLOW.md) |
| **Éviter un piège connu** avant de modifier une zone | [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) |
| **Comprendre un terme métier ou un acronyme** | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |
| **Comprendre la roadmap v0.4.0** (release vidéo en cours) | [`PLAN-V1.md`](PLAN-V1.md) |
| **Comprendre la roadmap v0.5.0+** (multi-catégorie) | [`PLAN-MULTICAT.md`](PLAN-MULTICAT.md) |
| **Lire les sources de vérité officielles Gemini** | `gemini/*.pdf` (7 PDFs) |
| **Voir l'historique des versions** | [`CHANGELOG.md`](CHANGELOG.md) |
| **Voir les notes à la volée de Louis** | [`NOTES.md`](NOTES.md) |
| **Charte design UI** | [`CHARTE.md`](CHARTE.md) |
| **Audit historique du codebase** | [`AUDIT.md`](AUDIT.md) (rev 2.2 archivée) |
| **Comprendre ce qu'il ne faut JAMAIS modifier** | §18 ci-dessous |

---

## TL;DR (30 secondes de lecture)

**`flox-uploader`** est un outil Python qui automatise la préparation et l'upload de
torrents vers le tracker privé francophone **Gemini** (g3mini, fork Unit3D). À partir
d'un fichier vidéo en entrée, il génère :

1. Un nom de release scene-compliant (charte Gemini : `Titre.Annee.MULTi.VFF.1080p.BluRay.x265-TEAM`)
2. Le fichier `.torrent` (avec announce + passkey)
3. Le NFO MediaInfo
4. La fiche BBCode (présentation pour le tracker)
5. Et l'**uploade** automatiquement via l'API du tracker (avec dédup préalable)

**Stack** : Python 3.10+, FastAPI + Jinja2 + Tailwind pour la web UI, SQLite pour la
queue de jobs, `torf` pour les torrents, MediaInfo CLI pour les métadonnées vidéo.

**Statut actuel → voir [`docs/STATUS.md`](docs/STATUS.md)** (source unique, chiffres
régénérés par `scripts/status_snapshot.py` — ne plus mettre de chiffres périssables
ici). En bref au 2026-07-19 :
- **v0.5.0 publiée** (2026-07-18) : vidéo (films/séries + anim/docu) **et livres**
  (BD/Manga/Audiobooks) livrés. ~1690 tests. Build **local** (GitHub Actions toujours
  désactivé sur le compte — installeur produit à la main, cf. `docs/KNOWN_ISSUES.md §1`).
- **À venir** : Jeux, Émission TV, Sport, Logiciels, Formations (multi-catégorie,
  plan [`PLAN-MULTICAT.md`](PLAN-MULTICAT.md) — à amender, il liste ces catégories
  comme non commencées).
- **Remédiation audit en cours** : [`AUDIT_2026-07-19.md`](AUDIT_2026-07-19.md)
  (vagues R1→R7 ; R1-R3 mergées).

**Cible produit (court terme)** : application web UI packagée user-friendly
(Windows .exe, Docker à venir) pour uploadeurs amateurs francophones. Tout
passe par l'UI. Le terminal est un détail d'implémentation (power-user /
scripting / CI seulement). Cf. [`PLAN-V1.md`](PLAN-V1.md) pour la roadmap
v0.4.0 et [`PLAN-MULTICAT.md`](PLAN-MULTICAT.md) pour v0.5.0+.

**Philosophie** : 100% déterministe (jamais d'appel LLM), human-in-the-loop
(signale les ambiguïtés au lieu de deviner silencieusement), atomic file
writes partout, dégradation gracieuse (jamais de mur sur un type de contenu).

---

## Sommaire

1. [Identité & contexte métier](#1-identité--contexte-métier)
2. [Stack technique](#2-stack-technique)
3. [Architecture du code](#3-architecture-du-code)
4. [Conventions et décisions architecturales](#4-conventions-et-décisions-architecturales)
5. [Pipeline naming (le cœur)](#5-pipeline-naming-le-cœur)
6. [Pipeline upload](#6-pipeline-upload)
7. [Système de scoring de confiance](#7-système-de-scoring-de-confiance)
8. [Web UI (FastAPI)](#8-web-ui-fastapi)
9. [Extensibilité multi-trackers](#9-extensibilité-multi-trackers)
10. [Tests](#10-tests)
11. [Comment lancer](#11-comment-lancer)
12. [Variables d'environnement](#12-variables-denvironnement)
13. [Roadmap restante](#13-roadmap-restante)
14. [Pièges connus (gotchas)](#14-pièges-connus-gotchas)
15. [Références externes](#15-références-externes)
16. [Workflow git](#16-workflow-git)
17. [Conseils pour les sessions Claude Code](#17-conseils-pour-les-sessions-claude-code)
18. [🚫 Zones intouchables](#18--zones-intouchables-à-ne-jamais-modifier-sans-validation-explicite)

---

## 1. Identité & contexte métier

- **Tracker cible** : Gemini (`gemini-tracker.org`, fork Unit3D appelé "G3MINI")
- **Communauté** : francophone, charte de naming stricte calquée sur la scene
- **User** : Louis (`fremontlouis@gmail.com`), uploadeur amateur qui veut industrialiser
  son workflow personnel sans uploader de la merde au tracker
- **Repo** : <https://github.com/FloxTool/flox-uploader> (organisation publique FloxTool)
- **Sources Gemini officielles** : `gemini/*.pdf` (commités dans le repo) — 7 PDFs :
  TORRENT API (IDs catégories/types/résolutions), RÈGLES DE NOMMAGE, RÈGLES
  D'UPLOAD (général + ebook), Règle d'encodage, TEAMS INTERDITES, glossaire
  sources (FULL/REMUX/BDRIP/WEB...). **C'est la VÉRITÉ TERRAIN** — relire
  avant toute décision contestée.

Le projet est né en réécrivant from-scratch un fork existant (`Unit3Dup-G3MINI` de
Roger-Almeida) jugé trop fragile — voir
[Référence Unit3Dup-G3MINI](https://github.com/Roger-Almeida/Unit3Dup-G3MINI). On va
**TOUJOURS** lire le code de ce fork avant d'inventer quoi que ce soit côté API
Unit3D/Gemini (mapping IDs catégories/résolutions/types, payload upload, gestion erreurs).

### Charte de naming Gemini (résumé)

Format obligatoire : `Titre.Annee.LANG.RES.SOURCE.AUDIO.VCODEC-TEAM`

- **Langue** : `MULTi.VFF` / `MULTi.VFQ` / `MULTi.VFB` / `MULTi.VF2` (multi-piste)
  ou `VFF` / `VFQ` / `VFB` / `VOF` / `VOQ` / `VOB` / `VOSTFR` (mono-piste).
  - `FRENCH` et `FR` génériques sont **rejetés** par la charte.
  - `MULTi` sans précision après → review humaine requise.
- **VFF/VFQ/VFB** = doublage (langue d'origine ≠ FR). **VOF/VOQ/VOB** = original FR
  selon pays de production (France/Québec/Belgique).
- **Résolution** : `1080p`, `2160p`, `720p`, etc. (lowercase `p`).
- **Source** : `BluRay`, `WEB-DL`, `WEBRip`, `BDRip`, `HDTV`, `REMUX`, `DVDRip`.
- **Audio** : codec collé aux channels (`DDP5.1`, `AC35.1`) sauf si tiret dans codec
  (`E-AC3.5.1`, `DTS-HD.MA`).
- **Vidéo** : `x264`/`x265` (encode confirmé), `H.264`/`H.265` (capture WEB native),
  `HEVC`/`AVC` (REMUX, codec natif sans re-encode). Inférence automatique selon source
  + MediaInfo.
- **HDR** : `HDR10`, `HDR10P` (pas `HDR10+`), `DV` (pas `DoVi`).
- **Channels** : `2CH` / `6CH` / `8CH` (uppercase).
- **Team** : casse signature préservée (`Punisher694`, `PopHD`, `mHDgz`, `Frosties`).

---

## 2. Stack technique

```
Python 3.10+  ←  base
├── requests              # HTTP (TMDB, OMDb, tracker API)
├── torf                  # création .torrent
├── python-dotenv         # config .env
├── fastapi               # web UI (optional)
├── uvicorn               # serveur ASGI
├── jinja2                # templates HTML
├── python-multipart      # uploads form
└── pytest, pytest-cov, ruff, httpx  # dev
```

- **MediaInfo CLI** : binaire externe requis (`mediainfo --Output=JSON`)
- **SQLite** : pour `data/jobs.db` (queue de jobs web UI)
- **Tailwind CSS** : via CDN dans les templates (pas de build pipeline JS)

---

## 3. Architecture du code

```
src/flox_uploader/
├── __init__.py
├── cli.py                       # entrée CLI (power-user / scripting)
├── pipeline.py                  # orchestration : video → package
├── config.py                    # chargement .env + paths runtime (data_dir, etc.)
│
├── core/
│   ├── debug.py                 # collecteur debug.json (1 fichier vs N writes)
│   ├── errors.py                # die() = exit propre
│   ├── http.py                  # http_get_with_retry (backoff exponentiel)
│   ├── flags.py                 # ISO 3166-1 → emoji drapeau
│   │
│   ├── release_name.py          # ★ CŒUR : construction du nom de release
│   ├── naming_signals.py        # signaux de fallback (cf. §7)
│   ├── confidence.py            # scoring 0-100 + 5 buckets
│   ├── compliance.py            # vérification charte Gemini (NFO ↔ release_name)
│   ├── media_type.py            # MediaType enum + détection saison/épisode/film
│   ├── mediainfo_parser.py      # parsing MediaInfo JSON → dict structuré
│   ├── nfo.py                   # parsing NFO scene + inférence variante FR
│   │
│   ├── tmdb.py                  # client TMDB (search + details + cache atomique)
│   ├── omdb.py                  # client OMDb (note IMDb fallback)
│   │
│   ├── torrent.py               # création .torrent via torf
│   ├── bbcode_renderer.py       # template BBCode → fiche présentation
│   │
│   ├── package_state.py         # state machine + persist atomique
│   ├── jobs_db.py               # SQLite jobs queue (web UI)
│   ├── gemini_api.py            # client API Unit3D Gemini (search dup + upload)
│   └── upload_orchestrator.py   # orchestre dedup → upload → save .torrent final
│
├── trackers/
│   ├── base.py                  # Tracker dataclass + load_tracker_rules
│   ├── __init__.py              # list_trackers, load_tracker
│   └── gemini/
│       ├── tracker.py           # construction Gemini Tracker
│       ├── rules.json           # règles de naming (replace_tokens, drop_tokens, etc.)
│       ├── template.bbcode      # template fiche BBCode
│       └── unit3d_mapping.py    # mapping IDs catégories/résolutions/types Gemini
│
└── web/                         # web UI optionnelle (extra "web")
    ├── app.py                   # FastAPI app + routes
    ├── config_view.py           # schema/read/write/validate du .env
    ├── jobs_runner.py           # background worker (process_one)
    └── templates/
        ├── base.html            # layout (sidebar, sombre/clair, loader)
        ├── inbox.html           # browser de fichiers
        ├── queue.html           # queue jobs + uploads SSE
        ├── package_detail.html  # détail package (overrides, score, fallbacks)
        └── config.html          # édition .env

tests/                           # suite pytest (compte -> docs/STATUS.md)
├── conftest.py
├── test_release_name_*.py       # 3 fichiers : phase2, real_cases (12), split_team
├── test_naming_signals_and_score.py  # Phase 3 : signaux + 5 buckets
├── test_confidence.py
├── test_merge_multi_language.py # logique langue (CAS 1-4)
├── test_resolution_label.py
├── test_unit3d_mapping.py
├── test_gemini_api.py
├── test_jobs_db.py
├── test_package_state.py
└── test_web_app.py              # smoke tests FastAPI
```

---

## 4. Conventions et décisions architecturales

### 🚫 Pas de LLM pour la fiche de présentation

**Décision figée**. La fiche BBCode est générée 100% déterministiquement à partir de
TMDB + OMDb + MediaInfo + un template. **Jamais d'appel OpenAI/Claude/etc.** Raison :
reproductibilité, pas de surprise pour le user, pas de coût/quotas, pas de fuite de
données vers des tiers.

### ✋ Human-in-the-loop systématique

Le pipeline ne **devine jamais silencieusement**. Quand il y a ambiguïté (variante FR
indéterminable, doublon ambigu, TMDB qui ne match rien), il :

1. Émet un signal/warning structuré dans `debug.json`
2. Met le state à `prepared` avec un score < 90 (review)
3. Laisse le user choisir via la web UI ou via override CLI

Exemple : `MULTi` sans précision → score -20 + reason "Variante FR à choisir".
**Jamais** d'upload silencieux : le user doit valider explicitement (via UI ou CLI).

### 💾 Atomic file writes partout

Tous les writes critiques (`package_state.json`, `jobs.db`, `.tmdb_cache.json`, `.env`,
`debug.json`) passent par `tmp_file.write_text()` + `os.replace(tmp, target)`. Évite les
fichiers tronqués en cas de crash worker / antivirus Windows / interruption. Avec
recovery best-effort par regex en lecture (`_try_recover_state` dans `package_state.py`)
si un JSON tronqué est trouvé.

### 🔐 Force FR explicite, pas de devinette

Quand un fichier a un audio FR + audio non-FR sans tag distinctif (`MULTi` ou rien) :

- **Films** : on **bloque** et demande `--force-fr VFF/VFQ/VFB/VF2/VOF/VOQ/VOB`
- **Séries** : on assume `MULTi.VFF` par défaut (99% des distrib FR)

Le user peut toujours surcharger via la page détail ou la CLI.

### 📦 Package state machine (`PackageState` enum)

```
PREPARED → VALIDATED → UPLOADING → UPLOADED
    ↓
ABORTED_DUPLICATE / FAILED
```

Le state est persisté dans `<package_dir>/package_state.json`. Jamais de transition
silencieuse vers `VALIDATED` quand `dry_run=True` (un bug qu'on a fixé).

### 🎯 Casse canonique via `_CANONICAL_CASE`

Dans `release_name.py`, table dict `{"BLURAY": "BluRay", "X265": "x265", ...}` qui définit
la casse de sortie pour chaque token. Pour les tokens non listés, on capitalise la
première lettre (mots du titre). **N'utiliser cette table que pour les tokens scene** :
elle ne touche jamais la team (qui garde sa casse signature).

### 🧱 Tokens techniques mutualisés

Source unique de vérité dans `_TECH_TOKENS` (release_name.py) — utilisée par
`split_team` (rejet des candidates contenant un tech token) ET `_looks_minimal`
(détection des noms minimalistes pour fallback dossier→fichier). **Avant de modifier
cette liste**, vérifier qu'elle reste cohérente entre ces deux usages.

### 🚦 Signaux de fallback (Phase 3)

Chaque approximation faite par le pipeline (TMDB raccourci, langue inférée, résolution
inférée, team par défaut, etc.) émet un signal dans `debug.json["naming_signals"]`. Ces
signaux servent à :

1. Afficher un panneau "Détail du score" fusionné sur la page détail
2. Pondérer le score de confiance (-1 à -5 pts/signal)

Cf. `core/naming_signals.py` pour la liste complète et leurs métadonnées.

### 📝 Format release_name.txt + suffixe FR optionnel

Par défaut : `release_name.txt` contient juste le nom de release scene.

Si `APPEND_FR_TITLE_TO_RELEASE_NAME=1` (env var) : on ajoute ` (Titre français)` à la
fin du nom dans le fichier. Off par défaut, opt-in. Exposé en checkbox dans la web UI.

---

## 5. Pipeline naming (le cœur)

`build_release_name` dans `release_name.py` enchaîne ~13 étapes :

1. **Choix de la source** (folder vs filename via `_looks_minimal()`)
2. **`split_team(name, default_team)`** : 5 stratégies (scene `-TEAM`, `[TEAM]`,
   ` - TEAM`, ` - specs TEAM`, fallback `.team`)
3. **Normalisation du base** : `normalize_separators` (apostrophes, ponctuation),
   `split_glued_tokens` (`WEBripEAC3` → `WEBrip.EAC3`), `apply_replacements`
   (rules.json), `normalize_multi_language`, `normalize_channels`, `remove_tokens`,
   `collapse_dots`
4. **Tokenisation + merges** : `merge_video_codec_tokens` (`H.264`),
   `merge_compound_audio_codecs` (`DTS-HD`), `merge_audio_channel_tokens` (`5.1`)
5. **`classify_parts`** : tri en title/year/lang/resolution/audio/vcodec/optional/dropped
6. **TMDB resolve** (4 stratégies : en-US complet → fr-FR complet → fr-FR raccourci →
   en-US raccourci, garde-fou min 2 mots significatifs ≥ 3 chars)
7. **`merge_multi_language`** : réconcilie nom + NFO + force_fr + TMDB
   (CAS 1 MULTi, CAS 2 variante précise, CAS 3 VOSTFR seul, CAS 4 FRENCH/FR générique)
8. **Auto-enrichissement langue** (`_enrich_language_from_nfo`) :
   si lang vide ou générique + audio FR + non-FR → infère `MULTi.VFF`
9. **Auto-enrichissement résolution** (`_enrich_resolution_from_mediainfo`) :
   si absente du nom → MediaInfo
10. **Année** : si absente → TMDB `release_date`
11. **`infer_video_codec`** : REMUX→HEVC, WEB→H.265, etc., arbitré par MediaInfo
12. **Assembly + casse canonique** (`_normalize_token_case`)
13. **Team finale** : strip caractères invalides, fallback `default_team` (`NoTAG`)

### TMDB matching : règles importantes

- **Multi-langue** : essaie en-US d'abord (titres internationaux), puis fr-FR (films FR
  comme "Le Roi Lion"). Si ça matche en fr-FR : émet `SIG_TMDB_LANG_FALLBACK` (-3 pts).
- **Garde-fou raccourcissement** : ne descend jamais sous 2 mots significatifs (≥ 3
  chars). Évite `"Les"` → matche n'importe quoi (bug Sept Samouraïs).
- **Scoring du choix** : popularité + bonus 1000 si match exact titre + bonus 100 si
  startswith. Permet de discriminer entre homonymes (`Adolescence` vrai vs synopsis qui
  parle d'adolescents).
- **Cache atomique** dans `data/.tmdb_cache.json`, key = `{title.lower()}|{year}`.
- **Films CJK/cyrillique** : `_maybe_fetch_title_en()` fetch le titre EN si
  `original_language ∈ {ja, ko, zh, ru, ar, hi, th, vi, he, fa, uk, bg, el, sr, mk}`.
  Émet `SIG_TMDB_TITLE_EN_FALLBACK` (-2 pts).

### Inférence variante FR depuis TMDB

`infer_fr_variant_from_tmdb()` :

- `original_language='fr'` + France parmi pays → `VOF` (France domine sur coprods)
- `original_language='fr'` + Canada uniquement → `VOQ`
- `original_language='fr'` + Belgique uniquement → `VOB`
- `original_language='fr'` + autre (Suisse, Lux) → `VOF` par défaut
- `original_language != 'fr'` → `VFF` (doublage par défaut)

Exemple : *Délicieux* (2021), coprod France+Belgique → `VOF` (pas `VOB`).

---

## 6. Pipeline upload

`upload_orchestrator.upload_package()` orchestre :

1. **Lecture state + debug.json** (TMDB ID, IMDB, taille, mediainfo, etc.)
2. **Check duplicate via API tracker** (`gemini_api.search_duplicate`) avec cascade :
   - TMDB ID + taille à l'octet → `CERTAIN`
   - TMDB ID seul, delta taille < 5% → `VERY_LIKELY`
   - TMDB ID + delta < 20% → `AMBIGUOUS`
   - Sinon → recherche par nom secondaire en fallback
3. **Si CERTAIN** : abort propre (state → `ABORTED_DUPLICATE`), pas de tentative upload.
4. **Si non-CERTAIN ou `--force-upload --i-know-this-is-a-duplicate=ID`** : POST
   `/api/torrents/upload` avec payload Gemini-compliant (cf. `unit3d_mapping.py` pour
   les valeurs valides de `category_id`, `type_id`, `resolution_id`).
5. **Parse réponse** : `data` est l'URL du `.torrent` final (pas un objet, c'est un
   piège du fork Unit3Dup qui renvoie une string raw).
6. **Télécharge le `.torrent` final** (avec passkey) qui remplace le local.
7. **State → UPLOADED** + persist `uploaded_torrent_url` et `uploaded_torrent_id`.

Mode `--dry-run` : prépare le payload, log ce qui serait POST, mais ne fait **AUCUN**
appel réseau d'upload (transition state aussi évitée).

### Détection de doublons : règles

- TMDB ID + taille = signal le plus fort
- Sans TMDB : nom secondaire (release_name normalisé)
- Le user peut toujours forcer via `--force-upload --i-know-this-is-a-duplicate=ID`
  (friction intentionnelle : il faut combiner les 2 flags + ID exact).

---

## 7. Système de scoring de confiance

Score 0-100 calculé par `compute_confidence_score()` dans `core/confidence.py`.

### Pénalités structurantes (>5 pts, "dures")

| Pénalité | Points | Source |
|---|---|---|
| TMDB pas trouvé | -25 | `debug.tmdb_context` vide |
| IMDB ID manquant | -10 | `tmdb_context.imdb_id` vide |
| Variante FR ambiguë (`MULTi` seul) | -20 | `lang` contient `MULTi` brut |
| Variante FR à choisir (override requis) | -60 | `debug.lang_needs_choice` |
| Compliance issue ERROR (NFO ↔ release_name) | -15 par issue | `debug.compliance_issues` |
| Doublon AMBIGUOUS | -20 | `state_data.dedup_confidence` |
| Doublon VERY_LIKELY | -40 | idem |
| Doublon CERTAIN | -100 (court-circuit) | state ABORTED_DUPLICATE |

### Pénalités douces (1-5 pts, "fallbacks")

Lues depuis `debug.naming_signals` via `naming_signals.SIGNAL_METADATA` :

| Signal | Points |
|---|---|
| `tmdb_query_shortened` | -2 par mot droppé (capé à 10) |
| `tmdb_lang_fallback` | -3 |
| `tmdb_title_en_fallback` | -2 |
| `tmdb_title_fr_fallback` | -3 |
| `lang_inferred_from_nfo` | -3 |
| `lang_default_vff_used` | -2 |
| `resolution_inferred` | -2 |
| `team_default_used` | -2 |
| `folder_name_minimal_fallback` | -1 |
| `dropped_unknown_tokens` | -1 par token (capé à 10) |

### Buckets visuels (5 niveaux)

| Score | Bucket | Couleur Tailwind | Sens |
|---|---|---|---|
| ≥ 95 | `perfect` ✨ | `emerald` | upload les yeux fermés |
| 90-94 | `ready` ✓ | `green` | OK, jeter un œil rapide |
| 80-89 | `good` ~ | `yellow` | quelques fallbacks, vérifier |
| 60-79 | `review` ⚠ | `amber` | vraiment vérifier avant upload |
| < 60 | `blocked` ❌ | `red` | override requis |

### Snapshot des signaux dans le cache TMDB

Quand TMDB resolve avec succès, on stocke `tmdb_context["naming_signals_at_resolve"]`
dans le cache. Au prochain cache hit, on re-émet ces signaux pour que le score reste
cohérent même sans appel TMDB.

---

## 8. Web UI (FastAPI)

Démarrer : `flox-uploader serve` (par défaut sur `http://127.0.0.1:8000`).

### Routes principales

```
GET  /                     → redirige /inbox
GET  /inbox                → browser de fichiers
POST /api/queue/add        → ajoute fichier(s) à la queue, crée job(s)
GET  /queue                → page queue (jobs + uploads en cours)
GET  /api/queue/snapshot   → JSON pour polling intelligent (signature → reload only if change)
GET  /packages/{name}      → page détail package
POST /api/packages/{name}/reprepare      → relance pipeline avec overrides
POST /api/packages/{name}/options        → save personal_release / anonymous
POST /api/packages/{name}/upload         → lance upload (dry_run param)
GET  /api/packages/{name}/upload-status  → polling pour la page détail
GET  /api/uploads/{name}/stream          → SSE log streaming (upload)
GET  /api/jobs/{id}/stream               → SSE log streaming (prepare)
DELETE /api/jobs/{id}                    → supprime job
DELETE /api/packages/{name}              → supprime package
GET  /config                             → page config (édition .env)
GET  /api/config                         → JSON valeurs courantes (secrets masqués)
POST /api/config                         → save .env (preserve commentaires)
```

### Fonctionnalités clés

- **Inbox** : browse fichiers, drives Windows en racines rapides, breadcrumbs sticky,
  recherche multi-token, sélection multi-fichiers (films CDs / séries dossier).
- **Queue** : tri par colonne (release/taille/score/état/maj) avec persistance
  localStorage, polling intelligent (reload seulement si la signature a changé),
  upload batch depuis sélection, suppression batch, ligne live SSE par job/upload,
  doublon CERTAIN en rouge avec lien tracker.
- **Page détail** : poster TMDB, métadonnées, overrides (force_fr radios, TMDB ID
  manuel, release_name manuel verrouillé par défaut), section Upload (dry-run + réel)
  avec log SSE en direct, panneau "Détail du score" fusionné avec sections "Pénalités
  structurantes" + "Fallbacks utilisés", confirmation suppression package.
- **Config** : édition `.env` avec masking secrets (TMDB_API_KEY, OMDB_API_KEY,
  TRACKER_ANNOUNCE), validation des paths/URLs, preserve les commentaires du .env, retire
  carrément la ligne pour valeur vide (vs `KEY=` qui causait des bugs).
- **Mode sombre** : toggle dans sidebar, persistance localStorage.
- **Loader** : sur tous les liens top-level + intercepte navigation back via pageshow.
- **Reconciliation au boot** : `_reconcile_stuck_jobs()` remet les jobs `preparing`
  bloqués (worker crashé) en `failed`.

---

## 9. Extensibilité multi-trackers

Pour ajouter un tracker, créer `src/flox_uploader/trackers/<key>/` avec :

```
__init__.py
tracker.py        # load_<key>_tracker(announce_url) → Tracker
rules.json        # règles de naming spécifiques (replace_tokens, drop_tokens, etc.)
template.bbcode   # template fiche BBCode
unit3d_mapping.py # mapping IDs API si fork Unit3D (optionnel)
```

Le `Tracker` dataclass dans `trackers/base.py` expose : `key`, `display_name`,
`announce_url`, `rules` (dict), `torrent_source`, `default_team`, `private`.

Pour exposer le tracker : ajouter une entrée dans `trackers/__init__.py::list_trackers()`.

Aujourd'hui un seul tracker implémenté : Gemini. La structure est prête pour d'autres
forks Unit3D francophones.

---

## 10. Tests

- **Suite pytest** — nombre exact et à jour dans [`docs/STATUS.md`](docs/STATUS.md)
  (généré). Ne pas remettre de compte figé ici.
- Lancement : `python -m pytest tests/` (ou via venv : `.venv\Scripts\pytest`)
- Coverage : non encore configurée (à faire dans la roadmap).

### Fichiers de tests notables

- `test_release_name_real_cases.py` — 21 tests basés sur les 12 cas réels remontés par
  Louis (cat A à I). Si une régression casse un de ces tests, on sait immédiatement
  quel cas concret est cassé.
- `test_naming_signals_and_score.py` — 19 tests Phase 3 : émission signaux, calcul
  pénalités, 5 buckets, 3 cas réels (Time Machine, Sept Samouraïs).
- `test_merge_multi_language.py` — 4 CAS de la logique langue.
- `test_web_app.py` — smoke tests FastAPI (rendu pages, routes API).

### Convention tests

- Un test = une assertion claire, un nom explicite (`test_cat_a_team_punisher694_keeps_case`).
- Pas de mocks à outrance ; on préfère faire passer un mini-fixture (dict, Path tmp).
- Les helpers de fixtures sont dans `tests/conftest.py`.

---

## 11. Comment lancer

### Setup user-final (cible produit)

À terme : un installeur (PyInstaller `.exe` Windows / `docker compose up` ailleurs)
qui packagera MediaInfo, lancera le serveur et ouvrira le navigateur sur le
wizard `/setup`. Pas de terminal. Pas de `.env` à éditer à la main. Cf.
`AUDIT.md §4` pour la roadmap.

### Setup dev (mode editable, en attendant l'installeur)

```cmd
git clone https://github.com/fremontlouis/flox-uploader.git
cd flox-uploader

python -m venv .venv
.venv\Scripts\activate  # Windows / source .venv/bin/activate sur Linux

pip install -e ".[web,dev]"

copy .env.example .env  # puis remplir TRACKER_ANNOUNCE, TMDB_API_KEY, OMDB_API_KEY
```

Pré-requis externe (à packager dans l'installeur, manuel pour le dev) :
[MediaInfo CLI](https://mediaarea.net/en/MediaInfo/Download) dans le `PATH`.

### Lancement web UI (le seul flux user-facing)

```cmd
flox-uploader serve              # http://127.0.0.1:8765/
flox-uploader serve --port 8000  # port custom
```

### Commandes CLI power-user / scripting

Conservées pour Sonarr/Radarr post-import, CI, debug. Ne sont PAS
exposées au user lambda :

```cmd
# Préparer un package (sans upload)
flox-uploader prepare "C:\path\to\movie.mkv" --tracker gemini

# Forcer la variante FR
flox-uploader prepare "C:\path\to\movie.mkv" --force-fr VFF

# Préparer + uploader en dry-run
flox-uploader prepare "C:\path\to\movie.mkv" --upload --dry-run

# Préparer + upload réel
flox-uploader prepare "C:\path\to\movie.mkv" --upload --no-dry-run

# Inspect mapping unit3d (debug : récupère les attributs d'un torrent existant)
flox-uploader inspect 12345 --tmdb-id-hint=67890
```

### Forcer l'upload sur un doublon (rare, friction intentionnelle)

```cmd
flox-uploader upload <package_dir> --force-upload --i-know-this-is-a-duplicate=12345
```

---

## 12. Variables d'environnement

`.env` à la racine (jamais commité, cf. `.env.example`).

| Var | Obligatoire | Description |
|---|---|---|
| `TRACKER_ANNOUNCE` | ✓ | URL announce Gemini avec passkey (`https://gemini-tracker.org/announce/<passkey>`) |
| `TMDB_API_KEY` | ✓ | Clé v3 TMDB ([themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)) |
| `OMDB_API_KEY` | ✓ | Clé OMDb pour note IMDb fallback ([omdbapi.com/apikey.aspx](https://www.omdbapi.com/apikey.aspx)) |
| `TRACKER_API_KEY` | ✓ pour upload | Clé API Gemini (page profil tracker) |
| `TRACKER_API_URL` | ✓ pour upload | Base URL API tracker (`https://gemini-tracker.org/api`) |
| `OUTPUT_DIR` | optionnel | Dossier des packages générés (défaut : `./output`) |
| `BROWSE_ROOT` | optionnel | Racine par défaut du browser inbox (défaut : home user) |
| `BROWSE_ROOTS` | optionnel | Racines rapides additionnelles séparées par `;` |
| `APPEND_FR_TITLE_TO_RELEASE_NAME` | optionnel | Si `1` : ajoute ` (Titre français)` au release_name.txt |
| `FLOX_UPLOADER_DATA_DIR` | optionnel | Override du dossier `data/` (jobs.db, .tmdb_cache.json, etc.). **NE JAMAIS** mettre `.` ou un path relatif vide → fallback sur `<repo>/data` |

---

## 13. Roadmap restante

> **Référence canonique pour la roadmap actuelle :**
> - **v0.4.0 (release publique vidéo)** : [`PLAN-V1.md`](PLAN-V1.md) — Sprints 1
>   à 9. Sprints 1-8 livrés ; Sprint 9 (release v0.4.0 publique) bloqué sur
>   réintégration GitHub Actions.
> - **v0.5.0+ (multi-catégorie : livres, jeux, sport, émission TV,
>   logiciels, formations)** : [`PLAN-MULTICAT.md`](PLAN-MULTICAT.md) —
>   Sprints A à I, ~6-8 semaines homme. Dégradation gracieuse 4 barreaux.
> - **`AUDIT.md` (rev 2.2)** : audit historique du codebase (95% des findings
>   P0/P1 livrés), conservé pour traçabilité des références §X.Y.
>
> La section §13 ci-dessous reste pour la mémoire des bugs résolus et de
> quelques items long terme. Les détails actifs sont dans les deux PLAN-*.md.

### 13.1 Déjà fait depuis CLAUDE.md précédent (commit après 5023907)

- [x] **Nettoyage code obsolète** (~1380 lignes) : suppression de
      `windows_context_menu.py`, `input_list.py`, `batch.py`, des `.bat`
      racine (`install.bat`, `run_batch.bat`, `install_context_menu.bat`,
      `uninstall_context_menu.bat`), des sous-commandes CLI `cmd_add`,
      `cmd_batch`, `cmd_install_menu`, `cmd_uninstall_menu`, et des helpers
      `config.input_list_path()` / `config.history_dir()`.
- [x] **Bug operator-precedence `web/app.py:330`** : `mediainfo_nfo_text`
      n'est plus écrasé à tort par un NFO scene contenant "Format".
- [x] **`_extract_size_bytes` fallback réel** via `Torrent.size` : la dedup
      par taille n'est plus silencieusement désactivée pour les packages legacy.

### 13.2 Court terme (cible produit)

- [ ] **Packaging MediaInfo** dans l'installeur (PyInstaller embed +
      Docker `apt-get`). Cf. `AUDIT.md §4.1`. **P0 distribution.**
- [ ] **Wizard first-run** : redirect `/setup` quand `.env` incomplet, 5
      étapes, validation API live. Cf. `AUDIT.md §4.2`. **P0 distribution.**
- [ ] **`data_dir()` cross-platform via `platformdirs`** : survit aux
      updates PyInstaller. Cf. `AUDIT.md §4.3`. **P0 distribution.**
- [ ] **Page History** : liste des packages uploadés, recherche/filtre,
      lien tracker. Reclassé P1 dans la grille produit final.
- [ ] **Watcher mode** : surveille un dossier (ex : `\\NAS\torrents\completed\radarr\`)
      et auto-prepare les nouveaux fichiers. **Différé à la demande de Louis**.
- [ ] **Coverage tests** : `pytest-cov` est déjà dans `pyproject.toml`. Reste à
      ajouter `[tool.coverage.run]` + `.coveragerc`, badge dans README.
- [ ] **Masking secrets dans logs** + page logs UI. Cf. `AUDIT.md §5.2 + §4.9`.

### 13.3 Moyen terme

- [ ] **Distribution Docker** : Dockerfile + docker-compose. Cf. `AUDIT.md §4.4`.
      ⚠ Penser à conseiller au user de monter l'output dir dans un path court
      (ex : `C:\trackup\`) pour éviter le bug 8.3 sur l'upload `.torrent`.
- [ ] **Distribution PyInstaller** : standalone `.exe`, icône bureau,
      autostart opt-in, code signing. Cf. `AUDIT.md §4.4 + §4.8`.
- [ ] **Mécanisme d'updates** (banner `nouvelle version dispo`).
      Cf. `AUDIT.md §4.6`.
- [ ] **Erreurs de démarrage user-friendly** (dialog GUI, pas `print` sur
      stderr invisible). Cf. `AUDIT.md §4.7`.
- [ ] Plugin/intégration **Sonarr/Radarr** custom script pour déclencher la
      prepare automatiquement après import (conservé via API).

### 13.4 Long terme

- [ ] Support multi-trackers (autre fork Unit3D FR : ABnormal, etc. quand la
      base est stable). La struct est déjà prête.
- [ ] Refactor `release_name.py` 1275 lignes en sous-modules (`naming/normalize`,
      `naming/classify`, `naming/language`, `naming/build`).
- [ ] Tray icon Windows (pystray) + minimize-to-tray.
- [ ] Auth optionnelle UI (mot de passe) quand `--host` ≠ localhost.
- [ ] Mode "smart batch" via UI : prépare tout, présente une vue d'ensemble,
      l'user valide en bloc les "perfect" et review les autres.

### 13.5 Bugs/dette technique connus

- ~~Bug `audio_titles` vs `nfo_audio_titles` dans auto-enrichissement~~ ✓ fixé 2026-05-06
- ~~Bug team `team.upper()` qui détruit la casse signature~~ ✓ fixé
- ~~Bug TMDB matching "Les" tronqué à 1 mot~~ ✓ fixé (garde-fou 2 mots significatifs)
- ~~Bug `package_state.json` truncated → tous les packages disparaissent~~ ✓ fixé (atomic
  write + recovery par regex)
- ~~Bug operator-precedence `web/app.py:330` (rev 2 audit)~~ ✓ fixé
- ~~Bug `_extract_size_bytes` fallback désactivé (rev 2 audit)~~ ✓ fixé
- Path traversal sur `/inbox` + `/api/files` + `/api/queue/add` : à fixer
  avant v1 publique. Cf. `AUDIT.md §5.1`.
- `hash()` non-déterministe pour les noms de log. Cf. `AUDIT.md §6.3`.
- Multiples `except Exception:` silencieux. Cf. `AUDIT.md §6.5`.
- Pas encore de tests d'intégration end-to-end (vrai fichier mkv → vrai upload dry-run).

---

## 14. Pièges connus (gotchas)

### 🪟 Windows-specific

- **Path 8.3 court** : si l'output dir est sur un path long (`C:\Users\Long\...\Tracker
  Uploder\output\...`), `torf` peut planter à l'upload. Recommander un path court.
  À résoudre via `data_dir()` cross-platform (`platformdirs`) cf. `AUDIT.md §4.3`.
- **`autocrlf=true`** : Git Windows convertit LF → CRLF automatiquement. Ne pas s'en
  inquiéter, c'est juste cosmétique.
- **`.git/index.lock` orphelin** : si une session précédente a crashé. `del
  .git\index.lock` pour débloquer.
- **CMD vs PowerShell vs Git Bash** : pas la même syntaxe (`cat << EOF` ne marche pas
  en CMD). Toujours préciser ou donner les 2 versions.

### 🐧 Sandbox/mounts (n'arrive plus avec Claude Code natif Windows)

- Le mount Linux ↔ Windows utilisé par Cowork désynchronisait, créant des fichiers
  tronqués côté Linux alors que Windows était OK. **Pas un problème côté Claude Code
  natif**, mais à savoir si on a besoin de relancer un sandbox cloud un jour.

### 📦 Pipeline naming

- `team.upper()` est **interdit** : la casse signature de la team doit être préservée
  (`Punisher694` ≠ `PUNISHER694`).
- `_NEVER_TEAM` et `_TECH_TOKENS` étaient dupliqués → mutualisés en `_TECH_TOKENS` +
  `_TECH_UPPER`. Si tu modifies l'un, vérifie l'autre usage.
- `_looks_minimal` doit rester en sync avec `_TECH_TOKENS` (utilise le regex compilé
  `_LOOKS_MINIMAL_TECH_PATTERN`).
- L'auto-enrichissement langue regarde `inferred["audio_titles"]` (pas
  `nfo_audio_titles` qui n'existe pas — bug fréquent à éviter).

### 🌐 TMDB

- **Min 2 mots significatifs** (≥ 3 chars) lors du raccourcissement. `"Les"` seul match
  n'importe quoi.
- Multi-langue : essayer en-US d'abord, puis fr-FR. Pas l'inverse (sinon on récupère le
  titre FR pour des films internationaux).
- Pour CJK/cyrillique, fetcher le `title_en` séparément (pas dispo dans le call fr-FR).

### 🧪 Tests

- Quand on touche un bug d'un cas réel, **ajouter un test** dans
  `test_release_name_real_cases.py` ou `test_naming_signals_and_score.py`. Pas de fix
  sans test de non-régression.

---

## 15. Références externes

- **Repo principal** : <https://github.com/FloxTool/flox-uploader>
- **Doc officielle G3MINI TR4CK3R** : 7 PDFs **commités dans `gemini/`**
  (depuis 2026-05-22) — `TORRENT API.pdf`, `RÈGLES DE NOMMAGE.pdf`, `RÈGLES
  D'UPLOAD.pdf` (général), `RÈGLES D'UPLOAD EBOOK.pdf`, `Regle d'encodage.pdf`,
  `TEAMS INTERDITES.pdf`, `FULL, REMUX, BDRIP, WEB, WEBRIP, COMMENT CHOISIR.pdf`.
  **C'est la VÉRITÉ TERRAIN pour les IDs Unit3D** (category_id, type_id,
  resolution_id) — plus fiable que Unit3Dup-G3MINI qui contenait plusieurs
  IDs faux (BDRip=25 → vraiment 3, DVDRip=24 → vraiment 13, types
  WEBMux/DLMux/BDMux/3D inexistants). **Découverte 2026-05-22** :
  `unit3d_mapping.py` actuel n'a pas les TYPE_IDs 16-37 (Jeux\Windows,
  Livres\BD, Logiciels\Linux, etc.) — à compléter en Sprint A v0.5.0
  (cf. PLAN-MULTICAT §8.1).
- **Fork de référence** : <https://github.com/lantiumBot/Unit3Dup-G3MINI> —
  utile pour la logique d'upload, mais croiser les IDs avec le PDF officiel.
- **TMDB API** : <https://developer.themoviedb.org/reference/intro/getting-started>
- **OMDb API** : <https://www.omdbapi.com/>
- **Unit3D source** : <https://github.com/HDInnovations/UNIT3D> (pour lire le code des
  endpoints API si besoin).
- **Charte de naming Gemini** : pas de doc officielle publique, déduite via lecture du
  fork + tests sur le tracker. Voir `src/flox_uploader/trackers/gemini/rules.json`
  pour la version exécutable.

---

## 16. Workflow git

### Workflow PR → squash-merge sur `main` (depuis Sprint 1 PLAN-V1)

Le push direct sur `main` est **bloqué par le classifier Claude Code**
(décision validée avec Louis). Workflow standard :

```cmd
cd "C:\Users\Louis\Documents\Claude\Projects\Tracker Uploder"
git checkout main && git pull origin main
git checkout -b <feature-branch-name>
git add <fichiers>
git commit -m "..." -m "..."
git push -u origin <feature-branch-name>
gh pr create --title "..." --body "..."
```

Puis Louis merge via GitHub UI (squash + delete branch). Le tag (`vX.Y.Z`)
déclenche le build CI (Build Windows .exe → installeur Inno Setup) qui
attache l'installeur à la release.

**Important** : GitHub Actions est actuellement désactivé sur le compte
`fremontlouis` (cf. statut TL;DR). En attendant la réintégration, les PRs
peuvent être mergées mais les builds CI ne tournent pas.

### Format des commits préféré (calé avec Louis)

```
<sujet 50-72 chars : verbe au présent>

- Bullet 1 : changement principal
- Bullet 2 : changement principal
- ...

Tests : N/N verts
```

### Commande de push standard (CMD Windows, workflow PR)

À la fin de chaque itération significative, créer une PR (le push direct
sur `main` est bloqué) :

```cmd
cd "C:\Users\Louis\Documents\Claude\Projects\Tracker Uploder"
git checkout main && git pull origin main
git checkout -b feature-<sujet>
git add <fichiers ciblés, pas "git add .">
git commit -m "Sujet" -m "Body multi-lignes (-m répété pour body)" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push -u origin feature-<sujet>
gh pr create --title "..." --body "..."
```

**À ne JAMAIS commit** : `data/`, `jobs.db`, `jobs/`, `.claude/`, `.env`,
`__pycache__/`, `.tmdb_cache.json`, `gemini/_extracted/` (artefact PDF→text).
Les **PDFs Gemini** dans `gemini/` SONT commités (sources officielles, cf.
`.gitignore` exception `!gemini/*.pdf`). Cf. `.gitignore`.

---

## 17. Conseils pour les sessions Claude Code

### Lis ces fichiers en début de session si tu touches au naming

1. `src/flox_uploader/core/release_name.py` (le cœur, 1200+ lignes)
2. `src/flox_uploader/core/naming_signals.py` (signaux émis)
3. `src/flox_uploader/core/tmdb.py` (matching multi-langue)
4. `tests/test_release_name_real_cases.py` (les cas concrets de Louis)
5. `tests/test_naming_signals_and_score.py` (Phase 3)

### Lis ces fichiers en début de session si tu touches à la web UI

1. `src/flox_uploader/web/app.py` (1200+ lignes, toutes les routes)
2. `src/flox_uploader/web/templates/package_detail.html` (~770 lignes)
3. `src/flox_uploader/web/templates/queue.html` (~670 lignes)

### Conventions à suivre

- **Toujours lancer `pytest`** après une modif. Si un test casse, soit fixer le code,
  soit (plus rare) actualiser le test si le comportement attendu a changé.
- **Pas de print() de debug pour la prod** — utiliser `debug.set()` qui va dans
  `debug.json`, traçable.
- **Comments en français** dans le code (Louis lit le code en français — convention
  établie).
- **Docstrings** sur toutes les fonctions publiques. En français aussi.
- **Tests pour chaque cas réel remonté par Louis** : si un fichier sur son disque produit
  un mauvais release_name, c'est qu'il manque un test. À ajouter avant le fix.

### Push à chaque itération significative

Louis a explicitement demandé de lui fournir un bloc CMD prêt-à-coller à la fin de
chaque itération. Pas de heredoc bash (`<< EOF`) car il est sur CMD Windows. Cf. §16
pour le format.

### Mémoires de sessions précédentes (Cowork) consolidées ici

Toutes les décisions et apprentissages des sessions Claude Cowork (jusqu'au
2026-05-06) sont reportés dans ce fichier. Pas besoin de retrouver les anciennes
conversations.

---

## 18. 🚫 Zones intouchables (à ne JAMAIS modifier sans validation explicite)

> Liste consolidée des fichiers / décisions / zones où une modification doit
> être **explicitement validée par Louis** avant toute action. En cas de
> doute, demande avant d'agir.

### 18.1 Sources de vérité externes (ne JAMAIS modifier)

- **`gemini/*.pdf`** (7 fichiers) : sources officielles Gemini. En cas de
  désaccord entre le code et un PDF Gemini, **on relit le PDF avant de
  coder**. Modifier un PDF = perdre la source de vérité.
- **Référence Unit3D source** (https://github.com/HDInnovations/UNIT3D) :
  pour comprendre l'API tracker, on lit le code Unit3D upstream avant
  d'inventer.

### 18.2 Plans stratégiques (modifs nécessitent validation Louis)

- **[`PLAN-V1.md`](PLAN-V1.md)** : roadmap v0.4.0 (release publique vidéo).
  Décisions D1-D18 figées. Si une décision doit être révisée, **amender
  d'abord ce doc**, puis le code.
- **[`PLAN-MULTICAT.md`](PLAN-MULTICAT.md)** : roadmap v0.5.0+
  (multi-catégorie). Décisions D-MC1-15 figées. Idem.
- **[`AUDIT.md`](AUDIT.md)** : historique archivé. Ne pas modifier (refs
  utilisées par CLAUDE.md, README, code, tests).
- **[`CHARTE.md`](CHARTE.md)** : design system. Si une nouvelle convention
  UI est nécessaire, **l'ajouter d'abord à la charte**, puis l'implémenter.

### 18.3 Décisions figées (ne JAMAIS contredire silencieusement)

- **Aucun appel LLM** dans le pipeline (cf. §4 + D10 + ONBOARDING §3.1).
  C'est une décision produit fondamentale. Si tu vois une opportunité
  d'introduire un LLM, **la signaler à Louis avant**, jamais l'ajouter
  silencieusement.
- **`team.upper()` interdit** (cf. §14 + ONBOARDING §3.4). Casse signature
  des teams préservée.
- **Pas de télémétrie** (cf. D10). Aucune donnée ne quitte la machine sans
  appel API explicite de l'user.
- **Pas de push direct sur `main`** (cf. §16 + ONBOARDING §3.2). PR
  workflow obligatoire. Le classifier bloque de toute façon.
- **`tests/test_release_name_real_cases.py`** : 21 cas réels Louis = gold
  standard. **Ne JAMAIS amender** un de ces tests sans qu'il y ait une
  raison documentée (décision écrite dans un PLAN-*.md).

### 18.4 Infra / configuration (modifs valider Louis)

- **`.github/workflows/*.yml`** : modifs impactent les builds CI et la
  génération des installeurs. Valider Louis avant.
- **`pyproject.toml`** : changements de dépendances ou de version. Impact
  paquet. Valider.
- **`.gitignore`** : règles existantes (notamment exception
  `!gemini/*.pdf`). Ne pas casser.
- **`src/flox_uploader/trackers/gemini/unit3d_mapping.py`** : IDs API
  Gemini. Source = PDFs Gemini. Toute modif doit être justifiée par une
  ligne précise d'un PDF.

### 18.5 Workflow opérationnel (sprints en cours)

- **Sprint en cours d'exécution** : ne pas modifier un sprint marqué
  "en cours" dans PLAN-V1.md ou PLAN-MULTICAT.md sans amender le plan
  d'abord.
- **Branches feature actives** : ne pas force-push ni rebase brutal sur
  une branche partagée sans valider.
- **Tags `v*` poussés** : ne JAMAIS supprimer ni déplacer un tag publié
  (déclenche/a déclenché la CI). Pour corriger, créer un nouveau tag
  (v0.4.1 plutôt que re-tag v0.4.0).

### 18.6 Données utilisateur (jamais commit)

Cf. `.gitignore` + [`docs/WORKFLOW.md`](docs/WORKFLOW.md) §8 :
- `data/`, `jobs.db`, `.tmdb_cache.json` (runtime utilisateur)
- `.env`, `.env.local`, `*.passkey` (secrets)
- `.claude/` (sessions Claude Code locales)
- `gemini/_extracted/` (artefact d'extraction PDF, reproductible)

### 18.7 Et pour le reste ?

Pour les modifs **dans le scope d'un sprint actif** ou pour des
**améliorations chirurgicales bien documentées** : workflow PR standard,
pas besoin de demander avant chaque commit. Le filet de sécurité = la PR
+ la review.

---

*Dernière mise à jour : 2026-07-19 par Claude — état courant déplacé vers
[`docs/STATUS.md`](docs/STATUS.md) (source unique régénérée). v0.5.0 publiée
(vidéo + livres). Remédiation audit [`AUDIT_2026-07-19.md`](AUDIT_2026-07-19.md)
en cours (vagues R1→R7). Les chiffres de tests/version/routes ne sont plus figés
ici : voir STATUS.md. Ne plus recopier de compteurs périssables dans ce fichier.*

*Historique antérieur : 2026-05-07 (Lots K-S, web UI Phase 3c + bugs durs + auto-enrich
+ champs upload complets + UX/UI buckets 6 niveaux + BBCode parser).*

### Lot O (bugs durs) — points clés

- **Furiosa S01E265 résolu** : `EPISODE_PATTERNS` durci avec lookbehind
  anti-channel-layout. `5.1x265` ne matche plus comme S01E265.
- **TMDB ranking refondu** : on cumule en-US + fr-FR sans year-filter
  API, puis ranking par `year_score (tolérance ±1) + title_score +
  popularity + vote_count*0.5`. Plus de court-métrage qui gagne sur le
  blockbuster.
- **Drop tokens ambigus protégés avant l'année** : `MAX`, `NFLX`, etc.
  ne sont droppés que APRÈS l'année (ce sont des mots du titre avant).

### Lot P (enrichissement nom) — points clés

- `_enrich_audio_video_from_mediainfo` ajoute auto le codec audio (AAC,
  DDP), le layout (5.1, 7.1) et le codec vidéo (x265, x264) quand
  absents du nom mais détectés par MediaInfo.
- Mapping `_MEDIAINFO_TO_GEMINI_AUDIO_CODEC` centralise la conversion
  vers les tokens canoniques `rules.json`.
- Décision produit validée par Louis : on enrichit toujours (pas de
  toggle), c'est plus conforme à la charte Gemini.

### Lot Q (champs upload) — points clés

- `PackageStateData` étendu : `manual_imdb_id` (str), `manual_tvdb_id`,
  `manual_mal_id`, `manual_season_number`, `manual_episode_number`,
  `manual_distributor_id`, `manual_region_id`, `manual_keywords`.
- TMDB resolver fetch maintenant `tvdb_id` (via `external_ids`) et
  `keywords` (via `append_to_response=keywords`).
- UI : 3 grids responsives dans la carte "Options upload", visibilité
  conditionnelle (Saison/Épisode si cat TV, Distributeur/Région si
  type=Full Disc).
- `build_upload_payload` injecte distributor/region/keywords dans
  `extra` dict du UploadPayload.

### Lot R (UX/UI) — points clés

- 6 buckets score : **parfait** (=100, glow éclatant), **perfect**
  (95-99, glow atténué), ready, good, review, blocked.
- Code couleur uniformisé sur warnings : 🔴 rouge (≥10pts ou dup
  certain), 🟠 orange (5-9pts), 🔵 bleu (1-4pts info).
- Tous les blocs collapse via classe `.btn-collapse` + `data-target`,
  bouton qui dit "Afficher"/"Masquer" en alternance.
- Présentation et nom de release **masqués par défaut**.
- Tokens non reconnus groupés en une ligne : *« Tokens non reconnus :
  4K, 5 »* au lieu de N entrées séparées.

### Lot S (BBCode) — points clés

- `[center]` retire les `\n` internes pour permettre l'inline-centrage
  des images cast/poster (avant : `\n→<br>` empilait verticalement).
- `[img=W]`, `[img=WxH]`, `[img]` : trim permissif (`\s+`) pour gérer
  les URLs entourées de newlines. Placeholder visible si URL invalide
  au lieu de disparition silencieuse.

### Lot N (détection catégorie Gemini) — points clés

- `category_id_for(media_type, tmdb_context, release_name=...)` enrichi
  avec **priorité TMDB stricte** : si TMDB a matché (movie_id/tv_id/title/
  genres présents), on respecte TMDB. Les keywords Sports ne s'appliquent
  qu'en fallback. Le film F1 (TMDB 911430) reste FILM, une course F1
  réelle sans fiche TMDB tombe en SPORTS.
- `SPORTS_KEYWORDS` : ~70 entrées hardcodées (UFC, NFL, F1, FIFA, Tour de
  France, Wimbledon, WWE, etc.). Pré-trié par longueur décroissante pour
  que les keywords composites (`NBA.Finals`, `Super.Bowl`) gagnent.
- `category_guess_source(...)` : retourne un libellé humain affiché sous
  la dropdown catégorie pour transparence ("TMDB : genre 'Animation'",
  "Keyword sport detecté : 'F1'", "Defaut Films (TMDB sans match)").
- **Émission TV (cat 15) reste override-only** : trop ambigu à
  auto-détecter. Hint UI sous la dropdown invite l'user à override pour
  les talk-shows / télé-réalité / jeux télé.
- Catégories sans auto-détection : Émission TV (15), Livres (12), Jeux
  (3), Logiciels (17), Formations (18). L'app est positionnée pour
  Films / Séries / Anime / Docu / Sports.
- Nouveau signal `SIG_CATEGORY_LOW_CONFIDENCE` (pénalité -1 pt) émis
  quand l'auto tombe sur Films/Séries par défaut **sans** TMDB ni keyword.

### Lot K (compliance G3MINI durs) — points cl é s

- Nouvelle sévérité `Severity.BLOCKING` dans `compliance.py` : bloque le
  package en `FAILED` à la fin de `prepare` (avant l'upload). 9 checks
  ajoutés (C1 MKV, C2 MP3/FLAC, C3 PGS, C5 saison, C6 multi-team, C7 russe,
  C8 banned team, C9 EXTREME, C10 subs externes) + 1 check Lot M (CRF).
- Liste teams interdites configurable depuis `/config` via `BANNED_TEAMS`
  (séparateurs `,;\n`, kind=`textarea`, section "Conformité Gemini").
  Défauts hardcodés : `compliance.DEFAULT_BANNED_TEAMS = ("k0RE", "Slay3R")`.
  La liste configurée est ADDITIVE.
- Si tu ajoutes un check : `Severity.WARN` pour info, `Severity.ERROR` pour
  divergence visible (pénalise le score), `Severity.BLOCKING` pour règle
  dure Gemini (FAILED state).
