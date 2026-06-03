"""Signaux de fallback emis pendant la construction du release_name.

Chaque fois que le pipeline doit faire une approximation (TMDB raccourci,
langue inferee depuis le NFO faute de mieux, resolution inferee depuis
MediaInfo, etc.), on emet un signal structure dans `debug.json` sous la
clef `naming_signals` (un dict).

Ces signaux servent ensuite a :
- afficher un panneau "Fallbacks utilises" sur la page detail du package
- ponderer le score de confiance (cf. core/confidence.py) avec des
  penalites douces (1-5 pts) sans tomber dans la classe "review" pour
  autant : un signal isole = score 95+, plusieurs signaux = score 80-89.

Convention :
- chaque signal a une CLEF stable (constante string) pour eviter les typos
- chaque signal a une PENALITE numerique (lue par confidence.py)
- chaque signal a un LABEL humain (affiche dans la UI)
- la VALEUR du signal dans debug est :
    * `True` (signal binaire : "ce fallback a ete utilise")
    * un int (signal compteur : "N mots droppes lors de la recherche TMDB")
    * un dict (signal riche : details supplementaires)

Pour ajouter un nouveau signal :
1. Ajouter une constante NAMING_SIG_* ici avec son label + penalite
2. Emettre le signal depuis le pipeline via `emit_signal(debug, key, value)`
3. confidence.py l'integrera automatiquement dans le score
"""
from __future__ import annotations

from .debug import Debug


# ============================================================
# CLEFS DE SIGNAUX (constantes stables)
# ============================================================

# --- TMDB ---
SIG_TMDB_QUERY_SHORTENED = "tmdb_query_shortened"
"""La recherche TMDB a reussi apres avoir raccourci le titre (drop de N mots).
Valeur : int (nombre de mots droppes, >= 1)."""

SIG_TMDB_LANG_FALLBACK = "tmdb_lang_fallback"
"""La recherche en-US a echoue, on est passe en fr-FR. Valeur : True."""

SIG_TMDB_TITLE_EN_FALLBACK = "tmdb_title_en_fallback"
"""Le titre original est en non-latin (jp/ko/zh/ru/...), on a fetch et utilise
le titre EN. Valeur : True."""

SIG_TMDB_TITLE_FR_FALLBACK = "tmdb_title_fr_fallback"
"""Pas de title_en disponible, fallback sur le titre FR. Valeur : True."""

SIG_TMDB_DETAILS_FAILED = "tmdb_details_failed"
"""Lot O.7 : la recherche TMDB a trouve le bon film mais le fetch des
details (/movie/{id}) a echoue (502/503 transient). On a construit une
fiche minimale a partir du resultat de search — release_name OK mais
BBCode incomplete (pas de cast/synopsis/imdb_id). Valeur : True."""

# --- Langue / NFO ---
SIG_LANG_INFERRED_FROM_NFO = "lang_inferred_from_nfo"
"""Aucun tag langue dans le nom, on a infere depuis le NFO+MediaInfo
(ex: VFF -> MULTi.VFF si non-FR detecte). Valeur : True."""

SIG_LANG_DEFAULT_VFF_USED = "lang_default_vff_used"
"""Le NFO ne distingue pas VFF/VFQ/VFB, on a applique VFF par defaut.
Valeur : True."""

SIG_LANG_VFI_TO_VFF = "lang_vfi_to_vff"
"""Le NFO indiquait explicitement VFi (interdit par la charte Gemini).
On l'a traduit en VFF (regle replace_tokens). C'est une certitude
forte issue d'un signal explicite, pas une approximation par defaut.
Valeur : True."""

# --- MediaInfo ---
SIG_RESOLUTION_INFERRED = "resolution_inferred"
"""Resolution absente du nom, recuperee depuis MediaInfo. Valeur : True."""

