# PLAN-MULTICAT.md — Extension multi-catégorie (v0.5.0+)

> **Document de référence canonique** pour l'évolution de Flox Uploader, de
> *« uploader vidéo Gemini »* vers *« uploader tous-types Gemini avec
> dégradation gracieuse »*. À lire **après** `CLAUDE.md` (TL;DR projet) et
> **après** `PLAN-V1.md` (plan v0.4.0, en cours de release).
>
> **Toute décision ici fait autorité** — si une question revient, on relit ce
> doc. Si on change une décision, on l'amende **ici avant** de toucher au code.
>
> Version cible : `v0.5.0` (release publique multi-catégorie).
> Versions intermédiaires : `v0.4.x` (patches v0.4.0), `v0.5.0-betaN` pour les
> sprints sans rupture utilisateur.

---

## 0. TL;DR — 60 secondes de lecture

**Objectif** : permettre à Flox d'uploader **n'importe quelle catégorie
Gemini** (Films, Séries, Anime, Doc, **Émission TV**, **Sports**, **Livres**,
**Jeux**, **Logiciels**, **Formations**) — pas seulement la vidéo.

**Principe directeur** : *dégradation gracieuse* en 4 barreaux. Le pipeline ne
refuse jamais un type de contenu, il s'adapte au niveau d'automatisation
possible.

```
Barreau 1 — TOUT AUTO     → vidéo avec TMDB (films, séries, anime, doc)
Barreau 2 — SEMI-AUTO     → vidéo sans TMDB fiable (sport, émission TV)
Barreau 3 — ASSISTÉ       → livre/jeu : provider dédié (BnF, IGDB)
Barreau 4 — MANUEL GUIDÉ  → soft/formation : formulaire propre, l'user remplit
```

**Décisions structurantes** :
- v0.4.0 reste **vidéo-only** (release publique en cours, bloquée par
  réintégration GitHub Actions).
- v0.5.0 ajoute le multi-catégorie via **Strategy pattern** par catégorie.
- **Aucune API ne devient bloquante** : si la clé manque, on tombe au barreau
  suivant. Cohérent avec la philosophie *local-first + no telemetry*.
- **Sélecteur de catégorie sur Inbox** (visuel, couleurs/emojis) — l'user
  pré-set l'intention au moment d'ajouter à la queue.
- **L'app reste flexible** : la catégorie peut être ré-overridée sur la page
  détail (re-prepare avec autre catégorie si erreur).

**Stack APIs recommandées** (synthèse des 5 recherches agents) :
- Ebooks : **BnF SRU + Google Books + OpenLibrary** ; BD = +**ComicVine** ;
  Manga = +**AniList GraphQL**.
- Jeux : **IGDB** (Twitch OAuth, gratuit) + **Steam Store** (PC FR natif).
- Émissions TV : **TVmaze** (no key) + **TMDB** (déjà branché) + **Wikidata**
  pour présentateurs.
- Sports : **TheSportsDB** (clé `123` test) + **base statique JSON** logos
  des ~70 ligues déjà keywordées.
- Formations : **manuel** + auto-enrich si URL YouTube playlist.
- Logiciels : **manuel** + auto-enrich si URL GitHub repo + **VirusTotal**
  opt-in.

**Effort estimé total** : **~6 à 8 semaines homme** pour livrer **toutes** les
catégories proprement (vs 2 semaines si on se limitait à ebook+jeu).

---

## 1. Statut courant (2026-05-22) — point de départ

| Quoi | État |
|---|---|
| Version code | `0.3.17` (vidéo-only) |
| Tests | **772 passants** (`pytest`, exécutés en local le 2026-05-22) |
| Release publique | **v0.4.0** en attente (build CI bloqué : Actions désactivées sur le compte `fremontlouis`, ticket réintégration envoyé GitHub Support) |
| PRs en cours | `#17` (note UX filtres queue) |
| Branche en cours | `v0.5.0-planning` (cette doc) |
| Build local | `.exe` v0.3.17 compilé localement, smoke-testé OK |
| Catégories vraiment supportées | Films, Séries, Anime, Doc (auto-detect via genres TMDB) |
| Catégories partiellement supportées | Sports (keywords détectés, fiche pauvre) ; Émission TV (override-only) |
| Catégories non supportées | **Livres, Jeux, Logiciels, Formations** (catégorie sélectionnable mais aucun workflow) |

**Le présent plan suppose que v0.4.0 sera taguée et publiée dès que GitHub
réactive Actions** — c'est le préalable. Les sprints v0.5.0 commencent une
fois v0.4.0 publique.

---

## 2. Décisions stratégiques figées (D-MC = Multi-Cat)

