# Changelog

Toutes les modifications notables sont listées ici.

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
versionning [Semantic Versioning](https://semver.org/lang/fr/).

---

## [Unreleased]

_Rien pour l'instant — Sprint 2 démarre prochainement._

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
