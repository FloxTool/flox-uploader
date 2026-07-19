# Pièges connus & dette technique

> Consolidation des pièges, workarounds, limites, et zones fragiles du
> projet. Consulté **avant** de toucher à une zone du code, pour éviter
> de re-tomber dans un piège déjà identifié.
>
> Sources consolidées : `CLAUDE.md` §14 + `PLAN-MULTICAT.md` §11 +
> `CHANGELOG.md` (limitations par version) + `README.md` (SmartScreen) +
> observations directes.

---

## 1. État du projet (contexte temporel)

### 🚧 GitHub Actions désactivé sur le compte `fremontlouis`
**Statut au 2026-07-18 : toujours bloqué** (retesté via `workflow_dispatch`,
même erreur). Burst de ~73 workflow runs en 2 jours (2026-05-20) a déclenché
l'anti-abus de GitHub. L'erreur exacte :
```
HTTP 422: Actions has been disabled for this user.
```
**Conséquences** :
- Le build CI Windows (`.github/workflows/build-windows.yml`) ne peut pas
  tourner.
- Les tests CI ne tournent pas sur les PRs (mais pytest local fonctionne).
- **Le développement local reste 100% fonctionnel.** Coder, tester, créer
  des PRs, les merger via UI GitHub — tout marche.

**Ticket support** : réponse de triage reçue 2026-07-18 (« reply to
prioritize »), réponse envoyée le jour même. En attente de la review
manuelle.

**Workaround adopté (v0.5.0)** : **build 100% local** qui réplique les
étapes du workflow CI — PyInstaller (`packaging/flox_uploader.spec`) +
Inno Setup local (`ISCC.exe packaging\flox_uploader.iss
/DMyAppVersion=X.Y.Z`) + smoke tests. L'installeur et le ZIP portable
sont ensuite **attachés manuellement à la GitHub Release** via
`gh release create` — l'upload d'assets ne dépend pas d'Actions.
Premier build livré ainsi : v0.5.0 (2026-07-18).

---

## 2. Pièges Windows

