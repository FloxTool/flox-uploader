"""Rendu BBCode pour les uploads Livre / BD / Manga.

Sprint D.5 v0.5.0 (PLAN-MULTICAT §7.4). 100% deterministe, aucun appel LLM
(decision D10). Charge le template `template_book.bbcode` depuis le dossier
du tracker et le rend via Jinja2 avec un `BookMetadata`.

Le BBCode produit va dans `presentation.txt` du package, et c'est le contenu
qui sera POST au tracker dans le champ `description` au moment de l'upload.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..trackers.base import Tracker
from .providers.book_metadata import BookMetadata


def render_book_bbcode(
    meta: BookMetadata,
    release_name: str,
    tracker: Tracker,
    torrent_info: dict | None = None,
) -> str:
    """Rend le BBCode livre.

    Args:
        meta : BookMetadata enrichi (extraction locale + lookup providers).
        release_name : nom de release final (ex: "Auteur.Titre.2024.FRENCH.EPUB-Flox").
        tracker : Tracker (gemini).
        torrent_info : Sprint D.12 — dict optionnel avec infos torrent
            {'size_pretty': '12 Mo', 'file_count': 2, 'files': [{'name':..., 'size':...}]}.
            Si fourni, le template affiche taille + contenu du torrent.

    Returns:
        BBCode rendu pret a poster sur Gemini. Jamais vide : si le template
        n'existe pas, on retourne un BBCode minimaliste de fallback.
    """
    # Le template est dans le meme dossier que rules.json du tracker
    # (trackers/<key>/template_book.bbcode).
    template_dir = (
        Path(__file__).parent.parent / "trackers" / tracker.key
    )
    template_path = template_dir / "template_book.bbcode"

    if not template_path.is_file():
        return _fallback_bbcode(meta, release_name)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.get_template("template_book.bbcode")

    # On serialise BookMetadata en dict pour le passer au template (Jinja
    # n'aime pas les dataclasses avec property en filtres).
    # Sprint D.14 : book_to_dict serialise maintenant file_format aussi,
    # plus besoin du patch post-serialize.
    from .providers.book_metadata import book_to_dict
    meta_dict = book_to_dict(meta)

    return template.render(
        meta=meta_dict,
        release_name=release_name,
        tracker_name=tracker.display_name,
        torrent_info=torrent_info or {},
    )


def build_torrent_info(torrent_path: Path) -> dict:
    """Sprint D.12 v0.5.0 : extrait taille + liste des fichiers d'un .torrent.

    Utilise pour enrichir la fiche BBCode livre avec le contenu du torrent
    (Note Louis : 'on peut indiquer le nombre de fichier, montrer le contenu
    du torrent').

    Returns:
        Dict avec keys :
        - size_bytes : int (somme taille contenu)
        - size_pretty : str (ex '12.4 Mo')
        - file_count : int
        - files : list[dict{name, size_bytes, size_pretty}] capee a 50 entrees
        Vide si erreur de lecture.
    """
    if not torrent_path.is_file():
        return {}
    try:
        from torf import Torrent
        t = Torrent.read(str(torrent_path))
    except Exception as e:
        print(f"[WARN] build_torrent_info ({torrent_path.name}) : {type(e).__name__} {e}")
        return {}

    size_bytes = int(t.size or 0)
    files: list[dict] = []
    # torf renvoie t.files comme une list d'objets File ou de Path
    raw_files = list(t.files or [])
    for f in raw_files[:50]:  # cap a 50 entrees pour eviter les BBCode gigantesques
        try:
            # f peut etre un torf.File (a .size, .name) ou juste un Path
            name = str(getattr(f, "name", None) or f)
            fsize = int(getattr(f, "size", 0) or 0)
        except Exception:
            name = str(f)
            fsize = 0
        files.append({
            "name": name,
            "size_bytes": fsize,
            "size_pretty": _format_size(fsize) if fsize else "",
        })

    return {
        "size_bytes": size_bytes,
        "size_pretty": _format_size(size_bytes),
        "file_count": len(raw_files),
        "files": files,
        "truncated": len(raw_files) > 50,
    }


def _format_size(size_bytes: int) -> str:
    """Format taille humaine (1.5 Ko, 12.4 Mo, 1.23 Go)."""
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    return f"{size_bytes / (1024 ** 3):.2f} Go"


def _fallback_bbcode(meta: BookMetadata, release_name: str) -> str:
    """BBCode minimaliste si le template n'est pas accessible.

    Garantit qu'on a TOUJOURS un contenu non-vide a poster sur le tracker.
    """
    parts = [f"[b]{meta.title or release_name}[/b]"]
    if meta.authors:
        parts.append(f"Auteur(s) : {', '.join(meta.authors)}")
    if meta.publisher:
        parts.append(f"Editeur : {meta.publisher}")
    if meta.publication_year:
        parts.append(f"Annee : {meta.publication_year}")
    if meta.file_format:
        parts.append(f"Format : {meta.file_format.upper()}")
    if meta.description:
        parts.append("")
        parts.append(meta.description[:1000])
    return "\n".join(parts)
