"""Phase 3c : Config UI.

Definit le schema des variables editables depuis l'UI web, et les helpers
read_env_values / write_env_values qui preservent les commentaires existants
du `.env` quand on l'overwrite.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .. import config as _config


# ============================================================
# SCHEMA
# ============================================================


@dataclass
class ConfigField:
    """Une variable editable depuis l'UI."""

    key: str                # Nom de la variable d'env (TRACKER_API_URL, ...)
    label: str              # Libelle UI court
    section: str            # Regroupement : "Tracker", "TMDB", "Inbox", "Prepare"
    kind: str = "text"      # "text" / "password" / "url" / "path" / "bool" / "textarea"
    placeholder: str = ""
    description: str = ""   # Hint sous le champ
    default: str = ""       # Valeur par defaut si rien dans .env

    @property
    def is_secret(self) -> bool:
        return self.kind == "password"


# Liste deterministe = ordre d'affichage dans l'UI.
# Si tu ajoutes une cle ici, elle apparait dans la page Config.
SCHEMA: list[ConfigField] = [
    # --- Tracker Gemini ---
    ConfigField(
        key="TRACKER_API_URL",
        label="URL de l'API",
        section="Tracker (Gemini)",
        kind="url",
        placeholder="https://gemini-tracker.org/api",
        description="Endpoint racine de l'API Unit3D du tracker.",
    ),
    ConfigField(
        key="TRACKER_API_KEY",
        label="Cle API",
        section="Tracker (Gemini)",
        kind="password",
        placeholder="••••••••••••••••",
        description="Cle Bearer obtenue depuis ton profil sur le tracker.",
    ),
    ConfigField(
        key="TRACKER_ANNOUNCE",
        label="URL announce (avec passkey)",
        section="Tracker (Gemini)",
        kind="password",
        placeholder="https://tracker.example.com/announce/<passkey>",
        description="URL announce personnelle utilisee dans les .torrent generes.",
    ),
    # --- TMDB / OMDb ---
    ConfigField(
        key="TMDB_API_KEY",
        label="Cle API TMDB",
        section="Metadonnees (TMDB / OMDb)",
        kind="password",
        placeholder="••••••••••••••••",
        description="API v3 (https://www.themoviedb.org/settings/api). Necessaire pour les fiches.",
    ),
    ConfigField(
        key="OMDB_API_KEY",
        label="Cle API OMDb",
        section="Metadonnees (TMDB / OMDb)",
        kind="password",
        placeholder="••••••••",
        description="Optionnel : recupere note IMDb + recompenses (https://www.omdbapi.com).",
    ),
    # --- Inbox / browse ---
    ConfigField(
        key="BROWSE_ROOT",
        label="Dossier racine par defaut",
        section="Inbox",
        kind="path",
        placeholder="C:\\\\Films",
        description="Dossier ouvert par defaut quand tu vas sur /inbox.",
    ),
    ConfigField(
        key="BROWSE_ROOTS",
        label="Favoris (separes par ;)",
        section="Inbox",
        kind="text",
        placeholder=r"X:\Films;Y:\Series;Z:\Sonarr",
        description="Affiches en haut de l'inbox comme raccourcis.",
    ),
    # --- Preparation ---
    # NOTES round 7 : APPEND_FR_TITLE_TO_RELEASE_NAME retire de l'UI
    # (option peu utilisee, le user voulait epurer). L'env var continue
    # de fonctionner si elle est dans le .env directement, mais elle
    # n'apparait plus dans /config.
    ConfigField(
        key="FLOX_UPLOADER_DATA_DIR",
        label="Dossier de donnees",
        section="Preparation",
        kind="path",
        placeholder="C:\\\\trackup\\\\data",
        description="Override du dossier data/ par defaut. Vide = projet/data.",
    ),
    ConfigField(
        key="TORRENT_FINAL_DIR",
        label="Dossier de destination des .torrent uploades",
        section="Preparation",
        kind="path",
        placeholder=r"C:\qBittorrent\watched ou D:\seedbox\torrents",
        description=(
            "Apres un upload reussi, le .torrent final (avec passkey) est "
            "automatiquement COPIE dans ce dossier en plus d'etre garde "
            "dans le package_dir. Pratique pour pointer vers le watch folder "
            "de qBittorrent / Transmission qui lance automatiquement le "
            "seed. Vide = pas de copie (.torrent reste seulement dans le "
            "package_dir)."
        ),
    ),
    # --- Conformite Gemini (charte tracker) ---
    ConfigField(
        key="BANNED_TEAMS",
        label="Teams interdites supplementaires",
        section="Conformite Gemini",
        kind="textarea",
        placeholder="ExempleTeam1, ExempleTeam2",
        description=(
            "Liste de teams supplementaires a bloquer (en plus des defauts "
            "k0RE / Slay3R). Separateurs : virgule, point-virgule ou retour "
            "ligne. Si une release porte une team de cette liste, l'upload "
            "est refuse et le package marque en echec. "
            "Mets a jour cette liste quand le tracker en publie une nouvelle."
        ),
    ),
]


def schema_grouped() -> list[tuple[str, list[ConfigField]]]:
    """Retourne le schema regroupe par section, dans l'ordre d'apparition."""
    seen: list[str] = []
    by_section: dict[str, list[ConfigField]] = {}
    for f in SCHEMA:
        if f.section not in seen:
            seen.append(f.section)
            by_section[f.section] = []
        by_section[f.section].append(f)
    return [(s, by_section[s]) for s in seen]


