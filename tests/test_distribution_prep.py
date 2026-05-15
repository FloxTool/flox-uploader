"""Tests Sprint 4 (PLAN-V1.md) : préparation distribution.

NOTES v0.3.5 cleanup : retire les tests de detection + migration data legacy
qui couvraient une feature retiree (la detection auto ne fonctionnait pas
en mode packagé a cause de PROJECT_ROOT mal resolu, et le cas d'usage etait
quasi-inexistant pour les futurs users). Cf. config.py pour le contexte.

Tests conserves :
 - Protocol TrackerClient (anticipation multi-tracker v0.5+) :
   GeminiClient satisfait l'interface structurelle sans modification.
"""
from __future__ import annotations


# ============================================================
# Protocol TrackerClient
# ============================================================

def test_gemini_client_satisfies_tracker_client_protocol():
    """GeminiClient doit etre considere comme un TrackerClient grace au
    duck typing renforce par runtime_checkable."""
    from flox_uploader.trackers.base import TrackerClient
    from flox_uploader.core.gemini_api import GeminiClient
    # On a besoin d'une instance pour isinstance() avec un Protocol
    # runtime_checkable. Pas besoin d'init reseau, juste verifier la forme.
    client = GeminiClient(api_url="https://x.local/api", api_key="abc")
    assert isinstance(client, TrackerClient)


def test_tracker_client_protocol_rejects_random_class():
    """Une classe sans les methodes requises ne doit PAS etre un TrackerClient."""
    from flox_uploader.trackers.base import TrackerClient

    class NotATracker:
        def some_other_method(self):
            pass

    assert not isinstance(NotATracker(), TrackerClient)
