# Workflow opérationnel — Flox Uploader

> Toutes les commandes essentielles + conventions pour contribuer au projet.
> Consolide `README.md` (install), `CONTRIBUTING.md` (PR), `CLAUDE.md` §16
> (git), `.github/workflows/*.yml` (CI).

---

## 1. Install dev (mode editable)

### Pré-requis
- **Python ≥ 3.10** (testé en CI sur 3.10, 3.11, 3.12 ; en local sur 3.12)
- **MediaInfo CLI** installé dans le `PATH` (en dev — l'installeur Windows
  l'embarque sinon). [Download MediaInfo](https://mediaarea.net/en/MediaInfo/Download).
- **`gh` CLI** authentifié (`gh auth status` pour vérifier) — utilisé pour
  créer les PRs sans passer par l'UI GitHub.

### Étapes
```cmd
git clone https://github.com/FloxTool/flox-uploader.git
cd flox-uploader

python -m venv .venv
.venv\Scripts\activate            REM Windows
REM source .venv/bin/activate     # Linux / macOS

pip install -e ".[web,dev]"

copy .env.example .env            REM Windows
REM cp .env.example .env          # Linux / macOS
REM Édite .env et remplis :
REM  TRACKER_ANNOUNCE, TMDB_API_KEY, OMDB_API_KEY,
REM  TRACKER_API_URL, TRACKER_API_KEY
```

La commande `flox-uploader` est ensuite disponible dans le venv.

---

## 2. Lancer le serveur dev

```cmd
flox-uploader serve                       REM port par défaut 8765
flox-uploader serve --port 8000           REM port custom
flox-uploader serve --host 0.0.0.0        REM exposition réseau (cf. §SECURITY)
flox-uploader serve --no-browser          REM ne pas ouvrir le navigateur auto
```

**Auto-fallback de port** : si 8765 est occupé, l'app essaie 8766, 8767...
jusqu'à trouver un port libre.

**Hot reload des templates** : Jinja recharge les templates à chaque requête
en mode dev — pas besoin de redémarrer le serveur après une modif de
`.html`. Le code Python en revanche nécessite un restart.

### Tester rapidement une page
```cmd
curl -s http://127.0.0.1:8765/api/diagnostic
curl -s -o nul -w "HTTP %%{http_code}" http://127.0.0.1:8765/queue
```

---

## 3. Lancer les tests

```cmd
pytest                                            REM toute la suite
pytest tests/test_release_name_real_cases.py     REM un fichier
pytest -k "force_fr"                              REM filtre par nom
pytest -v                                         REM verbose
pytest --tb=short -q                              REM concis
```

**Variable d'env utile** : `FLOX_DISABLE_UPDATE_CHECK=1` pour désactiver
le check GitHub en local (évite les flakes liés au réseau / rate limit) :
```cmd
set FLOX_DISABLE_UPDATE_CHECK=1
pytest -q
```

**État actuel attendu** : **772/772 verts** (mai 2026). Toute régression
bloque le merge.

---

## 4. Workflow git — PR → squash → tag

### Règle absolue
**Le push direct sur `main` est bloqué par le classifier Claude Code.**
Toute modification passe par une **PR** + squash-merge.

### Cycle standard

```cmd
cd "C:\Users\Louis\Documents\Claude\Projects\Tracker Uploder"

REM 1. Toujours partir de main à jour
git checkout main
git pull --ff-only origin main

REM 2. Créer une branche dédiée
git checkout -b feature-<sujet>     REM ou fix-<sujet>, note-<sujet>, etc.

REM 3. Coder + tester
pytest -q

REM 4. Commit (style standard - cf. §5)
git add <fichiers ciblés, pas "git add .">
git commit -m "Sujet" ^
           -m "Body para 1" ^
           -m "Body para 2" ^
           -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

REM 5. Push branche + créer la PR
git push -u origin feature-<sujet>
gh pr create --title "..." --body "..."

REM 6. Merger (squash + delete branch)
gh pr merge <pr-num> --squash --delete-branch

REM 7. Sync main local
git checkout main
git pull --ff-only origin main
```

### Cas spécifique : release publique

```cmd
REM 1. Bumper la version dans pyproject.toml ET src/flox_uploader/__init__.py
REM 2. Mettre à jour CHANGELOG.md (section X.Y.Z avec date)
REM 3. PR comme d'habitude, merger
REM 4. Tagger le commit de merge
git checkout main && git pull
git tag -a vX.Y.Z -m "vX.Y.Z : description courte"
git push origin vX.Y.Z

REM Le workflow build-windows.yml déclenche auto :
REM  - PyInstaller build
REM  - Inno Setup compile FloxUploader-Setup-X.Y.Z.exe
REM  - Draft GitHub Release créée avec ZIP + setup.exe attachés
REM Puis : aller sur GitHub Releases, vérifier, publier la draft.
```

⚠ **GitHub Actions actuellement désactivé** (cf.
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) §1) → les builds CI ne tournent pas.
Workaround temporaire : build local du `.exe` portable, pas d'installeur
officiel jusqu'à réactivation.

