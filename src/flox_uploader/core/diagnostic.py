"""Sprint 8 PLAN-V1 — collecte d'infos pour les rapports de bug.

Quand l'user clique "Copier rapport" dans un toast d'erreur, ou "Signaler
un bug" dans le Guide, on construit un payload Markdown avec :

- Version Flox Uploader
- Python version
- OS + release
- Statut MediaInfo (vital pour reproduire les bugs MediaInfo)
- Setup complet ou pas

**Aucun secret n'est inclus** : pas de cles API, pas d'announce URL avec
passkey, pas de paths absolus contenant le nom user. Cette regle est
fondamentale puisque le rapport est destine a une GitHub Issue publique.

Le scrubbing actif sur les logs (cf. `log_scrubber.py`) est complementaire :
il filtre les writes vers les fichiers de log. Ici on choisit explicitement
ce qu'on collecte, donc rien a scrubber.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass

from .. import __version__


@dataclass(frozen=True)
class Diagnostic:
    """Snapshot des infos systeme pour un rapport de bug.

    Tous les champs sont surs a partager publiquement (pas de secrets,
    pas de paths absolus, pas d'identifiant user)."""

    version: str
    python_version: str
    os: str
    os_release: str
    mediainfo_available: bool
    mediainfo_version: str
    setup_complete: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_os_label() -> str:
    """Retourne un label compatible avec le dropdown du template bug.yml.

    Le template a comme options : Windows / macOS / Linux / Docker / Autre.
    On mappe `platform.system()` vers ces labels."""
    sys = platform.system()
    if sys == "Windows":
        return "Windows"
    if sys == "Darwin":
        return "macOS"
    if sys == "Linux":
        # On ne distingue pas Docker de Linux ici : le user devra cocher
        # Docker lui-meme dans le template s'il run dans un conteneur.
        # Detection automatique de Docker = trop fragile (heuristique
        # /.dockerenv + cgroups, pas fiable cross-platform).
        return "Linux"
    return "Autre"


def _detect_mediainfo() -> tuple[bool, str]:
    """Verifie que MediaInfo CLI est dispo et recupere sa version.

    Retourne (available, version_string). Version vide si non dispo.
    On limite a 3s pour eviter de bloquer le rendu de page si MediaInfo
    est tres lent (cas pathologique)."""
    if shutil.which("mediainfo") is None:
        return False, ""
    try:
        result = subprocess.run(
            ["mediainfo", "--Version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return False, ""
        # Output typique : "MediaInfoLib - v24.06"
        out = (result.stdout or result.stderr or "").strip()
        # On retourne la 1ere ligne, max 80 chars
        first_line = out.splitlines()[0] if out else ""
        return True, first_line[:80]
    except (subprocess.TimeoutExpired, OSError):
        return False, ""


def collect_diagnostic() -> Diagnostic:
    """Collecte les infos diagnostic. Appele a chaque rendu de page (via
    Jinja global). Doit etre rapide (timeout MediaInfo cape a 3s,
    typiquement <100ms en pratique)."""
    from ..config import is_setup_complete

    mediainfo_ok, mediainfo_ver = _detect_mediainfo()
    return Diagnostic(
        version=__version__,
        python_version=platform.python_version(),
        os=_detect_os_label(),
        os_release=platform.release(),
        mediainfo_available=mediainfo_ok,
        mediainfo_version=mediainfo_ver,
        setup_complete=is_setup_complete(),
    )


def build_markdown_report(
    diag: Diagnostic,
    *,
    page_url: str = "",
    error_message: str = "",
) -> str:
    """Construit le rapport Markdown qu'on copie en presse-papier ou qu'on
    injecte dans l'URL pre-remplie GitHub Issues.

    Format compact, sections claires. Render dans le textarea logs du
    template bug.yml qui a `render: shell` (police monospace)."""
    lines = ["## Diagnostic"]
    lines.append(f"- Flox Uploader : `{diag.version}`")
    lines.append(f"- Python : `{diag.python_version}`")
    lines.append(f"- OS : `{diag.os}` ({diag.os_release})")
    if diag.mediainfo_available:
        lines.append(f"- MediaInfo : `{diag.mediainfo_version}`")
    else:
        lines.append("- MediaInfo : **non detecte** (binaire mediainfo absent du PATH)")
    lines.append(f"- Setup complet : `{diag.setup_complete}`")
    if page_url:
        lines.append("")
        lines.append("## Contexte")
        lines.append(f"- Page : `{page_url}`")
    if error_message:
        lines.append("")
        lines.append("## Message d'erreur")
        lines.append("```")
        # On ne loggue jamais plus de 2000 chars pour eviter les URLs
        # GitHub trop longues (limite ~8KB). 2000 chars laisse de la marge.
        truncated = error_message[:2000]
        if len(error_message) > 2000:
            truncated += "\n... (tronque a 2000 chars)"
        lines.append(truncated)
        lines.append("```")
    return "\n".join(lines)
