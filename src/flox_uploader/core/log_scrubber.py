"""Filtre les secrets connus avant l'ecriture dans les logs.

Le user peut potentiellement consulter / telecharger / partager ses logs
(rapport de bug, support, etc.). Pour eviter qu'une exception reseau
remonte une URL contenant la passkey ou qu'un debug print accidentel
laisse fuiter une cle API, on intercale un `ScrubbingWriter` autour des
descripteurs de log.

Exemples masques :
- TRACKER_API_KEY : "abc123def456" -> "<redacted:TRACKER_API_KEY>"
- Passkey extraite de TRACKER_ANNOUNCE : "<redacted:passkey>"
- TMDB_API_KEY / OMDB_API_KEY : idem

Strategie : on construit la liste des secrets a partir de os.environ au
moment de la creation du scrubber, ce qui suit naturellement les
modifications via la page Config / le wizard de setup.
"""
from __future__ import annotations

import io
import os
import re
from typing import IO, Iterable


# Cle des variables d'env contenant des secrets a masquer.
# Plus la liste est large, plus on protege contre les fuites accidentelles.
SECRET_ENV_KEYS: tuple[str, ...] = (
    "TRACKER_API_KEY",
    "TMDB_API_KEY",
    "OMDB_API_KEY",
)


def _extract_passkey_from_announce(announce_url: str) -> str:
    """Extrait la passkey d'une URL announce Unit3D.

    Format Gemini observe : `https://gemini-tracker.org/announce/<passkey>`
    ou la passkey est le dernier segment du path (32 chars alphanumeriques
    typiquement). On retourne juste la passkey, vide si pas trouvee.
    """
    if not announce_url:
        return ""
    # Le dernier segment non-vide du path
    parts = [p for p in announce_url.rsplit("/", 2) if p]
    if not parts:
        return ""
    candidate = parts[-1].split("?")[0].strip()
    # On ne retient que si ca ressemble a une passkey (alphanum, 16+ chars)
    if len(candidate) >= 16 and candidate.replace("-", "").isalnum():
        return candidate
    return ""


def _collect_current_secrets() -> dict[str, str]:
    """Lit os.environ et retourne {label: secret_value} pour tous les secrets
    courants. Le label est utilise dans la chaine de remplacement (debug)."""
    out: dict[str, str] = {}
    for key in SECRET_ENV_KEYS:
        v = (os.getenv(key) or "").strip()
        if v and len(v) >= 8:  # ignore les valeurs trop courtes (faux positifs)
            out[key] = v
    announce = (os.getenv("TRACKER_ANNOUNCE") or "").strip()
    if announce:
        out["TRACKER_ANNOUNCE"] = announce
        passkey = _extract_passkey_from_announce(announce)
        if passkey:
            out["passkey"] = passkey
    return out


class SecretScrubber:
    """Remplace les secrets connus dans une chaine.

    Construit a partir de la liste courante des variables d'env. Si l'env
    change apres construction (ex: wizard qui ajoute une cle), creer un
    nouveau scrubber.
    """

    def __init__(self, extra_secrets: Iterable[tuple[str, str]] = ()):
        self._patterns: list[tuple[re.Pattern[str], str]] = []
        # Lecture des secrets depuis l'env + extras eventuels
        all_secrets: dict[str, str] = dict(_collect_current_secrets())
        for label, value in extra_secrets:
            if value and len(value) >= 8:
                all_secrets[label] = value
        # Tri par longueur decroissante : on veut masquer la passkey AVANT
        # de masquer l'URL announce qui la contient, pour ne pas la dupliquer.
        sorted_items = sorted(
            all_secrets.items(), key=lambda kv: len(kv[1]), reverse=True,
        )
        for label, value in sorted_items:
            self._patterns.append(
                (re.compile(re.escape(value)), f"<redacted:{label}>"),
            )

    def scrub(self, text: str) -> str:
        """Retourne `text` avec les secrets remplaces."""
        if not text or not self._patterns:
            return text
        out = text
        for pattern, replacement in self._patterns:
            out = pattern.sub(replacement, out)
        return out

    def __bool__(self) -> bool:
        """False si aucun secret a masquer (ex: setup pas encore complet)."""
        return bool(self._patterns)


class ScrubbingWriter(io.TextIOBase):
    """File-like wrapper autour d'un autre writer, qui scrub() chaque write.

    Compatible `contextlib.redirect_stdout` / `redirect_stderr`. Ne ferme
    PAS le writer sous-jacent dans `close()` (le caller controle son cycle
    de vie).
    """

    def __init__(self, target: IO[str], scrubber: SecretScrubber):
        self._target = target
        self._scrubber = scrubber

    def write(self, s: str) -> int:
        # Si la chaine contient un secret, on le remplace ; sinon on passe tel
        # quel pour ne pas perturber le buffering ligne du target.
        cleaned = self._scrubber.scrub(s) if self._scrubber else s
        self._target.write(cleaned)
        return len(s)  # convention : retourne la taille de l'entree

    def flush(self) -> None:
        try:
            self._target.flush()
        except Exception:
            pass

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        try:
            return self._target.isatty()
        except Exception:
            return False
