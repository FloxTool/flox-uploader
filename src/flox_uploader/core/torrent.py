"""Creation du fichier .torrent via la lib torf."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from torf import Torrent


# Bareme officiel des tailles de pieces .torrent recommandees par Gemini.
# Source : doc PDF G3MINI TR4CK3R - RÈGLES D'UPLOAD, page 5 (Sprint A v0.5.0
# §8.3). torf auto-calcule une piece_size raisonnable mais pas toujours
# strictement conforme au bareme Gemini, qui privilegie des valeurs
# conservatrices : on force donc manuellement avant generate().
#
#   < 500 Mo  -> 256 Ko
#   > 500 Mo  -> 512 Ko
#   > 1 Go    -> 1 Mo
#   > 2 Go    -> 2 Mo
#   > 4 Go    -> 4 Mo
#   > 8 Go    -> 8 Mo
#   > 20 Go   -> 16 Mo (max compat clients BitTorrent classiques)

_KB = 1024
_MB = 1024 * 1024
_GB = 1024 * _MB


def _recommended_piece_size(total_bytes: int) -> int:
    """Retourne la piece size .torrent conforme au bareme Gemini.

    Garantit la conformite avec les RÈGLES D'UPLOAD officielles. Toujours une
    puissance de 2 (requis par le format .torrent).

    Args:
        total_bytes : taille totale du contenu (fichier seul ou somme dossier).

    Returns:
        Piece size en bytes (256 KB a 16 MB).
    """
    if total_bytes < 500 * _MB:
        return 256 * _KB
    if total_bytes < 1 * _GB:
        return 512 * _KB
    if total_bytes < 2 * _GB:
        return 1 * _MB
    if total_bytes < 4 * _GB:
        return 2 * _MB
    if total_bytes < 8 * _GB:
        return 4 * _MB
    if total_bytes < 20 * _GB:
        return 8 * _MB
    return 16 * _MB


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
            # Sprint A v0.5.0 §8.3 : on force la piece_size conformement au
            # bareme Gemini officiel (vs auto-calcul torf parfois divergent).
            torrent.piece_size = _recommended_piece_size(torrent.size)
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
        # Sprint A v0.5.0 §8.3 : on force la piece_size conformement au
        # bareme Gemini officiel (vs auto-calcul torf parfois divergent).
        torrent.piece_size = _recommended_piece_size(torrent.size)
        torrent.generate()
        torrent.write(str(output_torrent))

    print(f"[OK] Torrent cree : {output_torrent}")