# --- Team ---
SIG_TEAM_DEFAULT_USED = "team_default_used"
"""Aucune team detectee dans le nom, fallback sur tracker.default_team
(NoTAG). Valeur : True."""

# --- Source ---
SIG_FOLDER_NAME_MINIMAL_FALLBACK = "folder_name_minimal_fallback"
"""Le nom du dossier source etait minimaliste (pas de tags scene), on est
passe au nom du 1er fichier video. Valeur : True."""

SIG_DROPPED_UNKNOWN_TOKENS = "dropped_unknown_tokens"
"""Des tokens inconnus apres l'annee ont ete jetes (Bluray-1080p, Criterion,
etc.). Valeur : list[str] des tokens jetes."""

# --- Overrides utilisateur (cf. NOTES.md : trust badge) ---
# Ces signaux ne sont PAS des bugs, juste un signal "intervention humaine"
# qui indique au futur visiteur du package que le release auto n'aurait pas
# tout matche tout seul. Pondere legerement le score (vrai 100 vs presque 100).

SIG_USER_FORCE_FR_USED = "user_force_fr_used"
"""L'utilisateur a force la variante FR via --force-fr ou la radio UI.
Indique que le naming initial n'etait pas suffisant pour determiner la
variante de doublage. Valeur : str (la variante choisie : VFF/VFQ/VFB/VF2/VOF/VOQ/VOB)."""

SIG_USER_MANUAL_TMDB_ID = "user_manual_tmdb_id"
"""L'utilisateur a force un TMDB ID specifique (manual_tmdb_id ou
--tmdb-id-hint). Indique que le matching TMDB automatique aurait selectionne
le mauvais titre. Valeur : int (l'ID force)."""

SIG_USER_MANUAL_RELEASE_NAME = "user_manual_release_name"
"""L'utilisateur a tape le release_name a la main (override total du
pipeline naming). Indique le plus haut niveau d'intervention humaine.
Valeur : True."""

# --- Donnees externes manquantes ---

SIG_OMDB_DATA_MISSING = "omdb_data_missing"
"""OMDb n'a pas retourne de note IMDb / recompenses (cle absente, IMDb ID
manquant, ou rate limit). La fiche BBCode sera moins riche (pas d'etoiles
IMDb, pas de bandeau awards). Valeur : True."""

SIG_YEAR_MISSING = "year_missing"
"""Annee absente du nom du fichier ET TMDB n'a pas trouve de candidat.
Cas typique : "Cours Lola Cours (Lola rennt).mkv" — pas d'annee dans le
nom, et TMDB rejette le candidat 104 faute de signal de pertinence
(notamment l'annee). Le release_name sortira sans annee (non conforme
charte) mais le package est cree quand meme pour permettre a l'user de
override le TMDB ID via la page detail et re-preparer. Sprint 8 hotfix v7."""

# --- Categorie (Lot N.4) ---

SIG_CATEGORY_LOW_CONFIDENCE = "category_low_confidence"
"""La categorie a ete devinee 'par defaut' (Films/Series) faute de signal :
TMDB n'a pas matche, et aucun keyword sport n'a ete trouve dans le release.
Indique au user que la cat envoyee au tracker pourrait etre fausse pour
un docu / anime / sport / emission TV — verifier et override si besoin.
Valeur : True."""


# --- Compliance ---

# --- Imgbb / host externe ---

SIG_SOURCE_MISSING = "source_missing"
"""Sprint D.48 v0.5.0 (feedback Louis batch upload) : la SOURCE
(BluRay/WEB-DL/WEBRip/HDTV/...) est absente du release_name. La charte
Gemini l'exige (Titre.Annee.LANG.RES.SOURCE.AUDIO.VCODEC-TEAM).
Penalite moderee (-5) + suggestion d'utiliser le champ 'Source forcee'
dans Re-preparer. Cas typique : releases amateurs FR sans NFO scene
ni source dans le nom d'origine (Hibernatus, La Guerre Des Boutons,
Polisse-NoTAG, etc.). Valeur : True."""


