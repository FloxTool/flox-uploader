"""Helper minimaliste pour nettoyer le HTML retourne par certains providers.

Sprint D.10 v0.5.0 — BnF SRU et certains Google Books renvoient des
descriptions emaillees de HTML basique (`<div>`, `<b>`, `<p>`, `<br>`,
`<i>`). Pour la fiche tracker BBCode et la page detail web, on prefere
du plain-text propre (BBCode n'est PAS HTML, et les `<div>` apparaissent
crus dans le BBCode final).

On utilise html.parser stdlib (pas de dependance). Conversion :
- <br>, <p>, <div> -> retour ligne
- <b>, <strong>, <i>, <em>, <u> -> tag retire (contenu garde)
- Tout autre tag -> retire (contenu garde, defensif)
- Entites HTML (`&amp;`, `&eacute;`) -> caractere correspondant via html.unescape
- Multi-espaces / multi-newlines -> compactes (1 newline max entre paragraphes)
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _PlainTextExtractor(HTMLParser):
    """Convertit du HTML en plain text avec respect des blocs."""

    # Tags qui produisent un saut de ligne
    _BLOCK_TAGS = frozenset({
        "p", "div", "br", "li", "blockquote", "h1", "h2", "h3",
        "h4", "h5", "h6", "tr", "section", "article", "hr",
    })

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(text: str) -> str:
    """Convertit du HTML en plain text propre.

    Args:
        text : texte potentiellement HTML.

    Returns:
        Plain text avec :
        - tags HTML retires
        - entites decodees (&amp; -> &, &eacute; -> é)
        - paragraphes preserves (1 saut de ligne entre)
        - espaces multiples compactes en 1
        - trim global

    Ne plante jamais : si parse echoue, retourne le texte brut.
    """
    if not text:
        return ""
    if "<" not in text and "&" not in text:
        # Pas de HTML detecte, fast-path
        return text.strip()

    try:
        parser = _PlainTextExtractor()
        parser.feed(text)
        parser.close()
        out = parser.get_text()
    except Exception:
        # Fallback ultime : regex brute pour les balises
        out = re.sub(r"<[^>]+>", " ", text)
        out = html.unescape(out)

    # Normalise les espaces : multi-espaces -> 1 espace, multi-newlines -> max 2
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # Trim lignes individuelles
    lines = [line.rstrip() for line in out.split("\n")]
    # Retire les lignes consecutivement vides en debut/fin et milieu
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(line.strip())
    return "\n".join(cleaned).strip()
