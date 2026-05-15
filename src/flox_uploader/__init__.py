"""flox_uploader — création de packages d'upload pour trackers de torrents."""

# Historique des versions :
#   0.1.0 : MVP CLI + UI minimale (prepare, upload, history)
#   0.2.0 : state machine + dedup workflow + validate batch + filters
#   0.3.0 : UI premium (round 8) — tooltip v2, command palette, rescore,
#           sticky action bar, hierarchical tree, focus polish, etc.
#   0.3.1 : Sprint 1 de PLAN-V1.md — rebranding tracker_uploader -> flox_uploader,
#           LICENSE MIT, CHANGELOG, CI GitHub Actions, issue templates.
#   0.3.2 : Sprint 2 de PLAN-V1.md — endpoint unifie /api/config/test-key,
#           tests OMDb + announce URL, welcome state 1er run, refonte /setup
#           avec badges de statut inline.
# Les bumps suivants suivent semver classique (PATCH pour bug-fix isole,
# MINOR pour batch de features coherent).
__version__ = "0.3.2"
