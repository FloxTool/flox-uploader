# flox-uploader

Application web locale pour préparer et uploader des releases vers les
trackers de torrents francophones (fork Unit3D). À partir d'un fichier
vidéo, elle génère **automatiquement** : nom de release scene-compliant,
fichier `.torrent`, NFO MediaInfo, fiche BBCode déterministe (TMDB + OMDb +
MediaInfo, **aucun appel LLM**), et upload vers le tracker avec dédup
préalable.

Le tracker [Gemini](https://gemini-tracker.org) est supporté en standard.
L'architecture est modulaire (un tracker = un sous-dossier de
`src/flox_uploader/trackers/`).

> **Statut** : produit en cours de packaging. Aujourd'hui le projet
> s'utilise via `pip install -e .` puis `flox-uploader serve`. La cible
> v1 publique est un installeur (PyInstaller `.exe` Windows / `docker
> compose` ailleurs) avec wizard first-run, pour que le user n'ait jamais
> besoin d'un terminal. Cf. [`AUDIT.md`](AUDIT.md) section "📦 Distribution
> & first-run UX" pour la roadmap.

## Ce qu'il fait

Pour chaque fichier vidéo donné en entrée, le pipeline produit dans
`data/upload_packages/<release_name>/` :

- **`<release_name>.torrent`** — fichier `.torrent` privé, source et
  announce du tracker injectés
- **`<release_name>.mediainfo.nfo`** — sortie MediaInfo brute (toujours
  présente) + un éventuel `<release_name>.nfo` scène recopié si fourni
- **`presentation.txt`** — fiche BBCode prête à coller, **générée de façon
  entièrement déterministe** à partir de TMDB + OMDb + MediaInfo, selon le
  template visuel du tracker
- **`release_name.txt`** — le nom de release normalisé selon les règles du
  tracker
- **`_debug/debug.json`** — JSON consolidé du run (parsing intermédiaire,
  signaux de fallback, score de confiance) — utile pour comprendre une
  décision du pipeline

Sous le capot : MediaInfo en CLI (texte + JSON), TMDB pour
titre/casting/genres/synopsis, OMDb pour note IMDb + récompenses + plot
fallback, `torf` pour le torrent, FastAPI + Jinja2 + Tailwind (CDN) pour la
web UI, SQLite pour la queue de jobs.

## Installation (mode dev, en attendant l'installeur)

### Pré-requis

