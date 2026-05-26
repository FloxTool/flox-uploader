"""Suivi d'etat d'un package d'upload.

Chaque dossier de package (`data/upload_packages/<release>/`) recoit un fichier
`package_state.json` qui suit son cycle de vie. C'est ce qui rend le pipeline
upload **idempotent** : si on relance --upload sur un package deja uploade,
il refuse poliment au lieu de double-uploader.

Cycle de vie nominal :

    PREPARED          (pipeline a fini, package complet, pas encore touche au tracker)
        |
        v  check_duplicate OK
    VALIDATED         (dedup verifie, pas de doublon, pret a uploader)
        |
        v  upload_torrent OK + download_torrent OK
    UPLOADED          (succes, ID tracker stocke, .torrent final remplace)

Branches alternatives :

    PREPARED -- doublon detecte --> ABORTED_DUPLICATE
    VALIDATED ou autre -- erreur --> FAILED
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

STATE_FILENAME = "package_state.json"


class PackageState(str, Enum):
    PREPARED = "prepared"
    VALIDATED = "validated"
    UPLOADED = "uploaded"
    ABORTED_DUPLICATE = "aborted-duplicate"
    FAILED = "failed"


# Transitions autorisees. Toute transition non listee est refusee. La logique
# vise a empecher les double-uploads et les retours en arriere accidentels.
_ALLOWED_TRANSITIONS: dict[PackageState, set[PackageState]] = {
    PackageState.PREPARED: {
        PackageState.PREPARED,           # idempotent (re-write metadata)
        PackageState.VALIDATED,
        PackageState.ABORTED_DUPLICATE,
        PackageState.FAILED,
    },
    PackageState.VALIDATED: {
        PackageState.VALIDATED,          # idempotent
        PackageState.UPLOADED,
        PackageState.ABORTED_DUPLICATE,  # un staff peut avoir upload entre-temps
        PackageState.FAILED,
        # NOTES round 7+ : user-controlled rollback. Permet au user de
        # devalider un package depuis l'UI (toggle bouton "Valider") s'il
        # change d'avis avant l'upload.
        PackageState.PREPARED,
    },
    PackageState.UPLOADED: {
        PackageState.UPLOADED,           # idempotent (re-write metadata)
        # Pas de retour en arriere : un upload reussi est terminal.
    },
    PackageState.ABORTED_DUPLICATE: {
        PackageState.ABORTED_DUPLICATE,
        PackageState.VALIDATED,          # force-upload : on bypass et re-tente
        PackageState.UPLOADED,           # force-upload reussi en une etape
        PackageState.FAILED,
    },
    PackageState.FAILED: {
        PackageState.FAILED,
        PackageState.PREPARED,           # retry depuis le debut
        PackageState.VALIDATED,          # retry direct si on sait pourquoi ca a foire
    },
}


@dataclass
class PackageStateData:
    """Contenu serialise de package_state.json.

    Tous les champs optionnels sont remplis au fur et a mesure du cycle de vie.
    """

    state: PackageState = PackageState.PREPARED
    release_name: str = ""
    tracker_key: str = ""
    created_at: str = ""           # ISO-8601 UTC
    updated_at: str = ""           # ISO-8601 UTC

    # Renseignes apres dedup check
    infohash: str = ""

    # Renseignes si doublon detecte ou upload reussi
    existing_torrent_id: int | None = None
    existing_torrent_url: str = ""

    # Renseignes apres upload reussi
    uploaded_torrent_id: int | None = None
    uploaded_torrent_url: str = ""
    uploaded_at: str = ""
    final_torrent_path: str = ""   # chemin du .torrent final (avec passkey) sur disque

    # Renseignes apres dedup check (pendant prepare en mode UI). Permet a la
    # page Queue d'afficher l'etat doublon sans re-faire l'appel API a chaque
    # affichage. Vide tant que le check n'a pas ete fait.
    dedup_confidence: str = ""           # "certain" / "very_likely" / "ambiguous" / "none"
    dedup_checked_at: str = ""           # ISO-8601 UTC du dernier check

    # Overrides utilisateur (Phase 3b.3). Definis depuis la page detail du
    # package, consommes au moment de l'upload (3b.4).
    personal_release: bool = False       # checkbox "ma propre release"
    anonymous: bool = False              # checkbox "upload anonyme"
    manual_tmdb_id: int = 0              # TMDB ID force par l'utilisateur (0 = auto)

    # Overrides champs Unit3D (F3 NOTES.md). Auto-derive depuis le release_name
    # par defaut (cf. unit3d_mapping). 0 = utiliser l'auto-detection.
    manual_category_id: int = 0          # 0=auto, 1=Movie, 2=TV
    manual_type_id: int = 0              # 0=auto, 1=full-disc, 2=remux, ...
    manual_resolution_id: int = 0        # 0=auto, 1=4320p, 2=2160p, ...

    # Lot Q : champs upload supplementaires (formulaire Gemini reel).
    # IDs externes : 0 = auto (fetched depuis TMDB external_ids quand
    # disponible) ou laisser le tracker resoudre. Override = forcer.
    manual_imdb_id: str = ""             # "tt1234567" force par l'user
    manual_tvdb_id: int = 0              # ID TheTVDB pour series (auto via TMDB)
    manual_mal_id: int = 0               # ID MyAnimeList (anime, manuel)

    # Numero saison/episode override (formulaire Gemini exige numerique).
    # 0 = utiliser l'auto-detection depuis media_info / TMDB.
    manual_season_number: int = 0
    manual_episode_number: int = 0

    # Distributeur / Region : pour Full Disc uniquement (cat=1, type=1).
    # 0 = auto (laisse vide cote tracker), >0 = ID Unit3D specifique.
    manual_distributor_id: int = 0
    manual_region_id: int = 0

    # Mots-cles : champ libre Gemini ("super-heros, dc comics, marvel").
    # Si vide, on utilise les TMDB keywords (auto-extraction).
    manual_keywords: str = ""

    # Sprint D.12 v0.5.0 - Options upload specifiques livres (cat 12).
    # manual_cover_url : URL personnalisee pour la couverture (override
    #   l'auto-extraction BnF/Google/local). Vide = utiliser cover_url
    #   du book_metadata.
    # manual_book_subtype : libelle sous-type pour la fiche tracker
    #   (roman/bd/manga/comics/audiobook/essai/manuel). Vide = auto via
    #   prefixe ISBN ou non specifie.
    manual_cover_url: str = ""
    manual_book_subtype: str = ""
    # Sprint D.40 v0.5.0 (feedback Louis) : URL banniere/headline pour la
    # fiche BBCode (en complement de la cover). Vide = pas de banner.
    manual_banner_url: str = ""

    # Renseignes en cas d'echec
    last_error: str = ""

    # Historique brut des transitions, utile pour le debug
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        d = asdict(self)
        d["state"] = self.state.value if isinstance(self.state, PackageState) else self.state
        return json.dumps(d, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "PackageStateData":
        d = json.loads(raw)
        if "state" in d and isinstance(d["state"], str):
            d["state"] = PackageState(d["state"])
        return cls(**d)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_path(package_dir: Path) -> Path:
    return package_dir / STATE_FILENAME


def read_state(package_dir: Path) -> PackageStateData | None:
    """Lit le state d'un package. Retourne None si pas encore initialise.

    Si le JSON est tronque (cas historique des writes non atomiques), on
    tente une reparation best-effort : on lit ce qui est lisible et on
    complete avec les defaults. AVANT d'overwriter le fichier reparé, on
    sauvegarde une copie `.corrupted-<timestamp>` pour permettre une
    analyse a posteriori (la regex de _try_recover_state ne preserve PAS
    `history`, donc le fichier original est la seule trace).
    """
    p = state_path(package_dir)
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8")
    try:
        return PackageStateData.from_json(raw)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        # Tentative de reparation : extraire les paires KEY:VALUE valides
        # avec une regex simple, et reconstruire un state minimal.
        recovered = _try_recover_state(raw)
        if recovered is not None:
            print(f"[WARN] package_state.json tronque dans {package_dir.name} : "
                  f"reparation auto. ({e})")
            # Sauvegarde de la version corrompue avant overwrite (l'history
            # serialisee en JSON n'est pas recuperable par notre regex).
            try:
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = p.with_suffix(p.suffix + f".corrupted-{ts}")
                backup.write_text(raw, encoding="utf-8")
            except OSError:
                pass
            try:
                # Re-ecrit le fichier pour stopper le warning a chaque lecture
                write_state(package_dir, recovered)
            except OSError:
                pass
            return recovered
        print(f"[WARN] package_state.json corrompu dans {package_dir.name} : {e}")
        return None


def _try_recover_state(raw: str) -> "PackageStateData | None":
    """Repare un package_state.json tronque en extrayant les paires
    KEY:VALUE valides via regex. Best-effort, retourne None si rien d'utile."""
    import re as _re
    fields: dict[str, Any] = {}
    # Strings
    for m in _re.finditer(r'"(\w+)"\s*:\s*"([^"\n]*)"', raw):
        fields[m.group(1)] = m.group(2)
    # Numbers (int/null)
    for m in _re.finditer(r'"(\w+)"\s*:\s*(-?\d+|null)', raw):
        v = m.group(2)
        fields[m.group(1)] = None if v == "null" else int(v)
    # Booleans
    for m in _re.finditer(r'"(\w+)"\s*:\s*(true|false)', raw):
        fields[m.group(1)] = (m.group(2) == "true")
    # Filtre aux champs connus du dataclass (sinon TypeError)
    allowed = set(PackageStateData.__dataclass_fields__.keys())
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return None
    # Convertir state si present
    if "state" in fields and isinstance(fields["state"], str):
        try:
            fields["state"] = PackageState(fields["state"])
        except ValueError:
            fields.pop("state", None)
    try:
        return PackageStateData(**fields)
    except TypeError:
        return None