---

## 5. Format de commits

### Patterns observés (style libre mais cohérent)

| Type | Exemple |
|---|---|
| Release | `v0.3.17 : fix faux positif compliance audio E-AC3.5.1` |
| Sprint majeur | `Sprint 8 PLAN-V1 : crash report helper` |
| Hotfix urgent | `Hotfix v0.3.9 : subprocess prepare casse en bundle PyInstaller` |
| Fix ponctuel | `fix(launcher): patch sys.stdout/stderr None en windowed mode` |
| Chore/CI | `ci(build-windows): permissions contents:write pour creer GitHub Release` |
| Note UX | `Note UX: inverser le comportement des filtres de la page queue` |
| Doc | `Planning v0.5.0 : multi-categorie + sources Gemini officielles` |
| Refonte UI | `Queue : inverser les filtres (cocher = isoler)` |

### Règles
- **Sujet 50-72 chars**, verbe au présent ou nominal, en français (parfois
  anglais accepté).
- **Body multi-lignes** via `-m` répétés (ou éditeur si pas en ligne) — sert
  à documenter le **pourquoi** et les conséquences, pas à répéter le quoi.
- **Pas de Conventional Commits strict** (`feat:`, `fix:`, `chore:` sont
  optionnels et utilisés ponctuellement, pas systématiquement).
- **Co-Authored-By** : pour les commits où Claude a contribué
  significativement, ajouter en dernier `-m` :
  ```
  -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```
  Convention introduite en mai 2026, à propager.
- **Pas de heredoc bash** (`<< EOF`) — Louis est sur CMD Windows. Toujours
  utiliser des `-m` répétés.

### Format PR
- **Titre** = sujet du commit principal
- **Body** = contexte + changements + tests + checklist + screenshots si UI
- Suffixé en bas : `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
  pour les PRs créées en grande partie par Claude.

---

## 6. Conventions Claude Code (pour les sessions IA)

### Avant de coder une tâche non-triviale
1. **Lis** `CLAUDE.md`, le `PLAN-*.md` actif (V1 pour v0.4.x, MULTICAT pour
   v0.5+), `KNOWN_ISSUES.md` pour la zone touchée.
2. **Propose un plan** à Louis avant d'écrire du code. Pas de "ça devrait
   marcher" — explique ce que tu vas faire et pourquoi.
3. **Vérifie l'état git** (`git status -sb`, `git log --oneline -5`,
   `gh pr list`) pour ne pas commencer sur une base désynchro.
4. **Lance `pytest -q`** comme baseline avant de toucher quoi que ce soit
   (= confirmer que tout est vert AVANT tes modifs).

### Pendant le code
- **Comments en français** dans le code (convention établie — Louis lit
  le code en français).
- **Docstrings en français** sur les fonctions publiques.
- **Type hints obligatoires** sur fonctions publiques (CONTRIBUTING.md).
- **Pas de `print()` de debug pour la prod** — utiliser `debug.set()`
  qui va dans `debug.json` (traçable).
- **Atomic file writes** : tout write critique passe par `tmp_file.write_text()`
  + `os.replace(tmp, target)`. Convention établie pour `package_state.json`,
  `.tmdb_cache.json`, `.env`, `debug.json`.
- **Pas de `print()` user-final** sur stderr en mode windowed PyInstaller
  → invisible. Utiliser dialog tkinter ou logguer + écrire dans un fichier
  accessible via la page Logs.
- **Atomic edits dans la doc** : pour CLAUDE.md, PLAN-*.md, etc., utiliser
  `Edit` (chirurgical), pas `Write` (réécriture complète).

### Sous-agents
- **Recommandés** pour les recherches parallèles ou les explorations
  larges (ex: scanner plusieurs modules en parallèle, recherche web sur
  N sujets).
- **Spawn via le tool `Agent`** avec `subagent_type` adapté (`Explore`
  pour recherche fan-out read-only, `general-purpose` pour tout le reste).
- **Mode batch** : lancer plusieurs agents dans le même message pour
  paralléliser (1 round-trip au lieu de N).

### Mise à jour de la doc
- **Tu touches au code ?** Pense à mettre à jour `NOTES.md` (notes brutes)
  si pertinent, et `CHANGELOG.md` section `[Unreleased]` pour les
  changements significatifs.
- **Tu touches à une décision figée ?** Amende d'abord le `PLAN-*.md`
  correspondant (D1-D18 ou D-MC1-15), puis modifie le code.
- **Tu découvres un nouveau piège ?** Ajoute-le dans
  [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).

### Commits Claude
- **Co-Authored-By** systématique sur les commits où Claude a écrit du code.
- **PR workflow** systématique (pas de push direct main).
- **Plusieurs commits atomiques** plutôt qu'un gros — un par "étape logique".

---

## 7. Comment ajouter une note dans NOTES.md

Le fichier `NOTES.md` a 5 sections pré-définies :
- `# Bug : ça plante / résultat faux / régression`
- `# Release name : un cas où le nom généré n'est pas conforme à la charte Gemini`
- `# UX/UI : truc moche, pas évident, manque, friction`
- `# Feature : envie de quelque chose qui n'existe pas`
- `# Question : pas sûr du comportement attendu`

