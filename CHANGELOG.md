# Changelog

Toutes les modifications notables sont listées ici.

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionning [Semantic Versioning](https://semver.org/lang/fr/).

---

## [Unreleased]

_Aucun changement non publié pour le moment._

---

## [0.3.14] — 2026-05-20

### Corrigé

- **🔴 Lien "Voir sur Gemini" toujours invisible après v0.3.13** : le fix v0.3.13
  acceptait `/torrents/` (pluriel) avec `[/?#$]` après l'ID. Mais Gemini renvoie
  en pratique `/torrent/download/19394.d289e42ad96d9089142351b9761e3655`
  (**singulier** `torrent` + `.` puis passkey 32 chars). La regex ne matchait pas.

  Capture du log d'upload récent (Les Trois Mousquetaires) :
  ```
  [WARN] _parse_torrent_id_from_url : aucun id parsable dans le path
  '/torrent/download/19394.d289e42ad96d9089142351b9761e3655'
  ```

  Fix : la regex accepte maintenant `torrent[s]?` + n'importe quel non-digit
  comme séparateur post-ID. +2 tests pour ce format spécifique.

### Ajouté

- **Section "Log d'upload" sur la page détail** : pour les packages en état
  `uploaded`, `failed` ou `aborted_duplicate`, un bouton "Afficher" charge
  le log complet de l'upload dans un `<pre>` collapsible. Permet de
  consulter le log après coup (le SSE stream ne marchait qu'en live).
  Nouvel endpoint `GET /api/uploads/{name}/log`.

---

## [0.3.13] — 2026-05-19

### Corrigé

- **🔴 Lien "Voir sur Gemini" invisible sur la page détail d'un upload réussi** :
  cas observé sur ton upload `Elio.2025...` (log : `torrent ID None`, `Page tracker:` vide).
  Cause : `_parse_torrent_id_from_url` ne matchait pas le format d'URL réellement
  renvoyé par Gemini → `torrent_id` toujours `None` → `uploaded_torrent_url` vide
  → la condition `{% if state == 'uploaded' and uploaded_torrent_url %}` du
  template échouait → pas de lien affiché.

  Fix : stratégie en 3 passes (pattern spécifique `/torrents/<id>` en priorité,
  puis fallback `/(\d+)` générique avec le dernier match, puis log explicite si
  rien ne match). 10 nouveaux tests `_parse_torrent_id_from_url`.

  **Limitation** : les packages déjà uploadés (avant ce fix) garderont leur
  `uploaded_torrent_url` vide en base. Le lien réapparaîtra pour les nouveaux
  uploads. Pour les anciens, soit ré-upload, soit éditer manuellement le state.

### Ajouté

- **Bouton "Ouvrir le dossier du `.torrent` uploadé"** sur la page détail
  d'un package en état `uploaded`. Le path affiché et ouvert priorise
  `TORRENT_FINAL_DIR` (watch folder qBittorrent / Transmission configuré
  dans `.env`) puis tombe sur le parent de `final_torrent_path` (= le
  `.torrent` final avec passkey dans le `package_dir`).
- Nouvel endpoint `POST /api/packages/{name}/open-torrent-folder`.

---

## [0.3.12] — 2026-05-19

Batch de 7 notes UX issues de `NOTES.md`.

### Corrigé

- **Terminal popup pendant les prepares** : sur Windows en bundle, le subprocess
  `prepare` ouvrait une fenêtre console qui pop au premier plan et volait le
  focus pendant la frappe utilisateur. Fix : `creationflags=CREATE_NO_WINDOW`
  passé à `subprocess.Popen` (no-op sur autres OS, le kill reste OK).
- **Sélection perdue dans "Préparations en cours" au reload auto** : la liste
  des jobs cochés disparaissait quand le polling de queue déclenchait un
  `window.location.reload()` (quand un job finissait par ex). Fix : persistance
  `sessionStorage` (`tu_queue_prep_selection_v1`), restaure au mount.

### Modifié

- **Colonne "Mode" retirée** de la table Uploads (vestige du dry-run obsolète).
- **Shift-click + check-all** sur la section "Préparations en cours" (existait
  déjà sur "Packages prêts" et Inbox — uniformisation).
- **Suppression d'un package uploadé autorisée** (avant : HTTP 409 + bouton
  caché). Garde-fou : la confirmation tape-le-nom reste. La zone dangereuse
  affiche maintenant un warning supplémentaire pour les uploadés : "recréer
  ce package créera un .torrent avec un infohash différent, non reconnu par
  le tracker".
- **Sélection des packages uploadés autorisée** sur la page Queue (avant :
  checkbox cachée). Bouton "Uploader" continue d'exclure les uploadés via
  filter `state in {prepared, validated}` — pas de risque de double upload.
- **Bouton "Ouvrir le dossier source"** sur la page détail (à côté de la
  ligne Source). Nouvel endpoint `POST /api/packages/{name}/open-source-folder`
  qui ouvre le parent du `.mkv` original dans l'Explorateur OS.

---

## [0.3.11] — 2026-05-19

Hotfix v10 — le bouton "Vérifier les mises à jour" mentait silencieusement.

### Corrigé

- **🔴 "Vérifier les mises à jour" affichait "À jour" même quand fetch GitHub échouait** :
  cas observé chez Louis sur v0.3.9 — il cliquait le bouton, le toast disait
  "À jour" alors que v0.3.10 venait de sortir. Cause : le silent fail (`except: pass`)
  cachait l'échec, le code lisait l'ancien cache (`latest=v0.3.9`), `is_newer`
  retournait False → toast "À jour" trompeur.

  Fix : `_fetch_latest_release()` retourne maintenant `(data, error_msg)`.
  L'erreur remonte jusqu'à l'endpoint `POST /api/update-info/refresh` qui
  retourne `{info, fetch_error}`. Le JS distingue :
  - `fetch_error == ""` + `info.available == True` → toast success "Nouvelle version vX.Y.Z"
  - `fetch_error == ""` + `info.available == False` → toast info "À jour"
  - `fetch_error != ""` → toast **danger** "Vérification impossible : `<raison>`" + bouton "Échec — réessayer"

  Messages d'erreur explicites : HTTP 4xx/5xx, timeout, connection refused, JSON invalide.

---

## [0.3.10] — 2026-05-19

Hotfix v9 — finit le travail de v0.3.9 qui ne suffisait pas.

### Corrigé

- **🔴 Subprocess prepare encore cassé en bundle (round 2)** : le fix v0.3.9
  appelait `[Flox Uploader.exe, "prepare", ...]` au lieu de `[exe, "-m", ...]`.
  Sauf que l'entry point du bundle est `launcher.py` (pas `cli.py`), qui a
  son propre argparse limité à `--host/--port/--no-browser/--insecure-host`.
  Résultat : *"unrecognized arguments: prepare ..."* — même symptôme que avant.

  Fix : `launcher.py` détecte si le 1er argument est une sous-commande connue
  (`prepare/upload/inspect/serve`) et délègue à `cli.main()` qui sait router
  via argparse subparsers. Sans args ou avec `--host/--port` : mode launcher
  classique (serve avec defaults) — comportement double-clic préservé.

---

## [0.3.9] — 2026-05-16

Hotfix critique : impossible de préparer un package depuis l'installeur Windows
v0.3.8 (régression depuis le bundling Sprint 5).

### Corrigé

- **🔴 Subprocess prepare cassé en bundle PyInstaller** : `jobs_runner.py` lançait
  le subprocess avec `[sys.executable, "-m", "flox_uploader.cli", "prepare", ...]`.
  En mode dev Python ça marche. En mode `.exe` PyInstaller, `sys.executable` est
  l'app elle-même (pas Python) → l'app reçoit `-m flox_uploader.cli prepare ...`
  comme arguments et argparse lève *"unrecognized arguments"*. Tous les jobs
  échouaient immédiatement avec cette erreur.

  Fix : détection `getattr(sys, "frozen", False)` (set par PyInstaller).
  En bundle : `[sys.executable, "prepare", ...]` (l'.exe route directement via
  argparse). En dev : pattern `-m` inchangé.

  Régression introduite par Sprint 5 (bundling Windows) mais révélée seulement
  maintenant que Louis essaie d'uploader pour de vrai depuis sa version installée.

---

## [0.3.8] — 2026-05-15

Hotfix Sprint 8 + batch de notes utilisateur. Régression critique du Sprint 8
réglée + 7 améliorations issues de `NOTES.md`.

### Corrigé

- **🔴 Régression JS Sprint 8** : `tu.toast` / `tu.showPageLoader` étaient
  cassés par un escape JS invalide dans `tu.buildBugReport` (`'## Message
  d\\'erreur'` créait une syntax error qui plantait tout le `<script>`).
  Conséquences en cascade : plus de loader entre les pages, plus de toast
  de confirmation après "Ajouter à la queue". Fix : remplacement par
  `"## Message d'erreur"` (double-quotes) + correction des `'\\n'` en `'\n'`.
- **Navigation Queue → Inbox bloquée pendant une préparation** : ancien
  handler avec `preventDefault()` + `setTimeout(50ms)` censé fermer les
  EventSources avant la nav annulait parfois la nav silencieusement.
  Simplifié : close synchrone, le browser navigue naturellement.
- **Checkbox "Tous les fichiers" dans Inbox ne filtrait pas correctement** :
  par défaut on affichait toujours les NFO / posters / sous-titres même
  quand la checkbox était décochée. Maintenant : décoché = dossiers + vidéos
  uniquement, coché = tout (NFO, posters, subs, archives, exotiques).
  Label renommé en "Afficher tout" + tooltip explicatif.
- **`HE-AAC` / `AAC-LC` sortaient en `He-aac` / `Aac-lc`** : ajout dans
  `_CANONICAL_CASE` et `_MEDIAINFO_TO_GEMINI_AUDIO_CODEC` pour préserver
  la casse. Les 3 tokens sont valides selon `rules.json` (Gemini).

### Ajouté

- **Pagination Inbox côté client** : sélecteur `25 / 50 / 100 / 200 / 400 / Tout`
  (par défaut 50, persisté en localStorage), navigation pages en haut et en bas,
  numéros de pages style "1 … 4 5 6 … 12" pour les gros dossiers. Sélection
  conservée à travers les pages. Compatible avec la recherche live et le
  filtre "Afficher tout". Cachée si 0 élément.
- **Click n'importe où sur une row Inbox toggle la checkbox** : même UX que
  Queue. Les clicks sur les liens (navigation sous-dossier) et les boutons
  sont préservés (pas de double-trigger).

### Modifié

- **Page Config — placeholder secret dynamique** : à l'ouverture, chaque
  champ secret affiche autant de puces `●` que la vraie clé a de caractères
  (avant : `***` fixe qui faisait croire que le champ était vide). Le bouton
  œil reveal toujours la vraie valeur. Détection "non modifié" côté POST
  accepte l'ancien sentinel `***` (backward compat) et le nouveau format.
- **Defaults Gemini pré-remplis** : `TRACKER_API_URL = https://gemini-tracker.org/api`
  et `BANNED_TEAMS = Slay3R, k0RE` arrivent pré-remplis au premier setup.
  Réduit le travail user vu qu'on ne supporte que Gemini en v1. (Comportement
  hardcodé compliance.py inchangé : les 2 teams restent bloquées même si
  l'user vide le champ.)

---

## [0.3.7] — 2026-05-15

Sprint 8 de `PLAN-V1.md` — **Crash report helper**. Quand quelque chose
plante, l'user peut signaler le bug en 2 clics avec un contexte technique
complet et zéro effort.

### Ajouté

- **Module `core/diagnostic.py`** :
  - `collect_diagnostic()` retourne version Flox + Python + OS + release +
    statut MediaInfo (présence + version) + statut setup.
  - `build_markdown_report()` produit le payload Markdown utilisé pour le
    presse-papier et l'URL pré-remplie GitHub Issues.
  - Cap automatique des messages d'erreur > 2000 chars (limite URL GitHub).
  - Aucun secret dans le payload (pas de clé API, pas de passkey, pas de
    paths absolus) — sûr à coller dans une Issue publique.
- **Endpoint `GET /api/diagnostic`** : retourne le dict structuré, sans secret.
- **Jinja global `app_diagnostic()`** : diagnostic injecté en JS global
  `window.APP_DIAGNOSTIC` sur toutes les pages, accessible sans round-trip API.
- **Bouton "Copier rapport"** dans tout toast `tone='danger'` :
  - Click → copie un rapport Markdown dans le presse-papier
    (version, OS, page courante, message d'erreur).
  - Feedback visuel : bouton devient "Copié" en vert.
- **Section "Signaler un bug" dans la page Guide** :
  - Bouton primary "Signaler un bug sur GitHub" qui ouvre directement
    l'Issue avec template `bug.yml` pré-rempli (version + os déjà cochés).
  - Pédagogie courte sur ce qui aide à résoudre vite.
- **Helpers JS** : `tu.buildBugReport({errorTitle, errorMessage})` et
  `tu.openBugReport({...})` réutilisables depuis n'importe quel script UI.
- **14 nouveaux tests** : détection OS / MediaInfo (mock subprocess),
  troncature longs messages, structure du Diagnostic, absence de secrets
  dans le rapport, endpoint `/api/diagnostic`, injection JS, rendu section
  Guide, présence des helpers JS dans base.html.

### Notes

- Cohérent avec la philosophie local-first (D10/D11) : aucun backend Flox
  n'est sollicité, tout transite par GitHub Issues que tu reçois en notifs.
- Pas de capture automatique des stack traces serveur en v1 — le scope
  actuel couvre les erreurs visibles dans l'UI (toasts) et le bug report
  manuel. Capture serveur globale envisageable v0.5+.

---

## [0.3.6] — 2026-05-15

Sprint 6 de `PLAN-V1.md` — **Auto-update v1**. L'app sait quand une nouvelle
version sort, sans aucune télémétrie en sortie.

### Ajouté

- **Module `core/update_check.py`** :
  - Fetch GitHub `/releases/latest` (exclut auto les pre-releases côté API).
  - Cache disque `data/.update_cache.json`, TTL 6h sur succès, conservé
    indéfiniment sur échec (silent fail offline / rate-limit / 5xx).
  - Comparateur semver strict : accepte `X.Y.Z` uniquement, rejette tout
    suffixe (`-rc1`, `-beta`, `+build`). Garde-fou défensif si une
    pre-release sneak quand même.
  - Refresh asynchrone via thread daemon (lock + idempotent). Non bloquant
    pour le boot serveur et le rendu des pages.
- **Endpoint `GET /api/update-info`** :
  - Lit le cache (instantané), déclenche un refresh background si stale.
  - Retourne `{available, current, latest, release_url, release_notes, fetched_at}`.
- **Banner UI "Nouvelle version disponible"** dans `base.html` :
  - Affiché en haut de toutes les pages, **masqué sur `/setup`** (décision
    figée PLAN-V1 §1.6 : ne pas perturber l'onboarding).
  - Couleurs primary (indigo, charte). Icône `sparkles`.
  - Bouton "Voir le détail" → ouvre GitHub Releases dans un nouvel onglet.
  - Bouton "×" dismiss per-version (localStorage `tu_dismissed_update_<latest>`).
    Quand une nouvelle release sort, la clé change → le banner revient.
- **57 nouveaux tests** : parsing semver, cache disque atomique, JSON corrompu,
  silent fail (404/403/503/network), refresh stale logic, endpoint smoke tests,
  banner rendering conditionnel.

### Notes

- Aucune télémétrie en sortie : on lit `/releases/latest`, on n'envoie aucune
  donnée user. Cohérent avec la philosophie local-first (D10).
- Pas d'auto-download / restart en v1 (cf. D16). Trop de cas d'erreurs
  (droits admin, rollback) pour 20 users. L'user clique le banner → page
  GitHub Releases → télécharge l'installeur lui-même.

---

## [0.3.5] — 2026-05-15

Sprint 5 de `PLAN-V1.md` — **bundling Windows**. Premier release publiable à
partir d'un installeur double-clic, sans Python ni venv côté user.

### Ajouté

- **Installeur Windows `FloxUploader-Setup-X.Y.Z.exe`** (Inno Setup 6) :
  - Install per-user (`%LOCALAPPDATA%\Programs\Flox Uploader\`), pas d'UAC.
  - Raccourci Menu Démarrer (toujours) + Bureau (option décochable).
  - Case "Lancer Flox Uploader" en fin d'install.
  - Désinstallation propre via "Ajout/Suppression de programmes" ; les
    data user (`%LOCALAPPDATA%\fremontlouis\flox-uploader\`) sont
    préservées car en dehors de `{app}`.
  - `CloseApplications=force` : reinstall silencieuse même si l'app
    tourne encore (skip le prompt "L'application est en cours d'utilisation").
- **`.exe` PyInstaller portable** (`FloxUploader-X.Y.Z-Windows-x64.zip`)
  publié en parallèle de l'installeur, pour les users qui préfèrent
  `unzip + double-clic`.
- **MediaInfo CLI Windows embarqué** dans le bundle
  (`packaging/vendor/mediainfo/`, pinned 24.06, téléchargé depuis
  mediaarea.net via `packaging/fetch_mediainfo_windows.py`). Plus besoin
  d'installer MediaInfo séparément.
- **Icône Flox** (`packaging/icon.ico`) générée depuis `logo.svg` via
  `resvg-py` + Pillow, multi-tailles (16/24/32/48/64/128/256). Visible
  sur le `.exe`, le `setup.exe`, et les raccourcis Menu Démarrer + Bureau.
- **Workflow GitHub Actions `Build Windows .exe`** :
  - Trigger : `workflow_dispatch` (manuel) + `push` sur tag `v*`.
  - 3 smoke tests : `--help` (argparse), boot uvicorn avec stdout
    redirigé (lisibilité des stack traces), mode windowed sans redirect
    (reproduit les conditions double-clic) + HTTP `/setup` 200.
  - Sur tag `v*` : draft GitHub Release auto avec setup.exe + ZIP.

### Retiré

- **Feature "migration data legacy"** (v0.3.4) : la détection automatique
  d'un `<repo>/data/` orphelin + bannière d'import dans l'UI a été retirée.
  Raisons :
  - En mode packagé, `PROJECT_ROOT` pointe vers le bundle (pas le repo),
    donc la détection auto ne pouvait pas fonctionner.
  - Les futurs users ne clonent jamais le repo — ils n'auront pas de data
    "legacy" orphelin.
  - La fonctionnalité ne servait essentiellement personne.
  - Conservé : `platformdirs` actif, Protocol `TrackerClient`, backward
    compat env var `TRACKER_UPLOADER_DATA_DIR`.
  - Si besoin futur (import explicite Win → Mac, backup/restore) on
    ajoutera un bouton "Importer un dossier" avec sélecteur de path.
- 14 tests `test_distribution_prep.py` qui couvraient cette feature
  retirée. 2 tests `TrackerClient` Protocol conservés.

### Corrigé

- **Launcher PyInstaller** : `from .cli` → `from flox_uploader.cli`
  (absolute import obligatoire en script top-level).
- **sys.stdout/stderr `None`** en mode windowed PyInstaller : patch
  vers `os.devnull` au tout début du launcher, AVANT tout import.
  Évite `AttributeError: 'NoneType' object has no attribute 'isatty'`
  d'uvicorn.
- **Test `test_bucket_thresholds` flaky sur Windows** : ajout
  `invalidate_score_cache(pkg)` entre chaque réécriture de debug.json.
  La résolution mtime Windows était insuffisante pour invalider le cache
  entre 3 écritures rapides.

---

## [0.3.4] — 2026-05-14

Sprint 4 de `PLAN-V1.md` — **préparation distribution**. Pose les fondations
nécessaires au passage en mode packagé (Sprint 5).

### Corrigé

- **Migration SQLite défensive** (`jobs_db._add_column_idempotent`) : la CI
  Python 3.12 plantait avec `sqlite3.OperationalError: duplicate column name`
  malgré le check `if col not in cols` qui précédait l'ALTER. Cause probable :
  changement de comportement `executescript()` en Python 3.12. Fix : helper
  qui swallow l'erreur "duplicate column" (idempotent), re-raise tout le reste.
  Pré-existait depuis Lot F2, juste révélé par les nouveaux tests Sprint 4.

### Ajouté

- **Détection automatique du data legacy** (`config.legacy_data_dir()`) :
  quand l'app tourne en mode packagé et qu'il y a un `<repo>/data/` avec
  des packages, on le signale comme migration possible. En mode dev, retourne
  toujours `None` (le `<repo>/data/` EST le data_dir actuel).
- **Stats descriptives** (`config.legacy_data_stats()`) : nombre de packages,
  taille totale, présence de .env / jobs.db / .tmdb_cache.json. Pour le
  preview UI avant import.
- **Migration douce** (`config.migrate_legacy_data()`) :
  - **Non-destructive** : on COPIE (jamais move). Le legacy reste intact.
  - **Skip overwrite** : si un package existe déjà dans target, on ne touche
    pas. Idem pour .env / jobs.db / .tmdb_cache.json.
  - **Dry-run** : `dry_run=True` simule sans rien copier (preview UI).
  - **Couvre** : `upload_packages/`, `.env` (data + racine repo legacy),
    `jobs.db`, `.tmdb_cache.json`.
- **Endpoint `GET /api/data-dir/legacy-status`** : retourne
  `{available, legacy_path, current_path, stats}` pour piloter la bannière UI.
- **Endpoint `POST /api/data-dir/migrate`** : lance la migration (avec
  `?dry_run=true` optionnel pour preview).
- **Bannière UI dans `base.html`** : visible sur toutes les pages quand un
  legacy est détecté. Non-bloquante (l'user peut dismisser via localStorage).
  Click "Importer" → preview via dry-run + confirm modal + migration réelle
  + toast de succès + reload de la queue.
- **Protocol `TrackerClient`** dans `trackers/base.py` : interface
  structurelle (duck typing) pour les futurs clients tracker. `GeminiClient`
  satisfait le protocole sans modification. Permettra d'ajouter des trackers
  en v0.5+ sans refactor du code applicatif.
- **16 nouveaux tests** dans `test_distribution_prep.py` couvrant détection,
  stats, migration (dry-run + réel + skip overwrite), endpoints HTTP,
  Protocol TrackerClient.

### Notes

- `platformdirs` était déjà actif dans `_default_data_dir()` (mode dev →
  `<repo>/data/`, mode packagé → `%APPDATA%\fremontlouis\flox-uploader\`).
- `webbrowser.open()` + port dynamique déjà actifs dans `cmd_serve`.

---

## [0.3.3] — 2026-05-14

Sprint 3 de `PLAN-V1.md` — **OMDb pleinement optionnel** : un user qui choisit
de ne pas configurer OMDb n'est plus pénalisé sur son score de confiance.

### Modifié

- **Pipeline** (`pipeline.py`) : `SIG_OMDB_DATA_MISSING` ne s'émet plus quand
  `OMDB_API_KEY` est absent. Avant : tout package perdait -1 pt + voyait un
  warning "Pas de note IMDb / récompenses (OMDb non disponible)" même si
  l'user n'avait jamais configuré OMDb. C'était pénaliser un choix explicite.
- **Pipeline** : flag debug `omdb_not_configured: true` quand la clé est
  absente (trace pour debug, pas un warning visible côté UI).
- **BBCode** (`_build_awards_section`) : retour vide pour les inputs
  whitespace-only et None (plus défensif). Évite les sections "Récompenses"
  fantômes avec titre mais sans contenu.

### Conservé

- Le signal `SIG_OMDB_DATA_MISSING` s'émet toujours quand l'user **a une clé
  OMDb configurée** mais que l'API ne renvoie rien (cas légitime — la donnée
  manque vraiment).
- Lot O.5 conservé : films sortis < 6 mois ne déclenchent pas le signal (délai
  d'indexation OMDb attendu).
- Le `/setup` documente déjà OMDb comme "Optionnel mais encouragé" (Sprint 2).

### Ajouté

- **8 nouveaux tests** (`test_omdb_optional.py`) qui couvrent :
  - `fetch_omdb_data` sans clé → retour vide + flag debug
  - `fetch_omdb_data` sans IMDB ID → retour vide sans flag (cas neutre)
  - Métadonnée du signal `SIG_OMDB_DATA_MISSING`
  - `_build_awards_section` : vide / whitespace / N/A / NONE / texte réel
  - Confidence score : pas de pénalité quand le signal n'est pas émis
  - Confidence score : pénalité présente quand le signal est explicitement émis
  - Logique conditionnelle du pipeline en isolation

---

## [0.3.2] — 2026-05-14

Sprint 2 de `PLAN-V1.md` — amélioration de la page `/setup` pour qu'un user
puisse compléter sa config en < 5 min sans aide externe.

### Ajouté

- **Endpoint unifié `POST /api/config/test-key`** qui gère 4 kinds :
  - `tmdb` : ping `https://api.themoviedb.org/3/configuration`
  - `omdb` : ping OMDb avec un IMDb ID connu, détecte les erreurs "Invalid API key" et "Request limit reached"
  - `tracker` : ping `{api_url}/torrents/filter?id=1` avec Bearer auth
  - `announce` : valide le format de l'URL announce (scheme, host, /announce, passkey présente)
- **Badges de statut inline** sur la page `/setup` : `Non testé` / `Test en cours…` / `OK` / `Erreur`, avec animation pulse pour le loading state, et reset auto au moindre changement du champ
- **Test buttons pour OMDb et URL announce** (manquaient ; seuls TMDB et tracker en avaient un)
- **Welcome state au premier run** : hero différencié avec emoji 👋, animation `hero-in`, message rassurant "tout reste local"
- **Pédagogie renforcée** : 1 phrase "à quoi ça sert" par section, hints sous chaque champ (où trouver, ce qui se passe sans)
- **Réorganisation** : 3 sections logiques (Métadonnées / Tracker / Préférences) au lieu de 4 étapes plates
- **CI** : env var `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` pour anticiper la deprecation Node 20
- **23 nouveaux tests** dans `test_config_test_key_endpoint.py` (couvre les 4 kinds + erreurs + backward compat + welcome state)

### Modifié

- Page `/setup` : refonte complète du HTML pour utiliser les nouvelles sections, badges, et endpoint unifié. La logique JS est entièrement réécrite mais le contrat avec le backend reste rétro-compatible.

### Conservé (backward compat)

- Endpoints legacy `/api/setup/test-tmdb` et `/api/setup/test-tracker` (marqués DEPRECATED) — délèguent au nouveau code. À retirer dans une release future après vérification qu'aucun script externe ne les utilise.

### Corrigé

- **CI GitHub Actions** plantait sur `test_validate_endpoint.py` (et autres tests web) avec `ModuleNotFoundError: No module named 'fastapi'` — le workflow installait `[dev]` seulement, manquait le groupe `[web]`. Maintenant `pip install -e .[web,dev]`.

---

## [0.3.1] — 2026-05-13

Sprint 1 de `PLAN-V1.md` — rebranding complet et hygiène repo pour préparer la
release publique v0.4.0.

### Ajouté

- `LICENSE` MIT à la racine (Copyright Flox)
- `CHANGELOG.md` (ce fichier, format Keep a Changelog)
- `CONTRIBUTING.md` (workflow PR, style code, tests)
- `SECURITY.md` (politique de signalement vuln)
- Issue templates GitHub (bug / feature / question + config)
- GitHub Actions workflow `tests.yml` (matrix Python 3.10/3.11/3.12, MediaInfo CLI installé en CI)
- Disclaimer légal dans la page `/guide` (section "Ta responsabilité")
- Backward compat env var : `TRACKER_UPLOADER_DATA_DIR` continue à fonctionner pendant la transition

### Modifié

- **Refactor complet** : package Python `tracker_uploader` → `flox_uploader`
  - Dossier `src/tracker_uploader/` → `src/flox_uploader/`
  - 373 occurrences remplacées sur 58 fichiers
  - Tous les imports, paths, env vars, strings UI alignés
- Slug PyPI/repo : `tracker-uploader` → `flox-uploader`
- Strings UI "Tracker Uploader" → "Flox Uploader" sur 8 templates
- Env var canonique : `TRACKER_UPLOADER_DATA_DIR` → `FLOX_UPLOADER_DATA_DIR`
- URL repo dans `pyproject.toml` : `github.com/FloxTool/flox-uploader`
- Auteur dans `pyproject.toml` : `Flox` (au lieu du nom personnel)

### Notes

- 622 tests verts (aucune régression du refactor)
- Aucun changement de comportement utilisateur — strict refactor de naming

---

## [0.3.0] — 2026-05-13

Première release "premium UI" — l'app passe d'un outil fonctionnel à un
outil professionnel polishé. Voir `PLAN-V1.md` pour le contexte stratégique
et `CHARTE.md` pour le design system résultant.

### Ajouté

- **Design system complet** (round 8 — "premium UI sprint")
  - Tokens unifiés : couleurs sémantiques (primary indigo, success emerald, warning amber, danger red, neutral slate)
  - Échelle d'espacement 4px-grid documentée
  - Typographie Inter + JetBrains Mono avec letter-spacing serré sur h1/h2
  - Échelle de durées (180ms / 240ms / 320ms) + easing custom `cubic-bezier(0.16, 1, 0.3, 1)`
  - Classe `.interactive` (active scale 0.97, transitions unifiées, disabled state)
- **Tooltip v2** (`data-tu-tooltip`)
  - Timing 220ms show / 80ms hide, focus clavier supporté
  - Flèche pointée, ARIA `role="tooltip"` + `aria-describedby` auto
  - Support `<kbd>` inline pour raccourcis (`data-tu-tooltip-kbd`)
  - Migration de 29 `title="..."` HTML natifs vers `data-tu-tooltip` sur 5 templates
- **Command palette** ⌘K / Ctrl+K avec navigation clavier, recherche fuzzy
- **Smart collapsibles** sur Override naming + Options upload (auto-expand si override actif)
- **Sticky upload action bar** (apparaît quand on scrolle past la section Upload)
- **Sticky TOC right rail** (xl+) avec scrollspy actif
- **Empty state inline** dans la queue quand filtres/search masquent tout
- **Skeleton loader** (`tu-skeleton` shimmer) sur le tree view torrent
- **Helper `tu.button(el, asyncFn)`** : spinner inline + disabled + toast d'erreur auto
- **Active filter pills** style Linear au-dessus de la table queue
- **Rows queue entièrement cliquables** vers package detail (avec respect Cmd/Ctrl/middle-click)
- **Modal focus selon destructivité** (anti-accident sur tone danger/warning)
- **Cmd+K hint pulse** au 1er load (jusqu'à la 1ère utilisation, gated localStorage)
- **Drapeau canadien 🇨🇦** pour les variantes VFQ / VF2 / VOQ (per-track audio + sous-titres)
- **Réalisateur / créateur** dans la carte Media (depuis TMDB `director` / `created_by`)
- **Tree view hiérarchique** du contenu du torrent (carets repliables, agrégation taille + count par dossier)
- **Inbox toggle "Tous les fichiers"** (par défaut : vidéos + companions seulement)
- **Endpoint `/api/packages/{name}/rescore`** : re-exécute compliance check sans regénérer le .torrent (préserve l'infohash)
- **Endpoint `/api/packages/{name}/dedup-check`** : re-vérifie les doublons cote tracker
- **Bouton "Valider sans uploader"** (PREPARED ↔ VALIDATED) pour workflow batch
- **Queue filters** repensés en chips colorés par tone (état + score bucket), dropdown discret
- **Banner setup_incomplete** persistant sur toutes les pages tant qu'une clé essentielle manque
- **Page `/setup` dédiée** au premier lancement
- **Guide page complètement repensée** (round 9 Q2) avec périmètre v0.3 explicite, philosophie outil-pas-autopilote, pièges courants

### Modifié

- **Bug-1** : pagination pending_jobs > 100 (était cappé à 99) — bumpé `list_jobs(limit=10000)` sur les 3 call-sites
- **Bug-2** : "Contenu du torrent" affiche maintenant une vraie hiérarchie (avant : flat list)
- **Bug-3** : "select all" dans queue ne touche que les rows visibles (respecte les filtres)
- **UX-1** : message d'erreur "déjà uploadé au tracker" raccourci à 1 phrase claire
- **UX-2** : détection per-track des variantes francophones (VFQ/VF2 → 🇨🇦, VFB → 🇧🇪)
- **Background colors HTML root** appliqué AVANT que Tailwind charge (zéro flash blanc dark mode au boot)
- **Z-index ladder** documenté et organisé (tooltips 80, toasts 70, cmdk 60, modals 55, …)

### Corrigé

- `test_c3_pgs_only_in_encode_is_warn_not_blocking` : règle revisée — PGS dans encode avec subs texte = OK, PGS uniquement = WARN (au lieu de BLOCKING)
- Sticky filter-chip transitions remplacées par `.interactive` (active scale + ease-tu)
- Confirm modal Enter key respecte le focus actuel (Enter sur cancel = cancel, Enter sur confirm = confirm)
- Tooltip ne reste plus accroché en scroll de page

---

## [0.2.x] — historique condensé

Cette section condense le travail des rounds 2 à 7 (de v0.1.0 jusqu'à pre-v0.3.0).
L'historique détaillé est dans `NOTES.md`.

### Ajouté pendant les rounds 2-7

- State machine `PackageState` (PREPARED / VALIDATED / UPLOADED / ABORTED_DUPLICATE / FAILED) avec transitions strictes
- Pre-check de doublon anticipé (avant `create_torrent`) basé sur `try_check_duplicate` + TMDB ID + size_bytes
- Dedup confidence levels : CERTAIN / VERY_LIKELY / AMBIGUOUS / NONE
- Workflow batch upload : sélection multi + upload séquentiel via `/api/queue/upload-selection`
- Compliance check Gemini (codecs audio, PGS, container, teams interdites, season completeness, multi-team-in-pack, banned-teams config user)
- Score de confiance (0-100) avec buckets : parfait / quasi / prêt / à vérifier / bloqué
- TMDB v3 API : recherche, fiche détaillée, credits, external_ids, release_dates, keywords
- OMDb : note IMDB + récompenses
- Confidence cache mémoire avec invalidation par mtime debug.json + state.json
- BBCode preview avec édition + reset + save autonome
- Bundle multi-fichiers : un torrent avec plusieurs items (film + poster + NFO)
- Force FR variant : override manuel VFF / VFQ / VFB / VOF / VOQ / VOB
- Re-prepare avec options (override de force_fr, TMDB ID, release_name)
- Drag-and-drop reorder de la queue
- Pause / resume / move-up / move-down sur les jobs pending
- Detection de jobs "stuck" (preparing depuis > N min sans update)
- Persistance de sélection queue en sessionStorage
- Filtres queue par état + score bucket, persistance localStorage
- Search input avec clear button universel (`.tu-search-wrap` + `.tu-search-clear`)
- Skip-to-content link (a11y)
- Mobile drawer sidebar (< md)

---

## [0.1.0] — initial

MVP CLI + UI minimale couvrant prepare + upload + history.
