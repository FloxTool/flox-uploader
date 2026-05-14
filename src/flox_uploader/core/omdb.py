"""OMDb : note IMDb + poster + awards + plot."""
from __future__ import annotations

from .debug import Debug
from .http import http_get_with_retry

OMDB_URL = "https://www.omdbapi.com/"


def fetch_omdb_data(imdb_id: str, api_key: str, debug: Debug) -> dict:
    """Recupere donnees depuis OMDb (gratuit ~1000 req/jour)."""
    result = {
        "imdb_rating": "", "imdb_vote_count": 0,
        "poster_url": "", "awards": "", "plot": "",
    }

    if not imdb_id:
        return result
    if not api_key:
        debug.set("omdb_skipped_reason", "OMDB_API_KEY absent")
        return result

    try:
        resp = http_get_with_retry(
            OMDB_URL,
            params={"i": imdb_id, "apikey": api_key, "plot": "full"},
            timeout=10,
        )
        data = resp.json()
    except Exception as e:
        debug.set("omdb_error", f"{e}")
        return result

    if data.get("Response") != "True":
        debug.set("omdb_response_error", data.get("Error", "Unknown error"))
        return result

    rating = str(data.get("imdbRating", "")).strip()
    if rating and rating != "N/A":
        result["imdb_rating"] = f"{rating}/10"

    votes = str(data.get("imdbVotes", "")).strip()
    if votes and votes != "N/A":
        try:
            result["imdb_vote_count"] = int(votes.replace(",", "").replace(".", ""))
        except (TypeError, ValueError):
            result["imdb_vote_count"] = 0

    poster = str(data.get("Poster", "")).strip()
    if poster and poster != "N/A":
        result["poster_url"] = poster

    awards = str(data.get("Awards", "")).strip()
    if awards and awards.upper() not in {"N/A", "NONE"}:
        result["awards"] = awards

    plot = str(data.get("Plot", "")).strip()
    if plot and plot != "N/A":
        result["plot"] = plot

    return result


def pick_best_poster_url(tmdb_context, omdb_poster_url: str) -> str:
    """Priorite TMDB taille original > OMDb."""
    if tmdb_context:
        tmdb_poster = (tmdb_context.get("tmdb_poster_path") or "").strip()
        if tmdb_poster:
            return f"https://image.tmdb.org/t/p/original{tmdb_poster}"
    return omdb_poster_url or ""