**Format** : 1 bullet par note, en texte libre (Louis écrit à la volée,
Claude lit et reformule en code/PR). Cf. l'en-tête de `NOTES.md` pour le
contrat d'interprétation.

**Workflow** : Louis ajoute des notes → Claude les lit dans la session
suivante → propose un plan d'action ou un PR → après merge, retirer la
note ou la marquer "✓ fait dans PR #N".

---

## 8. Sécurité opérationnelle

- **Jamais commit** : `data/`, `.env`, `jobs.db`, `.tmdb_cache.json`,
  `__pycache__/`, `.claude/`, `gemini/_extracted/` (cf. `.gitignore`).
- **PDFs Gemini** dans `gemini/` SONT commités (exception explicite
  `!gemini/*.pdf`).
- **Si une clé fuit** dans un commit : rotate immédiatement (nouvelle
  passkey tracker, nouvelle clé TMDB/OMDb), puis `git filter-repo` pour
  scrub l'historique (lourd).
- **Logs partagés en bug report** : le `ScrubbingWriter` masque
  automatiquement les clés API connues. Mais double-check toujours avant
  de partager.

---

## 9. Performance / cache

- **Cache TMDB** : `data/.tmdb_cache.json` (atomic write). Key =
  `{title.lower()}|{year}`. **Pas d'isolation films/séries actuellement**
  (TODO backlog).
- **Cache confidence score** : `_score_cache` en mémoire avec mtime
  composite (`debug.json` + `state.json`) comme clé de validité.
  `invalidate_score_cache(pkg)` exposé.
- **Cache update GitHub** : `data/.update_cache.json`, TTL 6h sur succès,
  conservé indéfiniment sur échec.
- **`_list_packages` dédup** : 1 lecture `debug.json` par package (pas 2).

---

## 10. Publier une nouvelle release (v0.4.x, v0.5.x...)

### Checklist
1. Tous les sprints prévus livrés (cf. `PLAN-V1.md` ou `PLAN-MULTICAT.md`
   selon la version)
2. Tests verts en local + CI (quand Actions réactivé)
3. `CHANGELOG.md` à jour avec section `[X.Y.Z] — YYYY-MM-DD`
4. `pyproject.toml` version bumpée
5. `src/flox_uploader/__init__.py::__version__` bumpée
6. PR de release créée, mergée
7. Tag `vX.Y.Z` poussé → CI build-windows.yml déclenche auto
8. Draft GitHub Release créée → vérifier le contenu, publier
9. Annonce optionnelle (forum Gemini, etc.)

### Que se passe-t-il quand on tag ?
Le workflow `.github/workflows/build-windows.yml` est triggered par
`push tags v*` :
1. Setup Python 3.12 + install dépendances
2. Download MediaInfo CLI Windows (vendoring via
   `packaging/fetch_mediainfo_windows.py`)
3. Run pytest (sanity check)
4. PyInstaller build (`packaging/flox_uploader.spec`)
5. 3 smoke tests (`--help`, boot uvicorn avec stdout, mode windowed double-clic)
6. Zip portable (`FloxUploader-X.Y.Z-Windows-x64.zip`)
7. Inno Setup compile (`FloxUploader-Setup-X.Y.Z.exe`)
8. Upload artifacts + attach à la GitHub Release (draft)

Sur push main (pas tag) : `tests.yml` tourne juste (matrix Python 3.10-3.12).

---

## 11. Que faire si quelque chose foire

| Symptôme | Solution |
|---|---|
| Tests rouges après une modif | Lire le test qui casse, comprendre, **NE PAS** modifier le test sans avoir confirmé que le comportement attendu a changé |
| `pytest` lent ou flake | `FLOX_DISABLE_UPDATE_CHECK=1 pytest -q` |
| `git push` refusé par classifier | Tu pousses sur `main` directement ? → créer une branche + PR |
| `gh pr create` 404 / auth | `gh auth login` |
| Serveur dev plante au boot | Lire le traceback (`pytest tests/test_web_app.py` pour iso le problème) |
| `MediaInfo` introuvable | Installer depuis https://mediaarea.net/MediaInfo/Download (Windows : ajouter au PATH ou utiliser l'installeur Flox bundlé) |
| GitHub Actions échoue avec 422 | Cf. [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) §1 — Actions désactivé, attendre réintégration Support |
| Quelque chose de non couvert ici | Voir [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) |

---

*Maintenu manuellement. Si tu introduis une nouvelle commande ou
convention, pense à l'ajouter ici.*