- Python 3.10 ou plus
- [MediaInfo CLI](https://mediaarea.net/en/MediaInfo/Download) accessible
  dans le `PATH` (sera embarqué dans l'installeur final)
- Une clé TMDB (gratuite), une clé OMDb (gratuite), et l'announce URL de
  ton tracker (avec ta passkey personnelle)

### Étapes

```bash
git clone https://github.com/fremontlouis/flox-uploader.git
cd flox-uploader

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -e ".[web,dev]"
cp .env.example .env
# Édite .env et remplis tes 4 valeurs : TRACKER_ANNOUNCE,
# TMDB_API_KEY, OMDB_API_KEY, TRACKER_API_URL/TRACKER_API_KEY
```

La commande `flox-uploader` est maintenant disponible.

## Usage : web UI (le seul flux user-facing)

```bash
flox-uploader serve
# → ouvre http://127.0.0.1:8765/ dans ton navigateur
```

La web UI expose :

- **Inbox** : navigation dans tes dossiers, sélection multi pour ajouter à
  la queue
- **Queue** : préparations en cours, packages prêts, uploads (dry-run ou
  réel) avec log live, suppression batch
- **Page détail d'un package** : poster TMDB, score de confiance + détail
  des pénalités, NFO, log, overrides (variante FR forcée, TMDB ID manuel,
  release_name manuel verrouillé par défaut), boutons d'upload
- **Config** : édition `.env` depuis l'UI (secrets masqués), validation
  des paths/URLs

## Usage : CLI (power-user / scripting)

Conservée pour l'intégration Sonarr/Radarr post-import, la CI, et le debug.
**Pas exposée au user lambda dans le produit final.**

```bash
# Préparer un package (sans upload)
flox-uploader prepare "X:\path\to\Mon.Film.2024.MULTi.VFF.1080p.BluRay.x265-QTZ.mkv"

# Forcer la variante FR (quand le release name dit MULTi/FRENCH ambigu)
flox-uploader prepare "Mon.Film.mkv" --force-fr VFF

# Préparer + upload dry-run (montre le payload, ne POST rien)
flox-uploader prepare "Mon.Film.mkv" --upload --dry-run

# Préparer + upload réel
flox-uploader prepare "Mon.Film.mkv" --upload --no-dry-run

# Re-uploader un package déjà préparé
flox-uploader upload data/upload_packages/Mon.Film...

# Inspecter un torrent existant sur le tracker (debug)
flox-uploader inspect 12345 --tmdb-id-hint=67890
```

Variantes `--force-fr` : `VFF` (France), `VFQ` (Québec), `VFB` (Belgique),
`VF2` (multi-piste France+Québec), `VOF` / `VOQ` / `VOB` (originaux FR).

## Architecture

```
src/flox_uploader/
├── core/                  ← agnostique du tracker
│   ├── nfo.py             ← MediaInfo + parsing langue depuis NFO
│   ├── tmdb.py            ← TMDB + cache disque atomique
│   ├── omdb.py            ← note IMDb + récompenses + poster fallback
│   ├── mediainfo_parser.py ← parse MediaInfo JSON en structure exploitable
│   ├── flags.py           ← mapping langue/pays → drapeau emoji
│   ├── bbcode_renderer.py ← rendu déterministe de la fiche BBCode
│   ├── torrent.py         ← création .torrent
│   ├── release_name.py    ← normalisation pilotée par les règles du tracker
│   ├── naming_signals.py  ← signaux de fallback (cf. AUDIT.md §4)
│   ├── confidence.py      ← scoring 0-100 + 5 buckets visuels
│   ├── compliance.py      ← vérification charte (NFO ↔ release_name)
│   ├── media_type.py      ← détection film / épisode / saison / intégrale
│   ├── package_state.py   ← state machine + persist atomique
│   ├── jobs_db.py         ← SQLite queue de jobs (web UI)
│   ├── gemini_api.py      ← client Unit3D : dedup + upload
│   ├── upload_orchestrator.py ← orchestration dedup → upload → download
│   ├── debug.py           ← collecteur de debug consolidé
│   ├── http.py            ← retry HTTP
│   └── errors.py
├── trackers/
│   ├── base.py            ← dataclass Tracker (interface)
│   └── gemini/
│       ├── tracker.py
│       ├── rules.json     ← drop_tokens, replace_tokens, etc.
│       ├── template_*.bbcode ← templates par type média (movie/episode/season/integrale)
│       └── unit3d_mapping.py ← mapping IDs catégories/types/résolutions
├── web/
│   ├── app.py             ← routes FastAPI
│   ├── jobs_runner.py     ← background worker (thread pool)
│   ├── config_view.py     ← schema + read/write/validate du .env
│   └── templates/         ← Jinja2 + Tailwind CDN
├── pipeline.py            ← orchestrateur (1 fichier → 1 package)
├── cli.py                 ← entry points (power-user / scripting)
└── config.py              ← paths runtime + chargement .env
```

## Ajouter un tracker

1. Dupliquer `src/flox_uploader/trackers/gemini/` en
   `src/flox_uploader/trackers/<nouveau>/`
2. Adapter `rules.json` (tokens à drop/replace, listes de codecs, etc.) aux
   conventions du nouveau tracker
3. Adapter les `template_*.bbcode` à la charte BBCode du nouveau tracker
   (placeholders `{title}`, `{header_line}`, `{audio_block}`, etc.)
4. Dans `tracker.py`, créer une fonction `load_<nom>_tracker(announce_url)`
   qui retourne une instance `Tracker` correctement renseignée
   (`torrent_source`, `default_team`, etc.)
5. Enregistrer le loader dans `trackers/__init__.py`

Le nouveau tracker est ensuite utilisable via `--tracker <nom>` côté CLI ou
visible dans la liste de la web UI.

## Sécurité

- `.env` contient ta passkey de tracker et tes clés API : il est dans
  `.gitignore`. Ne le commit jamais.
- Si une fuite arrive, **rotate immédiatement** : nouvelle passkey sur ton
  profil tracker, nouvelle clé TMDB / OMDb.
- Le repo n'inclut aucune donnée de `data/` (output, cache, jobs.db).
- La web UI bind 127.0.0.1 par défaut (local-only). Cf. [`AUDIT.md` §5.1](AUDIT.md) pour
  les implications si tu utilises `--host 0.0.0.0`.

## Licence

MIT.