# ============================================================
# READ / WRITE .env
# ============================================================

# Sentinel utilise pour signifier "ne change pas le secret existant".
SECRET_PLACEHOLDER = "***"


def read_env_values() -> dict[str, str]:
    """Lit toutes les valeurs courantes du .env (ou os.environ pour les
    variables non listees dans le .env). Resultat : {key: value} pour
    chaque cle du schema."""
    file_values = _read_env_file()
    out: dict[str, str] = {}
    for f in SCHEMA:
        # Priorite : valeur courante de os.environ (au cas ou le .env est
        # outdated par rapport a un override CLI). Sinon valeur du .env.
        v = os.environ.get(f.key, file_values.get(f.key, f.default))
        out[f.key] = v
    return out


def _read_env_file() -> dict[str, str]:
    """Parse simple du .env : KEY=VALUE par ligne, ignore les commentaires."""
    p = _config.env_file()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, value = s.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def write_env_values(updates: dict[str, str]) -> None:
    """Re-ecrit le .env en appliquant `updates` (cles sans changement
    conservees, commentaires existants preserves quand possible).

    Strategie :
    1. On lit le contenu existant ligne par ligne.
    2. Pour chaque ligne KEY=..., si KEY est dans updates -> on remplace.
    3. Les cles de updates qui n'existaient pas sont ajoutees a la fin.
    4. Commentaires et lignes vides preserves.
    """
    p = _config.env_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    if p.exists():
        existing_lines = p.read_text(encoding="utf-8").splitlines()

    seen_keys: set[str] = set()
    new_lines: list[str] = []
    for raw in existing_lines:
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            v = updates[key]
            seen_keys.add(key)
            # Valeur vide -> on supprime carrement la ligne (sinon python-dotenv
            # va lire `KEY=` et SET la variable a "" dans os.environ, ce qui
            # est different de "non defini" pour data_dir() etc.)
            if v == "":
                continue
            new_lines.append(_format_env_line(key, v))
        else:
            new_lines.append(line)

    # Cles ajoutees pour la 1ere fois -> en fin de fichier
    appended_any = False
    for key, v in updates.items():
        if key in seen_keys or v == "":
            continue
        if not appended_any:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("# --- Ajoute via UI ---")
            appended_any = True
        new_lines.append(_format_env_line(key, v))

    p.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


_NEEDS_QUOTE = re.compile(r"[\s#]")


def _format_env_line(key: str, value: str) -> str:
    """Format KEY=VALUE. Quote si la valeur contient des espaces ou des `#`."""
    v = value.strip()
    if _NEEDS_QUOTE.search(v):
        # Echappe les guillemets dans la valeur
        v = v.replace('"', '\\"')
        return f'{key}="{v}"'
    return f"{key}={v}"


# ============================================================
# Apply (mute os.environ + reload from disk pour la prochaine lecture)
# ============================================================


def apply_updates(updates: dict[str, str]) -> None:
    """Apres un write_env_values, met a jour os.environ pour que le worker
    actuel voit les nouvelles valeurs sans avoir a redemarrer."""
    for key, v in updates.items():
        if v == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = v


# ============================================================
# Validation
# ============================================================


def validate_updates(payload: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Filtre + valide un payload utilisateur.

    - Rejet : cles inconnues (pas dans SCHEMA).
    - Secrets : si la valeur recue == SECRET_PLACEHOLDER, on garde l'existant
      (= on ne touche PAS a cette cle).
    - Booleens : normalises en "0" ou "1".
    Retourne (updates_a_appliquer, list_d_erreurs).
    """
    schema_by_key = {f.key: f for f in SCHEMA}
    current = read_env_values()
    out: dict[str, str] = {}
    errors: list[str] = []
    for key, raw in (payload or {}).items():
        if key not in schema_by_key:
            errors.append(f"Cle inconnue : {key}")
            continue
        field = schema_by_key[key]
        v = (raw if raw is not None else "").strip() if isinstance(raw, str) else str(raw)
        # Secrets : SECRET_PLACEHOLDER -> on garde l'existant
        if field.is_secret and v == SECRET_PLACEHOLDER:
            continue  # ne PAS inclure dans updates
        if field.kind == "bool":
            v = "1" if v.lower() in ("1", "true", "yes", "on") else "0"
        # URL basique
        if field.kind == "url" and v and not (v.startswith("http://") or v.startswith("https://")):
            errors.append(f"{key} doit commencer par http:// ou https://")
            continue
        # Path : rejeter les chemins relatifs suspects (`, .., chemins courts)
        # qui font silencieusement pointer vers un dossier different selon le
        # cwd du serveur. Vide = OK (fallback sur le defaut projet).
        if field.kind == "path" and v:
            if v in (".", "..", "./", ".\\"):
                errors.append(f"{key} : '{v}' est un chemin relatif suspect. "
                              "Laisse le champ VIDE pour utiliser le defaut, "
                              "ou saisis un chemin absolu (ex: C:\\trackup\\data).")
                continue
            # Sur Windows : on attend un drive (C:\...) ou un UNC (\\server\...)
            # Sur Linux/Mac : un / au debut.
            if not (v.startswith("/") or v.startswith("\\\\")
                    or (len(v) >= 2 and v[1] == ":")):
                errors.append(f"{key} : '{v}' n'a pas l'air absolu. "
                              "Laisse vide ou saisis un chemin absolu.")
                continue
        out[key] = v
    return out, errors