SIG_IMGBB_RATE_LIMITED = "imgbb_rate_limited"
"""Sprint D.41 v0.5.0 (feedback Louis) : imgbb a refuse une ou plusieurs
images (cover/previews) avec un message 'Rate limit reached' (HTTP 400/429).
La fiche BBCode est incomplete : il manque les visuels en attendant que la
limite imgbb se reset (~1h). Penalite moderee (-5) + suggestion de
re-preparer plus tard affichee dans l'UI. Valeur : True."""


SIG_COMPLIANCE_WARNS = "compliance_warns"
"""Le check de conformite (NFO vs release_name) a leve un ou plusieurs WARN
non-bloquants. Differents des compliance ERROR (penalites dures -15 pts/issue).
Valeur : list[str] des messages des WARN (ex: ['Piste audio principale est
DDP mais aucun alias trouve dans le nom', 'MediaInfo detecte HDR10 mais aucun
tag HDR dans le nom']). Penalite : -1/warn cape a 5. Ancien nom :
SIG_COMPLIANCE_WARN_PRESENT (compteur)."""

# Alias deprecate pour retro-compatibilite cache TMDB / debug.json existants.
SIG_COMPLIANCE_WARN_PRESENT = SIG_COMPLIANCE_WARNS


# ============================================================
# METADATA : labels humains + penalites par signal
# ============================================================

