"""Helpers d'erreur communs au pipeline."""
from __future__ import annotations

import sys


def die(msg: str) -> None:
    """Imprime un message d'erreur et termine le process avec code 1.

    Conservé identique à l'ancien helper pour préserver le contrat
    de batch_prepare_upload.py qui parse les codes de retour.
    """
    print(f"[ERREUR] {msg}")
    sys.exit(1)
