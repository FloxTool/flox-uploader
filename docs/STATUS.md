# STATUS — état courant du projet

> **Source unique de vérité pour l'état courant.** Le bloc chiffré ci-dessous est
> **généré** par `python scripts/status_snapshot.py` (ne pas l'éditer à la main).
> Le reste (contexte rédigé) est mis à jour en fin de session/sprint.
>
> Créé en R6 (audit `AUDIT_2026-07-19.md`) pour tuer le drift doc↔réalité :
> `CLAUDE.md` annonçait « v0.5.0 en planification / 772 tests » alors que v0.5.0
> était publiée et que la suite comptait ~1600 tests.

## Chiffres (auto — `scripts/status_snapshot.py`)

<!-- AUTO:START -->
- **Version** : 0.5.4
- **Dernier tag git** : v0.5.0
- **Tests collectés** : 1713
- **Routes API (`web/app.py`)** : 61
- **Packages corpus dev** : 589
<!-- AUTO:END -->

## Contexte (rédigé)

- **Version publiée** : v0.5.0 (2026-07-18), multi-catégorie (livres) + tout le
  contenu v0.4.0 vidéo. Build **local** (GitHub Actions désactivé sur le compte —
  installeur PyInstaller + Inno Setup, attaché manuellement à la release).
- **Périmètre livré** : Films, Séries (+ anim/docu), **Livres/BD/Manga/Audiobooks**.
  À venir : Jeux, Émission TV, Sport, Logiciels, Formations.
- **Remédiation audit 2026-07-19 en cours** (voir `AUDIT_2026-07-19.md` §11) :
  - R1 — sécurité conformité (C9 EXTREME, gate compliance, garde-fou TMDB…) ✅ mergé
  - R2 — secrets & accès (imgbb, scan secrets, DNS-rebinding, 404 stylée) ✅ mergé
  - R3 — multi-catégorie débloqué (season/épisode, type livres, encode-library…) ✅ mergé
  - R4 — robustesse (claim atomique, verrou single-instance, timeouts, WAL) — en cours
  - R5 — score honnête (triple comptage TMDB, sous-typage blocked) — en cours
  - R6 — structure doc + UX ciblé — en cours
  - R7 — ambition (backup/export ; screenshots vidéo & qBittorrent différés) — en cours

## Comment mettre à jour

```bash
python scripts/status_snapshot.py          # régénère le bloc AUTO
python scripts/status_snapshot.py --check  # exit 1 si périmé (pour la CI/pre-commit)
```