def write_state(package_dir: Path, data: PackageStateData) -> None:
    """Ecrit le state sur disque de facon atomique.

    Strategie : ecrire dans un fichier .tmp puis renommer atomically.
    Cela evite les fichiers tronques en cas d interruption (crash worker,
    antivirus Windows qui bloque, etc.) qui rendaient les packages
    invisibles dans la queue.
    """
    import os as _os
    package_dir.mkdir(parents=True, exist_ok=True)
    target = state_path(package_dir)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = data.to_json()
    tmp.write_text(payload, encoding="utf-8")
    # os.replace = rename atomique cross-platform (ecrase la cible si existe)
    _os.replace(str(tmp), str(target))


def init_state(
    package_dir: Path,
    release_name: str,
    tracker_key: str,
) -> PackageStateData:
    """Cree (ou re-cree apres failure) un state PREPARED pour un package."""
    now = _now_iso()
    existing = read_state(package_dir)
    if existing is not None and existing.state in {
        PackageState.UPLOADED,
        PackageState.VALIDATED,
        PackageState.ABORTED_DUPLICATE,
    }:
        # Etat deja avance : on ne reset pas, on retourne l'existant.
        return existing

    data = PackageStateData(
        state=PackageState.PREPARED,
        release_name=release_name,
        tracker_key=tracker_key,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        history=(existing.history if existing else []) + [
            {"at": now, "to": PackageState.PREPARED.value, "note": "init"}
        ],
    )
    write_state(package_dir, data)
    return data


