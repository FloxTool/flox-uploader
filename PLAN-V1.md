# Plan de publication v1 — Flox Uploader

> Document de référence unique pour la première release publique.
> **Toute décision ici fait autorité** — si une question revient, on relit ce doc.
> Si on change une décision, on l'amende ici **avant** de toucher au code.

Version cible de la release publique : `v0.4.0`
Versions intermédiaires utilisées comme jalons : `v0.3.x` pour les sprints sans
rupture, `v0.4.0` pour le tag de release Windows publique.

---

## 0. Décisions stratégiques figées

| # | Décision | Choix |
|---|---|---|
| D1 | **Nom de l'app** | **Flox Uploader** |
| D2 | **Slug** | `flox-uploader` (pip/repo) / `flox_uploader` (Python package) |
| D3 | **Licence** | **MIT** + disclaimer dans README + Guide |
| D4 | **Hébergement code** | **`github.com/FloxTool/flox-uploader`** (organisation publique, membership owner en privé) |
| D4b | **Tagline officielle** | *"Préparation et upload soignés de releases vidéo pour trackers privés. Local-first."* (84 chars) |
| D4c | **Crédits signature** | "Flox" (commits, README, footer, etc.) |
| D4d | **Couleur de marque** | Indigo `#6366f1` (charte conservée, pas de changement) |
| D4e | **Canal de support** | GitHub Issues uniquement (pas de Discord, pas d'email) |
| D4f | **Git config local** | `user.name = "Flox"` + `user.email = "<ID>+flox@users.noreply.github.com"` pour ce repo (séparation pseudonyme / vrai compte) |
| D5 | **OMDb** | Optionnel, encouragé. Si vide → on retire silencieusement note IMDB + récompenses + warnings associés |
| D6 | **Onboarding** | Pas de wizard multi-étapes. On améliore la page `/setup` existante (liens API + pédagogie + **boutons "Tester" inline**) |
| D7 | **Multi-OS** | **Win d'abord** (v1 publique). Puis macOS, Linux, Docker (NAS) en série |
| D8 | **Multi-tracker** | Architecture l'anticipe (couche tracker abstraite). UI/Guide v1 = full Gemini |
| D9 | **Cible users initiale** | ~20 puis croissance |
| D10 | **Telemetry** | Aucune, jamais. Cohérent avec la philosophie local-first |
| D11 | **Crash reports** | "Copier rapport" + lien GitHub Issues. Zéro backend |
| D12 | **Code signing** | **Reporté post-v1**. v1 non-signée + doc qui explique le warning |
| D13 | **Tray icon** | Reporté à v0.5+ |
| D14 | **Watcher mode** (auto-prepare dossier surveillé) | Reporté à v0.5+ |
| D15 | **Exposition réseau + auth** | Reporté à v0.5+ (Docker couvre NAS en v1) |
| D16 | **Auto-update** | v1 : banner discret + lien manuel vers GitHub Releases. v0.5+ : auto-update intégré |
| D17 | **README v1** | Minimum (pitch + 3-4 captures + boutons download + install instructions) |
| D18 | **Stockage data** | OS-standard via `platformdirs` (avec respect de `FLOX_UPLOADER_DATA_DIR` si défini) |

---

## 1. Architecture cible v1

### 1.1 Identité

- **Nom complet** : Flox Uploader
- **Tagline officielle** : *"Prépare et upload tes releases proprement."*
- **Logo** : à fournir (en cours)
- **Licence** : MIT (fichier `LICENSE`)
- **Disclaimer légal** (à intégrer dans README + page `/guide`) :
  > Flox Uploader est un outil de préparation et d'envoi. L'utilisateur est seul
  > responsable du contenu qu'il prépare et envoie. Vérifie les règles de ton
  > tracker et les lois en vigueur dans ta juridiction avant chaque upload.
  > Aucune donnée ne quitte ta machine sans appel API explicite (TMDB, OMDb, tracker).

### 1.2 Canaux de distribution v1

```
Canal A — Installeur natif Windows .exe                  [v0.4.0]
  ↓
Canal B — Installeur natif macOS .dmg                    [v0.5.0]
  ↓
Canal C — Installeur natif Linux AppImage                [v0.5.0 ou v0.6.0]
  ↓
Canal D — Image Docker (docker-compose pour NAS)         [v0.5.0 ou v0.6.0]
```

Tag de version publique = Windows uniquement pour `v0.4.0`. Les autres OS
arrivent dans des releases ultérieures.

### 1.3 Stockage des données (OS-standard)

| OS | Path par défaut |
|---|---|
| Windows | `%APPDATA%\flox-uploader\` |
| macOS | `~/Library/Application Support/flox-uploader/` |
| Linux | `~/.config/flox-uploader/` (XDG) |
| Docker | `/data` (monté en volume) |

Contenu : `.env`, `jobs.db`, `data/upload_packages/`, `.tmdb_cache.json`, logs.

**Override env var** : `FLOX_UPLOADER_DATA_DIR` (renommée depuis l'actuelle
`TRACKER_UPLOADER_DATA_DIR`). Cas d'usage : Docker, ou user qui veut placer
ses données sur un autre disque.

**Implémentation** : librairie `platformdirs` (standard de facto pour ça en
Python). Fallback : si le path n'est pas writable, log un warning + utilise
un dossier temp.

**Migration depuis une install dev** : si `data/upload_packages/` existe dans
le CWD à la 1ère exec et que le path OS-standard est vide, on propose un
import (modal de bienvenue).

### 1.4 Architecture multi-tracker (anticipée, pas activée)

Aujourd'hui le code suppose Gemini (`tracker_uploader.core.gemini_api`). Pour
préparer l'extension future sans la livrer maintenant :

- Renommer `gemini_api.py` → garder le nom (c'est l'implémentation Gemini)
- Introduire `core/tracker_base.py` avec une **interface abstraite** :
  - `check_duplicate(tmdb_id, release_name, size_bytes) → DupResult`
  - `upload(package_dir, options) → UploadResult`
  - `get_torrent_url(torrent_id) → str`
- `GeminiClient` implémente cette interface.
- Tout le code applicatif (jobs_runner, upload_orchestrator, app.py) parle à
  l'interface, pas à `GeminiClient` directement.

**Coût** : ~1-2 jours de refacto. Bénéfice : ajout d'un tracker = écrire une
nouvelle classe, pas réécrire la couche métier. **À planifier dans Sprint 4-5**.

L'UI continue à dire "Gemini" partout. Quand on ajoutera un 2e tracker, on
ajoutera un sélecteur dans /config.

### 1.5 Lancement

Quand l'user double-clique l'installeur Windows :

1. L'app démarre **sans console visible** (PyInstaller `--windowed`).
2. Choisit un port libre dynamiquement (8000, sinon 8001, 8002…).
3. Ouvre `http://127.0.0.1:<port>/setup` dans le navigateur par défaut.
4. Si setup déjà complet → ouvre `/inbox` directement.
5. Si l'user ferme la fenêtre du navigateur, **l'app reste en arrière-plan**
   jusqu'au tray icon (v0.5+). En v1 sans tray, l'user kill via Gestionnaire
   des tâches. À documenter dans le README.

### 1.6 Auto-update v1

Au démarrage du serveur (async, non bloquant) :

1. Fetch `https://api.github.com/repos/flox/flox-uploader/releases/latest`.
2. Compare `tag_name` avec `__version__` local (semver).
3. Si update dispo : exposer un endpoint `/api/update-info` qui retourne
   `{available: bool, latest: str, current: str, release_url: str, changelog: str}`.
4. Côté UI : banner discret en haut de toutes les pages (au-dessus du banner
   setup_incomplete) avec **"Mise à jour disponible (vX.Y.Z) → voir le détail"**.
5. Click → ouvre la page GitHub Releases dans un nouvel onglet.
6. **Preference** stockée en localStorage : `tu_dismissed_update_X.Y.Z` →
   ne plus afficher cette version-là. Au prochain release, le banner revient.

Pas d'auto-download / restart en v1. Trop de cas d'erreurs (droits admin,
rollback, etc.) pour 20 users.

---

## 2. Roadmap par sprints

**En série, Windows d'abord.** Chaque sprint produit un livrable testable. On
ne passe au suivant que quand le précédent est mergé et tagué.

### Sprint 1 — Préparation repo + branding ✅ COMPLÉTÉ (2026-05-14)

**Objectif** : repo prêt à devenir public, identité figée.

**Repo créé** : `github.com/FloxTool/flox-uploader` (private)
**Tag** : `v0.3.1` (commit `d4c0018`, signé `Flox <flox@floxtool.dev>`)

| Tâche | Statut | Note |
|---|---|---|
| Logo final intégré (favicon, sidebar, manifest) | ✅ | `currentColor` + couleur charte par défaut |
| `LICENSE` fichier MIT à la racine | ✅ | Copyright Flox |
| Disclaimer dans Guide | ✅ | Section dédiée dans `/guide` |
| Refactor `tracker_uploader` → `flox_uploader` | ✅ | **373 occurrences, 58 fichiers** ; tests verts |
| `CHANGELOG.md` format Keep a Changelog | ✅ | Section v0.3.1 + rétrospectif v0.3.0 (rounds 1-9) |
| `CONTRIBUTING.md` + `SECURITY.md` | ✅ | Templates personnalisés |
| Issue templates `.github/ISSUE_TEMPLATE/` | ✅ | bug.yml + feature.yml + question.yml + config.yml |
| `.github/workflows/tests.yml` (GitHub Actions) | ✅ | Matrix Python 3.10/3.11/3.12 + MediaInfo CLI |
| Tag intermédiaire `v0.3.1` | ✅ | Pushé sur FloxTool |
| Backward compat env var `TRACKER_UPLOADER_DATA_DIR` | ✅ | Bonus : transition douce |

**Definition of Done Sprint 1** : ✅ TOUS VERTS
- ✅ `git clone + pip install -e .` marche (testé localement)
- ✅ 622/622 tests verts après refactor
- ✅ Repo créé sur FloxTool, identité "Flox Uploader" partout dans l'UI + docs
- ✅ CI verte sur les 3 versions Python (3.10 / 3.11 / 3.12, après fix `pip install -e .[web,dev]`)
- ✅ Node.js 20 deprecation gérée via `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`

**Hotfix appliqué post-tag v0.3.1** (commit `6e49984`) :
- Workflow CI installait `[dev]` seulement, manquait `[web]` (fastapi/uvicorn/jinja2)
- Symptôme : `ModuleNotFoundError: No module named 'fastapi'` sur tous tests web

### Sprint 2 — Amélioration de la page /setup (1 semaine)

**Objectif** : un user lambda comprend ce qu'il doit faire et a des outils
pour valider sa config sans aller voir Google.

| Tâche | Note |
|---|---|
| Ajouter une section "où trouver cette info" pour chaque champ | Liens vers themoviedb.org/settings/api, omdbapi.com, profil Gemini, etc. |
| Boutons "Tester" inline (TMDB key, OMDb key, tracker API key, URL announce) | Endpoint `/api/config/test-key?kind=tmdb` qui fait un appel rapide et retourne ok/erreur |
| Indicateur visuel par champ (vert = testé OK, rouge = erreur, gris = non testé) | Petit badge à droite du champ |
| Pédagogie courte au-dessus de chaque groupe | "Pourquoi on a besoin de TMDB ?" en 1 phrase |
| Réorganiser visuellement par groupes : Tracker / Métadonnées / Stockage | Actuellement c'est en vrac |
| Empty state "Bienvenue !" pour le 1er run | Détection : si .env n'existe pas → afficher un message d'accueil au-dessus du form |

**Definition of Done Sprint 2** : un user qui n'a jamais utilisé l'app peut
compléter sa config en < 5 min sans aide externe.

### Sprint 3 — OMDb optionnel (3-5 jours)

**Objectif** : OMDb absent = comportement gracieux, pas d'erreurs.

| Tâche | Note |
|---|---|
| Détecter OMDb absent au démarrage du pipeline | Skip silencieux des appels OMDb |
| Retirer "récompenses" de la BBCode si OMDb vide | Conditionnel dans le template |
| Retirer "note IMDB" de la carte Media si OMDb vide | Conditionnel dans package_detail.html |
| Retirer le warning "OMDb non configuré" qui doit exister quelque part | Audit du code |
| Tests : pipeline complet sans OMDb → score normal, BBCode propre | 3-4 tests |
| Doc dans /setup : OMDb marqué "Optionnel mais encouragé" | Visuel clair |

**Definition of Done Sprint 3** : tu peux installer Flox Uploader, configurer
TMDB + tracker seulement, et tout marche. Pas de log de warning sur OMDb.

### Sprint 4 — Préparation distribution (1-2 semaines)

**Objectif** : l'app peut tourner comme une app installée, plus comme un
projet de dev.

| Tâche | Note |
|---|---|
| Intégrer `platformdirs` (ajout dépendance) | https://pypi.org/project/platformdirs/ |
| Refactor `config.data_dir()` → utilise platformdirs + override env var | Remplace les paths hardcodés |
| Migration si dossier dev détecté → propose import au 1er run | Optionnel mais nice |
| Auto-launch navigateur au démarrage du serveur | `webbrowser.open(url)` après uvicorn ready |
| Port dynamique (8000 → 8001 → 8002 si occupé) | Fonction `find_free_port()` simple |
| Anticipation refactor multi-tracker | Création de `core/tracker_base.py` + adaptation `GeminiClient` |
| Tests doivent toujours passer | Toute la suite |

**Definition of Done Sprint 4** : `python -m flox_uploader serve` ouvre auto
le navigateur, écrit dans `%APPDATA%\flox-uploader\` sur Windows, et tous
les tests passent.

### Sprint 5 — Bundling Windows (2-3 semaines, le gros morceau)

**Objectif** : un `.exe` qui s'installe et marche sur une machine Windows
propre (pas de Python, pas de MediaInfo).

| Tâche | Note |
|---|---|
| Spec PyInstaller (`flox_uploader.spec`) | Onedir au début (plus simple à debug), passer onefile plus tard si besoin |
| Embed binaires MediaInfo Windows | Télécharge automatiquement depuis mediaarea.net dans le build |
| `--windowed` pour cacher la console | Cosmétique mais essentiel |
| Embed les templates Jinja, static, _icons.html | PyInstaller `datas` |
| Test sur VM Windows propre | Sans Python, sans MediaInfo préinstallé |
| Inno Setup script (`installer.iss`) | Génère le `.exe` setup. Crée raccourcis Bureau + Menu Démarrer |
| Désinstallation propre | Supprime l'app, **garde le data dir** par défaut (option "supprimer aussi mes données" cochable) |
| GitHub Actions Windows workflow | Sur tag → build PyInstaller → run Inno Setup → upload artifact |
| Doc README : "Comment passer le SmartScreen warning" | Capture d'écran "Plus d'infos → Exécuter quand même" |

**Definition of Done Sprint 5** : tu télécharges un `.exe` depuis ton drag-VM
propre, tu double-cliques, tu attends 30 sec, l'app s'ouvre dans ton
navigateur. Tu configures TMDB. Tu prepare un fichier. Tu vérifies. Tout marche.

### Sprint 6 — Auto-update v1 (4-5 jours)

**Objectif** : l'user sait quand une nouvelle version sort.

| Tâche | Note |
|---|---|
| Endpoint `/api/update-info` qui fetch GitHub Releases | Cache résultat 6h |
| Banner UI au-dessus du setup_incomplete | Discret, dismissible per version |
| LocalStorage `tu_dismissed_update_X.Y.Z` | Persistance du dismiss |
| Click → ouvre la page Releases dans un nouvel onglet | Pas d'auto-download |
| Tests : mock fetch, vérifier la logique de comparaison semver | Important pour éviter false positives |

**Definition of Done Sprint 6** : tu pushes `v0.4.0` puis `v0.4.1` plus tard,
les users qui ont `v0.4.0` voient le banner au prochain démarrage.

### Sprint 7 — Marketing v1 minimum (1 semaine)

**Objectif** : un user qui découvre le repo comprend en 30 sec pourquoi
installer.

| Tâche | Note |
|---|---|
| README orienté user (pas dev) | Hero pitch + screenshots + download + install + lien Guide |
| 3-4 captures d'écran HD (Inbox, Queue, Package detail, Score) | Light mode |
| Section "Pour qui c'est ?" courte | Cible francophone + tracker privé |
| Section "Ce que l'app fait / fait pas" | Hérité du Guide |
| Boutons download (Windows seulement pour la v0.4) | Lien direct release latest |
| Section "Install Windows" (3 étapes max + capture du SmartScreen) | |
| Lien "Documentation complète → Guide intégré dans l'app" | |
| Section "Roadmap" ou "À venir" | macOS / Linux / Docker / multi-tracker |
| Section "Crédits + Licence" | MIT + remerciements TMDB, OMDb, Lucide, etc. |
| README séparé pour les devs | `README-DEV.md` avec instructions pip install -e . |

**Definition of Done Sprint 7** : le README est aussi clean qu'une page produit
de Linear (sans le polish ultime, c'est juste un README markdown).

### Sprint 8 — Crash report helper (3-4 jours)

**Objectif** : quand ça plante, l'user peut t'aider à débugger en 2 clics.

| Tâche | Note |
|---|---|
| Bouton "Copier rapport" dans tout toast d'erreur | Copie : version, OS, dernières 50 lignes log, stack trace si dispo |
| Bouton "Signaler sur GitHub" → ouvre Issues avec template pré-rempli | URL `?template=bug.yml&title=...&body=...` |
| Template `.github/ISSUE_TEMPLATE/bug.yml` propre | Sections : description, version, OS, log, étapes |
| Bouton "Signaler un bug" dans le Guide page | Lien direct vers le template |
| Pas de logique côté serveur Flox | Tout passe par GitHub, tu reçois les notifs |

**Definition of Done Sprint 8** : tu provoques un crash en test, tu cliques
"Signaler", une nouvelle Issue GitHub se crée avec tout le contexte utile.

### Sprint 9 — Release v0.4.0 publique Windows (3-5 jours)

**Objectif** : tag, build, release, annonce.

| Tâche | Note |
|---|---|
| Test E2E manuel complet sur VM Windows propre | Install, setup, prepare, upload, désinstall |
| Audit final README + screenshots à jour | Pas de typo, pas de capture obsolète |
| Tag `v0.4.0` | Bump dans `pyproject.toml` + `__init__.py` |
| GitHub Release avec release notes | Format : Highlights / Features / Fixes / Breaking |
| Installer `.exe` attaché à la release | Auto-uploadé par CI sur tag |
| Annonce communauté (à toi de voir) | Forum/Discord Gemini, éventuellement r/torrents |

**Definition of Done Sprint 9** : un user qui va sur ton repo GitHub voit
la dernière release, clique "Télécharger Windows", installe, et l'app
fonctionne.

---

## 3. Backlog v0.5+ (post-release publique)

Ce qui suit n'est PAS dans le scope v1. À traiter dans des releases suivantes
quand on aura du retour des 20 premiers users.

### v0.5 candidate
- **Bundling macOS** (.dmg, Apple Developer 99 $/an pour notarization)
- **Bundling Linux** (AppImage)
- **Docker image + docker-compose** (cible NAS)
- **Tray icon Windows + macOS** (`pystray` ou wrapper Tauri léger)

### v0.6 candidate
- **Signing Windows** (cert EV ~300 €/an, supprime SmartScreen)
- **Auto-update v2** (download + restart automatique avec rollback)
- **Network exposure + mot de passe** (auth basic / session, pour usage NAS bare metal)

### v0.7+ candidate
- **Watcher mode** (surveiller un dossier → auto-prepare)
- **Multi-tracker activé** : ajout d'un 2e tracker FR au choix
- **Internationalization** : split strings vers fichier i18n, support EN
- **Backup/export du data dir** depuis l'UI (bouton "Sauvegarder mes données")

---

## 4. Anti-patterns à éviter pendant la v1

| ❌ Anti-pattern | ✅ À la place |
|---|---|
| Mettre une dépendance externe non bundlée | Bundler dans PyInstaller ou Docker |
| Hardcoder un chemin Windows / Linux dans le code | Toujours passer par `data_dir()` qui appelle platformdirs |
| Ajouter une fonctionnalité Gemini-spécifique dans le code générique | Tout passe par l'interface `tracker_base` |
| Casser la philosophie "no telemetry" | Aucune requête sortante hors APIs configurées par l'user |
| Sortir un installeur sans tester sur VM propre | Test obligatoire avant chaque tag |
| Inclure "Gemini" dans le nom du package ou des URLs | Garder Flox Uploader agnostique |
| Forcer l'user à éditer un fichier `.env` à la main | Tout doit être faisable via /setup ou /config |
| Logguer des données sensibles (clés API, passkeys) en clair | ScrubbingWriter déjà en place — garder vigilant |

---

## 5. Definition of Done — v0.4.0

Pour que `v0.4.0` puisse être taguée et release publiquement, **TOUS** ces
points doivent être vrais :

- [ ] Repo public sur GitHub avec README marketing
- [ ] LICENSE MIT à la racine + disclaimer dans Guide page
- [ ] Tag `v0.4.0` créé, release GitHub avec installer .exe attaché
- [ ] CHANGELOG.md à jour avec la section v0.4.0
- [ ] Installer Windows fonctionne sur VM propre (sans Python, sans MediaInfo)
- [ ] Setup wizard guidé avec test buttons opérationnels
- [ ] OMDb optionnel : pipeline marche sans OMDb configuré
- [ ] Data dir respecte le standard Windows (`%APPDATA%`)
- [ ] Auto-launch navigateur fonctionne
- [ ] Banner auto-update affiche si version > current
- [ ] Crash report helper opérationnel (copier + lien GitHub Issues)
- [ ] CI passe sur main (tests verts)
- [ ] README explique comment passer le SmartScreen warning
- [ ] Aucune télémétrie active, aucune donnée ne quitte la machine
- [ ] Documentation `flox-uploader` cohérente partout (plus aucune mention `tracker_uploader` dans le code utilisateur-facing)

---

## 6. Checklist pré-Sprint 1 — STATUT : ✅ COMPLÈTE

Tous les items bloquants Sprint 1 sont résolus :

- [x] **Logo final** ✅ Intégré (`assets/img/logo.svg` source + `src/.../static/logo.svg` runtime, en `currentColor` avec couleur charte par défaut)
- [x] **Nom du repo GitHub** ✅ `flox-uploader`
- [x] **GitHub org / handle** ✅ Organisation `FloxTool` → repo final = `github.com/FloxTool/flox-uploader`
- [x] **Couleur de marque** ✅ Indigo `#6366f1` (charte conservée)
- [x] **Tagline** ✅ *"Préparation et upload soignés de releases vidéo pour trackers privés. Local-first."*
- [x] **Crédits signature** ✅ "Flox"
- [x] **Canal de support** ✅ GitHub Issues uniquement

**On peut démarrer Sprint 1.**

---

## 7. Références croisées

- `CHARTE.md` — Design system (couleurs, typo, composants, patterns UX)
- `NOTES.md` — Notes brutes de dev (instructions Claude, bugs, idées)
- `README.md` — Version actuelle (à refondre Sprint 7)
- `pyproject.toml` — Métadonnées projet (à renommer Sprint 1)
- `src/tracker_uploader/__init__.py` — `__version__` (à renommer + bump)

---

## 8. Versioning

Convention : **semver**.

- `v0.3.x` — sprints incrémentaux pendant le développement v1 (pas de release publique)
- `v0.4.0` — **première release publique Windows**
- `v0.4.x` — patches sur la release Windows
- `v0.5.0` — extension macOS + Linux + Docker
- `v0.5.x` — patches multi-OS
- `v0.6.0` — signing + auto-update v2 + network exposure
- `v1.0.0` — quand l'app est stable, packagée propre sur 3 OS, signée, avec
  un volume d'users qui justifie le label "1.0"

Tag git = `v` + version. Branch model = `main` direct (pas de gitflow,
projet trop petit pour la complexité).

---

## 9. Notes pour Claude (sessions futures)

Quand on attaque l'implémentation :

- Lire ce doc d'abord
- **Ne pas modifier les décisions** sans confirmer avec l'utilisateur
- Travailler sprint par sprint dans l'ordre
- À la fin de chaque sprint : exécuter la "Definition of Done" du sprint
- Tag intermédiaire à la fin de chaque sprint si stable
- Maintenir le CHANGELOG.md à jour à chaque changement notable
- Si une décision doit être révisée pendant un sprint, **modifier ce doc en
  premier**, puis le code

Décisions implicites complémentaires :

- Tests : viser à garder 100% des tests verts à chaque sprint. Si un sprint
  refactor casse des tests, **fix les tests dans le même sprint**, pas plus tard.
- Commits : un commit par "étape logique" du sprint. Pas de gros commit
  fourre-tout.
- Pas de squash dans le `main`. L'historique est documentation.