# Mapping centralise : signal -> (penalite, label humain).
# La penalite est appliquee une seule fois (signaux binaires) OU multipliee
# par la valeur (signaux compteurs ou listes : penalite par item).
SIGNAL_METADATA: dict[str, tuple[int, str]] = {
    # TMDB
    SIG_TMDB_QUERY_SHORTENED:    (2, "Titre raccourci de {n} mot(s) pour trouver une correspondance TMDB"),
    SIG_TMDB_LANG_FALLBACK:      (3, "Match TMDB trouvé en français (la recherche en anglais n'a rien donné)"),
    SIG_TMDB_TITLE_EN_FALLBACK:  (2, "Titre anglais utilisé (l'original est en caractères non-latins)"),
    SIG_TMDB_TITLE_FR_FALLBACK:  (3, "Titre français utilisé (le titre anglais n'est pas disponible sur TMDB)"),
    # Lot O.7 : penalite moderee 5 pts (vs -25 si on avait abandonne complet).
    # Le user voit clairement que TMDB est OK mais que les details ont rate
    # — invitation a re-preparer plus tard pour avoir une fiche complete.
    SIG_TMDB_DETAILS_FAILED:     (5, "TMDB indisponible momentanément — fiche minimale (pas de cast/synopsis/IMDb). Re-prépare plus tard pour récupérer les détails complets."),
    # Langue
    SIG_LANG_INFERRED_FROM_NFO:  (3, "Tag de langue ajouté automatiquement (le nom du fichier ne le contenait pas)"),
    SIG_LANG_DEFAULT_VFF_USED:   (2, "Variante VFF appliquée par défaut (le NFO ne distinguait pas VFF/VFQ/VFB)"),
    # VFi -> VFF : signal informatif (penalite 1 = bleu "pas grave" pour
    # rester visible dans le panneau Detail du score). Le NFO indique
    # explicitement VFi, on a juste applique la regle de traduction
    # (charte Gemini interdit VFi) — pas une approximation par defaut.
    SIG_LANG_VFI_TO_VFF:         (1, "Tag VFi détecté dans le NFO → traduit en VFF (la charte Gemini interdit VFi)"),
    # MediaInfo
    SIG_RESOLUTION_INFERRED:     (2, "Résolution récupérée depuis MediaInfo (absente du nom du fichier)"),
    # Team
    SIG_TEAM_DEFAULT_USED:       (2, "Aucune team détectée — 'NoTAG' utilisé par défaut"),
    # Source
    SIG_FOLDER_NAME_MINIMAL_FALLBACK: (1, "Nom du dossier minimaliste — utilisation du nom du 1er fichier vidéo à la place"),
    SIG_DROPPED_UNKNOWN_TOKENS:  (1, "Token non reconnu et ignoré : {item}"),
    # Overrides utilisateur (intervention humaine, signal pas un bug)
    SIG_USER_FORCE_FR_USED:      (2, "Variante FR forcée manuellement : {n}"),
    SIG_USER_MANUAL_TMDB_ID:     (2, "TMDB ID forcé manuellement (ID {n})"),
    SIG_USER_MANUAL_RELEASE_NAME: (3, "Nom de release saisi à la main (pipeline auto bypass)"),
    # Données externes
    SIG_OMDB_DATA_MISSING:       (1, "Pas de note IMDb / récompenses (OMDb non disponible)"),
    # Sprint 8 hotfix v7 : annee manquante = bloquant pour charte Gemini mais
    # on ne plante plus le pipeline. Penalite forte (-20) pour signaler clairement
    # qu'il faut override TMDB / corriger.
    SIG_YEAR_MISSING:            (20, "Année manquante (ni dans le nom ni dans TMDB) — override TMDB ID requis pour conformité charte Gemini"),
    # Catégorie incertaine (Lot N.4) : -1 pt, juste un nudge pour aller vérifier.
    SIG_CATEGORY_LOW_CONFIDENCE: (1, "Catégorie devinée par défaut (TMDB sans match) — vérifie si c'est un docu, anime, sport ou émission TV avant l'upload"),
    # Sprint D.41 v0.5.0 (feedback Louis) : imgbb rate-limited. -5 pour
    # signaler clairement que la fiche est incomplete et qu'il faut
    # re-preparer plus tard pour recuperer les visuels manquants.
    SIG_IMGBB_RATE_LIMITED:      (5, "imgbb a atteint sa limite de débit — la fiche manque cover/previews. Re-prépare dans 1h pour compléter les visuels."),
    # Sprint D.48 v0.5.0 (feedback Louis batch upload) : SOURCE manquante.
    # Charte Gemini exige BluRay/WEB-DL/WEBRip/HDTV/... dans le release_name.
    SIG_SOURCE_MISSING:          (5, "Source manquante dans le release_name (BluRay/WEB-DL/...) — non conforme à la charte Gemini. Force-la via 'Source forcée' dans Re-préparer."),
    # Compliance : DEPRECATED depuis NOTES round 6. La penalite est passee
    # a 0 pour eliminer le double-comptage avec confidence.py qui traite
    # deja les WARN via le pattern is_warn_minor (-4 pour PGS-only). Source
    # canonique = compliance_issues[]. Le signal n'est plus emis par
    # pipeline.py mais on garde l'entree avec penalite=0 pour ne pas casser
    # les debug.json existants qui peuvent encore le contenir.
    SIG_COMPLIANCE_WARNS: (0, "Conformité (non-bloquant) : {item}"),
}


# Counter signals (multiplicatifs) : penalite = (valeur du signal) * unit_penalty.
# Les autres signaux sont binaires : penalite appliquee une fois si present.
COUNTER_SIGNALS = {SIG_TMDB_QUERY_SHORTENED}
LIST_SIGNALS = {SIG_DROPPED_UNKNOWN_TOKENS, SIG_COMPLIANCE_WARNS}

# Signaux dont le label utilise {n} pour afficher la valeur brute (pas un
# multiplicateur de penalite). Pour SIG_USER_FORCE_FR_USED par exemple,
# value = "VFF" -> label "Variante FR forcée manuellement : VFF".
VALUE_LABEL_SIGNALS = {
    SIG_USER_FORCE_FR_USED,
    SIG_USER_MANUAL_TMDB_ID,
}


