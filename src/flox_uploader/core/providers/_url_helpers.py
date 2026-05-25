"""Helpers de construction d'URLs pour les fiches externes (Google Books, BnF).

Sprint D.35 v0.5.0 (note Louis) : Google Books a 2 formats d'URL :

1. ANCIEN : `https://books.google.com/books?id={id}` → page basique, redirige
   souvent vers une fiche minimaliste sans preview ni infos detaillees.

2. NOUVEAU : `https://www.google.com/books/edition/{TitleSlug}/{id}?hl=fr`
   → page moderne avec preview integre, infos completes, design propre.

Le slug `{TitleSlug}` est utilise par Google pour SEO mais le routage se fait
sur l'ID. On peut donc generer un slug raisonnable sans risque.

Format du slug (observe sur Google) :
- Ponctuation `:` `;` `?` `!` `'` `"` `|` supprimee
- Slashes `/` `\\` -> espaces
- Espaces -> underscores
- Accents URL-encodes (é -> %C3%A9, à -> %C3%A0)
- Tronque a ~40 caracteres (du slug decode)
"""
from __future__ import annotations

import urllib.parse


def google_books_url(title: str, volume_id: str, hl: str = "fr",
                     max_slug_chars: int = 40) -> str:
    """Construit une URL Google Books format moderne /books/edition/<slug>/<id>.

    Args:
        title : titre du livre (sera converti en slug).
        volume_id : volumeId Google Books (ex: "Nw2eEQAAQBAJ").
        hl : code langue interface (defaut 'fr').
        max_slug_chars : longueur max du slug decode (defaut 40, observe Google).

    Returns:
        URL complete ou chaine vide si volume_id absent.

    Exemples :
        >>> google_books_url("Là où gisait le corps", "b1u20AEACAAJ")
        'https://www.google.com/books/edition/L%C3%A0_o%C3%B9_gisait_le_corps/b1u20AEACAAJ?hl=fr'

        >>> google_books_url("Guide Poitiers 2026 Petit Futé: Escapades", "Nw2eEQAAQBAJ")
        'https://www.google.com/books/edition/Guide_Poitiers_2026_Petit_Fut%C3%A9_Escapades/Nw2eEQAAQBAJ?hl=fr'
    """
    if not volume_id:
        return ""
    if not title:
        return f"https://www.google.com/books/edition/book/{volume_id}?hl={hl}"

    # Drop ponctuation que Google omet du slug
    drop_chars = set(":;?!|\"'")
    space_chars = set("/\\")
    cleaned = "".join(
        " " if c in space_chars else "" if c in drop_chars else c
        for c in title
    )
    # Spaces -> underscores
    slug = cleaned.replace(" ", "_").strip("_")
    # Compact double underscores
    while "__" in slug:
        slug = slug.replace("__", "_")
    # Truncate ~40 chars (sur le slug decode, pas l'URL encode)
    if len(slug) > max_slug_chars:
        slug = slug[:max_slug_chars].rstrip("_-.,;:")
    # URL-encode (accents -> %C3%XX, underscores et tirets preserves)
    slug_encoded = urllib.parse.quote(slug, safe="_-")
    return f"https://www.google.com/books/edition/{slug_encoded}/{volume_id}?hl={hl}"


def bnf_url(ark: str) -> str:
    """Construit l'URL BnF canonique pour un ARK.

    Args:
        ark : identifiant ARK BnF (ex: "cb47642056d").

    Returns:
        URL complete vers la notice BnF, ou chaine vide.
    """
    if not ark:
        return ""
    return f"https://catalogue.bnf.fr/ark:/12148/{ark}"
