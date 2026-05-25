"""Helper minimaliste pour scraper du HTML simple (regex-based).

Sprint D.26 v0.5.0 (note Louis N-LS2). Pour les providers comme
chasse-aux-livres.fr et leslibraires.ca qui n'ont pas d'API publique,
on scrape le HTML brut. Pas de BeautifulSoup pour rester leger.

Approche defensive :
- User-Agent realiste
- Timeout court (5-10s)
- Try/except partout, retourne None sur tout echec
- Logger en warning, jamais raise

Le scraping HTML est par nature fragile : si le site change ses templates,
les regex cassent. On accepte ce risque (sites changent rarement leur
structure principale).
"""
from __future__ import annotations

import re
from html import unescape


# User-Agent realiste pour eviter d'etre bloque comme un bot agressif.
# Identique au pattern de plein de scripts personnels.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_html(url: str, http_get=None, timeout: int = 10) -> str:
    """Fait un GET sur l'URL et retourne le HTML.

    Args:
        url : URL a fetcher.
        http_get : fonction HTTP injectable (pour les tests).
        timeout : timeout en secondes.

    Returns:
        HTML string ou "" sur echec.
    """
    if http_get is None:
        try:
            import requests
        except ImportError:
            print("[WARN] requests non installe pour scraping HTML.")
            return ""
        http_get = lambda u, **kw: requests.get(u, **kw)

    try:
        resp = http_get(
            url,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception as e:
        print(f"[WARN] HTML fetch ({url}) : {type(e).__name__} {e}")
        return ""

    try:
        if not getattr(resp, "ok", True):
            return ""
        return resp.text or ""
    except Exception:
        return ""


def extract_first(html: str, pattern: str, flags=re.IGNORECASE | re.DOTALL) -> str:
    """Extrait le 1er match d'une regex et le nettoie.

    Returns:
        Le contenu du 1er groupe match, ou "" si rien.
    """
    if not html or not pattern:
        return ""
    try:
        m = re.search(pattern, html, flags)
        if not m:
            return ""
        # Si la regex a un groupe, on prend le 1er groupe. Sinon, le full match.
        return _clean_html_content(m.group(1) if m.groups() else m.group(0))
    except (re.error, IndexError):
        return ""


def extract_all(html: str, pattern: str, flags=re.IGNORECASE | re.DOTALL) -> list[str]:
    """Extrait TOUS les matches d'une regex et les nettoie."""
    if not html or not pattern:
        return []
    try:
        return [
            _clean_html_content(m) for m in re.findall(pattern, html, flags)
        ]
    except re.error:
        return []


def _clean_html_content(text: str) -> str:
    """Nettoie un fragment HTML : retire tags inline, decode entites, trim."""
    if not text:
        return ""
    # Retire les tags inline (a, span, em, etc.)
    cleaned = re.sub(r"<[^>]+>", "", text)
    # Decode entites HTML
    cleaned = unescape(cleaned)
    # Compacte whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
