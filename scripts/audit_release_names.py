"""Audit release_name : pour chaque ancien package, on relance la nouvelle
logique de normalisation sur le NFO + original_stem deja stockes, et on
compare au release_name d'origine. Aucune API ni fichier video touche.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Setup PYTHONPATH pour importer le package
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flox_uploader.core.debug import Debug
from flox_uploader.core.release_name import build_release_name
from flox_uploader.trackers import get_tracker


def main():
    tracker = get_tracker("gemini", "https://example.com/announce/test")
    packages_dir = PROJECT_ROOT / "data" / "upload_packages"

    identical = 0
    different = []
    errors = []
    no_debug = []

    for pkg_dir in sorted(packages_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue

        old_release_name = pkg_dir.name
        debug_path = pkg_dir / "_debug" / "debug.json"
        if not debug_path.exists():
            no_debug.append(old_release_name)
            continue

        try:
            old_debug = json.loads(debug_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append((old_release_name, f"debug.json invalide: {e}"))
            continue

        original_stem = old_debug.get("original_stem")
        if not original_stem:
            errors.append((old_release_name, "original_stem manquant"))
            continue

        # NFO
        nfo_files = list(pkg_dir.glob("*.nfo"))
        if not nfo_files:
            errors.append((old_release_name, ".nfo manquant"))
            continue
        nfo_text = nfo_files[0].read_text(encoding="utf-8", errors="replace")

        # Reconstituer un faux video_path : on n'a besoin que du .stem pour
        # le builder, pas de l'existence reelle du fichier.
        fake_video_path = Path(f"{original_stem}.mkv")

        # Resolver TMDB MOCK qui retourne le tmdb_context deja cached dans debug
        # On reconstitue le tmdb_context partiel a partir des champs presents.
        cached_tmdb = {
            "title": old_debug.get("tmdb_title", ""),
            "original_title": old_debug.get("tmdb_original_title", ""),
            "original_language": old_debug.get("tmdb_original_language", ""),
            "production_countries": old_debug.get("tmdb_production_countries") or [],
            "release_date": old_debug.get("tmdb_release_date", ""),
        }
        # On reconstitue les title_parts_original
        original_parts = old_debug.get("title_parts_original") or []
        if original_parts and old_debug.get("title_parts_resolved"):
            # Le resolver doit retourner le title_parts_resolved
            resolved_parts = old_debug["title_parts_resolved"]
        else:
            resolved_parts = original_parts

        def fake_resolver(title_parts, year, debug_obj):
            # On retourne ce qui etait dans le debug original
            if not cached_tmdb.get("original_language"):
                return title_parts, None
            return resolved_parts, cached_tmdb

        force_fr = old_debug.get("forced_fr_variant")  # peut etre None ou str

        # Lance le nouveau builder
        try:
            debug = Debug(Path("/tmp"))
            new_release_name, _ = build_release_name(
                fake_video_path,
                tracker,
                nfo_text,
                debug,
                force_fr=force_fr,
                tmdb_resolver=fake_resolver,
            )
        except SystemExit as e:
            errors.append((old_release_name, f"build_release_name a die() : {e}"))
            continue
        except Exception as e:
            errors.append((old_release_name, f"build_release_name exception: {e}"))
            continue

        if new_release_name == old_release_name:
            identical += 1
        else:
            different.append((old_release_name, new_release_name))

    # Rapport
    total = identical + len(different) + len(errors) + len(no_debug)
    print("=" * 80)
    print(f"AUDIT RELEASE_NAME — {total} packages traités")
    print("=" * 80)
    print(f"Identiques : {identical} ({100 * identical / max(total, 1):.0f}%)")
    print(f"Différents : {len(different)}")
    print(f"Erreurs    : {len(errors)}")
    print(f"Sans debug : {len(no_debug)}")

    if different:
        print()
        print("=" * 80)
        print(f"DIFFERENCES ({len(different)})")
        print("=" * 80)
        for old, new in different:
            print(f"\n  ANCIEN : {old}")
            print(f"  NOUVEAU: {new}")

    if errors:
        print()
        print("=" * 80)
        print(f"ERREURS ({len(errors)})")
        print("=" * 80)
        for name, err in errors:
            print(f"  {name}")
            print(f"    -> {err}")

    if no_debug:
        print()
        print(f"Sans debug.json (ignores): {no_debug}")


if __name__ == "__main__":
    main()
