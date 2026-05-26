"""Upload d'images vers un host externe (imgbb + fallback Imgur).

Sprint D.19 v0.5.0 (note Louis Q3). Permet d'inclure les covers / previews
extraites localement dans le BBCode tracker, qui ne peut acceder qu'a des
URLs publiques (https://...).

Services utilises :
- imgbb (https://api.imgbb.com/) — principal, illimite en theorie mais
  rate-limit observe sur bursts (>~500 uploads/24h).
- Imgur (https://api.imgur.com/) — fallback Sprint D.42. Anonymous upload
  via Client-ID (pas d'auth user). Rate limit credit-based : 12500 credits/h
  (1 upload = 10 credits = 1250 uploads/h). Largement plus que imgbb.

Sprint D.42 v0.5.0 (feedback Louis) : strategie a 2 etages
1. Tente d'abord imgbb
2. Si imgbb retourne rate_limited=True ET IMGUR_CLIENT_ID est configure,
   on bascule sur Imgur pour cette upload precise.

Decision Louis : pas de cache. Re-upload a chaque prepare. Justification :
- Une prepare est rare (~1/jour max). Le ROI du cache est faible.
- Simplifie le code (pas de hash-tracking, pas de cache invalidation).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"
IMGUR_UPLOAD_URL = "https://api.imgur.com/3/image"

# Limite de taille imgbb : 32 MB par image (selon doc). On rejette avant
# de poster pour eviter une erreur HTTP 413.
IMGBB_MAX_BYTES = 32 * 1024 * 1024
# Limite Imgur : 10 MB pour PNG/JPEG anonyme.
IMGUR_MAX_BYTES = 10 * 1024 * 1024


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
    # Sprint D.42 v0.5.0 (feedback Louis) : host effectivement utilise.
    # "imgbb" / "imgur" / "" si echec. Permet au log + UI de tracer ou la
    # cover/preview a fini.
    host: str = ""


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

    # Marquer le host pour le success path final
    if isinstance(data, dict) and data.get("success"):
        pass  # le success path en bas ajoute host="imgbb"

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
        host="imgbb",
    )


def upload_to_imgur(
    image_path: Path,
    client_id: str,
    http_post=None,
    timeout: int = 30,
) -> ImgbbUploadResult:
    """Sprint D.42 v0.5.0 (feedback Louis) : upload via Imgur anonyme.

    Utilise comme fallback quand imgbb rate-limit. Imgur accepte les uploads
    anonymes via Client-ID (pas de Bearer token user requis).

    Doc : https://api.imgur.com/endpoints/image

    Args:
        image_path : path local de l'image.
        client_id : Imgur Client-ID (IMGUR_CLIENT_ID dans .env). A creer sur
            https://api.imgur.com/oauth2/addclient (Anonymous usage without
            authorization).
        http_post : injectable pour tests.
        timeout : timeout seconds.

    Returns:
        ImgbbUploadResult (reuse de la meme dataclass pour homogeneite).
        host="imgur" si success.
    """
    if not client_id:
        return ImgbbUploadResult(
            success=False, error="IMGUR_CLIENT_ID non configure.",
        )

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
    if size > IMGUR_MAX_BYTES:
        return ImgbbUploadResult(
            success=False,
            error=f"Image trop volumineuse : {size / 1024 / 1024:.1f} MB > 10 MB max Imgur.",
        )

    if http_post is None:
        try:
            import requests
        except ImportError:
            return ImgbbUploadResult(
                success=False, error="requests non installe.",
            )
        http_post = requests.post

    headers = {"Authorization": f"Client-ID {client_id}"}
    try:
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "application/octet-stream")}
            resp = http_post(
                IMGUR_UPLOAD_URL,
                files=files,
                headers=headers,
                timeout=timeout,
            )
    except Exception as e:
        return ImgbbUploadResult(
            success=False,
            error=f"Network error : {type(e).__name__} {e}",
        )

    try:
        data = resp.json()
    except Exception:
        body_preview = ""
        try:
            body_preview = resp.text[:200]
        except Exception:
            pass
        return ImgbbUploadResult(
            success=False,
            error=f"Reponse Imgur non JSON (HTTP {getattr(resp, 'status_code', '?')}) : {body_preview}",
        )

    if not isinstance(data, dict) or not data.get("success"):
        # Imgur error : {"data": {"error": "..."}, "status": N, "success": False}
        err_msg = ""
        try:
            err_data = data.get("data", {})
            if isinstance(err_data, dict):
                err_msg = err_data.get("error") or ""
                if isinstance(err_msg, dict):
                    err_msg = err_msg.get("message") or str(err_msg)
            err_msg = err_msg or data.get("message", "")
        except Exception:
            pass
        # Imgur rate limit : HTTP 429 ou "rate limit"
        is_rate_limited = (
            getattr(resp, "status_code", 0) == 429
            or "rate limit" in (err_msg or "").lower()
        )
        return ImgbbUploadResult(
            success=False,
            error=f"Imgur refus : {err_msg or 'unknown'}",
            rate_limited=is_rate_limited,
        )

    payload = data.get("data") or {}
    url = str(payload.get("link") or "")
    delete_hash = str(payload.get("deletehash") or "")
    if not url:
        return ImgbbUploadResult(
            success=False, error="Imgur : pas d'URL dans la reponse.",
        )

    return ImgbbUploadResult(
        success=True,
        url=url,
        delete_url=f"https://imgur.com/delete/{delete_hash}" if delete_hash else "",
        size=size,
        host="imgur",
    )


def upload_image(
    image_path: Path,
    imgbb_api_key: str = "",
    imgur_client_id: str = "",
    http_post=None,
    timeout: int = 30,
) -> ImgbbUploadResult:
    """Sprint D.42 v0.5.0 : strategie a 2 etages imgbb -> Imgur fallback.

    Tente d'abord imgbb. Si imgbb echoue avec rate_limited=True ET Imgur est
    configure, bascule sur Imgur. Sinon retourne l'echec imgbb tel quel.

    Si imgbb n'est pas configure (api_key vide), tente directement Imgur.

    Args:
        image_path : path de l'image a uploader.
        imgbb_api_key : cle imgbb (peut etre vide).
        imgur_client_id : Imgur Client-ID (peut etre vide).
        http_post : injectable pour tests (utilise pour les 2 hosts).
        timeout : timeout par requete.

    Returns:
        ImgbbUploadResult avec host="imgbb" ou "imgur" si success.
        Si les 2 echouent : success=False, error contient les 2 messages.
    """
    # Si imgbb pas configure, on saute direct sur Imgur.
    if not imgbb_api_key:
        if imgur_client_id:
            return upload_to_imgur(
                image_path, imgur_client_id,
                http_post=http_post, timeout=timeout,
            )
        return ImgbbUploadResult(
            success=False,
            error="Aucun host image configure (IMGBB_API_KEY + IMGUR_CLIENT_ID vides).",
        )

    # Tentative principale : imgbb
    result = upload_to_imgbb(
        image_path, imgbb_api_key,
        http_post=http_post, timeout=timeout,
    )
    if result.success:
        return result

    # Fallback Imgur seulement si imgbb a rate-limit ET Imgur configure
    if result.rate_limited and imgur_client_id:
        print(
            f"[INFO] imgbb rate-limit -> fallback Imgur pour {image_path.name}"
        )
        imgur_result = upload_to_imgur(
            image_path, imgur_client_id,
            http_post=http_post, timeout=timeout,
        )
        if imgur_result.success:
            return imgur_result
        # Si Imgur echoue aussi, on garde le rate_limited=True d'imgbb +
        # on agrege les 2 erreurs pour debug
        return ImgbbUploadResult(
            success=False,
            error=f"imgbb : {result.error} | Imgur fallback : {imgur_result.error}",
            rate_limited=True,
        )

    # Echec non-rate-limited OU pas de fallback Imgur configure -> retour
    # de l'echec imgbb tel quel.
    return result


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