# ============================================================
# HELPERS D'EMISSION
# ============================================================

def emit_signal(debug: Debug, key: str, value=True) -> None:
    """Emet un signal de fallback dans `debug.naming_signals`.

    Cree la cle naming_signals si absente, puis stocke value sous `key`.

    `value` peut etre :
    - True (defaut) : signal binaire
    - un int : signal compteur (ex: nombre de mots droppes)
    - une liste : signal liste (ex: tokens droppes)

    Si le signal existe deja, on ne l'ecrase PAS sauf si la nouvelle valeur
    est strictement plus "forte" (plus grand int, liste plus longue) - utile
    pour les boucles qui retentent.
    """
    sigs = debug.data.get("naming_signals") or {}
    if key in sigs:
        existing = sigs[key]
        # Comparaison int : on garde le max
        if isinstance(existing, int) and isinstance(value, int):
            value = max(existing, value)
        # Listes : merge sans doublons en preservant l'ordre
        elif isinstance(existing, list) and isinstance(value, list):
            seen = set(existing)
            merged = list(existing)
            for v in value:
                if v not in seen:
                    merged.append(v)
                    seen.add(v)
            value = merged
        # Sinon : on ecrase
    sigs[key] = value
    debug.set("naming_signals", sigs)


def get_signals(debug_dict: dict) -> dict:
    """Lit les signaux depuis un dict debug (ex: contenu de debug.json).
    Retourne un dict vide si la clef n'existe pas."""
    sigs = debug_dict.get("naming_signals") or {}
    return sigs if isinstance(sigs, dict) else {}


def compute_signal_penalty(signal_key: str, value) -> int:
    """Calcule la penalite a appliquer pour un signal donne.

    - Signaux compteurs (COUNTER_SIGNALS) : penalite * value (capee a 10)
    - Signaux liste (LIST_SIGNALS) : penalite * len(value) (capee a 10)
    - Autres : penalite si value est truthy
    """
    meta = SIGNAL_METADATA.get(signal_key)
    if not meta:
        return 0
    unit_penalty, _label = meta
    if signal_key in COUNTER_SIGNALS:
        n = int(value) if isinstance(value, (int, float)) else 0
        return min(unit_penalty * n, 10)
    if signal_key in LIST_SIGNALS:
        n = len(value) if isinstance(value, list) else 0
        return min(unit_penalty * n, 10)
    return unit_penalty if value else 0


def render_signal_label(signal_key: str, value) -> str:
    """Construit le label humain pour un signal (template + valeur).

    Lot R-D : pour SIG_DROPPED_UNKNOWN_TOKENS specifiquement, on regroupe
    tous les items dans un seul label `Token non reconnu : X, Y, Z` au
    lieu de N labels separes (qui produisaient des lignes redondantes
    "Token non reconnu : X / Token non reconnu : Y / ..." dans le panneau).
    """
    meta = SIGNAL_METADATA.get(signal_key)
    if not meta:
        return signal_key
    _penalty, template = meta
    if signal_key in COUNTER_SIGNALS and isinstance(value, int):
        return template.replace("{n}", str(value))
    if signal_key in LIST_SIGNALS and isinstance(value, list):
        if signal_key == SIG_DROPPED_UNKNOWN_TOKENS:
            # Regroupement : "Token non reconnu : X, Y, Z" (Lot R-D)
            joined = ", ".join(str(item) for item in value)
            return template.replace("{item}", joined).replace(
                "Token non reconnu et ignoré", "Tokens non reconnus"
            ) if len(value) > 1 else template.replace("{item}", str(value[0]))
        # Pour les autres listes : on retourne UN label par item
        return ", ".join(
            template.replace("{item}", str(item)) for item in value
        )
    if signal_key in VALUE_LABEL_SIGNALS:
        # La valeur (str ou int) est juste rendue dans le {n}
        return template.replace("{n}", str(value))
    return template