| # | Décision | Choix |
|---|---|---|
| **D-MC1** | **Périmètre v0.5.0** | Les **12 catégories Gemini** doivent fonctionner : Films(1), Séries(2), Jeux(3), Séries Anime(6), Films Anime(7), Sports(10), Livres(12), Films Doc(13), Séries Doc(14), Émission TV(15), Logiciels(17), Formations(18). |
| **D-MC2** | **Principe directeur** | Dégradation gracieuse 4 barreaux. **Jamais de mur.** Toute catégorie est uploadable, fût-ce avec un formulaire 100% manuel. |
| **D-MC3** | **Modèle de données code** | **Strategy pattern** par catégorie (`NamingStrategy`, `MetadataProvider`, `ConfidenceStrategy`, template BBCode). Ajouter une catégorie = écrire une strategy, ne pas toucher au core. |
| **D-MC4** | **APIs externes** | Toutes **optionnelles**. Pas de clé = fallback au barreau suivant. Les clés se configurent dans `/setup` (visuel par univers). Aucune télémétrie. |
| **D-MC5** | **Sélecteur catégorie sur Inbox** | OUI, sur la page Inbox au moment de l'ajout à la queue. Visuel : couleurs + emojis par catégorie. Films/Séries pré-cochés par défaut (majoritaires). Confirmation requise si une sélection mélange plusieurs catégories incompatibles. |
| **D-MC6** | **Override catégorie sur page détail** | OUI. Si user s'est trompé (ex: package préparé en "Livre" mais c'est un film), bouton **"Repréparer avec autre catégorie"** qui relance le pipeline avec une nouvelle strategy. |
| **D-MC7** | **Pages détail différentes** | OUI, par profil (`_detail_video.html`, `_detail_book.html`, `_detail_game.html`, `_detail_show.html`, `_detail_sport.html`, `_detail_manual.html`). Templates Jinja inclus dynamiquement selon `category_id`. |
| **D-MC8** | **Templates BBCode par catégorie** | OUI. `template_book.bbcode`, `template_game.bbcode`, `template_show.bbcode`, `template_sport.bbcode`. Fallback `template_manual.bbcode` pour Logiciels/Formations. |
| **D-MC9** | **MediaInfo** | Devient **conditionnel** à la catégorie (cf. `MEDIAINFO_REQUIRED_CATEGORIES` déjà déclaré dans `unit3d_mapping.py`). Skip silencieux pour ebook/jeu/soft/formation. |
| **D-MC10** | **Score de confiance** | Recalibré **par profil**. Score 0-100 reste, mais critères changent (un ebook ne se voit pas pénaliser pour "résolution manquante"). |
| **D-MC11** | **Compliance** | **Liste de checks par catégorie**. Le check "container=MKV obligatoire" ne s'applique qu'aux vidéos. Nouveaux checks ebook/jeu/soft à ajouter. |
| **D-MC12** | **Naming** | Charte Gemini officielle respectée par catégorie : `Auteur.Titre.Date.Langue.Format-TEAM` (ebook), `Titre.Version.Plateforme.Edition.Langue-TEAM` (jeu), etc. Si un user impose un nom manuel, on respecte (toujours possible aujourd'hui via `manual_release_name`). |
| **D-MC13** | **Garde-fou mélange queue** | Si l'user sélectionne plusieurs fichiers de catégories différentes (ex: un .mkv et un .epub), modal de confirmation : "Vous mélangez Vidéo + Livre. Créer 2 packages séparés ?" (default), ou "Les forcer dans la même catégorie ?" (opt-in conscient). |
| **D-MC14** | **Compat v0.4.0** | Toutes les modifs sont **additives**. Aucun pipeline vidéo existant n'est cassé. Les 772 tests vidéo doivent rester verts à 100% à chaque commit. |
| **D-MC15** | **Sources de vérité** | Les 7 PDFs Gemini officiels sont commités dans `gemini/` et **font autorité** sur tout désaccord. En cas d'ambiguïté, on relit le PDF avant de coder. |

---

## 3. Vision : la dégradation gracieuse

### 3.1 Les 4 barreaux

```
┌─────────────────────────────────────────────────────────────────┐
│  Barreau 1 — TOUT AUTO                                          │
│  Vidéo avec TMDB match fiable                                   │
│  Films / Séries / Anime / Doc                                   │
│  → Score 95-100, l'user clique "Upload" et c'est fini           │
└─────────────────────────────────────────────────────────────────┘
                            ↓ TMDB ne match pas / pas pertinent
┌─────────────────────────────────────────────────────────────────┐
│  Barreau 2 — SEMI-AUTO                                          │
│  Vidéo + provider spécialisé qui partage souvent les fields     │
│  Émission TV (TVmaze + TMDB partiel), Sports (TheSportsDB)      │
│  → Score 80-94, l'user vérifie / complète quelques champs       │
└─────────────────────────────────────────────────────────────────┘
                            ↓ Univers non-vidéo
┌─────────────────────────────────────────────────────────────────┐
│  Barreau 3 — ASSISTÉ                                            │
│  Provider dédié, pipeline naming spécifique                     │
│  Livres (BnF + Google Books), Jeux (IGDB + Steam)               │
│  → Score 60-89 selon richesse des champs récupérés              │
└─────────────────────────────────────────────────────────────────┘
                            ↓ Pas de provider / contenu obscur
┌─────────────────────────────────────────────────────────────────┐
│  Barreau 4 — MANUEL GUIDÉ                                       │
│  Formulaire propre, l'user remplit                              │
│  Logiciels, Formations, cas exotiques de toutes catégories      │
│  → Score 60-79 (review), l'user valide visuellement             │
└─────────────────────────────────────────────────────────────────┘
```

**Règle d'or** : *toujours monter le plus haut possible sur l'échelle, mais
**jamais bloquer*** parce qu'on ne peut pas monter. Le barreau 4 est le filet :
il garantit que **toute** catégorie est uploadable, même Photoshop CS6 ou un
tuto YouTube zippé.

### 3.2 Mapping catégorie → barreau (par défaut)

| Catégorie Gemini | ID | Barreau natif | Provider dédié |
|---|---|---|---|
| Films | 1 | 1 (TOUT AUTO) | TMDB + OMDb (déjà fait) |
| Séries | 2 | 1 | TMDB + OMDb (déjà fait) |
| Films Documentaires | 13 | 1 | TMDB (genre Documentary) |
| Séries Documentaires | 14 | 1 | TMDB (genre Documentary) |
| Films Animations | 7 | 1 | TMDB (genre Animation) |
| Séries Animations | 6 | 1 | TMDB (genre Animation) |
| Émission TV | 15 | 2 (SEMI-AUTO) | TVmaze + TMDB + Wikidata |
| Sports | 10 | 2 | TheSportsDB + base statique logos |
| Livres | 12 | 3 (ASSISTÉ) | BnF + Google Books + ComicVine + AniList |
| Jeux | 3 | 3 | IGDB + Steam Store + RAWG (fallback) |
| Logiciels | 17 | 4 (MANUEL GUIDÉ) | Auto-enrich si URL GitHub, sinon manuel |
| Formations | 18 | 4 | Auto-enrich si URL YouTube playlist, sinon manuel |

**Note** : un livre peut tomber au barreau 4 si BnF + Google Books ratent
tous les deux (livre auto-publié inconnu, p.ex.). Idem un jeu obscur PS1
japonais. La dégradation est **dynamique** par package, pas figée par
catégorie.

---

## 4. Statut par catégorie — la matrice

| Catégorie | Naming Gemini officiel | Méta source | BBCode template | Compliance | Status actuel | Effort manquant |
|---|---|---|---|---|---|---|
| Films (1) | `Titre.Année.Langue.Res.Source.Audio.Codec-TEAM` ✅ | TMDB+OMDb ✅ | `template_movie.bbcode` ✅ | 22 checks vidéo ✅ | **✅ Complet** | — |
| Séries (2) | Même + `SxxEyy`/`Sxx.COMPLETE`/`iNTEGRALE` ✅ | TMDB+OMDb ✅ | `template_episode/season/integrale` ✅ | ✅ | **✅ Complet** | — |
| Films Doc (13) | = Films + détecté via genre TMDB ✅ | TMDB ✅ | `template_movie` ✅ | ✅ | **✅ Complet** | — |
| Séries Doc (14) | = Séries ✅ | TMDB ✅ | ✅ | ✅ | **✅ Complet** | — |
| Films Anime (7) | = Films ✅ | TMDB ✅ | ✅ | ✅ | **✅ Complet** | — |
| Séries Anime (6) | = Séries ✅ | TMDB ✅ | ✅ | ✅ | **✅ Complet** | — |
| Émission TV (15) | = Séries (charte vidéo) | TMDB partiel | `template_episode` (réutilisé) | ✅ vidéo | 🟡 Override-only, fiche pauvre | TVmaze provider + `template_show.bbcode` + ScreenshotFFmpeg |
| Sports (10) | = Films (charte vidéo) | Aucune | `template_movie` (réutilisé) | ✅ vidéo | 🟡 Auto via 70 keywords, fiche pauvre | TheSportsDB + base statique logos + `template_sport.bbcode` |
| Livres (12) | `Auteur.Titre.Date.Langue.Format-TEAM` | **Aucune** | **Aucun** | ❌ vidéo only | ❌ Non supporté | `BookNamingStrategy` + `BookProvider` + `BookConfidence` + `template_book.bbcode` + checks ebook |
| Jeux (3) | `Titre.Version.Plateforme.Edition.Langue-TEAM` | **Aucune** | **Aucun** | ❌ | ❌ Non supporté | `GameNamingStrategy` + `GameProvider` (IGDB+Steam) + `template_game.bbcode` + checks jeu |
| Logiciels (17) | Charte libre (pas de pattern officiel) | **Aucune** | **Aucun** | ❌ | ❌ Non supporté | Manuel guidé + auto-enrich GitHub URL + VirusTotal opt-in + `template_software.bbcode` |
| Formations (18) | Charte libre | **Aucune** | **Aucun** | ❌ | ❌ Non supporté | Manuel guidé + auto-enrich YouTube playlist + `template_training.bbcode` |

**Lecture** : tout ce qui est ✅ doit le rester (non-régression). Tout ce qui
est 🟡 ou ❌ est le scope v0.5.0.

---

## 5. Architecture cible — les 5 briques à conditionner

L'analyse de scope (agent #6) a identifié **5 briques actuellement
"vidéo-only" en dur** qu'il faut rendre conditionnelles à la catégorie. Le
système est plus mûr qu'attendu (`unit3d_mapping.py` a déjà les sets
`MEDIAINFO_REQUIRED_CATEGORIES`, `TMDB_MOVIE_CATEGORIES`, etc.), mais **le
pipeline ne les consulte JAMAIS**. La catégorie est calculée tout à la fin,
dans `build_upload_payload`. Il faut la **précalculer tôt**.

### 5.1 Étape 0 — Précalcul catégorie (XS, 1-2h)

**Pourquoi en premier** : c'est le signal qui débloque toutes les autres
briques. Sans `category_id` connu tôt, on ne peut rien conditionner.

**Implémentation** : dans `pipeline.process_one`, **avant** `detect_media_type`,
appeler `_early_category_guess(input_path, override)` qui retourne :
1. Override user (si stocké dans `state.manual_category_id`) — prioritaire
2. Sélection user dans Inbox (cf. §6) — passé en argument
3. Détection par extension fichier (`.epub/.cbz` → 12, `.iso jeu` → 3, etc.)
4. Fallback : MOVIE par défaut si vidéo, sinon BOOK/GAME/SOFTWARE par
   extension

Stocker dans `debug.set("category_id_early", ...)`. Aucun comportement
modifié encore — c'est juste un signal disponible pour les briques suivantes.

### 5.2 Brique 1 — MediaInfo conditionnel (S/M, 1/2 à 1 jour)

