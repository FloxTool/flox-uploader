"""Upload d'images vers un host externe (imgbb).

Sprint D.19 v0.5.0 (note Louis Q3). Permet d'inclure les covers / previews
extraites localement dans le BBCode tracker, qui ne peut acceder qu'a des
URLs publiques (https://...).

Service utilise : imgbb (https://api.imgbb.com/)
- Gratuit, pas de rate limit pour usage perso
- API simple : POST multipart avec champ 'image' + parametre 'key' en query
- Retourne JSON avec 'data.url' = lien direct utilisable en BBCode
- Doc : https://api.imgbb.com/

Decision Louis : pas de cache. Re-upload a chaque prepare. Justification :
- Une prepare est rare (~1/jour max). Le ROI du cache est faible.
- Simplifie le code (pas de hash-tracking, pas de cache invalidation).
- Si l'user veut limiter les uploads, il desactive IMGBB_API_KEY temporairement.

Note : l'API imgbb accepte aussi le base64 en POST. On utilise multipart
file pour limiter l'usage RAM.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"

# Limite de taille imgbb : 32 MB par image (selon doc). On rejette avant
# de poster pour eviter une erreur HTTP 413.
IMGBB_MAX_BYTES = 32 * 1024 * 1024


@dataclass
class ImgbbUploadResult:
    """Resultat d'un upload imgbb. `success=False` si echec : `error` est rempli."""
    success: bool
    url: str = ""       # URL directe https://i.ibb.co/... a utiliser en BBCode
    delete_url: str = ""  # URL admin pour delete (gardee pour traçabilite)
    size: int = 0       # taille bytes
    error: str = ""     # message si echec
    # Sprint D.41 v0.5.0 (feedback Louis) : flag rate-limited explicite.
    # Permet au pipeline d'emettre un warning dedie + suggerer un re-prepare
    # plus tard. Distinct des autres echecs (cle invalide, fichier trop gros,
    # network down) qui n'ont aucun benefice a re-tenter.
    rate_limited: bool = False


def upload_to_imgbb(
    image_path: Path,
    api_key: str,
    http_post=None,
    timeout: int = 30,
) -> ImgbbUploadResult:
    """Upload une image vers imgbb et retourne l'URL publique.

    Args:
        image_path : path local de l'image a uploader.
        api_key : cle API imgbb (depuis IMGBB_API_KEY dans .env).
        http_post : fonction HTTP injectable (pour les tests). Signature
            (url, files, params, timeout) -> objet avec .ok, .status_code, .json().
            Defaut : requests.post.
        timeout : timeout en secondes (defaut 30).

    Returns:
        ImgbbUploadResult avec success=True+url si OK, success=False+error sinon.
        Ne plante jamais sur erreur reseau / fichier absent / key invalide.
    """
    if not api_key:
        return ImgbbUploadResult(success=False, error="IMGBB_API_KEY non configure.")

    if not image_path.is_file():
        return ImgbbUploadResult(
            success=False, error=f"Image absente : {image_path}",
        )

    try:
        size = image_path.stat().st_size
    except OSError as e:
        return ImgbbUploadResult(success=False, error=f"Stat echec : {e}")

    if size == 0:
        return ImgbbUploadResult(success=False, error="Image vide (0 bytes).")
    if size > IMGBB_MAX_BYTES:
        return ImgbbUploadResult(
            success=False,
            error=f"Image trop volumineuse : {size / 1024 / 1024:.1f} MB > 32 MB max imgbb.",
        )

    # Fonction HTTP par defaut : requests
    if http_post is None:
        try:
            import requests
        except ImportError:
            return ImgbbUploadResult(
                success=False, error="requests non installe.",
            )
        http_post = requests.post

    try:
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "application/octet-stream")}
            resp = http_post(
                IMGBB_UPLOAD_URL,
                files=files,
                params={"key": api_key},
                timeout=timeout,
            )
    except Exception as e:
        return ImgbbUploadResult(
            success=False,
            error=f"Network error : {type(e).__name__} {e}",
        )

    # Parse response
    try:
        data = resp.json()
    except Exception as e:
        # Pas de JSON : on degrade
        body_preview = ""
        try:
            body_preview = resp.text[:200]
        except Exception:
            pass
        return ImgbbUploadResult(
            success=False,
            error=f"Reponse imgbb non JSON (HTTP {getattr(resp, 'status_code', '?')}) : {body_preview}",
        )

    if not isinstance(data, dict) or not data.get("success"):
        # imgbb error : {"status_code":N, "error": {"message": "..."}}
        err_msg = ""
        try:
            err_msg = data.get("error", {}).get("message") or data.get("message", "")
        except Exception:
            pass
        # Sprint D.41 v0.5.0 (feedback Louis) : detection rate limit imgbb.
        # imgbb retourne HTTP 400 avec "Rate limit reached" dans error.message
        # (rare en usage normal mais arrive sur des bursts de previews).
        # Aussi : HTTP 429 standard.
        is_rate_limited = (
            getattr(resp, "status_code", 0) == 429
            or "rate limit" in (err_msg or "").lower()
            or "too many requests" in (err_msg or "").lower()
        )
        return ImgbbUploadResult(
            success=False,
            error=f"imgbb refus : {err_msg or 'unknown'}",
            rate_limited=is_rate_limited,
        )

    payload = data.get("data") or {}
    # Champs imgbb : url (direct image), display_url (page), delete_url
    url = str(payload.get("url") or payload.get("display_url") or "")
    delete_url = str(payload.get("delete_url") or "")

    if not url:
        return ImgbbUploadResult(
            success=False, error="imgbb : pas d'URL dans la reponse.",
        )

    return ImgbbUploadResult(
        success=True,
        url=url,
        delete_url=delete_url,
        size=size,
    )


def upload_batch_to_imgbb(
    image_paths: list[Path],
    api_key: str,
    http_post=None,
    inter_request_delay: float = 0.0,
) -> list[ImgbbUploadResult]:
    """Upload une liste d'images en sequence.

    Args:
        image_paths : liste de paths a uploader.
        api_key : cle API imgbb.
        http_post : injectable pour tests.
        inter_request_delay : seconds entre 2 uploads (anti-rate-limit
            preventif, defaut 0 = pas de delai).

    Returns:
        Liste de ImgbbUploadResult, dans le meme ordre que image_paths.
        Si une upload echoue, on continue avec les suivantes.
    """
    results: list[ImgbbUploadResult] = []
    for i, p in enumerate(image_paths):
        if i > 0 and inter_request_delay > 0:
            time.sleep(inter_request_delay)
        results.append(upload_to_imgbb(p, api_key, http_post=http_post))
    return results
