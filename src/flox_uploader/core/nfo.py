"""Génération de NFO (MediaInfo) et extraction d'infos langue depuis le NFO."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import die


def _resolve_mediainfo_bin() -> str:
    """Resout le chemin du binaire MediaInfo selon le contexte.

    Priorite :
    1. Override explicite via la var d'env `MEDIAINFO_BIN` (dev / debug).
    2. Bundle PyInstaller : `sys._MEIPASS/mediainfo/MediaInfo.exe`.
    3. A cote de l'executable principal (standalone Windows hors PyInstaller).
    4. PATH systeme via `shutil.which("mediainfo")` (mode dev / Docker).

    Retourne `"mediainfo"` en dernier recours pour laisser un message d'erreur
    coherent quand MediaInfo n'est pas du tout installe (le subprocess plantera
    avec FileNotFoundError mais avec une erreur lisible plutot qu'un mystere).
    """
    override = os.getenv("MEDIAINFO_BIN", "").strip()
    if override:
        return override

    exe_name = "MediaInfo.exe" if os.name == "nt" else "mediainfo"

    # Bundle PyInstaller
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "mediainfo" / exe_name
        if candidate.is_file():
            return str(candidate)

    # A cote de sys.executable (standalone non-PyInstaller, ou tray app)
    if getattr(sys, "frozen", False):
        sibling = Path(sys.executable).parent / exe_name
        if sibling.is_file():
            return str(sibling)
        # Et un sous-dossier dedie
        sibling = Path(sys.executable).parent / "mediainfo" / exe_name
        if sibling.is_file():
            return str(sibling)

    # PATH systeme
    found = shutil.which("mediainfo") or shutil.which("MediaInfo")
    if found:
        return found

    return "mediainfo"


# Resolu une fois a l'import : chaque appel subprocess utilise le binaire decide
# au demarrage. On peut forcer une re-resolution via _resolve_mediainfo_bin()
# si besoin (ex: tests).
MEDIAINFO_BIN = _resolve_mediainfo_bin()

# R4 (audit AUDIT_2026-07-19) : timeout des appels MediaInfo sur un fichier
# (protege le worker mono-thread d'un fichier reseau/verrouille qui bloque).
# Configurable via env pour les tres gros fichiers sur stockage lent.
try:
    MEDIAINFO_TIMEOUT_S = int(os.getenv("FLOX_MEDIAINFO_TIMEOUT_S", "300"))
except ValueError:
    MEDIAINFO_TIMEOUT_S = 300


def check_mediainfo_available() -> tuple[bool, str]:
    """Health check : appelle `mediainfo --Version` et retourne (ok, info).

    Utile au boot du serveur web pour afficher une erreur claire si le
    binaire est introuvable, plutot que de planter au premier upload avec
    un FileNotFoundError cryptique.

    Retourne :
      (True, "MediaInfoLib v25.04") en cas de succes
      (False, "<message d'erreur>") si introuvable / probleme
    """
    try:
        result = subprocess.run(
            [MEDIAINFO_BIN, "--Version"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return False, (
            f"Binaire MediaInfo introuvable (cherche : {MEDIAINFO_BIN}). "
            "Telecharger sur https://mediaarea.net/MediaInfo/Download "
            "et le placer dans le PATH, ou definir MEDIAINFO_BIN."
        )
    except subprocess.TimeoutExpired:
        return False, f"MediaInfo a timeout sur --Version ({MEDIAINFO_BIN})."
    except OSError as e:
        return False, f"Erreur OS en lancant {MEDIAINFO_BIN} : {e}"

    if result.returncode != 0:
        return False, (
            f"MediaInfo a retourne le code {result.returncode}. "
            f"stderr : {(result.stderr or '').strip()[:200]}"
        )
    # MediaInfo --Version ecrit sur stdout, parfois sur stderr selon versions
    info = (result.stdout or result.stderr or "").strip().splitlines()
    return True, info[0] if info else "MediaInfo OK (version inconnue)"


def find_companion_nfo(torrent_target: Path, reference_video: Path) -> Path | None:
    """Cherche le .nfo scene fourni avec la release.

    Cas couverts :
    - torrent_target est un DOSSIER (release scene complete) : on prend
      le premier .nfo trouve au top-level du dossier (pas de recursion).

    Cas explicitement NON couverts :
    - torrent_target est un FICHIER (.mkv standalone) : on NE detecte PAS
      automatiquement le .nfo frere. C'est un choix delibere : la grande
      majorite des seeders ne partagent que le .mkv, donc inclure un .nfo
      automatiquement casserait le cross-seed. L'utilisateur doit
      explicitement passer le .nfo via --companion-nfo (CLI prepare) ou en
      ajoutant les deux fichiers dans input_list (batch group la paire).

    Retourne None si aucun NFO scene n'est trouve.
    """
    if torrent_target.is_dir():
        for child in sorted(torrent_target.iterdir()):
            if child.is_file() and child.suffix.lower() == ".nfo":
                return child
        return None

    # mkv standalone : pas d'auto-detection, le .nfo doit etre passe explicitement
    return None


def generate_nfo(video_path: Path, output_nfo: Path) -> None:
    print("[INFO] Génération du .nfo...")

    if not video_path.exists():
        die(f"Fichier vidéo introuvable pour MediaInfo : {video_path}")

    # R4 (audit AUDIT_2026-07-19) : timeout obligatoire. Sans lui, un fichier
    # sur un partage reseau devenu injoignable ou verrouille par l'antivirus
    # fait bloquer MediaInfo indefiniment -> le job « preparing » ne rend
    # jamais la main -> tout le batch (worker mono-thread) est gele.
    try:
        result = subprocess.run(
            [MEDIAINFO_BIN, "--Output=TEXT", str(video_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MEDIAINFO_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        die(
            f"MediaInfo a depasse le timeout de {MEDIAINFO_TIMEOUT_S}s sur "
            f"{video_path}. Fichier sur un partage reseau injoignable, "
            "verrouille (antivirus), ou corrompu ?"
        )
        return
    if result.returncode != 0:
        die(
            f"MediaInfo a échoué (code {result.returncode}) : "
            f"{result.stderr or 'pas de détail'}"
        )

    nfo_content = result.stdout.strip()
    if not nfo_content:
        die(
            f"MediaInfo a retourné un résultat vide pour : {video_path}\n"
            f"  Causes possibles :\n"
            f"  - Le fichier est sur un chemin réseau inaccessible depuis ce contexte\n"
            f"  - Le fichier est verrouillé par un autre programme\n"
            f"  - Le fichier est corrompu ou de taille 0\n"
            f"  Vérifier que le fichier est lisible : mediainfo \"{video_path}\""
        )

    output_nfo.write_text(nfo_content + "\n", encoding="utf-8")
    print(f"[OK] NFO créé : {output_nfo} ({len(nfo_content)} caractères)")


def infer_french_variant_from_nfo(nfo_text: str) -> dict:
    """Analyse les pistes audio/sous-titres du NFO pour deviner la variante FR.

    Retourne :
    - variant : VFF | VFQ | VFB | VF2 | None
    - found_variants : variantes détectées dans les pistes
    - audio_titles : titres bruts des pistes audio (debug)
    - has_french_audio / has_french_subtitle / is_vostfr : flags
    """
    variants: set[str] = set()
    audio_titles: list[str] = []
    has_french_audio = False
    has_french_subtitle = False
    has_any_audio = False
    vfi_detected = False  # VFi explicite dans le NFO -> traduit en VFF (label specifique)

    # Séparation en blocs par type de piste (Audio / Text)
    blocks = re.split(r"\n(?=(?:Audio|Text)\b)", nfo_text, flags=re.IGNORECASE)

    for block in blocks:
        is_audio = bool(re.match(r"^\s*Audio", block, flags=re.IGNORECASE))
        is_text = bool(re.match(r"^\s*Text", block, flags=re.IGNORECASE))

        if not (is_audio or is_text):
            continue

        lang_match = re.search(
            r"^\s*Language\s*:\s*(.+)$", block, flags=re.IGNORECASE | re.MULTILINE
        )
        title_match = re.search(
            r"^\s*Title\s*:\s*(.+)$", block, flags=re.IGNORECASE | re.MULTILINE
        )

        language = lang_match.group(1).strip() if lang_match else ""
        title = title_match.group(1).strip() if title_match else ""

        combined = f"{language} {title}".upper()
        is_french = (
            "FRENCH" in combined
            or "FRANCAIS" in combined
            or "FRANÇAIS" in combined
        )

        if is_audio:
            has_any_audio = True
            if title:
                audio_titles.append(title)
            if is_french:
                has_french_audio = True
                if (
                    "VFQ" in combined
                    or "QUEBEC" in combined
                    or "QUÉBEC" in combined
                    or "CANADIAN" in combined
                ):
                    variants.add("VFQ")
                    continue
                if "VFB" in combined or "BELG" in combined:
                    variants.add("VFB")
                    continue
                if (
                    "VFF" in combined
                    or "TRUEFRENCH" in combined
                    or "FRANCE" in combined
                ):
                    variants.add("VFF")
                    continue
                # Charte Gemini : VFi est interdit, doit etre traduit en VFF.
                # On le detecte explicitement et on tag pour un label specifique
                # (eviter le faux "VFF par defaut" generique qui ment sur la
                # source — la NFO distinguait bien VFi, on a juste applique
                # la regle de traduction).
                if (
                    re.search(r"\bVFI\b", combined)
                    or re.search(r"\(VFI\)", combined)
                ):
                    variants.add("VFF")
                    vfi_detected = True
                    continue

        elif is_text and is_french:
            has_french_subtitle = True

    variant: str | None = None
    if "VFF" in variants and "VFQ" in variants:
        variant = "VF2"
    elif "VFF" in variants:
        variant = "VFF"
    elif "VFQ" in variants:
        variant = "VFQ"
    elif "VFB" in variants:
        variant = "VFB"

    # Détection VOSTFR : aucune piste audio FR + au moins un sous-titre FR
    is_vostfr = has_any_audio and not has_french_audio and has_french_subtitle

    # Compte des pistes audio FR "principales" (= une vraie version FR distincte).
    # On EXCLUT les pistes auxiliaires : audio description (AD), commentaires,
    # malentendants/SDH — elles ne constituent PAS une variante differente
    # (un AD-FR sur la meme VFF reste une seule version FR).
    #
    # Cette heuristique est utilisee en dernier recours quand on n'arrive pas
    # a identifier la variante par le tag du release name ou par le NFO :
    # 0 piste -> rien, 1+ piste -> VFF par defaut.
    # VF2 ne peut JAMAIS etre deduit du compte seul : il faut un tag explicite
    # (VF2 dans le nom, --force-fr VF2) ou des variantes distinctes etiquetees
    # (VFF + VFQ trouves dans les titres de pistes).
    AUX_TRACK_KEYWORDS = (
        "AUDIO DESCRIPTION", "AUDIODESCRIPTION", "DESCRIPTIVE",
        "(AD)", "[AD]", " AD ", " AD-", "-AD ",
        "COMMENTARY", "COMMENTAIRE", "COMMENT.",
        "SDH", "MALENTENDANT", "HEARING IMPAIRED",
        " HI ", "(HI)", "[HI]",
        "VISUALLY IMPAIRED", " VI ",
    )
    french_audio_count = 0
    for block in blocks:
        if not re.match(r"^\s*Audio", block, flags=re.IGNORECASE):
            continue
        lang_m = re.search(
            r"^\s*Language\s*:\s*(.+)$",
            block, flags=re.IGNORECASE | re.MULTILINE,
        )
        title_m = re.search(
            r"^\s*Title\s*:\s*(.+)$",
            block, flags=re.IGNORECASE | re.MULTILINE,
        )
        lang = lang_m.group(1).strip().upper() if lang_m else ""
        title = title_m.group(1).strip().upper() if title_m else ""
        combined = f"{lang} {title}"
        is_french_track = (
            "FRENCH" in combined or "FRANCAIS" in combined
            or "FRANÇAIS" in combined or "FR-" in combined
            or combined.strip() == "FR" or combined.strip().startswith("FR ")
        )
        if not is_french_track:
            continue
        # Filtrer les pistes auxiliaires (AD, commentaires, SDH)
        title_padded = f" {title} "
        is_auxiliary = any(kw in title_padded for kw in AUX_TRACK_KEYWORDS)
        if is_auxiliary:
            continue
        french_audio_count += 1

    return {
        "variant": variant,
        "found_variants": sorted(list(variants)),
        "audio_titles": audio_titles,
        "has_french_audio": has_french_audio,
        "has_french_subtitle": has_french_subtitle,
        "is_vostfr": is_vostfr,
        "french_audio_count": french_audio_count,
        "vfi_detected": vfi_detected,
    }
