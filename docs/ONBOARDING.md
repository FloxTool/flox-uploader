# Onboarding 5 min — Session Claude Code sur Flox Uploader

> Tu es Claude, c'est ta première session sur ce projet. Lis ce fichier
> en 5 min, suis l'ordre de lecture, puis tu sauras où aller pour tout
> le reste.

---

## 1. Le projet en 3 lignes

**Flox Uploader** est un outil Python qui prépare et upload des releases
torrents vers le tracker privé francophone **Gemini** (fork Unit3D). À
partir d'un fichier vidéo, il génère : nom de release scene-compliant,
`.torrent`, NFO MediaInfo, fiche BBCode déterministe (TMDB + OMDb +
MediaInfo, **aucun appel LLM**), upload avec dédup préalable. UI web
locale (FastAPI + Jinja + Tailwind) en français.

**Public cible** : uploadeurs amateurs francophones Gemini. **Cible
produit** : web UI packagée user-friendly (Windows .exe livré, Docker
à venir).

**Statut** : voir [`STATUS.md`](STATUS.md) (source unique, bloc chiffré
régénéré). En bref au 2026-11-15 : v0.5.0 publiée (vidéo + livres), suivie
de builds locaux de correctifs non tagués. La v0.4.0 n'a jamais été taguée
(son contenu est dans la v0.5.0). GitHub Actions, désactivé à partir du
2026-05-20, est de nouveau opérationnel (cf.
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) §1). Restent à venir : jeux, sport,
émission TV, logiciels, formations.

---

## 2. Ordre de lecture obligatoire (10 min total)