**Couplage actuel** :
- `pipeline.py:83` `detect_media_type(input_path)` lève si pas de vidéo
- `pipeline.py:101-113` appelle `generate_nfo()` + `parse_mediainfo_json()`
  inconditionnellement, avec `die()` si MediaInfo échoue
- `mediainfo_parser.py:326-341` die() si stdout vide ou JSON invalide

**Refactor** :
- Si `category_id ∉ MEDIAINFO_REQUIRED_CATEGORIES` (déjà dans
  `unit3d_mapping.py:56`) → skip MediaInfo + `nfo`, remplir
  `mediainfo_data = {}` ;
- Étendre `detect_media_type` (ou créer `detect_content_type`) pour
  reconnaître `.epub/.pdf/.cbz/.iso/.exe` au lieu de lever ;
- `total_size_recursive` (existe déjà) fournit la taille pour n'importe quel
  fichier/dossier.

**Risque** : faible. La branche vidéo reste intacte. Risque réel = oublier
un endroit qui lit `mediainfo_data["video"]` sans guard — à scanner avant
de merge.

### 5.3 Brique 2 — Compliance par catégorie (S, 1/2 jour)

**Couplage actuel** : tous les checks de `compliance.py` sont lancés en bloc
inconditionnellement depuis `check_compliance` (lignes 692-721). Aucun
filtrage par catégorie.

**Refactor** : signature `check_compliance(..., *, category_id=...)` qui
route vers une liste de checks selon un registre :
```python
CHECKS_BY_PROFILE = {
    "video":  [_check_container_mkv, _check_resolution, ..., _check_team_present],
    "book":   [_check_team_present, _check_banned_team, _check_book_format,
               _check_book_archives],
    "game":   [_check_team_present, _check_banned_team, _check_game_archive,
               _check_game_platform_token],
    "show":   [...],  # = video moins les checks trop stricts
    "sport":  [...],  # = video moins les checks vidéo-précis
    "manual": [_check_team_present, _check_banned_team],
}
```

Avec un mapping `category_id → profile` dans `unit3d_mapping.py`.

