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


def is_external_cover_url(cover_url: str) -> bool:
    """Sprint D.18 v0.5.0 : True si l'URL de la cover est accessible
    publiquement (http/https), False si c'est un chemin local
    (/packages/.../cover) que le tracker ne peut pas atteindre.

    Le BBCode ne doit inclure que les covers EXTERNES, sinon le `[img]`
    apparaitrait casse sur la fiche tracker."""
    if not cover_url:
        return False
    return cover_url.startswith(("http://", "https://"))


def pick_bbcode_cover_url(meta: BookMetadata, manual_cover_url: str = "") -> str:
    """Sprint D.18 v0.5.0 : choisit la cover a inclure dans le BBCode.

    Ordre de priorite :
    1. manual_cover_url (override user via Options upload, D.12) si externe
    2. meta.cover_url si externe (BnF / Google Books / OpenLibrary)
    3. "" sinon — la cover locale extraite (D.7) n'est PAS incluse car
       le tracker ne peut pas atteindre /packages/... du serveur local

    Args:
        meta : BookMetadata.
        manual_cover_url : URL override saisie par l'user dans Options upload.

    Returns:
        URL externe a utiliser dans le BBCode, ou "" si rien d'utilisable.
    """
    if is_external_cover_url(manual_cover_url):
        return manual_cover_url
    if is_external_cover_url(meta.cover_url):
        return meta.cover_url
    return ""


def render_book_bbcode(
    meta: BookMetadata,
    release_name: str,
    tracker: Tracker,
    torrent_info: dict | None = None,
    manual_cover_url: str = "",
) -> str:
    """Rend le BBCode livre.

    Args:
        meta : BookMetadata enrichi (extraction locale + lookup providers).
        release_name : nom de release final (ex: "Auteur.Titre.2024.FRENCH.EPUB-Flox").
        tracker : Tracker (gemini).
        torrent_info : Sprint D.12 — dict optionnel avec infos torrent
            {'size_pretty': '12 Mo', 'file_count': 2, 'files': [{'name':..., 'size':...}]}.
            Si fourni, le template affiche taille + contenu du torrent.
        manual_cover_url : Sprint D.18 — URL override saisie par l'user
            dans Options upload (priorite sur meta.cover_url). Si elle
            est externe (https), elle est utilisee dans le BBCode.

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
    # Sprint D.35 v0.5.0 : helpers URL Google Books moderne + BnF.
    # Permet d'utiliser {{ title | google_books_url(id) }} dans le template.
    from .providers._url_helpers import google_books_url, bnf_url
    env.filters["google_books_url"] = google_books_url
    env.filters["bnf_url"] = bnf_url

    template = env.get_template("template_book.bbcode")

    # On serialise BookMetadata en dict pour le passer au template (Jinja
    # n'aime pas les dataclasses avec property en filtres).
    # Sprint D.14 : book_to_dict serialise maintenant file_format aussi,
    # plus besoin du patch post-serialize.
    from .providers.book_metadata import book_to_dict
    meta_dict = book_to_dict(meta)

    # Sprint D.18 : on remplace cover_url dans le dict par celle qui
    # convient pour le BBCode (externe uniquement). Les covers locales
    # extraites (cover_url = /packages/.../cover) sont videes pour
    # eviter un [img] casse dans la fiche tracker.
    bbcode_cover = pick_bbcode_cover_url(meta, manual_cover_url)
    meta_dict["cover_url"] = bbcode_cover

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
    # Sprint D.25 fix : torf.File herite de Path. f.name = juste le nom
    # de fichier ('Tome_01.pdf'), tandis que str(f) = full path relatif
    # dans le torrent ('PDF/Tome_01.pdf'). On veut le full path pour
    # preserver la hierarchie dans le tree.
    for f in raw_files[:50]:  # cap a 50 entrees pour eviter les BBCode gigantesques
        try:
            full_path = str(f).replace("\\", "/")
            fsize = int(getattr(f, "size", 0) or 0)
        except Exception:
            full_path = str(f)
            fsize = 0
        files.append({
            "name": full_path,
            "size_bytes": fsize,
            "size_pretty": _format_size(fsize) if fsize else "",
        })

    # Sprint D.25 v0.5.0 (note Louis N-R4) : on construit aussi une vue
    # hierarchique pour preserver l'arborescence dans le BBCode.
    # Pour LARGO_WINCH/PDF/Tome_01.pdf + LARGO_WINCH/CBZ/Tome_01.cbz,
    # on veut voir les 2 sous-dossiers indentes au lieu d'une liste flat.
    tree_lines = _build_tree_lines(files)

    return {
        "size_bytes": size_bytes,
        "size_pretty": _format_size(size_bytes),
        "file_count": len(raw_files),
        "files": files,
        "tree_lines": tree_lines,
        "truncated": len(raw_files) > 50,
    }


def _build_tree_lines(files: list[dict]) -> list[str]:
    """Sprint D.25 v0.5.0 : construit une representation hierarchique
    indentee depuis la liste des fichiers.

    Args:
        files : liste de {"name": str, "size_pretty": str, ...}

    Returns:
        Liste de strings, chacune une ligne indentee a inclure dans un
        [code] block du BBCode. Conserve l'ordre des fichiers tels qu'ils
        apparaissent dans le torrent (sans sort agressif).

    Exemple :
        Input : [
          {"name": "PDF/Tome_01.pdf", "size_pretty": "45 Mo"},
          {"name": "PDF/Tome_02.pdf", "size_pretty": "43 Mo"},
          {"name": "CBZ/Tome_01.cbz", "size_pretty": "12 Mo"},
        ]
        Output :
          ["PDF/",
           "  Tome_01.pdf (45 Mo)",
           "  Tome_02.pdf (43 Mo)",
           "CBZ/",
           "  Tome_01.cbz (12 Mo)"]
    """
    if not files:
        return []

    lines: list[str] = []
    seen_dirs: set[str] = set()
    for f in files:
        name = f.get("name", "")
        size_pretty = f.get("size_pretty", "")
        if not name:
            continue
        # Normalisation : / au lieu de \ pour les paths Windows
        path_norm = name.replace("\\", "/")
        parts = path_norm.split("/")

        # Pour chaque niveau de dossier non encore vu, on emet une ligne
        # "Dir/" indentee.
        for i in range(len(parts) - 1):
            dir_path = "/".join(parts[: i + 1])
            if dir_path in seen_dirs:
                continue
            seen_dirs.add(dir_path)
            indent = "  " * i
            lines.append(f"{indent}{parts[i]}/")

        # Le fichier lui-meme, indente selon sa profondeur
        depth = len(parts) - 1
        indent = "  " * depth
        size_suffix = f" ({size_pretty})" if size_pretty else ""
        lines.append(f"{indent}{parts[-1]}{size_suffix}")

    return lines


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
