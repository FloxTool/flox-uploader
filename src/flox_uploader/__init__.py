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
#   0.3.7 : Sprint 8 de PLAN-V1.md — Crash report helper. Bouton "Copier
#           rapport" dans tout toast d'erreur (Markdown : version, OS,
#           page, message). Section "Signaler un bug" dans le Guide
#           avec ouverture directe GitHub Issues + template bug.yml
#           pre-rempli (version, os, logs). Module core/diagnostic.py
#           collecte version + Python + OS + MediaInfo + statut setup,
#           expose en Jinja global et endpoint /api/diagnostic. Aucun
#           secret dans le payload.
#   0.5.0 : Release multi-categorie (Sprints A a D.48 de PLAN-MULTICAT).
#           Pipeline Livres complet : BnF + Google Books, covers (locale
#           prioritaire, imgbb + fallback Imgur), previews EPUB/PDF/CBZ,
#           release names livres, volume strict, periodiques, compliance
#           ebook. Inclut aussi tout le contenu v0.4.0 jamais publie
#           (Sprints 1-8 PLAN-V1 : installeur, wizard /setup, update
#           banner, crash report). NB versions : la v0.4.0 n'a jamais ete
#           taguee ni releasee (GitHub Actions bloque) ; le tag v0.3.17
#           existe sans release. On saute directement 0.3.17 -> 0.5.0,
#           premier build livre en local (hors CI).
#   0.3.17 : Sprint 8 hotfix v17 — 4e faux positif compliance audio
#           (Emilia Perez : E-AC3.5.1). Le findall non-overlappant matchait
#           `3.5` (le 3 de AC3 + .5) et ratait le vrai `5.1`. Fix : capture
#           en chevauchement (lookahead) + filtre sur les layouts audio
#           valides (_VALID_AUDIO_LAYOUTS : 1.0/2.0/2.1/4.0/5.1/6.1/7.1) —
#           '3.5' et '2.2' n'en font pas partie donc ne sont jamais pris
#           pour des layouts.
#   0.3.16 : Sprint 8 hotfix v16 — batch UX/compliance/feature :
#           (1) Console mediainfo qui flashait a chaque page render fix via
#           cache module-level + CREATE_NO_WINDOW (cause des bugs curseur
#           glitch + terminal pop signales par Louis sur v0.3.14 bundle) ;
#           (2) Polling queue ne se bloque plus eternellement si l'user
#           ouvre la modal log au moment d'un job qui finit ;
#           (3) Compliance audio_channels refactore : nouveau regex
#           \\d\\.\\d(?!\\d) evite faux positifs `2.2` de `VF2.2160p` +
#           detecte les formats colles `AC35.1`/`DDP5.1` + accepte
#           N'IMPORTE QUELLE piste audio (pas juste la principale) ;
#           (4) Section 'Upload vers le tracker' visible aussi en
#           state=uploaded, recap centralise : badge + lien Gemini gros
#           + lien dossier .torrent + log d'upload collapsible.
#   0.3.15 : Sprint 8 hotfix v15 — message rate limit GitHub explicite.
#           Quand l'API renvoyait 403 + 'rate limit' (60 req/h IP non-auth),
#           le user voyait juste 'HTTP 403'. Maintenant : message specifique
#           "Limite GitHub atteinte ... reinitialise dans ~X min (vers HH:MM
#           heure locale)" en parsant le header X-RateLimit-Reset.
#   0.3.14 : Sprint 8 hotfix v14 — fix critique parser URL Gemini (suite v13).
#           Le format reel observe sur Gemini est /torrent/download/<id>.<passkey>
#           (singulier 'torrent' + '.' suivi de la passkey 32 chars). v13
#           matchait /torrents/ (pluriel) et exigeait [/?#$] apres l'id —
#           ne matchait donc PAS ce format. Fix : regex acceptent torrent[s]?
#           + tout non-digit comme separateur post-id. Plus bouton "Afficher
#           log d'upload" sur la page detail (endpoint /api/uploads/{name}/log).
#   0.3.13 : Sprint 8 hotfix v12+v13 — bouton "Ouvrir le dossier du .torrent
#           uploade" sur la page detail. Priorise TORRENT_FINAL_DIR (watch
#           folder qBittorrent) puis parent de final_torrent_path en fallback.
#           Endpoint POST /api/packages/{name}/open-torrent-folder.
#           + Fix critique : _parse_torrent_id_from_url ne matchait pas les
#           URLs Gemini reelles -> torrent_id=None -> lien "Voir sur Gemini"
#           jamais affiche sur page detail. Strategie en 3 passes + log
#           explicite en cas de format inconnu.
#   0.3.12 : Sprint 8 hotfix v11 — batch de 7 notes UX NOTES.md :
#           (1) terminal popup pendant prepare cache via CREATE_NO_WINDOW,
#           (2) colonne "Mode" obsolete retiree de la table Uploads,
#           (3-4) shift-click + check-all + persistance sessionStorage
#           sur la section Preparations en cours, (5) suppression package
#           uploaded autorisee avec warning specifique sur le nouvel
#           infohash, (6) selection des packages uploaded sur queue
#           (exclus du bouton Uploader), (7) bouton "Ouvrir le dossier
#           source" sur la page detail (parent du .mkv original).
#   0.3.11 : Sprint 8 hotfix v10 — propage les erreurs de fetch GitHub.
#           Le bouton "Verifier les mises a jour" mentait avec "A jour"
#           quand le fetch GitHub avait silencieusement echoue. Maintenant
#           on retourne l'erreur explicite + le JS affiche un toast danger
#           "Verification impossible : <raison>" + label "Echec - reessayer".
#   0.3.10 : Sprint 8 hotfix v9 — fix incomplet de v0.3.9. Le fix v0.3.9
#           appelait [exe, "prepare", ...] mais l'entry point bundle est
#           launcher.py (pas cli.py) qui a son propre argparse limite a
#           --host/--port/etc. Resultat : "unrecognized arguments: prepare ...".
#           Fix v0.3.10 : launcher.py detecte les sous-commandes connues
#           (prepare/upload/inspect/serve) et delegue a cli.main().
#   0.3.9 : Sprint 8 hotfix v8 — fix critique bundle PyInstaller. Le
#           subprocess prepare etait lance avec `sys.executable -m
#           flox_uploader.cli prepare ...`, ce qui en mode .exe (frozen)
#           passait `-m flox_uploader.cli prepare ...` comme args a l'app
#           principale -> "unrecognized arguments". Aucun upload possible
#           sur la v0.3.8 installee. Fix : detecter sys.frozen et invoquer
#           le .exe directement avec la sous-commande. ⚠ INCOMPLET — voir v0.3.10.
#   0.3.8 : Sprint 8 hotfix — fixes JS escape (regression Sprint 8 qui
#           cassait tu.toast / tu.showPageLoader) + 7 notes NOTES.md :
#           (1) checkbox inbox "Afficher tout" : par defaut on n'affiche
#           que dossiers + videos, les NFO/poster/sub sous le toggle ;
#           (2) navigation Queue->Inbox debloquee (suppression preventDefault
#           + setTimeout fragile) ; (3) HE-AAC / AAC-LC preserves en
#           majuscules ; (4) secret placeholder dynamique : autant de
#           puces que de caracteres ; (5) defaults Gemini pre-remplis
#           (TRACKER_API_URL, BANNED_TEAMS) ; (6) pagination Inbox
#           client-side (25/50/100/200/400/Tout, page navigation) ;
#           (7) click row inbox toggle la checkbox.
# Les bumps suivants suivent semver classique (PATCH pour bug-fix isole,
# MINOR pour batch de features coherent).
__version__ = "0.5.3"