| # | Fichier | Pourquoi | Temps |
|---|---|---|---|
| 1 | [`../CLAUDE.md`](../CLAUDE.md) | Index principal du projet : TL;DR, architecture, conventions, pièges, roadmap | 4 min (lecture sélective via Index navigation en tête) |
| 2 | [`../PLAN-V1.md`](../PLAN-V1.md) OU [`../PLAN-MULTICAT.md`](../PLAN-MULTICAT.md) | Plan stratégique actif. **V1 si tu travailles sur v0.4.x.** **MULTICAT si tu attaques v0.5.0+.** | 3 min |
| 3 | [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Pièges à éviter avant de toucher du code | 2 min |
| 4 | [`WORKFLOW.md`](WORKFLOW.md) | Commandes (install, test, PR, release) | 1 min |

**Si tu touches au naming** : ajoute [`GLOSSARY.md`](GLOSSARY.md) §1-§2
+ `src/flox_uploader/core/release_name.py`.

**Si tu touches à un PDF Gemini** : tu ne touches PAS à un PDF Gemini.
Ils sont **sources de vérité**, en lecture seule.

---

## 3. Les 5 trucs à savoir immédiatement (zones intouchables et règles dures)

### ⛔ 1. Aucun appel LLM dans le pipeline
**Décision figée.** La fiche BBCode est générée 100% déterministiquement
à partir de TMDB + OMDb + MediaInfo + un template. **Jamais d'appel
OpenAI/Claude/Gemini API/etc.** dans le code applicatif. Raison :
reproductibilité, pas de coût, pas de fuite données vers des tiers.
Cohérent avec la philosophie *local-first + no telemetry*.

### ⛔ 2. Pas de push direct sur `main` — workflow PR obligatoire
Le classifier Claude Code **bloque** `git push origin main` direct. Tout
passe par : branche dédiée → commit → push branche → `gh pr create` →
`gh pr merge --squash --delete-branch`. Cf.
[`WORKFLOW.md`](WORKFLOW.md) §4.

### ⛔ 3. Les 7 PDFs `gemini/*.pdf` sont sources de vérité
TORRENT API (IDs catégories/types/résolutions), RÈGLES DE NOMMAGE,
RÈGLES D'UPLOAD (général + ebook), Règle d'encodage, TEAMS INTERDITES,
glossaire sources vidéo. **Ne JAMAIS les modifier.** Si une décision
contredit un PDF Gemini, **on relit le PDF avant de coder**.

### ⛔ 4. `team.upper()` est interdit
La casse signature de la team release doit être préservée (`Punisher694`
≠ `PUNISHER694`, `mHDgz`, `Frosties`...). `_CANONICAL_CASE` ne
s'applique qu'aux tokens scene (BluRay, x265, ...), **jamais à la team**.
Cf. [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) §3.

### ⛔ 5. Tests gold standard `tests/test_release_name_real_cases.py`
21 cas réels remontés par Louis (catégories A à I). Si l'un casse, tu
as cassé un cas concret. **Reviens en arrière, comprends, corrige**.
N'amende jamais ces tests sans qu'il y ait une raison documentée
(décision écrite dans un PLAN-*.md).

---

## 4. Comment je sais où on en est (commandes à lancer en début de session)

```cmd
cd "C:\Users\Louis\Documents\Claude\Projects\Tracker Uploder"

REM État git
git log --oneline -5
git branch --show-current
git status -sb

REM PRs ouvertes / récentes
gh pr list --state all --limit 5

REM Tests verts ? (devrait afficher 772 passed)
set FLOX_DISABLE_UPDATE_CHECK=1
.venv\Scripts\python -m pytest -q

REM Version actuelle
type pyproject.toml | findstr "^version"
```

---

## 5. Avant de coder une tâche non-triviale

1. Lecture des 4 fichiers ci-dessus (§2). Si tu touches à une zone
   spécifique, ajoute le fichier code concerné.
2. **Propose un plan à Louis avant d'écrire du code.** Pas de
   "je crois que ça devrait marcher" — explique ce que tu vas faire
   et pourquoi.
3. **Vérifie l'état git** (cf. §4) pour ne pas démarrer sur une base
   désynchro.
4. **Lance `pytest -q`** comme baseline pour confirmer que tout est
   vert AVANT tes modifs.
5. Si tu vois un piège connu (cf. `KNOWN_ISSUES.md`) dans ta zone :
   tag-le explicitement dans ton plan.

---

## 6. Test cold-start (= ce fichier valide-t-il ?)

Si tu reçois cette demande dans une session vierge :

> *« Lis la documentation du projet Flox Uploader et résume-moi en
> 10 lignes : (1) ce qu'on construit et pour qui, (2) l'état
> d'avancement actuel et le prochain jalon, (3) les 5 trucs que je
> dois absolument éviter de te demander ou de faire. »*

Tu devrais pouvoir répondre **uniquement** en ayant lu ce fichier
(ONBOARDING) + CLAUDE.md + PLAN actif. Si tu hésites sur un point :
- Sur le « ce qu'on construit » → CLAUDE.md TL;DR
- Sur l'« état actuel » → CLAUDE.md TL;DR + `git log --oneline -5`
- Sur les « 5 trucs à éviter » → ce fichier §3

Si la doc ne te permet pas de répondre, **dis-le à Louis** plutôt que
d'inventer — il viendra compléter la doc manquante.

---

## 7. Conventions express

- **Comments / docstrings** : en français.
- **Commits** : sujet 50-72 chars, body multi-`-m`, `Co-Authored-By:
  Claude Opus 4.7 (1M context) <noreply@anthropic.com>` en dernière
  ligne quand Claude contribue significativement.
- **PR squash + delete branch** : standard. Cf.
  [`WORKFLOW.md`](WORKFLOW.md) §4.
- **Atomic file writes** partout pour les fichiers critiques (state,
  cache, .env, debug.json). `tmp_file.write_text()` + `os.replace()`.
- **Human-in-the-loop** : si ambiguïté (variante FR, TMDB pas trouvé,
  doublon douteux), **signale + score baissé**, **jamais** d'invention
  silencieuse.

---

## 8. Où aller pour la suite

- **Liste des décisions figées** : `PLAN-V1.md` §0 (D1-D18) et
  `PLAN-MULTICAT.md` §2 (D-MC1-15).
- **Architecture détaillée** : `CLAUDE.md` §3 et `PLAN-MULTICAT.md` §5.
- **Vocabulaire métier** : [`GLOSSARY.md`](GLOSSARY.md).
- **Commandes opérationnelles** : [`WORKFLOW.md`](WORKFLOW.md).
- **Pièges et limitations** : [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md).
- **Sources de vérité Gemini** : `gemini/*.pdf`.
- **Historique versions** : `CHANGELOG.md`.
- **Notes Louis à la volée** : `NOTES.md`.
- **Design system UI** : `CHARTE.md`.

---

*Maintenu manuellement. Mis à jour quand le contexte projet évolue
significativement.*