def transition(
    package_dir: Path,
    new_state: PackageState,
    note: str = "",
    **field_updates: Any,
) -> PackageStateData:
    """Transitionne un package vers un nouvel etat. Leve ValueError si interdit.

    `field_updates` permet de mettre a jour les champs en meme temps (ex:
    `existing_torrent_id=42` lors d'une transition vers ABORTED_DUPLICATE).
    """
    current = read_state(package_dir)
    if current is None:
        raise ValueError(
            f"Package {package_dir.name} : aucun state initial. "
            "Appeler init_state() d'abord."
        )

    allowed = _ALLOWED_TRANSITIONS.get(current.state, set())
    if new_state not in allowed:
        raise ValueError(
            f"Transition interdite : {current.state.value} -> {new_state.value} "
            f"(autorisees : {sorted(s.value for s in allowed)})"
        )

    now = _now_iso()
    current.state = new_state
    current.updated_at = now
    for k, v in field_updates.items():
        if not hasattr(current, k):
            raise AttributeError(f"PackageStateData n'a pas de champ '{k}'")
        setattr(current, k, v)
    current.history.append({
        "at": now,
        "to": new_state.value,
        "note": note,
        **{f"set_{k}": v for k, v in field_updates.items()},
    })
    write_state(package_dir, current)
    return current
