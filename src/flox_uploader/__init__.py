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
#   0.3.3 : Sprint 3 de PLAN-V1.md — OMDb pleinement optionnel. Pas de
#           penalite de score quand la cle n'est pas configuree (user choisit
#           explicitement de skip). Bbcode awards plus robust (whitespace).
#   0.3.4 : Sprint 4 de PLAN-V1.md — preparation distribution. Migration douce
#           data legacy (banniere UI + endpoint /api/data-dir/migrate),
#           anticipation multi-tracker via Protocol TrackerClient.
#   0.3.5 : Sprint 5 de PLAN-V1.md — bundling Windows. PyInstaller .exe +
#           Inno Setup installeur (FloxUploader-Setup-X.Y.Z.exe) + icone
#           Flox (multi-tailles ICO depuis SVG). CI GitHub Actions
#           Build Windows .exe avec 3 smoke tests (--help, uvicorn boot,
#           windowed mode + HTTP /setup). MediaInfo CLI bundle. Premier
#           release publiable a partir d'un installeur double-clic.
#   0.3.6 : Sprint 6 de PLAN-V1.md — Auto-update v1. Endpoint
#           /api/update-info qui fetch GitHub Releases en background
#           (cache disque 6h, silent fail offline). Banner UI discret
#           "Nouvelle version disponible" en haut de chaque page (sauf
#           /setup), dismissible per-version via localStorage. Semver
#           strict, pre-releases ignorees. Aucune telemetry : on lit
#           juste /releases/latest, on n'envoie rien.
# Les bumps suivants suivent semver classique (PATCH pour bug-fix isole,
# MINOR pour batch de features coherent).
__version__ = "0.3.6"
