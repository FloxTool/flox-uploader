"""Creation du fichier .torrent via la lib torf."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from torf import Torrent


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink si possible (rapide, zero-copy), sinon copie."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def create_torrent(
    video_path: Path,
    output_torrent: Path,
    announce_url: str,
    source: str,
    private: bool = True,
    companion_files: list[Path] | None = None,
    torrent_root_name: str | None = None,
) -> None:
    """Cree le .torrent.

    - video_path est un DOSSIER (ex: dossier scene complet) -> torrent
      multi-fichiers contenant tout le dossier (cross-seed scene preserve).
    - video_path est un FICHIER sans companion -> torrent mono-fichier.
    - video_path est un FICHIER + companion_files -> torrent multi-fichiers
      compose de {video_path, *companion_files}, avec comme racine logique
      `torrent_root_name` (ou le stem du fichier video). On materialise
      cette racine via un dossier temporaire + hardlinks sur les fichiers
      d'origine, on hash, puis on nettoie. Cote seed, l'utilisateur doit
      recreer la meme structure (release_name/Film.mkv + release_name/Film.nfo)
      via hardlinks pour permettre le cross-seed.

    Si `output_torrent` existe deja, on le supprime avant write (cas de
    re-prepare d'un meme package). Le caller doit verifier en amont le
    state pour ne PAS overrider un .torrent deja uploade (cf. process_one
    qui die si state == UPLOADED avant d'appeler ici).
    """
    print("[INFO] Creation du .torrent...")

    # B4 NOTES.md : torf.write refuse d'ecraser un fichier existant.
    # On supprime explicitement avant write pour permettre le re-prepare.
    # Le caller (process_one) a deja verifie que state != UPLOADED.
    if output_torrent.is_file():
        try:
            output_torrent.unlink()
        except OSError as e:
            from .errors import die
            die(
                f"Impossible de supprimer le .torrent existant pour le re-creer : {e}. "
                f"Path : {output_torrent}"
            )

    if companion_files and video_path.is_file():
        root_name = torrent_root_name or video_path.stem
        tmp_root = Path(tempfile.mkdtemp(prefix="trackup_torrent_"))
        try:
            stage = tmp_root / root_name
            stage.mkdir()
            files_to_link = [video_path] + list(companion_files)
            for src in files_to_link:
                dst = stage / src.name
                _link_or_copy(src, dst)
            print(
                f"[INFO] Mode multi-fichiers : racine = {root_name}, "
                f"contenu = {[f.name for f in files_to_link]}"
            )
            torrent = Torrent(path=str(stage))
            torrent.private = private
            torrent.trackers = [[announce_url]]
            torrent.source = source
            torrent.comment = f"Created for {source}"
            torrent.generate()
            torrent.write(str(output_torrent))
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)
    else:
        torrent = Torrent(path=str(video_path))
        torrent.private = private
        torrent.trackers = [[announce_url]]
        torrent.source = source
        torrent.comment = f"Created for {source}"
        torrent.generate()
        torrent.write(str(output_torrent))

    print(f"[OK] Torrent cree : {output_torrent}")
