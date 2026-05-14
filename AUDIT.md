# AUDIT — flox-uploader (2026-05-06, rev 2.2)

> Audit honnête du codebase. **Rev 2** : ré-évalué dans la grille **produit
> final = web UI packagée user-friendly** (Docker + PyInstaller, cible
> uploadeurs amateurs, tout passe par l'UI).
>
> **Rev 2.2 (sprint P0+P1)** : 5 lots commités (~ commits cf4e77d, f12da55,
> 2551464, 0c146d9, 9ee88ed). 328/328 tests verts (39% coverage baseline).
> Tout le top P0 distribution + sécurité critique + bugs résiduels +
> refactor partiel + perf web sont livrés. Reste : §7.2 (factorisation
> TMDB resolvers, SKIP justifié), §4.4 (build PyInstaller / Dockerfile),
> §4.6 (banner updates) — dépendent de la phase distribution publique.
>
> Légende :
> **[P0]** critique/sécurité, **[P1]** à faire bientôt, **[P2]** nice-to-have, **[P3]** long terme.
> **🆕** nouveau finding rev 2. **🔄** priorité changée vs rev 1. **✅** résolu rev 2.1+.

---

## Résumé exécutif — Top findings (rev 2.2)

### ✅ Tous les P0 audit livrés

| # | Section | Finding | Statut |
|---|---|---|---|
| 1 | §6.1 | Bug operator-precedence `web/app.py:330` | ✅ Lot rev 2.1 |
| 2 | §6.2 | `_extract_size_bytes` ignore `torrent_path` | ✅ Lot rev 2.1 |
| 3 | §4.1 | Packaging MediaInfo (résolution runtime) | ✅ Lot 1 [cf4e77d] |
| 4 | §4.2 | Wizard first-run `/setup` | ✅ Lot 1 [cf4e77d] |
| 5 | §4.3 | `data_dir()` cross-platform via `platformdirs` | ✅ Lot 1 [cf4e77d] |
| 6 | §4.5 | `.env` co-localisé avec data_dir + migration auto | ✅ Lot 1 [cf4e77d] |
| 7 | §5.1 | Path traversal `/inbox` + `/api/files` + `/api/queue/add` | ✅ Lot 2 [f12da55] |
| 8 | §5.2 | Masking secrets dans logs | ✅ Lot 2 [f12da55] |
| 9 | §4.7 | Erreurs démarrage user-friendly (dialog tkinter, fallback port) | ✅ Lot 2 [f12da55] |

### ✅ Bugs P1 résiduels résolus (Lot 3 [2551464])

- §6.3 `hash()` non-déterministe pour les noms de log → md5 stable
- §6.4 `_sort_key` `-hash(ts)` → tri 2-passes ASC actifs / DESC finished
- §6.5 `except Exception:` silencieux les plus critiques (tmdb, cache TMDB)
- §6.6 `_try_recover_state` sauvegarde une copie `.corrupted-<timestamp>` avant overwrite

### ✅ Architecture P1 (Lot 4 [0c146d9])

- §7.3 Helpers `try_check_duplicate` + `mark_aborted_duplicate` extraits dans `upload_orchestrator`, utilisés depuis pipeline + jobs_runner (élimine la duplication 3-sites)
- §7.6 `cmd_inspect` utilise maintenant `GeminiClient.get_torrent` (au lieu de re-implémenter le HTTP)
- ⏸️ §7.2 Factorisation TMDB resolvers movie + TV : **SKIP justifié** — 700 lignes avec gros risque de régression sur les 21 tests `test_release_name_real_cases`. À reprendre dans une session dédiée avec mocks TMDB explicites.

### ✅ Perf + UX + tests (Lot 5 [9ee88ed])

- §9.1 `_list_packages` dédup lecture debug.json (1 lecture au lieu de 2 par package)
- §9.2 Cache `compute_confidence_score` avec mtime composite (debug + state)
- §10.2 Page History livrée (route + template + lien sidebar activé)
- §8.1 Coverage configurée dans `pyproject.toml` (baseline 39%)
- §8.2 Tests upload_orchestrator helpers + bundle (19 nouveaux, +14% coverage sur ce module)
- `pyproject.toml` package-data : ajout des templates par type média qui manquaient

### ⏸️ Reportés à la phase distribution publique

| Section | Item | Raison report |
|---|---|---|
| §4.4 | Build PyInstaller `.spec` + Dockerfile | Demande accès build + tests d'install réels, hors scope d'une session de refactor code |
| §4.6 | Banner updates GitHub releases | Peu de valeur tant que pas de release publique en cours |
| §7.2 | Factorisation TMDB resolvers | Risque de régression > bénéfice. Session dédiée à prévoir |
| §8.2 (suite) | Tests : porter coverage à 70%+ | Nécessite tests d'intégration avec mocks réseau (TMDB, OMDb, tracker). 1+ jour à part |

### 📊 Avant / après

| Mesure | Rev 2.0 (départ) | Rev 2.2 (fin sprint) |
|---|---|---|
| Tests | 291/291 verts | **328/328 verts** |
| Lignes code obsolètes | ~1380 | 0 |
| Findings P0 ouverts | 5 | 0 |
| Findings P1 ouverts | 12+ | 5 (reportés justifiés) |
| Coverage baseline | non mesurée | 39% |

---

## Sommaire

1. [Résumé exécutif](#résumé-exécutif--top-5-findings-rev-2)
2. [Recommandation A/B/C](#2-recommandation-abc--par-où-attaquer)
3. [🗑 À déprécier / retirer](#3--à-déprécier--retirer)
4. [📦 Distribution & first-run UX](#4--distribution--first-run-ux)
5. [Sécurité](#5-sécurité)
6. [Bugs fonctionnels & robustesse](#6-bugs-fonctionnels--robustesse)
7. [Architecture & duplication](#7-architecture--duplication)
8. [Tests & coverage](#8-tests--coverage)
9. [Performance](#9-performance)
10. [UX & ergonomie web UI](#10-ux--ergonomie-web-ui)
11. [Documentation](#11-documentation)
12. [Petites perles](#12-petites-perles-informationnel)
13. [Re-priorisation rev 1 → rev 2](#13-re-priorisation-rev-1--rev-2)

---

## 2. Recommandation A/B/C — par où attaquer

Tu m'as proposé 3 directions :

- **A) Bugs critiques** (P0 actuels)
- **B) Nettoyage code obsolète** (deprecate / suppression)
- **C) Distribution & first-run UX**

**Ma reco : B → A → C, avec un sous-set de A en parallèle dès le début.**

Justification :

- **B en premier** parce que `windows_context_menu.py` (239 lignes), `batch.py`
  (541 lignes), `input_list.py` (241 lignes), `cli.py::cmd_inspect` (113
  lignes), 4 fichiers `.bat`, et plusieurs sous-commandes CLI font ~1200
  lignes de code à charger mentalement à chaque modif. **Les supprimer
  d'abord rend tout le reste plus simple :** moins de paths d'erreur à
  tester, moins de sécurité à valider sur des inputs CLI, moins de doc à
  maintenir, et zéro travail gaspillé à corriger des bugs dans du code
  voué à dégager.

- **A en parallèle dès le début** parce que les 4 P0 fonctionnels sont
  petits chacun (5 à 30 min), et à fixer **avant** de distribuer pour de
  vrai : `app.py:330` operator-precedence (5 min), `_extract_size_bytes`
  fallback réel (15 min). Ces 2-là à caler entre 2 sessions de B.

- **C en dernier** parce qu'il faut un codebase propre pour le packager
  (sinon on package du code qu'on va virer), et parce que C est le morceau
  le plus stratégique : data_dir, wizard, MediaInfo embed, autostart,
  updates. Mieux vaut le faire en bloc cohérent qu'en bricolage.

Si tu veux malgré tout commencer par A : `app.py:330` et `_extract_size_bytes`
sont des fixes propres, isolés, avec test possible — bonne énergie de
session pour redémarrer en mode "let's ship". Mais ne fais pas A en entier
avant B sinon tu re-tests des paths CLI qu'on va de toute façon supprimer.

---

## 3. 🗑 À déprécier / retirer ✅ (résolu rev 2.1)

> **Section RÉSOLUE rev 2.1.** Toutes les suppressions §3.1 → §3.4 ont été
> exécutées. ~1380 lignes en moins, 292/292 tests verts. Détails conservés
> ci-dessous pour traçabilité.

### 3.1 [P1] ✅ `windows_context_menu.py` + commandes associées
**Fichiers concernés :**
- [src/flox_uploader/windows_context_menu.py](src/flox_uploader/windows_context_menu.py) (239 lignes, suppression complète)
- [src/flox_uploader/cli.py:294-302](src/flox_uploader/cli.py:294) (`cmd_install_menu`, `cmd_uninstall_menu`)
- [src/flox_uploader/cli.py:393-403](src/flox_uploader/cli.py:393) (sous-parsers `install-context-menu` / `uninstall-context-menu`)
- `install_context_menu.bat` (racine, 67 lignes)
- `uninstall_context_menu.bat` (racine, 51 lignes)
- `scripts/windows/` (dossier généré)

**Justification :** le user-final ne fait plus clic-droit pour ajouter des
fichiers. Il ouvre la web UI, browse vers le fichier, clique "Ajouter à la
queue". Le bouton fait le même boulot, sans toucher au registre Windows.

**Impact :** zéro régression côté UI. Dépendance à dénouer : `cli.py::cmd_add`
était la cible des entrées du menu contextuel — si on supprime aussi `cmd_add`
(cf. §3.3), pas de fil pendant. Mention CLAUDE.md §11 et §3 (architecture)
à mettre à jour.

**Tests touchés :** aucun (pas de test sur `windows_context_menu`).

---

### 3.2 [P1] ✅ `input_list.py` + workflow input_list.txt
**Fichiers concernés :**
- [src/flox_uploader/input_list.py](src/flox_uploader/input_list.py) (241 lignes)
- [src/flox_uploader/cli.py:271-273](src/flox_uploader/cli.py:271) (`cmd_add`)
- [src/flox_uploader/cli.py:371-376](src/flox_uploader/cli.py:371) (sous-parser `add`)
- [src/flox_uploader/config.py::input_list_path()](src/flox_uploader/config.py:36)

**Justification :** `input_list.txt` était le pont entre le clic-droit
Windows et le batch CLI. Les deux mondes disparaissent. La queue web a
remplacé `input_list.txt` par `data/jobs.db` (déjà en place).

**Impact :** `batch.py::run_batch` lit toujours `input_list.txt` (cf. §3.3).
Si on supprime input_list, batch tombe → cohérent.

**Tests touchés :** aucun direct. À vérifier : `test_split_team` etc. ne
testent pas le workflow input_list, ils testent `release_name`.

---

### 3.3 [P1] ✅ `batch.py` + commande `flox-uploader batch`
**Fichiers concernés :**
- [src/flox_uploader/batch.py](src/flox_uploader/batch.py) (541 lignes)
- [src/flox_uploader/cli.py:260-268](src/flox_uploader/cli.py:260) (`cmd_batch`)
- [src/flox_uploader/cli.py:364-369](src/flox_uploader/cli.py:364) (sous-parser `batch`)
- `run_batch.bat` (racine, 91 lignes)
- [src/flox_uploader/config.py::history_dir()](src/flox_uploader/config.py:46) (uniquement utilisé par batch)

**Justification :** la web UI a un bouton "Upload sélection" sur la page
Queue qui fait du batch en mode UI. Le mode CLI ajoute juste de la
complexité (subprocess invocation, archive CSV, regroupement MKV+NFO).

**Nuance :** `batch.py::group_mkv_nfo_pairs` ([batch.py:83-161](src/flox_uploader/batch.py:83))
contient une logique propre (regroupement automatique des paires .mkv+.nfo)
qui pourrait être utile en UI lors d'un `add multi`. À extraire dans un
helper réutilisable avant de supprimer le reste de `batch.py`.

**Power-user :** on peut garder un mode batch caché derrière un endpoint
API (`POST /api/queue/add` accepte déjà des listes) ; pas besoin de la CLI
batch séparée.

**Impact :** le mode CLI batch part. La sous-commande `flox-uploader batch`
disparaît de l'aide. La web UI ne perd rien.

**Tests touchés :** aucun test direct sur `batch.py` (déjà identifié comme
trou de coverage en rev 1). Donc suppression libre.

**Dépendances à dénouer :**
- `subprocess.run([sys.executable, '-m', 'flox_uploader.cli', 'prepare', ...])` ([batch.py:212](src/flox_uploader/batch.py:212)) — ce path subprocess sera supprimé. La web UI utilise déjà `jobs_runner._run_prepare_job` in-process avec ThreadPool, **aucune dépendance** à subprocess.
- `MAX_WORKERS = 1` race condition (cf. rev 1) → résolue mécaniquement par la suppression.

---

### 3.4 [P1] ✅ `install.bat` + setup CLI
**Fichiers concernés :**
- `install.bat` (racine, 85 lignes)
- README.md §"Setup initial" (à réécrire pour pointer vers l'installeur)

**Justification :** un user lambda double-clique un installeur (`.exe`
PyInstaller ou `docker compose up`), pas un `.bat`. Le `install.bat`
crée un venv + `pip install -e .` + copie `.env.example` — flux dev,
pas user.

**Impact :** les développeurs continuent d'utiliser `python -m venv .venv && pip install -e .[web,dev]`
documenté dans CLAUDE.md §11 et le README. Pas de régression.

---

### 3.5 [P1] CLI sous-commandes `prepare` / `upload` / `inspect` — à reclasser

**Position :** rester dans le code mais sortir du flux user-facing.

**Fichiers concernés :**
- [src/flox_uploader/cli.py:100-116](src/flox_uploader/cli.py:100) (`cmd_prepare`)
- [src/flox_uploader/cli.py:119-124](src/flox_uploader/cli.py:119) (`cmd_upload`)
- [src/flox_uploader/cli.py:127-240](src/flox_uploader/cli.py:127) (`cmd_inspect`, 113 lignes)

**Justification :** ces sous-commandes ont une vraie utilité pour les
power-users / debug / scripting (Sonarr/Radarr post-import, CI tests).
Les garder mais :
- les ne plus mentionner dans le README user-facing (qui pointe vers
  l'installeur et la web UI uniquement)
- les documenter dans une section "Power user / scripting" séparée
- ajouter `flox-uploader serve` en commande par défaut quand on lance
  le binaire sans arg (cf. §4.4)

**`cmd_inspect` spécifiquement** : 113 lignes de logique HTTP duppliquée
avec `gemini_api.get_torrent` (cf. §7.6 ci-dessous). À refactoriser pour
utiliser le client. C'est un outil de debug, mais doit être propre.

---

### 3.6 [P2] `.env.example` à la racine
**Fichier :** `.env.example` (à conserver pour les devs, mais le user
final ne le voit jamais).

**Justification :** redondant avec le wizard first-run (cf. §4.2). Le
wizard pré-remplit les valeurs et les écrit dans `data/.env` (cf. §4.5).
Le `.env.example` sert juste de doc dev, à laisser tel quel.

**Pas à supprimer**, juste à déclasser dans la doc user.

---

### 3.7 [P2] CLI flag `--companion-nfo`
[src/flox_uploader/cli.py:318-326](src/flox_uploader/cli.py:318)
+ [pipeline.py:102-104, 259-265](src/flox_uploader/pipeline.py:102)

**Justification :** la web UI peut détecter automatiquement le `.nfo` frère
du `.mkv` ajouté à la queue (heuristique simple, déjà présente dans
[batch.py::group_mkv_nfo_pairs](src/flox_uploader/batch.py:83) — à
extraire en helper, cf. §3.3).

**Reco :** garder l'argument côté `process_one()` (utilisé par tests et
power-users), supprimer l'option CLI `--companion-nfo` du flag visible.
Ou le garder caché derrière `--advanced`.

**Tests touchés :** aucun test direct sur `--companion-nfo` côté CLI.

---

### 3.8 Récap des suppressions proposées

| Fichier / lignes | Lignes | Catégorie |
|---|---|---|
| `windows_context_menu.py` | 239 | suppression complète |
| `input_list.py` | 241 | suppression complète |
| `batch.py` | 541 | suppression (sauf helper `group_mkv_nfo_pairs`) |
| `install.bat` | 85 | suppression |
| `run_batch.bat` | 91 | suppression |
| `install_context_menu.bat` | 67 | suppression |
| `uninstall_context_menu.bat` | 51 | suppression |
| CLI `cmd_install_menu`, `cmd_uninstall_menu`, `cmd_add`, `cmd_batch` | ~50 | suppression |
| `config.py::input_list_path()`, `history_dir()` | ~15 | suppression |
| `scripts/windows/` (généré) | dossier | suppression |
| **Total estimé** | **~1380 lignes** | **~8.5% du codebase** |

CLAUDE.md à mettre à jour : §3 (architecture), §11 (commandes), §13 (roadmap).

---

## 4. 📦 Distribution & first-run UX

L'objectif : un user lambda télécharge un installeur, double-clique, ouvre
le navigateur, configure ses 3 clés API via wizard, browse vers son film,
upload. Pas un terminal en vue.

### 4.1 [P0 🆕 ✅] Packaging MediaInfo (résolution runtime livrée)
**État actuel :** [src/flox_uploader/core/nfo.py:10](src/flox_uploader/core/nfo.py:10)
hardcode `MEDIAINFO_BIN = "mediainfo"` qui suppose un binaire dans `PATH`.
[install.bat:27-33](install.bat) avertit le user mais ne l'installe pas.

**Cible :**
- **PyInstaller (Windows)** : embed `MediaInfo_CLI_Windows_x64.zip` dans le
  bundle. Au runtime, résoudre le binaire depuis `sys._MEIPASS` (PyInstaller
  bundle dir) ou à côté de `sys.executable` en standalone, avec fallback
  PATH pour le mode dev.
- **Docker** : `apt-get install -y mediainfo` dans le `Dockerfile`. Trivial.
- **Mac** (si jamais) : `brew install mediainfo` ou `.app` bundle.

**Fix :**
```python
# core/nfo.py
def _resolve_mediainfo_bin() -> str:
    # 1. Bundle PyInstaller
    if hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "mediainfo" / "MediaInfo.exe"
        if bundled.is_file(): return str(bundled)
    # 2. À côté de l'exe (standalone Windows)
    sibling = Path(sys.executable).parent / "MediaInfo.exe"
    if sibling.is_file(): return str(sibling)
    # 3. PATH (dev / Docker)
    if which("mediainfo"): return "mediainfo"
    raise RuntimeError("MediaInfo introuvable. ...")

MEDIAINFO_BIN = _resolve_mediainfo_bin()
```

**À ajouter au boot du serveur :** un health-check qui appelle `mediainfo --version`,
loggue la version trouvée, et si erreur → afficher un dialog d'erreur dans
la UI (page d'accueil) plutôt que de planter au premier upload.

---

### 4.2 [P0 🆕 ✅] Wizard first-run (livré rev 2.2 Lot 1)
**État actuel :** [src/flox_uploader/web/app.py:584](src/flox_uploader/web/app.py:584)
`create_app()` charge `.env`, démarre, redirige `/` vers `/inbox`. Si l'env
n'a pas `TRACKER_API_KEY`, l'utilisateur tombe sur l'inbox (qui marche),
mais dès qu'il essaie d'uploader → erreur cryptique.

**Cible :** au boot, vérifier que les variables critiques sont présentes :
`TRACKER_API_URL`, `TRACKER_API_KEY`, `TRACKER_ANNOUNCE`, `TMDB_API_KEY`.
Si une manque → middleware redirect vers `/setup` (nouvelle page).

**Wizard `/setup` (5 étapes proposées) :**
1. **Bienvenue** : explique ce que fait l'app, ce qu'il va falloir.
2. **TMDB & OMDb** : champ pour la TMDB key (lien direct vers
   themoviedb.org/settings/api), champ optionnel OMDb (lien aussi). Bouton
   "Tester" qui appelle l'API et confirme la validité.
3. **Tracker** : URL announce (avec passkey), API URL, API key. Bouton
   "Tester" qui appelle `GET /api/torrents/filter?id=1` pour valider.
4. **Préférences** : `BROWSE_ROOT` (pré-rempli avec home), `OUTPUT_DIR`
   (data dir), `APPEND_FR_TITLE_TO_RELEASE_NAME` (case à cocher).
5. **C'est prêt** : récap + bouton "Vers l'inbox".

Le wizard appelle `write_env_values()` (déjà existant dans
[config_view.py:175](src/flox_uploader/web/config_view.py:175)) +
`apply_updates()` à chaque étape. Pas besoin de redémarrer l'app.

**Routes à ajouter :**
- `GET /setup` (wizard UI)
- `POST /api/setup/test-tmdb` (validation côté serveur)
- `POST /api/setup/test-tracker` (validation côté serveur)
- `POST /api/setup/save` (write + apply)

**Code existant réutilisable :**
- [config_view.py::SCHEMA](src/flox_uploader/web/config_view.py:41) déjà bien structuré, peut alimenter le wizard.
- [config_view.py::validate_updates](src/flox_uploader/web/config_view.py:260) déjà en place.

---

### 4.3 [P0 🆕 ✅] `data_dir()` cross-platform et upgrade-safe (livré)
**État actuel :** [src/flox_uploader/config.py:16, 31](src/flox_uploader/config.py:16)
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
def data_dir() -> Path:
    raw = os.getenv("FLOX_UPLOADER_DATA_DIR", "").strip()
    if raw: p = Path(raw)
    else:    p = PROJECT_ROOT / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p
```

**Problème :**
- **PyInstaller** : `PROJECT_ROOT` pointe dans le bundle (`sys._MEIPASS`),
  qui est en lecture seule sur certains OS et **détruit à chaque update**
  → données utilisateur perdues à chaque mise à jour de l'app.
- **Docker** : `/app/data` par défaut, demande au user de monter
  explicitement un volume — non-trivial pour le user lambda. À documenter
  ou à préserver via `VOLUME` dans le Dockerfile.

**Fix proposé :**
```python
import platformdirs

def _default_data_dir() -> Path:
    # Mode dev (install editable) : garder PROJECT_ROOT/data
    if (PROJECT_ROOT / "pyproject.toml").is_file() and not _is_frozen():
        return PROJECT_ROOT / "data"
    # Mode packagé : OS-standard
    return Path(platformdirs.user_data_dir("flox-uploader", "fremontlouis"))

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)  # PyInstaller flag
```

Résultat sur Windows packagé : `C:\Users\<user>\AppData\Local\fremontlouis\flox-uploader\`.
Survit aux updates. Override via `FLOX_UPLOADER_DATA_DIR` toujours
respecté.

**Migration :** au premier boot après upgrade, si l'ancien data dir
(PROJECT_ROOT/data) existe ET pas le nouveau → proposer la migration via
un dialog UI ("Migrer vos données vers le nouvel emplacement ?"). One-shot.

**Dépendance :** `platformdirs` à ajouter dans `requirements.txt` (4 KB,
pure Python, déjà très largement utilisé).

---

### 4.4 [P1 🆕] Lancement du serveur via l'installeur
**Cible :**
- **PyInstaller** : un binaire `flox-uploader.exe` qui appelle
  `cli.cmd_serve` directement (sans args) puis `webbrowser.open("http://127.0.0.1:8765/")`.
  Idéalement : tray icon Windows (avec `pystray`) qui permet
  d'ouvrir/quitter rapidement, et notifications.
- **Icône bureau** : `.lnk` créé à l'install, pointant vers le binaire.
- **Autostart Windows** : opt-in dans la page Config UI, écrit dans
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`. Très
  petit module à créer.
- **Docker** : `docker compose up -d`, le user ouvre `http://localhost:8765/`
  manuellement. Power-user OK avec ça.

**Code à ajouter :**
- `scripts/build_pyinstaller.spec` (config PyInstaller) + un `.spec` file.
- `Dockerfile` + `docker-compose.yml`.
- `flox_uploader/__main__.py` qui appelle `cli.main()` quand le binaire
  est lancé sans args, défaut sur `serve`.

---

### 4.5 [P1 🆕 ✅] Gestion du `.env` côté wizard et upgrade (livré)
**État actuel :** `.env` à la racine projet ([config.py::env_file()](src/flox_uploader/config.py:78)).
Idem que data dir : disparaît à chaque update PyInstaller.

**Cible :** déplacer `.env` dans le data_dir (cohérent avec §4.3). Le data
dir survit aux updates → les clés du user aussi.

**Fix :**
```python
def env_file() -> Path:
    # Dev : racine projet (compat tests)
    if not _is_frozen() and (PROJECT_ROOT / ".env").is_file():
        return PROJECT_ROOT / ".env"
    # Packagé : data_dir/.env
    return data_dir() / ".env"
```

Le wizard écrit toujours via `write_env_values()`, pointe automatiquement
vers le bon path. Le user ne voit jamais le fichier.

**Migration :** au premier boot après upgrade, si `PROJECT_ROOT/.env`
existe et pas `data_dir()/.env` → copier l'ancien dans le nouveau.

---

### 4.6 [P1 🆕] Updates de l'app
**Cible :** détection version au boot, banner "nouvelle version dispo"
dans la sidebar.

**Stratégie :**
- Source : `https://api.github.com/repos/fremontlouis/flox-uploader/releases/latest`,
  cache 24h.
- Comparaison `tag_name` vs version locale (lue depuis `pyproject.toml`
  ou `__version__`).
- Si différent : afficher un toast/banner avec lien vers le release.
- **Pas d'auto-update** dans la v1 (complexité Windows + Mac + Linux). User
  télécharge manuellement le nouvel installeur.

**Routes :**
- `GET /api/version` retourne `{"current": "0.1.0", "latest": "0.2.0", "url": "..."}`.

**Sécurité :** la requête GitHub se fait depuis le serveur (pas le browser
qui CORS), donc OK.

---

### 4.7 [P1 🆕 ✅] Erreurs de démarrage user-friendly (livré)
**Cible :** quand le binaire packagé démarre, plusieurs choses peuvent foirer :

| Erreur | Affichage cible |
|---|---|
| Port 8765 déjà occupé | Try 8766, 8767 jusqu'à OK ; afficher le port final dans le toast / log |
| MediaInfo introuvable | Dialog GUI avec lien d'aide (cf. §4.1) |
| `.env` corrompu | Logger, redirect `/setup` avec valeurs par défaut |
| Antivirus bloque (faux positif) | Doc dédiée, signature du binaire (cf. §4.8) |
| Cert TMDB expiré | Bouton "Réessayer" dans le toast |

**État actuel :** [cli.py:415](src/flox_uploader/cli.py:415) `except Exception: die(...)`
print l'erreur sur stderr. Pour PyInstaller windowed (sans console), `print`
ne va nulle part. **À remplacer** par un dialog GUI minimaliste (tkinter
suffit) qui affiche le message + bouton "Voir le log" + bouton "Quitter".

---

### 4.8 [P2 🆕] Code signing & distribution
**Sans signature, Windows SmartScreen affiche un warning gros ("application
non reconnue") qui fait fuir 95% des users.**

- **Windows** : certificat code signing (~80€/an chez SSL.com, gratuit
  via OpenSource Code Signing pour repos OSS). À déléguer à plus tard
  mais à anticiper dans la stratégie de release.
- **Mac** : Apple Developer ID (~99€/an) + notarization. Pas urgent (pas
  prioritaire selon le contexte FR).
- **Linux** : pas de signing universel ; .deb ou AppImage suffisent.

**Tracking :** GitHub Releases pour la distribution, avec checksums SHA256
publiés à côté.

---

### 4.9 [P2 🆕] Logs accessibles depuis la UI
**Le user lambda ne sait pas où sont les logs si quelque chose foire.**

**Cible :** une page `/logs` ou un panneau dans `/config` qui :
- liste les logs récents (`data/jobs/*.log`, `data/uploads/*.log`)
- permet de les copier/télécharger
- propose un bouton "Joindre à un rapport de bug" (zip + pré-remplit un
  formulaire GitHub Issue)

**Sécurité :** masquer les secrets dans les logs (cf. §5.2 ci-dessous, pas
optionnel quand le user peut télécharger les logs).

---

### 4.10 [P3 🆕] Tray icon Windows + minimize-to-tray
Plus tard. Une vraie app desktop reste accessible quand le user ferme la
fenêtre du browser. `pystray` permet de faire ça en ~50 lignes.

---

## 5. Sécurité

### 5.1 [P1 🔄 ✅] Path traversal & filesystem ouvert sur la web UI (livré)
**Re-évaluation rev 2 :** était P0 en rev 1. Re-classé **P1** parce que :

- En PyInstaller standalone Windows, le serveur écoute par défaut sur
  127.0.0.1 (cf. `cli.py:384` `default="127.0.0.1"`). Risque CSRF possible
  mais limité (un site web malveillant aurait besoin de connaître exactement
  le port + endpoint, et la même-origin policy bloque le retour des
  données).
- En Docker, le user monte ses dossiers en volumes → le scope est limité
  aux volumes montés.
- Le risque réel se manifeste si l'user expose `--host 0.0.0.0` (pour accès
  depuis téléphone par ex). À sécuriser avant la v1 publique malgré tout.

**Reste P1 et à fixer avant la v1 publique.** Cf. rev 1 §1.1 pour les détails
techniques (`/inbox`, `/api/files`, `/api/queue/add`).

**Reco :** ajouter `_assert_path_in_browse_roots(target)` qui valide contre
`_list_quick_roots()` et lève `HTTPException(403)`. Combiner avec un check
au boot : si `--host` n'est pas localhost ET aucun mot de passe configuré
(cf. §5.4 ci-dessous), refuser de démarrer.

---

### 5.2 [P0 🆕 ✅] Masking des secrets dans les logs (livré)
**Lié au §4.9 (logs téléchargeables depuis la UI).** Si le user peut
télécharger ses logs et les partager (rapport de bug GitHub par ex), les
secrets ne doivent jamais y apparaître.

**État actuel :** le redirect stdout/stderr dans
[jobs_runner.py:135-136](src/flox_uploader/web/jobs_runner.py:135) capture
toute exception. Si une `requests.RequestException` remonte une URL
contenant la passkey ou l'api_key, elle finit dans le log.

**Reco :** wrapper `LogScrubber` qui regex-replace les secrets connus
(`TRACKER_API_KEY`, `TMDB_API_KEY`, `OMDB_API_KEY`, passkey extraite de
`TRACKER_ANNOUNCE`) avant chaque écriture. Appliquer dans `redirect_stdout`
et dans `traceback.format_exc()`.

---

### 5.3 [P1] Cache TMDB sans isolation films/séries
Inchangé depuis rev 1. Cf. [src/flox_uploader/core/tmdb.py:46](src/flox_uploader/core/tmdb.py:46).
Préfixer la clé films `movie|...` et invalider l'ancien cache au prochain
boot.

---

### 5.4 [P2 🆕] Pas d'authentification sur la web UI
**Cible :** local-only, donc pas d'auth nécessaire en mode 127.0.0.1. Mais
si un user expose `--host 0.0.0.0` (téléphone, multi-device), il devrait
pouvoir mettre un mot de passe simple.

**Reco :** auth basique en option dans `/config` (`UI_PASSWORD` env). Si
défini → middleware HTTPBasicAuth sur toutes les routes sauf `/static/*`.
Pas urgent pour la v1 single-user.

---

### 5.5 [P2] `BROWSE_ROOTS` non validé
Inchangé depuis rev 1. Devient un peu plus pertinent côté wizard (qui
écrit `BROWSE_ROOT`), à valider proprement.

---

### 5.6 [P2] Templates Jinja & échappement HTML
Vérifié OK en rev 1. Auto-escape activé. Inchangé.

---

## 6. Bugs fonctionnels & robustesse

### 6.1 [P0] ✅ Operator precedence bug — heuristique NFO
**RÉSOLU rev 2.1.** [web/app.py:330](src/flox_uploader/web/app.py:330)
remplacé par une condition propre : on ne reclasse un NFO scene comme
mediainfo que si **pas de mediainfo.nfo déjà trouvé** ET le contenu commence
par "General" (signature MediaInfo --Output=TEXT). Plus de OR mal-parenthésé.

---

### 6.2 [P0] ✅ `_extract_size_bytes` ignore son paramètre `torrent_path`
**RÉSOLU rev 2.1.** [upload_orchestrator.py:238](src/flox_uploader/core/upload_orchestrator.py:238)
fallback ajouté : `Torrent.read(path).size` (somme du contenu décrit dans
le .torrent, PAS la taille du fichier .torrent lui-même). Les packages
legacy sans `mediainfo_data.size_bytes` retournent maintenant la vraie
taille → dedup par taille restaurée.

---

### 6.3 [P1] ✅ `hash()` non-déterministe → noms de log qui prolifèrent
**RÉSOLU rev 2.2 (Lot 3 [2551464]).** [jobs_runner.py:_run_upload_job](src/flox_uploader/web/jobs_runner.py:115)
utilise maintenant `hashlib.md5(key)[:12]` stable cross-process. Plus de
prolifération de fichiers log à chaque redémarrage du serveur.

---

### 6.4 [P1] ✅ `_sort_key` upload statuses utilise `-hash(ts)`
**RÉSOLU rev 2.2 (Lot 3 [2551464]).** [list_upload_statuses](src/flox_uploader/web/jobs_runner.py:65)
refait avec deux passes explicites : actifs ASC par `updated_at`, finished
DESC par `updated_at`. Tri ISO 8601 lexicographique == chronologique.

---

### 6.5 [P1] ✅ Try/except silencieux (sample critique résolu)
**Partiellement RÉSOLU rev 2.2 (Lot 3 [2551464]).** Sites les plus critiques
fixés : `tmdb._maybe_fetch_title_en` stocke l'erreur dans
`tmdb_context["_title_en_error"]` (traçable dans debug.json) ;
`tmdb._cache_load`/`_cache_save` exceptions spécifiées (json.JSONDecodeError,
OSError, etc.) au lieu de bare `Exception`. Reste ~6 sites à finir
(web/app.py, jobs_runner._try_dedup_check) : low-priority parce que les
erreurs y sont déjà loguées en `[WARN]`, juste avec un type vague.

---

### 6.6 [P1] ✅ `_try_recover_state` perd l'historique
**RÉSOLU rev 2.2 (Lot 3 [2551464]).** [read_state](src/flox_uploader/core/package_state.py:141)
sauvegarde maintenant une copie `package_state.json.corrupted-<timestamp>`
avant overwrite par la version réparée. Test dédié dans
`test_package_state.test_recover_creates_corrupted_backup`.

---

### 6.7 [P3 ✅🔄] Race condition cache TMDB en batch — bridé à 1 worker
**RÉSOLU rev 2.1** mécaniquement par la suppression de `batch.py` (§3.3).
Plus de batch CLI multi-worker → plus de race possible.

---

### 6.8 [P3 🔄] `cmd_inspect` swallow plusieurs erreurs avec juste un print
**Re-classé P3** : `cmd_inspect` est un outil de debug power-user
(cf. §3.5), pas un flux user-final. Acceptable en l'état. À refactoriser
si on retouche `cli.py`.

---

### 6.9 [P2] `_extract_team` (gemini_api) divergent de `split_team`
Inchangé depuis rev 1. Cf. [gemini_api.py:147](src/flox_uploader/core/gemini_api.py:147).

---

## 7. Architecture & duplication

### 7.1 [P3 ✅🔄] `ALLOWED_FORCE_FR` triplé avec contenus divergents
**RÉSOLU rev 2.1** mécaniquement : `batch.py` et `input_list.py` supprimés
(§3.2, §3.3). Source unique restante : [release_name.py:21](src/flox_uploader/core/release_name.py:21)
avec la liste complète `{VFF, VFQ, VFB, VF2, VOF, VOQ, VOB}`. La web UI
expose les overrides via les radios de la page détail (qui lit cette
constante via `cli.ALLOWED_FORCE_FR` ré-exporté). Vérifié, plus de
divergence.

---

### 7.2 [P1] Resolvers TMDB largement dupliqués
Inchangé depuis rev 1. Cf. [tmdb.py:213-471, 575-713](src/flox_uploader/core/tmdb.py:213).
~80% de logique partagée entre movie/TV resolvers + leurs variantes
forced_id.

---

### 7.3 [P1] ✅ `pipeline.py` early-dedup duplique `upload_orchestrator`
**RÉSOLU rev 2.2 (Lot 4 [0c146d9]).** Helpers extraits :
[upload_orchestrator.try_check_duplicate](src/flox_uploader/core/upload_orchestrator.py)
(wrapper qui swallow `GeminiAPIError` avec log) et
[mark_aborted_duplicate](src/flox_uploader/core/upload_orchestrator.py)
(transition vers ABORTED_DUPLICATE avec champs lies). Utilisés depuis
`pipeline.process_one` ET `web.jobs_runner._try_dedup_check`. Tests dédiés
dans `tests/test_upload_orchestrator.py`.

---

### 7.4 [P2] `unit3d_mapping` couplé en dur dans l'orchestrator
Inchangé depuis rev 1. Cf. [upload_orchestrator.py:34](src/flox_uploader/core/upload_orchestrator.py:34).

---

### 7.5 [P2] `_format_size` × 3 implémentations
Inchangé depuis rev 1.

---

### 7.6 [P1 ✅🔄] `cmd_inspect` duplique la logique HTTP de `gemini_api`
**RÉSOLU rev 2.2 (Lot 4 [0c146d9]).** [cli.cmd_inspect](src/flox_uploader/cli.py:127)
utilise maintenant `GeminiClient.get_torrent` en tentative 1, et
`client._extract_all_matches` pour parser les fallbacks (filter?id, filter?tmdbId).
Plus de duplication HTTP avec headers Bearer.

---

### 7.7 [P3] `release_name.py` à 1275 lignes
Inchangé. Cf. rev 1 §3.6.

---

### 7.8 [P3] Beaucoup d'imports locaux pour casser les cycles
Inchangé. Cf. rev 1 §3.7.

---

### 7.9 [P3] `bbcode_renderer.py:899-908` code mort
Inchangé. Cf. rev 1 §3.8.

---

## 8. Tests & coverage

### 8.1 [P1] ✅ Aucune coverage configurée
**RÉSOLU rev 2.2 (Lot 5 [9ee88ed]).** `pyproject.toml` enrichi :
- `[tool.pytest.ini_options]` (testpaths, addopts, filterwarnings)
- `[tool.coverage.run]` (source, omit, branch)
- `[tool.coverage.report]` (exclude_lines, show_missing)

Baseline coverage : **39% global**. Modules les plus faibles à attaquer
(probablement Lot 6 dédié) : `tmdb` 11%, `pipeline` 7%, `omdb` 9%,
`mediainfo_parser` 11%, `upload_orchestrator` 14% (était 0%, +14% via
test_upload_orchestrator.py).

---

### 8.2 [P1] Modules sous-testés (estimés)
Liste rev 1 mise à jour avec la grille produit final :

| Module | Statut rev 2 |
|---|---|
| `cli.py::cmd_inspect` | Power-user, P2 (§3.5) |
| `batch.py::group_mkv_nfo_pairs` | À EXTRAIRE en helper, puis tester (§3.3) |
| `pipeline.py` early dedup | **P1, à tester** : flux user-final |
| `web/jobs_runner.py::_run_upload_job` paths d'erreur | **P0**, c'est ce que voit le user dans la UI |
| `web/jobs_runner.py::_try_dedup_check` | **P1**, idem |
| `web/config_view.py::write_env_values` | **P0** côté produit final (le wizard l'utilise §4.2) |
| `web/config_view.py::validate_updates` | **P0** côté wizard |
| `package_state.py::_try_recover_state` | P1, simulation truncate utile |
| `compliance.py::check_compliance` | P2 (déjà couvert indirectement via test_release_name_real_cases) |
| `flags.py::flag_for_language_with_context` | P2 |
| `windows_context_menu.py` | À supprimer (§3.1) |

---

### 8.3 [P2 🆕] Tests d'intégration end-to-end
**Devient P1** côté produit final (smoke test au build PyInstaller / Docker).
- Mini-mkv 1MB + mock HTTP server pour TMDB/OMDb/Gemini.
- Test : `process_one → upload_package(dry_run=True)` complet.
- À intégrer dans la CI avant chaque build de release.

---

### 8.4 [P2] `tests/conftest.py` réorganise `sys.path`
Inchangé. Hack à reconsidérer dans la grille install editable propre.

---

## 9. Performance

### 9.1 [P1] ✅ `_list_packages()` fait 2× le travail par package
**RÉSOLU rev 2.2 (Lot 5 [9ee88ed]).** [_list_packages](src/flox_uploader/web/app.py:159)
appelle maintenant `_read_package_size(d)` une seule fois par itération,
stocké dans une variable locale réutilisée pour `size_bytes` et
`size_pretty`.

---

### 9.2 [P1] ✅ `compute_confidence_score()` recalcule à chaque snapshot
**RÉSOLU rev 2.2 (Lot 5 [9ee88ed]).** [core/confidence.py](src/flox_uploader/core/confidence.py)
mémoize via `_score_cache: dict[Path, tuple[float, ConfidenceScore]]` avec
mtime composite (`debug.json` + `package_state.json`) comme clé de validité.
Nouvelle fonction `invalidate_score_cache()` exportée pour cas explicites.

---

### 9.3 [P2] `jobs_db._connect()` ré-applique le schéma à chaque connexion
Inchangé depuis rev 1.

---

### 9.4 [P2] TMDB resolver génère beaucoup d'attempts
Inchangé.

---

### 9.5 [P3] MediaInfo pas exécuté pour saisons sur tous les épisodes
Inchangé.

---

### 9.6 [P3] `_sse_tail_log` poll-based plutôt qu'inotify
Inchangé.

---

## 10. UX & ergonomie web UI

### 10.1 [P2 🔄] Port serveur incohérent : 8000 vs 8765
**Re-classé P2** : pour le produit final, l'installeur lance lui-même le
serveur, le user ne voit même pas le port. Reste utile à aligner pour la
CLAUDE.md / doc dev.

---

### 10.2 [P1 ✅🔄] Page History désactivée
**RÉSOLU rev 2.2 (Lot 5 [9ee88ed]).** Route `GET /history` ajoutée à
`web/app.py`, template `history.html` créé (recherche live JS, lien
clickable vers le tracker pour chaque torrent uploadé), lien sidebar
activé dans `base.html`.

---

### 10.3 [P2] Rafraîchissement queue manuel
Inchangé.

---

### 10.4 [P2] Inbox ne paginate pas
Inchangé.

---

### 10.5 [P3] Pas d'affichage de l'audit/diff prepare↔upload
Inchangé.

---

### 10.6 [P3] `package_detail.html` 770 lignes monolithiques
Inchangé.

---

### 10.7 [P1 🆕] Loader plein-écran sur premier load lent
Pendant le wizard ou un boot lent (download MediaInfo first time, cache
TMDB volumineux à charger), l'user voit une page blanche. Ajouter un
splash screen / lazy boot screen.

---

### 10.8 [P2 🆕] L'inbox affiche ".env" et ".tmdb_cache.json" dans le data dir
Si le user navigue jusqu'à son data dir via l'inbox, il voit ses propres
secrets. Pas un risque (c'est sa machine), mais polluant. Filtrer le data
dir + ses fichiers spéciaux dans `_list_directory`. Pas critique.

---

## 11. Documentation

### 11.1 [P1 🔄] CLAUDE.md à mettre à jour pour la grille produit final
- §3 Architecture : retirer windows_context_menu / batch / input_list après
  suppression.
- §11 Comment lancer : remplacer "flox-uploader prepare ..." par "Lance
  l'installeur, ouvre le navigateur".
- §13 Roadmap : ajouter "wizard first-run", "MediaInfo embed", "data_dir
  appdirs", "code signing".
- §14 Pièges : retirer mentions clic-droit / `input_list.txt`.

---

### 11.2 [P1 🔄] README.md user-facing
**Doit être réécrit** pour le user lambda :
- Section "Installation" → un lien vers le release GitHub avec le `.exe`
  (Windows), `docker compose` (autres).
- Plus de `pip install`, plus de `.env` à éditer, plus de menu contextuel.
- Section "Pour les développeurs" séparée à la fin (avec `pip install -e .`,
  les tests, la build).
- Captures d'écran de la web UI (wizard, inbox, queue, page détail).

---

### 11.3 [P2] Docstrings — peu d'omissions critiques
Inchangé.

---

### 11.4 [P3] Pas de CONTRIBUTING / DEV docs séparés
Inchangé.

---

## 12. Petites perles (informationnel)

Inchangées vs rev 1.

---

## 13. Re-priorisation rev 1 → rev 2

Synthèse des changements de priorité avec la grille produit final :

| Finding | Rev 1 | Rev 2 | Raison |
|---|---|---|---|
| Bug operator-precedence app.py:330 | P0 | **P0 ✅** | RÉSOLU rev 2.1 |
| `_extract_size_bytes` ignore param | P0 | **P0 ✅** | RÉSOLU rev 2.1 (fallback `Torrent.size`) |
| Path traversal /inbox + /api/files | P0 | **P1** 🔄 | Local-only par défaut ; reste à fixer avant v1 publique |
| `ALLOWED_FORCE_FR` triplé | P1 | **P3 ✅** | RÉSOLU rev 2.1 (suppression §3.2 + §3.3) |
| Aucune coverage configurée | P1 | **P1** | Partiellement levé : `pytest-cov` déjà dans pyproject ; reste config + badge |
| Race condition cache TMDB en batch | P1 | **P3 ✅** | RÉSOLU rev 2.1 (suppression §3.3) |
| `hash()` non-déterministe logs | P1 | **P1** | Plus visible produit packagé |
| `_sort_key` `-hash(ts)` | P1 | **P1** | Inchangé |
| Try/except silencieux | P1 | **P1** | Plus critique sans console |
| `_try_recover_state` perd historique | P1 | **P1** | Inchangé |
| Resolvers TMDB dupliqués | P1 | **P1** | Inchangé |
| pipeline early-dedup duplique orchestrator | P1 | **P1** | Inchangé |
| `cmd_inspect` swallow erreurs | P2 | **P3** 🔄 | Power-user, hors flux principal |
| `cmd_inspect` duplique HTTP | P2 | **P1** 🔄 | À refactor quand on touche cli.py |
| Page History désactivée | P3 | **P1** 🔄 | Visible user-final |
| Port 8000 vs 8765 | P1 | **P2** 🔄 | User ne voit jamais le port |
| `_format_size` × 3 | P2 | **P2** | Inchangé |
| README/docs périmés | P2 | **P1** 🔄 | Cible user lambda |

### 🆕 Nouveaux findings rev 2

| Finding | Priorité | Section |
|---|---|---|
| Packaging MediaInfo absent | **P0** | §4.1 |
| Pas de wizard first-run | **P0** | §4.2 |
| `data_dir()` non upgrade-safe | **P0** | §4.3 |
| Lancement serveur via installeur | **P1** | §4.4 |
| `.env` dans le data_dir | **P1** | §4.5 |
| Mécanisme d'updates | **P1** | §4.6 |
| Erreurs démarrage user-friendly | **P1** | §4.7 |
| Code signing | **P2** | §4.8 |
| Logs accessibles depuis UI | **P2** | §4.9 |
| Tray icon Windows | **P3** | §4.10 |
| Masking secrets dans logs | **P0** | §5.2 |
| Auth optionnelle UI | **P2** | §5.4 |
| Loader splash boot lent | **P1** | §10.7 |
| Inbox masque `.env` | **P2** | §10.8 |
| Tests E2E (CI build) | **P1** | §8.3 |

---

## 14. Top 5 (rev 2) — ce qu'il reste à attaquer

Items 1-3 du top initial ✅ résolus rev 2.1. Reste 2 P0 immédiats + le
masking secrets ; ci-dessous un nouveau top 5 pour la suite.

### 1. **[P0 / Cat. C] Triple : MediaInfo embed + data_dir cross-platform + wizard first-run**
Référence : §4.1 + §4.3 + §4.2. Effort : ~1 jour. Triple parce que ces 3
items se font main dans la main : sans data_dir cross-platform, le wizard
écrit dans le mauvais endroit ; sans MediaInfo embed, le wizard plante au
premier upload. **À attaquer en bloc cohérent.**

### 2. **[P0 / Cat. C] Masking des secrets dans les logs + page logs UI**
Référence : §5.2 + §4.9. Effort : 2-4h. Indispensable pour qu'un user
puisse partager ses logs (rapport de bug) sans fuiter ses passkeys.

### 3. **[P1 / Cat. A] Path traversal /inbox + /api/files + /api/queue/add**
Référence : §5.1. Effort : 1-2h. À fixer avant v1 publique. Ajouter
`_assert_path_in_browse_roots()` + warning loud quand `--host != 127.0.0.1`.

### 4. **[P1 / Cat. A+C] Build PyInstaller (`.spec`) + Dockerfile**
Référence : §4.4. Effort : 1 jour. Une fois MediaInfo embed et data_dir
cross-platform en place (top 1), packager pour de vrai.

### 5. **[P1 / Cat. A] Erreurs de démarrage user-friendly**
Référence : §4.7. Effort : 2-3h. Dialog GUI minimaliste (tkinter) pour
les erreurs avant qu'uvicorn démarre, et fallback de port si 8765 occupé.

**Reste mais non-top-5 :** updates banner (§4.6), code signing (§4.8),
coverage config (§8.1), refactor TMDB resolvers (§7.2),
hash() non-déterministe (§6.3), tests E2E (§8.3).

---

*Audit rev 2 produit le 2026-05-06. Rev 2.1 (post-itération 1) : nettoyage
§3 + fixes §6.1, §6.2 livrés ; 292/292 tests verts. Rev 2.2 (sprint
P0+P1) : 5 lots commités (Lot 1 distribution, Lot 2 sécurité, Lot 3
robustesse, Lot 4 architecture, Lot 5 UX/perf/tests) ; 328/328 tests
verts ; tous les P0 livrés, P1 résiduels reportés ou résolus
mécaniquement. À mettre à jour à la prochaine itération.*

---

## Rev 2.5 — Lots K + L + M (conformité G3MINI critique)

Date : 2026-05-07. Tests : 426/426 verts (+60 vs rev 2.4 : tests
`test_compliance_lot_k.py` + `test_lot_l_m_naming.py`). Source des
exigences : 6 PDFs G3MINI TR4CK3R officiels (Comment Choisir, Teams
Interdites, Règles d'Upload, Règles d'Upload Ebook, Règles de Nommage,
Règle d'encodage) que Louis a fournis en input.

### Lot K — Compliance critique (charte Gemini durs)

Nouvelle sévérité `BLOCKING` ajoutée à `compliance.ComplianceIssue`. Les
issues BLOCKING font transitionner le package vers `FAILED` à la fin
de `prepare`, l'upload est refusé tant qu'une re-préparation ne corrige
pas le problème.

| ID  | Check                                  | Sévérité | Source PDF |
|-----|----------------------------------------|----------|------------|
| C1  | Container MKV obligatoire              | BLOCKING (MP4/AVI), WARN (M2TS/VOB toleré pour Full Disc) | Règles d'Upload |
| C2  | MP3 interdit + FLAC > 2ch interdit     | BLOCKING | Règles d'encodage |
| C3  | Sub PGS dans encode (BDRip/WEBRip)     | BLOCKING (toleré dans REMUX) | Règles d'Upload |
| C5  | Saison incomplète (épisodes non-consécutifs) | WARN | Comment Choisir |
| C6  | Multi-team dans un pack TV             | WARN     | Comment Choisir |
| C7  | Piste russe                            | WARN (choix Louis)     | Teams Interdites |
| C8  | Team du release dans BANNED_TEAMS      | BLOCKING (choix Louis : FAILED) | Teams Interdites |
| C9  | EXTREME team sur REMUX/raw BluRay      | BLOCKING | Teams Interdites |
| C10 | Sous-titres .srt/.ass externes au MKV  | WARN     | Règles d'Upload |

Skipped per choix Louis : C4 (MULTi exige VO+VF+subFR — déjà partiellement
couvert par `_check_multi_has_variant`), C11 (crop), C12 (upscale).

**Liste teams interdites configurable** : nouvelle variable d'env
`BANNED_TEAMS` (séparateurs `,`, `;`, `\n`) éditable depuis `/config`
(section "Conformité Gemini", `kind=textarea`). Défauts hardcodés dans
`compliance.DEFAULT_BANNED_TEAMS = ("k0RE", "Slay3R")`. La liste configurée
est ADDITIVE (s'ajoute aux défauts).

### Lot L — Compléments naming (`rules.json`)

| Catégorie | Tokens ajoutés |
|---|---|
| `source_tokens` | `BRRip`, `DVDRip`, `TVRip` |
| `replace_tokens` (normalisation casse) | `BRRIP→BRRip`, `TVRIP→TVRip` |
| `audio_codec_tokens` | `HE-AAC`, `AAC-LC`, `FLAC` (manquait) |
| `video_codec_tokens` | `VP9` |
| `allowed_optional_tokens` | `UNCENSORED`, `DiRFiX`/`DIRFIX`, `READ.NFO`, `LEAK`, **3D : `3D`, `SBS`, `HSBS`, `TAB`, `HTAB`, `MVC`** |
| `drop_tokens` | `NoTAG`, `NoGRP`, `NoGroup` (alias "team manquante") |

`Atmos` reste dans `drop_tokens` per choix Louis (continue à être retiré
du release name pour respecter la canonicalisation Gemini).

### Lot M — Tooling avancé

**CRF hors plage Gemini** (signal WARN) :
- Parser `_extract_crf` ajouté à `mediainfo_parser.py` : lit le champ
  `Encoded_Library_Settings` de la track vidéo MediaInfo et extrait
  `crf=XX.X`.
- `_check_crf_in_range` dans `compliance.py` compare au tableau PDF :
  - x264 8-bit 720p / 1080p : 18-21
  - x265 10-bit 720p : 19-22
  - x265 10-bit 1080p : 20-23
  - x265 10-bit 2160p : 22-26
  - AV1 1080p : 22-28
  - AV1 2160p : 24-32
- WARN si hors plage. **Silence si l'info absente** (cas fréquent : VC-1,
  AV1 sans `crf=` dans encoding_settings, sources non-encodées) — pas de
  bruit sans valeur ajoutée.

**Bit depth exposé** : `mediainfo_data["video"]["bit_depth_int"]` (en plus
de `bit_depth` formaté texte) pour les usages futurs (badge UI).

**Piece size** : skip per choix Louis. 180 torrents ont déjà cross-seedé
avec la méthode actuelle (laisse `torf` calculer), donc aucune raison de
forcer une nouvelle piece size.

### Fichiers touchés

```
src/flox_uploader/core/compliance.py        (+ ~250 lignes : checks C1-C10 + CRF + Severity.BLOCKING + has_blocking)
src/flox_uploader/core/mediainfo_parser.py  (+ _extract_crf, expose encoding_settings/crf/bit_depth_int)
src/flox_uploader/config.py                 (+ banned_teams_list())
src/flox_uploader/pipeline.py               (passe torrent_target + banned_teams ; transitionne FAILED si BLOCKING)
src/flox_uploader/trackers/gemini/rules.json (+ 11 tokens nouveaux)
src/flox_uploader/web/config_view.py        (+ ConfigField BANNED_TEAMS section "Conformité Gemini")
tests/test_compliance_lot_k.py                 (NOUVEAU : 35 tests)
tests/test_lot_l_m_naming.py                   (NOUVEAU : 25 tests)
```

---

## Rev 2.6 — Lot N (détection catégorie enrichie)

Date : 2026-05-07. Tests : 458/458 verts (+32 vs rev 2.5 :
`test_lot_n_category.py`). Source des exigences : NOTES.md round 3, focus
sur les catégories Gemini autres que Films/Séries (cat 1, 2).

### N.1 — Sports par keywords (avec priorité TMDB stricte)

`category_id_for` enrichi avec un fallback `_has_sports_keyword(release_name)`
qui ne s'applique **que si TMDB n'a pas matché** (`tmdb_context` vide ou
sans `movie_id`/`tv_id`/`title`/`genres`).

Priorité finale :

```
1. TMDB matche ET genre 'Animation'    -> ANIME (cat 6 ou 7)
2. TMDB matche ET genre 'Documentary'  -> DOC (cat 13 ou 14)
3. TMDB matche (autres genres)         -> FILM/SERIE (cat 1 ou 2)  ← le film F1 (Brad Pitt) tombe ici
4. TMDB ne matche pas + keyword sport  -> SPORTS (cat 10)
5. TMDB ne matche pas + pas de keyword -> FILM/SERIE par défaut + SIG_CATEGORY_LOW_CONFIDENCE
```

Garde-fou validé par Louis : le film "F1" (TMDB id 911430) reste classé
Films même s'il contient le keyword sport "F1", parce que TMDB a matché.
Une vraie course F1 sans fiche TMDB tombe en Sports.

`SPORTS_KEYWORDS` : ~70 entrées (UFC/NFL/NBA/NHL/MLB/F1/MotoGP/FIFA/UEFA/
Tour de France/Wimbledon/Roland-Garros/WWE/AEW/Olympics/etc.) avec tri
implicite par longueur décroissante (`NBA.Finals` matche avant `NBA`).

### N.2 — Skip Émission TV (cat 15)

Trop ambigu pour auto-détecter sans risque (talk-shows ressemblent à des
séries, télé-réalité confuse avec docu-séries). Hint UI ajouté sous la
dropdown Catégorie : *« Talk-show, télé-réalité ou jeu télé ? Coche
l'override et choisis "Émission TV" »*. Reste 100% override-only.

Catégories sans auto-détection (override manuel uniquement) : Émission TV
(15), Livres (12), Jeux (3), Logiciels (17), Formations (18). L'app est
explicitement positionnée pour Films / Séries / Anime / Docu / Sports.

### N.3 — Source du guess affichée dans l'UI

Nouvelle fonction `category_guess_source(media_type, tmdb_context, release_name)`
qui retourne un libellé humain :
- `"TMDB : genre 'Animation' detecte"`
- `"TMDB : genres Action, Drama"`
- `"Keyword sport detecte : 'F1'"`
- `"Defaut Films (TMDB n'a pas matche, aucun keyword sport)"`

Affiché en italique sous la dropdown catégorie (page détail), invisible si
l'user a coché l'override (logique : on affiche uniquement quand c'est l'auto).

### N.4 — Signal trust badge "catégorie incertaine"

Nouveau signal `SIG_CATEGORY_LOW_CONFIDENCE` émis quand l'auto-détect tombe
sur le défaut Films/Séries (cat 1 ou 2) **sans** match TMDB **et sans**
keyword sport. Pénalité : -1 pt + label *« Catégorie devinée par défaut
(TMDB sans match) — vérifie si c'est un docu, anime, sport ou émission TV
avant l'upload »*. Un nudge léger pour aller vérifier avant d'uploader.

### Fichiers touchés

```
src/flox_uploader/trackers/gemini/unit3d_mapping.py  (+ SPORTS_KEYWORDS, _has_sports_keyword, category_guess_source ; signature category_id_for étendue release_name)
src/flox_uploader/core/naming_signals.py             (+ SIG_CATEGORY_LOW_CONFIDENCE, label dans SIGNAL_METADATA)
src/flox_uploader/pipeline.py                        (émission du signal si défaut sans TMDB)
src/flox_uploader/web/app.py                         (passe release_name à category_id_for + auto_category_source)
src/flox_uploader/core/upload_orchestrator.py        (passe release_name à category_id_for au build payload)
src/flox_uploader/web/templates/package_detail.html  (affiche source du guess + hint Émission TV)
tests/test_lot_n_category.py                            (NOUVEAU : 32 tests)
```

---

## Rev 2.7 — Lots O + P + Q + R + S (sprint NOTES.md round 3)

Date : 2026-05-07. Tests : 490/490 verts (+32 vs rev 2.6 : Lot O+P + Lot Q).
Source : NOTES.md round 3 + 5 debug.json de cas reels uploadés par Louis +
screenshots du formulaire Gemini.

### Lot O — Bugs durs détectés sur cas réels

**O.1 — Furiosa S01E265 → film classé en TV** : le pattern alt `1x01`
matchait `1x265` dans `5.1x265-Elcrackito` (codec x265 collé au layout 5.1).
Fix dans `media_type.EPISODE_PATTERNS` :
- Negative lookbehind `(?<!\d\.)` : rejette si le 1er chiffre est précédé
  par un autre chiffre + point (ex: `5.1x265` → `5.` rejette).
- Limite à 99 max pour le 2e chiffre (`\d{1,2}` au lieu de `\d{1,3}`) :
  un episode > 99 sur le pattern alt est suspect.

**O.2 + O.4 — TMDB Dragons → Dragonslayer Doppelgänger** : ranking refait.
Avant : on stoppait au 1er résultat trouvé (en-US avant fr-FR), donc des
court-métrages obscurs gagnaient. Maintenant :
- On cumule les résultats de **en-US ET fr-FR** sans year-filter API.
- Ranking par score combiné : `year_score + title_score + popularity + 0.5×vote_count`.
- **Tolérance année ±1** : `year_score` = 5000 (exact), 2500 (±1), 500 (±2), 0 sinon.
  Couvre les cas Italie/International (I.Am.Love sort 2009 IT vs 2010 INT).
- Bonus +1000 si `title` ou `original_title` matche exactement la query.

**O.3 — TMDB "Furiosa une Saga Mad" → 0 résultats** : le tokenizer
sortait "Mad Max" → "Mad" parce que `MAX` est dans `drop_tokens` (HBO Max
streaming service). Fix : `_AMBIGUOUS_DROP_TOKENS_UPPER` = liste des
tokens streaming (NF, NFLX, AMZN, DSNP, ATVP, HMAX, MAX, PCOK, PMTP, STAN,
SHO, HULU, ATMOS) qui ne sont droppés que **APRÈS l'année** dans le nom.
Avant l'année, ce sont des mots du titre légitimes.

**O.5 — OMDb pas de note pour films < 6 mois** : ne plus pénaliser
`SIG_OMDB_DATA_MISSING` quand le film est sorti < 180j (délai d'indexation
OMDb normal). Log info à la place : *« OMDb pas de note pour film récent
({date}) — probable délai d'indexation »*.

### Lot P — Enrichissement automatique du nom (validé par Louis)

Décision produit : on passe du mode "préserver fidèle" à "enrichir
intelligemment". Quand un champ obligatoire Gemini est détecté par
MediaInfo mais absent du nom, on l'ajoute automatiquement.

Nouvelle fonction `_enrich_audio_video_from_mediainfo(audio, vcodec,
mediainfo_data, rules)` :
- **Codec audio** (AAC, DDP, DD, DTS, FLAC, etc.) : ajouté si absent,
  inséré juste avant le layout existant.
- **Layout** (5.1, 7.1, 2.0) : ajouté si absent.
- **Codec vidéo** (x265, x264, AV1, VP9) : inféré depuis MediaInfo si
  absent du nom (avant on ajoutait juste un warning).

Cas réels résolus :
- `Dragons.2.2014.MULTi.VFF.2160p.HDR.BluRay.5.1.x265-QTZ` → ajout `AAC` :
  `Dragons.2.2014.MULTi.VFF.2160p.HDR.BluRay.AAC.5.1.x265-QTZ`
- `I.Am.Love.2009.MULTi.1080p.WEB.x264-FW` → ajout `DDP.2.0` :
  `I.Am.Love.2009.MULTi.1080p.WEB.DDP.2.0.x264-FW`

Mapping centralisé `_MEDIAINFO_TO_GEMINI_AUDIO_CODEC` (DDP→DDP, DTS-HD MA→
DTS-HDMA, TrueHD Atmos→TrueHD, etc.) garantit que les tokens canoniques
Gemini sont utilisés.

### Lot Q — Champs upload supplémentaires (formulaire Gemini réel)

Nouveaux champs exposés dans la page détail :

| Champ | Source auto | Override |
|---|---|---|
| Numéro saison | `media_info.season` ou TMDB | `manual_season_number` |
| Numéro épisode | `media_info.episode` | `manual_episode_number` |
| Distributeur | — (Full Disc only) | `manual_distributor_id` |
| Région | — (Full Disc only) | `manual_region_id` |
| TMDB ID | TMDB resolver | `manual_tmdb_id` (déjà) |
| IMDB ID | TMDB external_ids | `manual_imdb_id` (string `tt...`) |
| **TVDB ID** | **TMDB external_ids (NEW)** | `manual_tvdb_id` |
| MAL ID | — (anime, manuel) | `manual_mal_id` |
| Mots-clés | TMDB keywords (8 max) | `manual_keywords` |

`_build_tmdb_context` et `_build_tv_context` étendus pour extraire
`tvdb_id` (via `external_ids`) et `keywords` (via `append_to_response=keywords`).

Section UI dans la carte "Options pour l'upload" : 3 grids responsives
(saison/épisode visible si cat TV, distributeur/région visible si type=1
Full Disc, IDs externes toujours visibles, mots-clés en bas).

`build_upload_payload` étendu : applique les overrides + injecte
`distributor_id`/`region_id`/`keywords` dans le `extra` dict du payload
(toléré par Unit3D pour les champs custom Gemini).

### Lot R — UX/UI (validation NOTES.md round 3)

- **R-A** : tous les blocs (NFO scene, NFO mediainfo, log, présentation,
  nom de release) ont maintenant un bouton uniforme `Afficher`/`Masquer`
  via classe `.btn-collapse` avec `data-target=ID`. JS unifié au boot.
  **Présentation et nom de release sont masqués par défaut** (NOTES.md).
- **R-B** : section "Options pour l'upload" réorganisée. Sous-titres
  redondants supprimés ("Drapeaux upload", "🎯 Champs envoyés au tracker").
  Override checkbox collé à gauche. Drapeaux personal/anonyme déplacés en
  bas (après tous les champs upload).
- **R-C** : panneau score unifié (plus de séparation hard/soft). Code
  couleur cohérent par sévérité :
  - 🔴 **rouge** : doublon CERTAIN ou pénalité ≥ 10
  - 🟠 **orange** : pénalité 5-9 (warnings sérieux)
  - 🔵 **bleu** : pénalité 1-4 (info, peu grave)
- **R-C bis** : nouveau bucket "**parfait**" pour score = 100 exact (avec
  glow plus éclatant `score-glow-parfait`). 95-99 reste "perfect" mais
  glow atténué `score-glow-perfect`. 6 buckets total au lieu de 5.
- **R-D** : tokens groupés. `Tokens non reconnus : 4K, 5` en une ligne
  au lieu de N entrées `Token non reconnu et ignoré : X` répétitives.
  `render_signal_label` traite spécifiquement `SIG_DROPPED_UNKNOWN_TOKENS`.

### Lot S — BBCode parser fixes

- `[center]...[/center]` : retire les `\n` internes avant le `\n→<br>`
  final, pour permettre aux images du cast/poster de rester inline et
  centrées horizontalement (sinon empilées verticalement par les `<br>`).
- `[img=W]`, `[img=WxH]`, `[img]` : trim `\s+` au lieu de `.trim()` pour
  gérer les URLs entourées de newlines/espaces. Si l'URL n'est pas valide,
  affiche un placeholder visible *« ⚠ [img=W] URL invalide »* au lieu de
  silently disparaître.

### Fichiers touchés

```
src/flox_uploader/core/media_type.py        (EPISODE_PATTERNS Lot O.1)
src/flox_uploader/core/release_name.py      (drop_tokens ambigus + _enrich_audio_video Lot O.3 + P)
src/flox_uploader/core/tmdb.py              (refonte resolver Lot O.2/O.3/O.4 + tvdb_id + keywords Q.2)
src/flox_uploader/core/package_state.py     (manual_imdb_id/tvdb_id/mal_id/season/episode/distributor/region/keywords Q.1)
src/flox_uploader/core/upload_orchestrator.py (build_upload_payload Lot Q.5)
src/flox_uploader/core/confidence.py        (bucket "parfait" Lot R-C)
src/flox_uploader/core/naming_signals.py    (groupement tokens Lot R-D)
src/flox_uploader/pipeline.py               (OMDb soft warning Lot O.5)
src/flox_uploader/web/app.py                (state -> template Lot Q + endpoint /options Lot Q.5)
src/flox_uploader/web/templates/package_detail.html  (UI Lot R-A/B/C, BBCode S, champs Q.3-Q.4)
src/flox_uploader/web/templates/base.html   (CSS glow parfait/perfect Lot R-C)
tests/test_lot_o_p_bugs_reels.py               (NOUVEAU : 20 tests)
tests/test_lot_q_upload_fields.py              (NOUVEAU : 12 tests)
```
