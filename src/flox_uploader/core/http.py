"""Wrapper HTTP avec retry exponentiel léger."""
from __future__ import annotations

import time

import requests

HTTP_TIMEOUT = 20
HTTP_MAX_RETRIES = 3


def http_get_with_retry(
    url: str,
    params: dict | None = None,
    timeout: int = HTTP_TIMEOUT,
    max_retries: int = HTTP_MAX_RETRIES,
) -> requests.Response:
    """GET avec retry exponentiel.

    Lot O.7 : backoff doux par defaut (1s, 2s — 4xx en general definitive
    n'a pas besoin de plus). Pour les 5xx (transient cote serveur, typique
    TMDB qui a des coupures occasionnelles), on rallonge a 3s, 6s, 12s
    pour donner du temps au service de se retablir.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            last_exc = e
            status = getattr(e.response, "status_code", 0) if e.response is not None else 0
            is_5xx = 500 <= status < 600
            if attempt < max_retries - 1:
                # Backoff plus long pour les 5xx transient.
                wait = (3 * (2 ** attempt)) if is_5xx else (1 + attempt)
                print(
                    f"[WARN] HTTP retry {attempt + 1}/{max_retries - 1} "
                    f"après erreur {status} : {e} (attente {wait}s)"
                )
                time.sleep(wait)
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                wait = 1 + attempt
                print(
                    f"[WARN] HTTP retry {attempt + 1}/{max_retries - 1} "
                    f"après erreur : {e} (attente {wait}s)"
                )
                time.sleep(wait)
    raise last_exc if last_exc else RuntimeError("http_get_with_retry failed")