**Risque** : faible-moyen. Les tests `test_compliance_lot_k.py` devront être
annotés avec `category_id=`. Risque = oublier de retirer un check d'une
catégorie où il pollue (ex: `_check_french_audio_in_name` ne doit pas
s'appliquer aux ebooks).

### 5.4 Brique 3 — Score de confiance par profil (M, 1-2 jours)

**Couplage actuel** : `compute_confidence_score()` est mono-paradigme vidéo
— pénalise TMDB manquant (-35), IMDB manquant (-15), variante FR (-60),
etc. Aucun signal n'est conditionnel à la catégorie.

**Refactor** : Strategy formel. Créer `core/confidence_strategies/`
contenant `video.py` (= copie byte-pour-byte de l'actuel), `book.py`,
`game.py`, `show.py`, `sport.py`, `manual.py`. Chacun expose
`score(debug, state_data) -> ConfidenceScore`. Dispatch via
`state_data.category_id` → profile.

Buckets (perfect/ready/good/review/blocked) et seuils restent communs. Ce
qui change c'est la composition des pénalités.

**Exemple `book.py`** : -20 si auteur absent, -15 si pas d'ISBN, -10 si pas
de format reconnu, -10 si NFO absent, -5 si description vide, -3 par signal
de fallback BnF/Google/OpenLibrary.

**Risque** : faible. `VideoConfidenceStrategy` = clone exact de l'actuel,
tous les 50+ tests `test_confidence.py` + `test_naming_signals_and_score.py`
continuent de passer en `profile="video"` par défaut.

### 5.5 Brique 4 — NamingStrategy par catégorie (L, ~1 semaine)

**Le gros morceau.** `build_release_name` (`release_name.py:1330`, 318
lignes) est profondément couplé au schéma scene vidéo : split_team → normalize →
classify_parts (langue/résolution/audio/vcodec/source) → TMDB resolve → merge.

`build_upload_payload` est **déjà bien isolé** : il appelle `category_id_for`,
`type_id_for`, `resolution_id_for`. Pour une nouvelle catégorie il suffit
que `category_id_for` retourne le bon ID et le payload se construit. Les
champs ebook/jeu doivent juste être ajoutés en `extra={...}`.

**Refactor — Strategy pattern obligatoire** :
```python
# core/naming/strategy.py
class NamingStrategy(Protocol):
    name: str  # "video" / "book" / "game" / "show" / "sport" / "manual"

    def detect_content(self, input_path) -> ContentInfo: ...
    def build_release_name(self, content_info, tracker, nfo_text, debug,
                           *, force_overrides, providers, media_info,
                           mediainfo_data) -> tuple[str, dict | None]: ...
    def build_extra_payload(self, state_data) -> dict: ...
    def compliance_profile(self) -> str: ...
    def confidence_profile(self) -> str: ...
    def bbcode_template(self) -> str: ...
```

Strategies :
- `VideoNamingStrategy` ← l'actuel `build_release_name` déplacé tel quel
- `BookNamingStrategy` ← `Auteur.Titre.Date.Langue.Format-TEAM`
- `GameNamingStrategy` ← `Titre.Version.Plateforme.Edition.Langue-TEAM`
- `ShowNamingStrategy` ← variante vidéo plus permissive (saison/épisode
  facultatif)
- `SportNamingStrategy` ← variante vidéo (la charte vidéo s'applique pour
  source/résolution, mais pas d'année obligatoire)
- `ManualNamingStrategy` ← utilise toujours le `manual_release_name` que
  l'user a saisi (raise si vide)

**Refactor préparatoire CRITIQUE** : extraire les helpers réutilisables de
`release_name.py` (`split_team`, `normalize_separators`, `collapse_dots`,
`ascii_fold`, `_normalize_token_case`) dans `naming/_helpers.py` — tous les
profils s'en servent. Cette extraction doit être **strictement NO-OP** au
début (juste déplacer le code, tous les tests verts).

**Décomposition** :
- Jour 1-2 : extraction helpers + déplacer `build_release_name` dans
  `VideoNamingStrategy` sans rien changer. Tests verts.
- Jour 3 : Router dans `pipeline.process_one` via `get_strategy(category_id)`.
  Tests verts (toujours sur Video).
- Jour 4-5 : Écrire `BookNamingStrategy` + `rules_book.json` + champs `extra`
  ebook (igdb=0, tmdb=0, etc.).
- Jour 6-7 : `GameNamingStrategy` + champs `extra` jeu (igdb=...).

**Risque** : fort si fait à l'arrache, moyen si l'extraction préparatoire
est strictement no-op. **`tests/test_release_name_real_cases.py` (21 cas
réels Louis) est le gold standard à ne JAMAIS casser.**

### 5.6 Brique 5 — UI conditionnelle (M, 1-2 jours)

**Couplage actuel** : `package_detail.html` (2722 lignes) est UN seul
template qui affiche systématiquement résolution / codec / HDR / audio / subs
/ variante FR / `gemini_type_options` vidéo. Inbox filtre dur sur `VIDEO_EXTS`
(`web/app.py:33`).

**Refactor** :
- `package_detail.html` devient un "shell" qui include dynamiquement
  `_detail_<profile>.html` :
  ```jinja
  {% set profile = category_profile %}
  {% include "_detail_" ~ profile ~ ".html" %}
  ```
- Templates partiels : `_detail_video.html`, `_detail_book.html`,
  `_detail_game.html`, `_detail_show.html`, `_detail_sport.html`,
  `_detail_manual.html`.
- `gemini_type_options` devient conditionnel à la catégorie (type_id 16-37
  pour Jeux/Livres/Logiciels — à ajouter, cf. §10).
- Inbox : toggle de catégorie au moment de "Ajouter à la queue" (cf. §6).

**Risque** : faible. Tant que `profile="video"` reste le défaut, tout est
intact pour la branche vidéo.

---

## 6. Sélecteur de catégorie sur Inbox (D-MC5)

### 6.1 UI cible

Sur la page **Inbox**, lors du clic sur **"Ajouter à la queue"**, une modal
ou un panneau latéral demande la catégorie cible :

```
┌─────────────────────────────────────────────────────┐
│  Ajouter 3 fichiers à la queue                     │
│                                                     │
│  Catégorie de l'upload :                            │
│                                                     │
│  🎬 Vidéo (par défaut)                              │
│     ├─ 🎬 Film                                      │
│     ├─ 📺 Série                                     │
│     ├─ 🎌 Anime (film / série)                      │
│     ├─ 📹 Documentaire (film / série)               │
│     ├─ 🎤 Émission TV                               │
│     └─ 🏟  Sport                                     │
│                                                     │
│  📚 Livre / BD / Manga                              │
│  🎮 Jeu vidéo                                       │
│  💻 Logiciel                                        │
│  🎓 Formation                                       │
│                                                     │
│  [Annuler]              [Ajouter à la queue] →     │
└─────────────────────────────────────────────────────┘
```

**Code couleur** par catégorie (Tailwind palette) :
- Films/Séries/Doc/Anime → **violet/indigo** (couleur charte actuelle)
- Émission TV → **rose**
- Sports → **orange**
- Livres → **émeraude**
- Jeux → **bleu cyan**
- Logiciels → **gris**
- Formations → **jaune**

Chaque catégorie a son emoji + son badge couleur qui s'affichera ensuite
sur la queue, la page détail et l'history.

### 6.2 Détection automatique + suggestion

À l'ouverture de la modal, on **suggère** la catégorie la plus probable
selon les extensions des fichiers sélectionnés :

| Extensions principales | Suggestion |
|---|---|
| `.mkv/.mp4/.avi/.ts` | Vidéo → Film (si fichier unique) ou Série (si plusieurs S0xE0x) |
| `.epub/.pdf/.mobi/.azw3/.djvu` | Livre |
| `.cbr/.cbz` | Livre → BD/Comics/Manga |
| `.iso` (>3 Go vidéo) ou `.bdmv` | Vidéo → Full Disc |
| `.iso` (jeu) ou `.bin/.cue` ou répertoire `PS3_GAME` | Jeu |
| `.exe`, `.msi`, `setup_*.zip` | Logiciel |
| Playlist YouTube détectée (URL collée) | Formation |

### 6.3 Garde-fous (D-MC13)

**Cas 1 : mélange détecté** dans la sélection
→ Si les fichiers ont des extensions de plusieurs univers (vidéo + ebook par
ex), modal :
```
⚠ Vous avez sélectionné des fichiers de natures différentes :
   • 2 fichiers vidéo (.mkv)
   • 1 fichier livre (.epub)

   [Créer 2 packages séparés (recommandé)]
   [Tout regrouper dans : ? choisir]
   [Annuler]
```

**Cas 2 : incohérence catégorie ↔ contenu** (l'user choisit "Jeu" mais a
sélectionné un `.mkv`)
→ Avertissement non-bloquant : "Attention : vous uploadez un fichier vidéo
en catégorie Jeu. Confirmer ?"

**Cas 3 : déjà préparé sous une autre catégorie** (re-prepare)
→ Sur la page détail, bouton **"Repréparer avec autre catégorie"** ouvre la
même modal de sélection. Sauvegarde dans
`state.manual_category_id_override`, relance `process_one` avec la nouvelle
strategy. L'ancien score/release_name/BBCode sont remplacés. État du
`.torrent` invalidé (re-créé).

---

## 7. APIs externes — par univers

### 7.1 Vidéo (déjà branché — pas de changement v0.5.0)

| API | Rôle | Var env |
|---|---|---|
| TMDB | Métadonnées films/séries | `TMDB_API_KEY` (gratuit) |
| OMDb | Note IMDb fallback | `OMDB_API_KEY` (optionnel, gratuit 1000/jour) |

### 7.2 Émissions TV (catégorie 15) — barreau 2

| API | Rôle | Var env | Coût |
|---|---|---|---|
| **TVmaze** | Source primaire (champ `type`: Talk Show/Reality/Game/News granulaire) | Aucune | Gratuit, 20 req/10s |
| TMDB (déjà branché) | Fallback + poster FR + overview FR | `TMDB_API_KEY` | Gratuit |
| Wikidata SPARQL | Présentateurs (P371), chaîne (P449), genre (P136) | Aucune | Gratuit |
| ffmpeg | Génération screenshots si TVmaze image=null | (déjà bundlé) | — |

**Pourquoi** : TVmaze a un champ `type` natif qui catégorise (Talk
Show/Reality/Game/News) — exactement ce qui manque à TMDB. Couverture FR
non-fiction ~80% (TPMP, Quotidien, Cash Investigation, Slam, etc.).

**Limite** : épisodes summary/image quasi-toujours null → fallback ffmpeg
pour les screenshots.

**Endpoint** :
```
https://api.tvmaze.com/singlesearch/shows?q=Quotidien&embed[]=cast
```

### 7.3 Sports (catégorie 10) — barreau 2

| Layer | Rôle | Var env |
|---|---|---|
| **Base statique JSON** | ~70 logos précachés (NBA, NFL, F1, UFC, Premier League, Ligue 1, Tour de France, etc.) mappés sur les keywords déjà détectés | Aucune (livré avec l'app) |
| **TheSportsDB** | Enrichissement événement (venue, date, fighters, résultat) | `THESPORTSDB_API_KEY` = `"123"` par défaut (clé test publique, 30 req/min, 2 résultats par search) |
| TheSportsDB Patreon | Clé prod sans watermark | Patreon 9 USD/mois optionnel |

**Pourquoi** : aucune API gratuite n'a la couverture sport mondiale +
événement individuel sauf TheSportsDB. La base statique JSON locale garantit
qu'un logo de ligue est toujours dispo même offline.

**Endpoint** :
```
https://www.thesportsdb.com/api/v1/json/123/searchevents.php?e=UFC_300
```

**Identifiants utiles** (à intégrer en statique) :
- F1 = 4370, UFC = 4443, UCI World Tour = 4465, NBA = 4387, NFL = 4391,
  Premier League = 4328, Ligue 1 = 4334, etc.

**À écarter** : ESPN (non-officielle, instable), API-Football (foot seul),
Sportradar (10k$/mois).

### 7.4 Livres / Ebooks / BD / Manga (catégorie 12) — barreau 3

| API | Rôle | Var env | Coût |
|---|---|---|---|
| **BnF SRU** | **Pivot FR** — métadonnées canoniques livre FR (auteur, titre, éditeur, ISBN, pages, langue) | Aucune | Gratuit (institution publique) |
| **Google Books** | Résumé FR + couverture (BnF n'en fournit pas) | `GOOGLE_BOOKS_API_KEY` | Gratuit 1000/jour, optionnel jusqu'à 100k |
| OpenLibrary | Fallback gratuit sans clé | Aucune | Gratuit, 1 req/s anonyme |
| **BnF Service Couvertures** | Couvertures FR libres de droits | Aucune | Gratuit |
| **ComicVine** (BD/Comics US/UK) | Spécialisé comics | `COMICVINE_API_KEY` | Gratuit 200 req/h |
| **AniList GraphQL** (Manga) | Spécialisé manga, couvertures HD | Aucune | Gratuit 90 req/min |
| Jikan v4 (Manga fallback) | Wrapper MAL non-officiel | Aucune | Gratuit 60 req/min |

**Routage par sous-type** (détecté via extension + ISBN + metadata EPUB) :
- `.epub/.pdf/.mobi/.azw3/.djvu` → **BOOK** → BnF + Google Books + OpenLibrary
- `.cbr/.cbz` + ISBN 978-2 (FR) → **BD** → BnF + Google Books + ComicVine
- `.cbr/.cbz` + ISBN 978-1 (UK/US) ou pas d'ISBN + nom US → **COMIC** →
  ComicVine + Google Books + OpenLibrary
- `.cbr/.cbz` + ISBN 978-4 (JP) ou détection japonaise → **MANGA** →
  AniList + Jikan + BnF (pour éditeur FR)

**À écarter** : ISBNdb (payant), Goodreads (déprécié), WorldCat (friction
institutionnelle), Bedetheque (pas d'API, scraping fragile).

**Cache** : `data/.books_cache.json` keyé par `isbn13|source` (atomic write
comme `.tmdb_cache.json`).

### 7.5 Jeux (catégorie 3) — barreau 3

| API | Rôle | Var env | Coût |
|---|---|---|---|
| **IGDB** | **Source principale toutes plateformes** (Twitch OAuth) | `IGDB_CLIENT_ID` + `IGDB_CLIENT_SECRET` | Gratuit, 4 req/s, non-commercial |
| **Steam Store** | Quand plateforme=PC : résumé FR officiel + **configuration requise** | Aucune | Gratuit |
| RAWG (fallback) | Si IGDB rate | `RAWG_API_KEY` | Gratuit 20k req/mois |

**Auth IGDB** : OAuth2 Client Credentials via Twitch :
1. Compte sur [dev.twitch.tv](https://dev.twitch.tv/console/apps), créer une
   app → `Client-ID` + `Client-Secret`
2. `POST https://id.twitch.tv/oauth2/token?client_id=X&client_secret=Y&grant_type=client_credentials`
   → access token valide 60 jours
3. Cache token en atomic write (`data/.igdb_token.json`)

**Endpoint search** :
```
POST https://api.igdb.com/v4/games
Headers: Client-ID: <id>, Authorization: Bearer <token>
Body (Apicalypse): search "elden ring"; fields name,summary,first_release_date,
  platforms.name,involved_companies.company.name,involved_companies.developer,
  involved_companies.publisher,cover.image_id,screenshots.image_id,
  genres.name,age_ratings.rating; limit 5;
```

**Image URL** : `https://images.igdb.com/igdb/image/upload/t_cover_big/<id>.jpg`

**Couverture FR** : `summary` est généralement en anglais. Si plateforme =
Windows/Mac/Linux → cross-référencer Steam pour avoir le résumé FR Valve.

**À écarter** : MobyGames (payant depuis 2024), GiantBomb (rate limit cassé
post-Fandom), GameFAQs (scraping uniquement).

### 7.6 Logiciels (catégorie 17) — barreau 4

| API | Rôle | Var env | Coût |
|---|---|---|---|
| Formulaire manuel | Tous champs (nom, éditeur, version, plateforme, type, langue, etc.) | — | — |
| **GitHub API** | Auto-enrich si l'user colle une URL `github.com/owner/repo` | `GITHUB_TOKEN` (optionnel, sinon 60 req/h) | Gratuit |
| **VirusTotal** | Hash SHA256 de l'installer → "X/70 moteurs AV : clean / suspicious" | `VIRUSTOTAL_API_KEY` (opt-in) | Gratuit 4 req/min |

**Champs formulaire** : Nom, Éditeur, Version, Date de sortie, Langue
(FR/EN/MULTi), Plateforme (Windows/macOS/Linux/Android), Architecture
(x64/x86/ARM), Type (Installateur/Portable/Patch/Crack), Licence
(Freeware/Shareware/Commercial/Open-Source), URL site officiel, Description.

**À écarter** : Microsoft Store API (pas d'API publique catalogue),
AlternativeTo (pas d'API), Softpedia (scraping fragile), Coursera/Udemy
(licences/dépréciés).

### 7.7 Formations (catégorie 18) — barreau 4

| API | Rôle | Var env | Coût |
|---|---|---|---|
| Formulaire manuel | Tous champs (titre, formateur, plateforme, langue, durée, niveau, catégorie) | — | — |
| **YouTube Data API v3** | Auto-enrich si l'user colle URL `youtube.com/playlist?list=...` | `YOUTUBE_API_KEY` | Gratuit 10k unités/jour |

**Champs formulaire** : Titre, Auteur/Formateur, Plateforme d'origine
(dropdown: Udemy/OpenClassrooms/LinkedIn Learning/YouTube/Autre), Année,
Langue, Durée totale, Niveau (Débutant/Intermédiaire/Avancé), Catégorie
tech (dropdown: Dev Web/Data/DevOps/Design/Bureautique/…), Description.

**Cas YouTube playlist** : on fetch les métadonnées de la playlist + de
chaque vidéo (titre, durée, chaîne = "formateur", description = synopsis).
Coût ~102 unités → ~95 lookups/jour gratuit.

**À écarter** : Udemy Affiliate API (morte depuis 1/1/2025), Coursera
(licence ambiguë, beta perpétuelle), LinkedIn Learning (gated entreprise),
Pluralsight (payant), OpenClassrooms (pas d'API publique).

---

## 8. Découvertes critiques (sources Gemini)

En lisant les 7 PDFs Gemini commités dans `gemini/`, j'ai trouvé des
**écarts majeurs** entre la doc officielle et `unit3d_mapping.py` actuel.
**À corriger en Sprint A** avant tout autre travail.

### 8.1 Type_IDs 16-37 manquants dans `unit3d_mapping.py`

`TORRENT_API.txt` documente officiellement les `type_id` Gemini :

| ID | Type | Catégorie associée |
|---|---|---|
| 16 | Jeux\Windows | 3 |
| 17 | Jeux\Autre | 3 |
| 18 | Jeux\Linux | 3 |
| 19 | Jeux\MacOS | 3 |
| 20 | Jeux\Xbox | 3 |
| 21 | Jeux\Nintendo | 3 |
| 22 | Jeux\Smartphone | 3 |
| 23 | Jeux\Sony | 3 |
| 24 | Jeux\Tablette | 3 |
| 25 | Livres\M4B | 12 |
| 26 | Livres\MP3 | 12 |
| 27 | Livres | 12 |
| 28 | Livres\BD | 12 |
| 29 | Livres\Comics | 12 |
| 30 | Livres\Mangas | 12 |
| 31 | Livres\Magazine | 12 |
| 32 | Livres\Presse | 12 |
| 33 | Livres\Audio | 12 |
| 34 | Logiciels\Windows | 17 |
| 35 | Logiciels\MacOS | 17 |
| 36 | Logiciels\Linux | 17 |
| 37 | Logiciels\Autres | 17 |

**Aucun n'est dans `unit3d_mapping.py` aujourd'hui.** L'upload jeu/livre/soft
serait rejeté par l'API faute de type_id valide. **Bloquer en Sprint A.**

### 8.2 Teams interdites — liste plus longue qu'aujourd'hui

`TEAMS_INTERDITES.txt` officiel :
- **Films/Vidéo** : `k0RE`, `Slay3R`, `EXTREME` (cas spécial : encodes
  interdits, REMUX/Full Blu-ray/WEB-DL autorisés)
- **Jeux/Apps** : `Fenixx`, `KMS.Tools.Portable`, `MAXAGENT`, `Seyter`,
  `Vansik`

Le code actuel a juste `DEFAULT_BANNED_TEAMS = ("k0RE", "Slay3R")`. **À
étendre** avec un mapping par catégorie + ajouter `EXTREME` au check
`_check_extreme_team_only_encodes` (qui existe déjà, à vérifier).

### 8.3 Tailles de pièces .torrent recommandées

`RÈGLES_DUPLOAD.txt` page 5 documente le barème officiel :
- < 500 Mo → 256 Ko
- > 500 Mo → 512 Ko
- > 1 Go → 1 Mo
- > 2 Go → 2 Mo
- > 4 Go → 4 Mo
- > 8 Go → 8 Mo
- > 20 Go → 16 Mo (max, incompat clients)

**À vérifier** : le code utilise `torf` qui auto-calcule ; voir si le
résultat respecte ce barème ou si on doit forcer manuellement.

### 8.4 MediaInfo obligatoire / non-obligatoire — confirmation

Confirmé par `TORRENT_API.txt` :
- **Obligatoire** : 1 (Films), 2 (Séries), 6 (Séries Anime), 7 (Films
  Anime), 10 (Sports), 13 (Films Doc), 14 (Séries Doc), 15 (Émission TV)
- **Non obligatoire** : 3 (Jeux), 12 (Livres), 17 (Logiciels), 18
  (Formations)

C'est exactement ce que `MEDIAINFO_REQUIRED_CATEGORIES` a déjà — il "suffit"
de le consulter (cf. Brique 1).

### 8.5 Champs upload par catégorie

`TORRENT_API.txt` confirme :
- **Films TMDB-oui** (1, 7, 13) → champ `tmdb` obligatoire (movie_id), `imdb`/`tvdb`/`mal` optionnels
- **Séries TMDB-oui** (2, 6, 14, 15) → champ `tmdb` (tv_id) + `season_number` + `episode_number` (souvent 0 pour saison complète) obligatoires
- **Jeux** (3) → champ `igdb` (igdb_id) obligatoire
- **Autres** (10, 12, 17, 18) → IDs externes optionnels
- `resolution_id` requis si catégorie Film/Série TMDB ; sinon vide/null OK
- `region_id` / `distributor_id` → optionnels pour FULL DISC

### 8.6 Règles ebooks spécifiques

`RÈGLES_DUPLOAD_EBOOK.txt` :
- Formats autorisés : `.CBR`, `.CBZ`, `.EPUB`, `.DJVU`, `.MOBI`, formats
  Kindle (`.AZW3`), `.PDF`
- **Archives RAR/ZIP/7Z interdites** → check à ajouter dans
  compliance ebook
- NFO **obligatoire** pour tous les ebooks
- Multiformat OK (max 2-3 formats du même ebook : PDF + EPUB par ex)
- Pas de chapitres séparés hors tomes
- Métadonnées via **Calibre** encouragées (un futur enrichissement
  potentiel — Calibre a un CLI lisible)
- Résolution requise pour BD/Manga/Comics si elle varie par tome
- Tolérance packs presse : pack avec >1/5 doublons → refusé

---

## 9. Sprints v0.5.0

### Sprint A — Fondation invisibles (1 semaine)

**Objectif** : refactor préparatoire qui ne change rien à l'expérience user.
Tous tests verts à chaque commit.

| Tâche | Détail | Effort |
|---|---|---|
| Compléter `unit3d_mapping.py` | Ajouter TYPE_IDs 16-37 (§8.1) | S |
| Étendre `DEFAULT_BANNED_TEAMS` | Mapping par catégorie + ajouter Fenixx/MAXAGENT/Vansik/etc. (§8.2) | S |
| Vérifier tailles pièces .torrent | Audit `torrent.py` vs barème §8.3, ajuster si besoin | XS |
| **Étape 0** : `_early_category_guess()` | Précalcul catégorie tôt dans le pipeline | XS |
| **Brique 1** : MediaInfo conditionnel | Skip MediaInfo si cat ∉ MEDIAINFO_REQUIRED_CATEGORIES + `detect_content_type` étendu | S/M |
| **Brique 2** : Compliance par profil | Refactor `check_compliance` + registre `CHECKS_BY_PROFILE` | S |
| Tests : annoter test_compliance avec `category_id=` | Maintenir 772 tests verts | S |

**DoD Sprint A** :
- ✅ On peut passer un `.epub` ou `.iso jeu` dans `pipeline.process_one` **sans
  qu'il plante** (il s'arrête juste avant le naming, qui n'est pas encore
  refactoré — c'est OK).
- ✅ 772 tests vidéo restent verts.
- ✅ `unit3d_mapping.py` est complet et conforme à `TORRENT_API.txt`.

### Sprint B — Routeur naming + extraction helpers (1.5 semaine)

**Objectif** : isoler la logique vidéo dans `VideoNamingStrategy` sans rien
changer fonctionnellement. Préparer le terrain pour ajouter les autres
strategies en O(1).

| Tâche | Détail | Effort |
|---|---|---|
| Extraire `naming/_helpers.py` | `split_team`, `normalize_separators`, `collapse_dots`, `ascii_fold`, `_normalize_token_case` | M |
| Créer `naming/strategy.py` Protocol | Interface + dispatcher `get_strategy(category_id)` | XS |
| Déplacer `build_release_name` → `VideoNamingStrategy` | NO-OP, just move | M |
| Router dans `pipeline.process_one` | `strategy = get_strategy(category_id_early)` puis `strategy.build_release_name(...)` | S |
| Refactor `build_upload_payload` → `strategy.build_extra_payload()` | Idem NO-OP | S |

**DoD Sprint B** :
- ✅ Tous les 772 tests verts.
- ✅ Aucun changement de comportement pour vidéo.
- ✅ `tests/test_release_name_real_cases.py` (21 cas réels Louis) passe sans
  régression.
- ✅ La structure est prête à recevoir `BookNamingStrategy` / `GameNamingStrategy`
  sans toucher au pipeline.

### Sprint C — UI sélecteur de catégorie (3-5 jours)

**Objectif** : Inbox demande la catégorie au moment d'ajouter à la queue.
Pages détail conditionnelles.

| Tâche | Détail | Effort |
|---|---|---|
| Modal "Ajouter à la queue" avec catégorie | Côté Inbox JS + endpoint backend qui accepte `category_id_hint` | M |
| Détection auto + suggestion | Mapping extension → catégorie suggérée (§6.2) | S |
| Garde-fou mélange | Modal de confirmation si extensions mixtes (§6.3) | S |
| Badge couleur + emoji par catégorie | Sur Inbox, Queue, Page détail, History | S |
| Templates `_detail_<profile>.html` | 6 templates (video/book/game/show/sport/manual) — encore vides pour les 5 nouveaux | M |
| Bouton "Repréparer avec autre catégorie" | Sur page détail | S |
| Brique 3 (score) : `ConfidenceStrategy` Protocol + 6 stubs | `video.py` = copie exacte, les 5 autres = minimal pass-through | M |
| Brique 5 (UI) : `gemini_type_options` conditionnel | Type 16-37 pour Jeux/Livres/Logiciels | S |

**DoD Sprint C** :
- ✅ L'user peut sélectionner "Livre" sur Inbox et le package est créé avec
  `category_id=12` (même si le pipeline ne sait pas encore quoi en faire).
- ✅ La page détail affiche un template par catégorie (vide pour les 5
  nouveaux, OK pour l'instant).
- ✅ Tous tests verts.

### Sprint D — Pipeline Livre (1 semaine)

**Objectif** : un `.epub` ou `.cbz` peut être uploadé proprement.

| Tâche | Détail | Effort |
|---|---|---|
| `BookNamingStrategy` | `Auteur.Titre.Date.Langue.Format-TEAM` | M |
| `core/providers/bnf.py` | Client SRU BnF (XML Dublin Core) | S |
| `core/providers/google_books.py` | Client + cache | S |
| `core/providers/openlibrary.py` | Client + cache fallback | S |
| `core/providers/comicvine.py` | Client BD US/UK | S |
| `core/providers/anilist.py` | Client GraphQL manga | S |
| `BookConfidenceStrategy` | Pénalités auteur/ISBN/format/NFO/description | S |
| Compliance ebook | `_check_book_format` (CBR/CBZ/EPUB/PDF/MOBI/AZW3/DJVU), `_check_book_archives` (rejet RAR/ZIP/7Z), `_check_book_nfo_present` | S |
| `template_book.bbcode` | Couverture, auteur, titre, ISBN, éditeur, résumé, pages, langue, série/tome | S |
| `_detail_book.html` | Formulaire override (ISBN manuel, auteur, etc.) | M |
| Tests | Au minimum 10 tests : naming book, BnF parsing, BBCode book, compliance ebook | M |

**DoD Sprint D** :
- ✅ Uploader *Le Seigneur des Anneaux* en `.epub` produit un release_name
  `J.R.R.Tolkien.Le.Seigneur.Des.Anneaux.1954.FRENCH.EPUB-Flox`.
- ✅ BnF récupère auteur+titre+éditeur+année.
- ✅ Google Books complète couverture + résumé FR.
- ✅ La fiche BBCode rend visuellement propre.
- ✅ 10 nouveaux tests verts + 772 anciens.

### Sprint E — Pipeline Jeu (1 semaine)

**Objectif** : un dossier de jeu (ou ISO) peut être uploadé.

| Tâche | Détail | Effort |
|---|---|---|
| `GameNamingStrategy` | `Titre.Version.Plateforme.Edition.Langue-TEAM` | M |
| `core/providers/igdb.py` | Client IGDB Twitch OAuth + cache token 60j | M |
| `core/providers/steam_store.py` | Client Steam appdetails FR (no auth) | S |
| `core/providers/rawg.py` | Fallback | S |
| `GameConfidenceStrategy` | Pénalités titre/plateforme/version/IGDB ID | S |
| Compliance jeu | `_check_game_archive` (zip/rar OK pour jeux), `_check_game_platform_token` (plateforme dans le release_name) | S |
| `template_game.bbcode` | Jaquette, studio, plateformes, genres, résumé FR (Steam), specs PC | S |
| `_detail_game.html` | Formulaire (plateforme, version, edition, IGDB_id manuel) | M |
| Tests | 10 tests minimum | M |

**DoD Sprint E** :
- ✅ Uploader *Elden Ring PS5* produit `Elden.Ring.PS5.MULTi.Deluxe.Edition-Flox`.
- ✅ IGDB récupère studio/éditeur/genres/jaquette.
- ✅ Steam Store (pour PC) ajoute résumé FR + specs.
- ✅ Tests verts.

### Sprint F — Pipeline Émission TV (4-5 jours)

**Objectif** : Quotidien/TPMP/Koh-Lanta uploadable avec fiche correcte.

| Tâche | Détail | Effort |
|---|---|---|
| `ShowNamingStrategy` | Variante vidéo (saison/épisode optionnels) | S |
| `core/providers/tvmaze.py` | Client + cache | S |
| `core/providers/wikidata_sparql.py` | Présentateurs/chaîne | S |
| `ShowConfidenceStrategy` | Pénalités si TVmaze rate / présentateur manquant | S |
| Compliance émission | Profile "show" = video sans certains checks rigides (charte sport applicable) | S |
| `template_show.bbcode` | Chaîne, présentateur, genre, résumé, dates | S |
| Génération ffmpeg screenshots si TVmaze image=null | Helper `_extract_thumbnails(video, count=3)` | S |
| `_detail_show.html` | Formulaire (chaîne, présentateur, épisode date) | S |
| Tests | 8 tests minimum | M |

**DoD Sprint F** :
- ✅ Quotidien 2024-05-20 uploadable avec fiche complète (Yann Barthès,
  TMC, résumé, 3 screenshots ffmpeg).

### Sprint G — Pipeline Sport (3-4 jours)

**Objectif** : UFC/F1/Tour de France uploadable avec fiche propre.

| Tâche | Détail | Effort |
|---|---|---|
| `SportNamingStrategy` | Variante vidéo (charte technique respectée, mais pas d'année obligatoire ; date utilisée) | S |
| `core/providers/thesportsdb.py` | Client + cache | S |
| `gemini/assets/sport_logos/*.png` | ~70 logos précachés des ligues détectées par les keywords (SPORTS_KEYWORDS) | M (collecte) |
| `sport_logos.json` | Mapping keyword → {league_name, league_id_sportsdb, logo_path} | S |
| `SportConfidenceStrategy` | Pénalités si pas de ligue identifiée | XS |
| `template_sport.bbcode` | Logo ligue + nom + date + lieu + thumbnails | S |
| `_detail_sport.html` | Formulaire override | S |
| Tests | 6 tests minimum | S |

**DoD Sprint G** :
- ✅ Un upload `UFC.300.2024.PPV-FLOX` affiche logo UFC + venue T-Mobile
  Arena + date + main card.

### Sprint H — Pipeline manuel guidé (3-4 jours)

**Objectif** : Logiciels / Formations / cas exotiques de toutes catégories
sont uploadables.

| Tâche | Détail | Effort |
|---|---|---|
| `ManualNamingStrategy` | Utilise `manual_release_name`, raise si vide | XS |
| `_detail_software.html` | Formulaire complet logiciel (§7.6 champs) | S |
| `_detail_training.html` | Formulaire complet formation (§7.7) | S |
| `_detail_manual.html` | Fallback générique pour cas non identifiés | S |
| `core/providers/github_repo.py` | Auto-enrich si URL `github.com/owner/repo` collée | S |
| `core/providers/youtube_playlist.py` | Auto-enrich si URL `youtube.com/playlist?list=...` collée | S |
| `core/providers/virustotal.py` | Opt-in dans `/config` — hash SHA256 installer | S |
| `template_software.bbcode` + `template_training.bbcode` | Mise en page propre | S |
| Tests | 6 tests minimum | S |

**DoD Sprint H** :
- ✅ Uploader OBS Studio (URL GitHub collée) → fiche enrichie automatiquement
  (description, licence GPL, version).
- ✅ Uploader une playlist YouTube collée → titre, chaîne, durée totale,
  description.
- ✅ Tout le reste passe par formulaire manuel propre.

### Sprint I — Release v0.5.0 (3-5 jours)

| Tâche | Détail | Effort |
|---|---|---|
| Tests E2E manuels sur VM Windows propre | Toutes catégories | M |
| Mise à jour `/setup` | Sections par univers (clés API optionnelles) | M |
| Mise à jour `/guide` | Doc utilisateur des 4 barreaux + des catégories | M |
| Mise à jour README | Section "Multi-catégorie depuis v0.5.0" + captures | S |
| Mise à jour CHANGELOG | Section v0.5.0 | XS |
| Tag `v0.5.0` | Bump dans `pyproject.toml` + `__init__.py` | XS |
| GitHub Release avec installeur + portable .exe | Auto via CI sur tag | XS |
| Annonce communauté (optionnel) | Forum Gemini | XS |

**DoD Sprint I (= DoD v0.5.0 globale)** :
- ✅ 12 catégories Gemini fonctionnent (au moins barreau 4).
- ✅ Pipeline vidéo non-régressé (772+ tests).
- ✅ Au moins 50 nouveaux tests pour les catégories non-vidéo.
- ✅ Page `/setup` permet de configurer toutes les clés API par univers.
- ✅ Doc utilisateur claire sur les 4 barreaux.
- ✅ Installeur Windows .exe livré (cf. PLAN-V1.md pour le workflow).
- ✅ Tag v0.5.0 publié.

**Total estimé v0.5.0** : 6 à 8 semaines homme.

---

## 10. Variables d'environnement à ajouter

| Var | Catégorie | Obligatoire | Source / coût |
|---|---|---|---|
| `GOOGLE_BOOKS_API_KEY` | Livres | Optionnelle | [console.cloud.google.com](https://console.cloud.google.com/) — gratuit 1000/jour |
| `COMICVINE_API_KEY` | Livres (BD/Comics) | Optionnelle | [comicvine.gamespot.com/api](https://comicvine.gamespot.com/api/) — gratuit 200/h |
| `IGDB_CLIENT_ID` | Jeux | Obligatoire pour jeux | [dev.twitch.tv](https://dev.twitch.tv/console/apps) — gratuit |
| `IGDB_CLIENT_SECRET` | Jeux | Obligatoire pour jeux | idem |
| `RAWG_API_KEY` | Jeux | Optionnelle (fallback) | [rawg.io/apidocs](https://rawg.io/apidocs) — gratuit 20k/mois |
| `THESPORTSDB_API_KEY` | Sports | Défaut `"123"` | [thesportsdb.com](https://www.thesportsdb.com/) — gratuit 30/min |
| `YOUTUBE_API_KEY` | Formations | Optionnelle | [console.cloud.google.com](https://console.cloud.google.com/) — gratuit 10k unités/jour |
| `GITHUB_TOKEN` | Logiciels | Optionnelle (rate limit) | [github.com/settings/tokens](https://github.com/settings/tokens) — gratuit |
| `VIRUSTOTAL_API_KEY` | Logiciels | Opt-in | [virustotal.com](https://www.virustotal.com/) — gratuit 4/min |

**Toutes optionnelles** sauf IGDB (les jeux sont inutilisables sans). Si une
clé manque, dégradation gracieuse au barreau suivant.

---

## 11. Pièges connus (croissants)

### Pièges hérités (déjà documentés CLAUDE.md §14)
- `team.upper()` interdit (casse signature à préserver)
- `_NEVER_TEAM` / `_TECH_TOKENS` mutualisés
- TMDB min 2 mots significatifs (sinon `Les` match n'importe quoi)
- Path traversal `/inbox` à auditer avant exposition réseau

### Nouveaux pièges v0.5.0

**BnF SRU portal** : `api.bnf.fr` a renvoyé 500 pendant la recherche initiale.
Wrapper le client BnF avec retry + fallback explicite vers Google Books.

**IGDB token** : valide **60 jours**. Cache en atomic write + auto-refresh
quand >55 jours. Ne pas spammer `oauth2/token` à chaque requête (4 req/s
sufficient pour tout l'usage).

**TVmaze épisodes** : `summary` et `image` quasi-toujours `null` pour
émissions FR. Générer screenshots via ffmpeg systématiquement pour le
template `show`.

**ISBN routage** : `978-2` = FR, `978-1` = UK/US, `978-4` = JP. Routage des
BD/Manga selon cette heuristique. ISBN absent = fallback nom + langue
détectée.

**IGDB FR** : `summary` IGDB est presque toujours en EN. Pour plateforme =
Windows/Mac/Linux, **toujours** cross-référencer Steam (`cc=fr&l=french`)
pour avoir le résumé FR officiel Valve.

**TheSportsDB clé `"123"`** : limite à **2 résultats par search**. Si le
match est ambigu, l'app doit afficher les 2 candidats et laisser l'user
choisir. Sinon, Patreon 9 USD/mois pour clé prod.

**YouTube quota** : 10k unités/jour. Une lookup playlist = ~102 unités.
Limite à ~95 playlists/jour gratuit — peut être un goulot pour les
gros uploaders de formations.

**VirusTotal opt-in** : si l'user n'a pas configuré, ne JAMAIS uploader le
hash silencieusement. Strict respect "aucune donnée ne quitte la machine
sans appel API explicite par l'user".

**Calibre integration** (future, optionnelle) : Calibre a un CLI lisible
(`calibredb list`, `ebook-meta`) qui peut compléter BnF+Google Books avec
les métadonnées embarquées dans l'EPUB. À considérer en v0.6+.

**Templates par catégorie** : 6 templates au final
(`_detail_video.html` × 5 autres) + 6 templates BBCode. Penser à les tester
visuellement à chaque release, pas seulement unitaires.

**Compliance teams interdites par catégorie** : la liste change selon
films/jeux/apps. Ne pas appliquer "Fenixx interdit" sur un upload film.

**Type_id resolution** : pour un livre, `type_id` ∈ {25-33} selon
sous-format. Pour un jeu, `type_id` ∈ {16-24} selon plateforme. Le mapping
plateforme → type_id n'existe pas encore — à créer dans `unit3d_mapping.py`.

---

## 12. Definition of Done — v0.5.0

Pour que `v0.5.0` puisse être taguée et release publiquement, **TOUS** ces
points doivent être vrais :

### Pré-requis (déjà fait ou hérité de v0.4.0)
- [ ] **v0.4.0 publiée** (préalable bloquant — GitHub Actions réactivée)
- [x] Repo public, LICENSE MIT, disclaimer Guide
- [x] Wizard setup
- [x] Crash report helper
- [x] Banner auto-update
- [x] Data dir cross-platform

### Architecture multi-catégorie
- [ ] 12 catégories Gemini fonctionnent au moins au barreau 4 (manuel)
- [ ] `unit3d_mapping.py` complet (TYPE_IDs 16-37 ajoutés)
- [ ] Strategy pattern en place : `NamingStrategy`, `ConfidenceStrategy`,
      `MetadataProvider`, templates BBCode
- [ ] Précalcul catégorie tôt dans le pipeline
- [ ] MediaInfo conditionnel
- [ ] Compliance par profil

### Pipelines catégories
- [ ] Vidéo : non-régressé (772+ tests)
- [ ] Livre : BnF + Google Books + OpenLibrary opérationnels
- [ ] Jeu : IGDB + Steam Store opérationnels
- [ ] Émission TV : TVmaze + ffmpeg screenshots opérationnels
- [ ] Sport : TheSportsDB + base statique logos opérationnels
- [ ] Logiciel : manuel + auto-enrich GitHub + VirusTotal opt-in opérationnels
- [ ] Formation : manuel + auto-enrich YouTube playlist opérationnels

### UI
- [ ] Sélecteur catégorie sur Inbox (modal + suggestion auto)
- [ ] Garde-fou mélange de catégories
- [ ] Templates `_detail_<profile>.html` × 6
- [ ] Templates BBCode × 6 (`template_book/game/show/sport/software/training.bbcode`)
- [ ] Badge couleur + emoji par catégorie sur Queue/Inbox/History/Page détail
- [ ] Bouton "Repréparer avec autre catégorie"

### Tests
- [ ] 822+ tests verts (772 vidéo + ~50 nouveaux par catégorie)
- [ ] `test_release_name_real_cases.py` ne perd aucun cas Louis
- [ ] Couverture maintenue ≥ 39%

### Doc
- [ ] `/setup` page mise à jour avec sections par univers
- [ ] `/guide` page mise à jour avec les 4 barreaux
- [ ] README à jour avec captures multi-catégorie
- [ ] CHANGELOG section v0.5.0
- [ ] `CLAUDE.md` à jour (cf. §13)
- [ ] PLAN-MULTICAT.md gardé synchro

### Distribution
- [ ] Installeur Windows v0.5.0 buildé en CI (GitHub Actions réactivée)
- [ ] Smoke test sur VM Windows propre
- [ ] Release GitHub avec changelog clair

---

## 13. Continuité de session (IMPORTANT)

Quand une nouvelle session Claude reprend ce projet, voici l'ordre de lecture
**obligatoire** :

1. **`CLAUDE.md`** — TL;DR projet, architecture, conventions, pièges connus.
2. **`PLAN-V1.md`** — Plan v0.4.0 (release publique vidéo) — encore pertinent
   pour les patches v0.4.x.
3. **`PLAN-MULTICAT.md`** — Ce doc. Le plan v0.5.0 et au-delà.
4. **`gemini/*.pdf`** — Sources de vérité officielles Gemini.
5. **`NOTES.md`** — Notes brutes à la volée (le format est documenté en haut
   du fichier).

### Comment savoir où on en est ?

```bash
git log --oneline -10           # Derniers commits
git branch --show-current       # Branche active
git status -sb                  # Modifs non commitées
gh pr list                      # PRs ouvertes
gh release list                 # Releases publiées
.venv/Scripts/python -m pytest -q 2>&1 | tail -3  # Tests verts ?
```

### Avant de coder en v0.5.0, vérifier
- [ ] v0.4.0 est-elle taguée et publiée ?
- [ ] Quelle sprint A→I est en cours ?
- [ ] La PR ouverte la plus récente sur quoi porte-t-elle ?
- [ ] Y a-t-il des décisions amendées dans ce doc depuis la dernière session ?
- [ ] Les 772+ tests passent-ils en local ?

### Modifier ce doc avant de modifier le code
Si une décision doit être révisée, **on modifie PLAN-MULTICAT.md en premier**,
puis le code. L'historique git de ce fichier sert d'audit des décisions
produit.

### Mémoire des sessions précédentes (Cowork, antérieures à 2026-05-22)
Toutes consolidées dans `CLAUDE.md`. Pas besoin de retrouver les anciennes
conversations.

---

## 14. Références croisées

- `CLAUDE.md` — Vue d'ensemble du projet (TL;DR, architecture, conventions)
- `PLAN-V1.md` — Plan v0.4.0 (release publique vidéo)
- `AUDIT.md` — Audit historique (rev 2.2, archivé)
- `CHARTE.md` — Design system UI (couleurs, typo, composants)
- `NOTES.md` — Notes brutes à la volée
- `README.md` — User-facing (à refondre Sprint I)
- `CHANGELOG.md` — Historique des releases (section v0.5.0 à ajouter Sprint I)
- `gemini/G3MINI TR4CK3R - TORRENT API.pdf` — Doc officielle API (charger
  les IDs)
- `gemini/G3MINI TR4CK3R - RÈGLES DE NOMMAGE.pdf` — Charte naming officielle
- `gemini/G3MINI TR4CK3R - RÈGLES D'UPLOAD.pdf` — Règles générales upload
- `gemini/G3MINI TR4CK3R - RÈGLES D'UPLOAD EBOOK.pdf` — Spécifique ebooks
- `gemini/G3MINI TR4CK3R - Regle d'encodage.pdf` — Charte encodage vidéo
- `gemini/G3MINI TR4CK3R - TEAMS INTERDITES.pdf` — Liste teams bannies
  (par catégorie)
- `gemini/G3MINI TR4CK3R -FULL, REMUX, BDRIP, WEB, WEBRIP, COMMENT
  CHOISIR.pdf` — Glossaire sources vidéo

---

*Dernière mise à jour : 2026-05-22 — création initiale par Claude après
recherche parallèle (5 agents APIs + 1 agent scope code) sur la base des 7
PDFs Gemini officiels.*
*Auteur : Flox + Claude Opus 4.7 (1M context).*