- **Path 8.3 court** : si l'output dir est sur un path long
  (`C:\Users\Long\...\Tracker Uploder\output\...`), `torf` peut planter à
  l'upload. **Recommander à l'user un path court** (ex: `C:\trackup\`).
  À résoudre via `data_dir()` cross-platform avec `platformdirs` (déjà fait
  en Sprint 4 PLAN-V1, cf. `%LOCALAPPDATA%\fremontlouis\flox-uploader\`).
- **`autocrlf=true`** : Git Windows convertit LF → CRLF automatiquement.
  Cosmétique, ne pas s'en inquiéter — `git diff` montre des warnings
  bénins.
- **`.git/index.lock` orphelin** : si une session précédente a crashé.
  Solution : `del .git\index.lock` pour débloquer.
- **CMD vs PowerShell vs Git Bash** : syntaxes différentes (`cat << EOF`
  ne marche pas en CMD). Toujours préciser ou donner les 2 versions.
- **SmartScreen warning** : l'installeur n'étant pas signé (pas de
  certificat EV à 300€/an pour un side-project), Windows affiche *"Windows
  a protégé votre PC"* au 1er lancement. L'user doit cliquer
  **"Informations complémentaires"** → **"Exécuter quand même"**.
  Documenté dans `README.md`. Solution réelle = code signing (reporté
  post-v1, cf. PLAN-V1.md D12).
- **Subprocess avec console qui flash (résolu v0.3.16)** : sur Windows
  bundle PyInstaller, `subprocess.run([...])` ouvre une fenêtre console
  qui pop au premier plan et vole le focus. **Toujours ajouter
  `creationflags=subprocess.CREATE_NO_WINDOW` sur Windows** pour les
  subprocess que l'user ne doit pas voir.
- **`sys.stdout/stderr = None` en mode windowed PyInstaller (résolu
  v0.3.5)** : `python -m flox_uploader serve` avec PyInstaller `--windowed`
  → `sys.stdout = None`, ce qui plante uvicorn (`AttributeError: 'NoneType'
  object has no attribute 'isatty'`). **Fix dans `launcher.py`** : patch
  `sys.stdout/stderr` vers `os.devnull` au tout début, AVANT tout import.

---

## 3. Pièges pipeline naming

- **`team.upper()` est INTERDIT** : la casse signature de la team doit être
  préservée (`Punisher694` ≠ `PUNISHER694`, `PopHD` ≠ `POPHD`, `mHDgz`,
  `Frosties`). Le `_CANONICAL_CASE` ne s'applique **qu'aux tokens scene**
  (BluRay, x265, etc.), jamais à la team.
- **`_NEVER_TEAM` et `_TECH_TOKENS` étaient dupliqués** → mutualisés en
  `_TECH_TOKENS` + `_TECH_UPPER`. Si tu modifies l'un, **vérifie l'autre
  usage** (notamment `split_team` ET `_looks_minimal`).
- **`_looks_minimal` doit rester en sync avec `_TECH_TOKENS`** (utilise le
  regex compilé `_LOOKS_MINIMAL_TECH_PATTERN`). Modifier les tokens sans
  recompiler le regex = bug silencieux.
- **Auto-enrichissement langue : `inferred["audio_titles"]`**, **PAS**
  `nfo_audio_titles` qui n'existe pas. Bug fréquent à éviter.
- **Furiosa S01E265 résolu (v0.3.x)** : `EPISODE_PATTERNS` durci avec
  lookbehind anti-channel-layout. Sans le fix, `5.1x265` matchait comme
  S01E265 (le `5.1` confondu avec un numéro d'épisode).
- **MAX/NFLX/etc. droppés trop tôt (résolu)** : tokens ambigus protégés
  AVANT l'année (ce sont des mots du titre avant), droppés APRÈS.
- **`infer_french_variant` strict** : ne devine jamais silencieusement.
  Si ambigu (`MULTi` sans précision) → émet signal + score < 90 → review
  humaine. Cf. CLAUDE.md §4 "Human-in-the-loop systématique".

---

## 4. Pièges TMDB / OMDb

- **Min 2 mots significatifs** (≥ 3 chars) lors du raccourcissement TMDB.
  `"Les"` seul match n'importe quoi (bug "Sept Samouraïs" résolu).
- **Multi-langue** : essayer **en-US d'abord**, puis fr-FR. Pas l'inverse
  (sinon on récupère le titre FR pour des films internationaux).
- **CJK/cyrillique** : fetcher le `title_en` séparément
  (`_maybe_fetch_title_en`) car pas dispo dans le call fr-FR. Émet
  `SIG_TMDB_TITLE_EN_FALLBACK` (-2 pts).
- **TMDB ranking refondu (Lot O)** : on cumule en-US + fr-FR sans
  year-filter API, puis ranking par `year_score (tolérance ±1) +
  title_score + popularity + vote_count*0.5`. Évite qu'un court-métrage
  gagne sur le blockbuster homonyme.
- **OMDb optionnel (Sprint 3)** : si pas configuré → skip silencieux, pas
  de pénalité score, pas de warning. Penalty `SIG_OMDB_DATA_MISSING`
  s'émet **uniquement** si la clé est configurée mais l'API ne renvoie
  rien (cas légitime).
- **OMDb 6 mois** : films sortis < 6 mois ne déclenchent pas le signal
  (délai d'indexation OMDb attendu).
- **GitHub API rate limit** : 60 req/h pour IP non-authentifiée. Le bouton
  "Vérifier les mises à jour" peut frapper la limite — message d'erreur
  explicite avec heure de reset (v0.3.15).

---

## 5. Pièges UI / web

- **Templates monolithiques** :
  - `web/templates/package_detail.html` (~2700 lignes)
  - `web/templates/queue.html` (~1700 lignes)
  - `web/app.py` (116 KB, ~3000 lignes)

  Réfléchir avant d'ajouter encore du contenu — la complexité commence à
  être problématique. PLAN-MULTICAT prévoit de découper par profil
  catégorie (`_detail_video.html`, `_detail_book.html`, etc.) au Sprint C.

- **Console MediaInfo qui flashait à chaque page (résolu v0.3.16)** :
  `_detect_mediainfo()` lançait `subprocess.run` à chaque render via le
  diagnostic. **Fix : cache module-level + `CREATE_NO_WINDOW`**. Ne pas
  réintroduire d'appel subprocess non-caché dans les hooks Jinja globaux.

- **Loader plein écran sur navigation lente** : à l'origine cassé par un
  escape JS invalide (`'## Message d\\'erreur'`). Toujours utiliser
  double-quotes pour les strings contenant des apostrophes.

- **Polling queue bloqué si modal ouverte (résolu v0.3.16)** : quand un
  job finissait pendant que la modal "log" était ouverte, le polling
  faisait `return` sans reprogrammer de tick. **Toujours reprogrammer le
  poll même modal ouverte.**

- **Sélection perdue dans "Préparations en cours" au reload auto (résolu
  v0.3.12)** : persistance `sessionStorage` (`tu_queue_prep_selection_v1`).

- **Filtres queue : logique inversée (v0.3.18 PR #19)** : tous cochés par
  défaut = tout affiché ; cocher = retirer → contre-intuitif. Refondu
  inversé : sets vides par défaut = tout affiché ; cocher = isoler.
  Bump localStorage `tu_queue_filters_v2 → v3` pour invalider les
  sauvegardes ancien schéma.

- **Path traversal sur `/inbox` + `/api/files` + `/api/queue/add`** : à
  auditer **avant exposition réseau** (v0.5+). Local-only en v1 →
  surface d'attaque limitée. Voir `AUDIT.md` §5.1.

- **Anti-patterns CHARTE.md §15** :
  - ❌ Couleurs hex hors palette → utiliser les tokens Tailwind / vars CSS
  - ❌ `transition-colors` + `.interactive` en même temps → choisir l'un
  - ❌ `title="…"` HTML natif → toujours `data-tu-tooltip="…"`
  - ❌ `window.confirm()` / `window.alert()` → `tu.confirm()` / `tu.alert()`
  - ❌ Emoji dans l'UI (sauf drapeaux Twemoji)
  - ❌ Padding hors échelle 4px-grid
  - ❌ Z-index > 80 → casse l'ordre des tooltips
  - ❌ Toast sans `tone` → toujours préciser info/success/warning/danger

---

## 6. Pièges compliance audio (cas réels résolus)

Quelques faux positifs résolus, à retenir pour ne pas régresser :

- **`E-AC3.5.1` lu comme `3.5` (résolu v0.3.17)** : `re.findall` non-chevauchant
  matchait `3.5` (le `3` de AC**3** + `.5`) puis ratait le vrai `5.1` qui
  suivait. **Fix** : capture en chevauchement `(?=(\d\.\d))` + filtrage
  contre `_VALID_AUDIO_LAYOUTS = frozenset({"1.0","2.0","2.1","4.0","5.1","6.1","7.1"})`.
- **`2.2` extrait de `VF2.2160p` (résolu v0.3.16)** : regex `\d\.\d(?!\d)`
  évite ce piège (lookahead anti-3-chiffres).
- **`AC35.1` / `DDP5.1` collés (résolu v0.3.16)** : matchent désormais.
- **Multi-pistes audio (résolu v0.3.16)** : accepte **n'importe quelle
  piste audio** (pas uniquement `audio_tracks[0]`). Avant : un release
  avec 2 pistes (7.1 default + 5.1 alt) taggé `5.1` levait un faux warning.

---

## 7. Pièges Gemini / API tracker

- **Format URL Gemini réel (résolu v0.3.14)** : `/torrent/download/<id>.<passkey>`
  (singulier `torrent` + `.` puis passkey 32 chars). La regex `_parse_torrent_id_from_url`
  doit accepter `torrent[s]?` + **tout non-digit** comme séparateur post-id.
- **Limitation packages legacy** : les packages déjà uploadés AVANT v0.3.13
  gardent leur `uploaded_torrent_url` vide en base. Pas de migration auto
  → re-upload ou édition manuelle du state.
- **MediaInfo obligatoire / non-obligatoire selon catégorie** : cf.
  `unit3d_mapping.py::MEDIAINFO_REQUIRED_CATEGORIES`. Pour ebook/jeu/soft
  c'est `False` (mais le pipeline appelle MediaInfo inconditionnellement
  aujourd'hui — bug bloquant pour le non-vidéo, à fixer en Sprint A v0.5.0).
- **TYPE_IDs 16-37 manquants** dans `unit3d_mapping.py` (Jeux\Windows,
  Livres\BD, etc.). Bloqueur upload non-vidéo. Cf. `PLAN-MULTICAT.md` §8.1.
- **Teams interdites incomplètes** : `DEFAULT_BANNED_TEAMS = ("k0RE",
  "Slay3R")` seulement. Liste officielle Gemini ajoute Fenixx,
  KMS.Tools.Portable, MAXAGENT, Seyter, Vansik (jeux/apps). EXTREME en
  cas spécial (encodes interdits, REMUX/Full Blu-ray/WEB-DL autorisés).
  À étendre Sprint A v0.5.0.

---

## 8. Pièges anticipés v0.5.0 (multi-catégorie)

À garder en tête quand on attaquera les Sprints D-H de
[`PLAN-MULTICAT.md`](../PLAN-MULTICAT.md) :

- **BnF SRU portal** : `api.bnf.fr` renvoie 500 occasionnellement.
  Wrapper le client BnF avec retry + fallback explicite vers Google Books.
- **IGDB token valide 60 jours** : cache atomic write + auto-refresh à
  >55 jours. Ne pas spammer `oauth2/token` (4 req/s suffisent pour tout
  l'usage).
- **TVmaze épisodes `summary`/`image` souvent null** pour émissions FR.
  Fallback ffmpeg pour générer 3 screenshots systématiquement.
- **ISBN routage FR/JP/US** : `978-2` = FR, `978-1` = UK/US, `978-4` = JP.
  Routage des BD/Manga selon cette heuristique.
- **IGDB summary en EN** : pour plateforme = Windows/Mac/Linux,
  **toujours** cross-référencer Steam (`cc=fr&l=french`) pour résumé FR
  officiel Valve.
- **TheSportsDB clé `"123"`** : limite à 2 résultats par search. Si
  match ambigu, l'app doit afficher les 2 candidats et laisser l'user
  choisir.
- **YouTube quota 10k unités/jour** : 1 lookup playlist = ~102 unités →
  ~95 playlists/jour gratuit. Peut être un goulot pour gros uploaders
  formations.
- **VirusTotal opt-in** : strict respect "aucune donnée ne quitte la
  machine sans appel API explicite par l'user". Si pas configuré, ne
  JAMAIS uploader le hash silencieusement.
- **Goodreads API morte** depuis 2020. Ne pas chercher à l'utiliser.
- **ESPN API instable** (non-officielle). Ne pas l'utiliser malgré la
  bonne couverture.

---

## 9. Modules complexes (à manipuler avec précaution)

Par poids fichier (= proxy de la complexité) :

| Module | Taille | Pourquoi c'est lourd |
|---|---|---|
| `web/app.py` | 116 KB | Toutes les routes FastAPI + helpers HTTP + logique métier en cascade |
| `core/release_name.py` | 67 KB | Le cœur du naming, 13 étapes pipeline, 318 lignes pour `build_release_name` seul |
| `core/tmdb.py` | 65 KB | 4 stratégies de résolution × films/séries, cache atomique, multi-langue, garde-fous |
| `core/gemini_api.py` | 41 KB | Client HTTP + dedup cascade + parsing réponses Unit3D |
| `core/bbcode_renderer.py` | 39 KB | Rendu déterministe + 4 templates (movie/episode/season/integrale) |
| `core/upload_orchestrator.py` | 35 KB | Orchestration dedup → upload → save .torrent → state transitions |
| `core/compliance.py` | 31 KB | 22 checks vidéo avec 3 niveaux de sévérité |
| `pipeline.py` | 25 KB | Orchestrateur 1 fichier → 1 package, ~13 étapes |
| `web/jobs_runner.py` | 25 KB | Background worker, threading, subprocess, SSE streaming |

**Recommandations** :
- **Lire avant de toucher** — ne pas modifier en aveugle.
- **Tests d'abord** : si tu casses un test `test_release_name_real_cases.py`,
  tu as cassé un cas réel de Louis → arrête, reviens en arrière, comprends.
- **Refactor planifié** : `release_name.py` à découper en sous-modules
  (`naming/normalize`, `naming/classify`, `naming/language`, `naming/build`)
  dans Sprint B v0.5.0 (cf. `PLAN-MULTICAT.md` §5.5).

---

## 10. Dette technique connue (non bloquante)

- **`release_name.py` 1200+ lignes monolithique** — à découper Sprint B v0.5.0
- **`package_detail.html` 2700 lignes monolithique** — à découper par profil
  catégorie Sprint C v0.5.0
- **Pas de tests d'intégration E2E** (vrai fichier mkv → vrai upload dry-run).
  À ajouter quand pertinent.
- **Coverage à 39% baseline** — config en place, pas d'objectif strict.
  Modules sous-testés : `tmdb` 11%, `pipeline` 7%, `omdb` 9%, `mediainfo_parser` 11%.
- **`hash()` non-déterministe pour noms de log (résolu v0.3.x)** : utiliser
  `hashlib.md5(key)[:12]` pour stabilité cross-process.
- **Multiples `except Exception:` silencieux** : partiellement résolus
  (`tmdb._maybe_fetch_title_en`, `tmdb._cache_*`). Reste ~6 sites web/app.py,
  jobs_runner — low priority car erreurs déjà loguées en `[WARN]`.

---

## 11. Pas de `TODO` / `FIXME` / `HACK` taggés dans le code

`grep -rE "TODO|FIXME|HACK|XXX" src/` → **0 occurrence**. Discipline
forte historique. Si tu en ajoutes :
- Préfère un commentaire explicite avec contexte qu'un `TODO` cryptique.
- Si vraiment besoin : `# TODO(scope): explication détaillée — référence #issue`.

---

*Dernière mise à jour : 2026-05-22. À mettre à jour à chaque nouveau piège
identifié.*
