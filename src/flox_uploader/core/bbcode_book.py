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
) -> str:
    """Rend le BBCode livre.

    Args:
        meta : BookMetadata enrichi (extraction locale + lookup providers).
        release_name : nom de release final (ex: "Auteur.Titre.2024.FRENCH.EPUB-Flox").
        tracker : Tracker (gemini).

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
    from .providers.book_metadata import book_to_dict
    meta_dict = book_to_dict(meta)
    # On ajoute file_format qui n'est pas dans book_to_dict
    meta_dict["file_format"] = meta.file_format

    return template.render(
        meta=meta_dict,
        release_name=release_name,
        tracker_name=tracker.display_name,
    )


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
