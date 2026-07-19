"""Client API Unit3D pour le tracker Gemini (G3MINI).

Trois responsabilites :

1. `check_duplicate(tmdb_id, size_bytes, release_name, ...)` : interroge
   `/api/torrents/filter` pour savoir si une release equivalente existe deja
   sur le tracker. Strategie en cascade :

   - Filtre principal : TMDB ID (`?tmdbId=X`). On recupere TOUS les torrents
     du film/episode et on compare leur taille a la notre.
   - Classification par delta de taille (le critere en or : un vrai doublon
     a la meme taille a l'octet pres) :
         delta < 0.1 %  -> CERTAIN     (abort silencieux par defaut)
         delta < 2 %    -> VERY_LIKELY (prompt CLI)
         delta < 10 %   -> AMBIGUOUS   (prompt CLI avec contexte)
         delta >= 10 %  -> NONE        (autre qualite, pas un doublon)
   - Fallback si TMDB ID indisponible : recherche par nom (`?name=...`)
     avec confirmation par taille.

2. `upload_torrent(payload, dry_run)` : POST multipart vers `/api/torrents/upload`.
   En mode dry_run, ne POST pas mais retourne ce qu'il aurait envoye pour
   validation visuelle avant le vrai upload.

3. `download_torrent(torrent_id, dest)` : GET `/api/torrents/download/{id}`.
   Le tracker retourne le .torrent avec l'announce URL personnalisee (passkey
   injectee). C'est ce fichier qu'on charge dans qBittorrent / rTorrent / Transmission.

Auth : `Authorization: Bearer <api_key>` sur toutes les requetes.

Le module ne sait rien du package_state ni du pipeline ; il prend en entree
des donnees primitives et retourne des dataclasses simples. La composition
avec package_state et l'UX (prompt CLI, etc.) vit dans `upload_orchestrator.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import requests


# ============================================================
# SEUILS DE CLASSIFICATION
# ============================================================
# Seuils en pourcentage de delta de taille entre notre torrent et celui du
# tracker. La taille est le critere en or : un vrai doublon a la meme taille
# a l'octet pres parce que les piece hashes sont calcules byte-by-byte.

DELTA_PCT_CERTAIN = 0.1       # < 0.1 % de delta -> doublon certain
DELTA_PCT_VERY_LIKELY = 2.0   # < 2 %   -> doublon tres probable
DELTA_PCT_AMBIGUOUS = 10.0    # < 10 %  -> ambigu (peut-etre meme rip avec metadata diff)
                              # >= 10 % -> autre qualite (1080p vs 2160p), pas un doublon


# ============================================================
# HELPERS DE VERIFICATION DEFENSIVE
# ============================================================

def _normalize_for_compare(name: str) -> str:
    """Normalise un release_name pour comparaison souple :
    - lowercase
    - separateurs '.' / '_' / '-' / espaces -> espaces
    - espaces multiples -> espace simple
    """
    s = name.lower()
    s = re.sub(r"[._\-\s]+", " ", s)
    return s.strip()


def _compute_delta_pct(our_size: int, their_size: int) -> float:
    """Delta de taille en pourcentage. Retourne float('inf') si incomparable."""
    if our_size <= 0 or their_size <= 0:
        return float("inf")
    return abs(our_size - their_size) / max(our_size, their_size) * 100.0


def _classify_delta(
    delta_pct: float,
    our_size: int,
    their_size: int,
    our_release_name: str = "",
    their_release_name: str = "",
) -> "DupConfidence":
    """Classifie un candidat selon le delta de taille avec le notre, en
    croisant avec team et resolution si disponibles.

    Regles :
    - Tailles inconnues -> AMBIGUOUS
    - Resolution differente connue de chaque cote -> NONE (pas un doublon, c'est
      juste un autre rip de meme contenu).
    - Team differente connue de chaque cote -> downgrade :
        CERTAIN -> AMBIGUOUS
        VERY_LIKELY -> AMBIGUOUS
        (le size match est suspect : si team differente, ce n'est probablement
        pas le meme rip, juste une coincidence sur la taille)
    """
    if our_size <= 0 or their_size <= 0:
        return DupConfidence.AMBIGUOUS

    # Classification de base sur la taille
    if delta_pct < DELTA_PCT_CERTAIN:
        base = DupConfidence.CERTAIN
    elif delta_pct < DELTA_PCT_VERY_LIKELY:
        base = DupConfidence.VERY_LIKELY
    elif delta_pct < DELTA_PCT_AMBIGUOUS:
        base = DupConfidence.AMBIGUOUS
    else:
        return DupConfidence.NONE

    # Cross-check resolution : si elles sont connues des deux cotes ET differentes,
    # ce n'est PAS un doublon (c'est juste un autre encodage). On retourne NONE.
    our_res = _extract_resolution(our_release_name)
    their_res = _extract_resolution(their_release_name)
    if our_res and their_res and our_res != their_res:
        return DupConfidence.NONE

    # Cross-check team : si differentes, le size match est suspect -> on
    # downgrade vers AMBIGUOUS (au mieux). Le user verifie a la main.
    our_team = _extract_team(our_release_name).lower()
    their_team = _extract_team(their_release_name).lower()
    if our_team and their_team and our_team != their_team:
        if base in {DupConfidence.CERTAIN, DupConfidence.VERY_LIKELY}:
            return DupConfidence.AMBIGUOUS

    return base


def _extract_resolution(release_name: str) -> str:
    """Extrait '720p' / '1080p' / '2160p' / '480p' depuis un release_name.
    Retourne '' si rien trouve."""
    if not release_name:
        return ""
    m = re.search(r"\b(2160p|1440p|1080p|720p|576p|480p|360p)\b", release_name)
    return m.group(1) if m else ""


def _extract_team(release_name: str) -> str:
    """Extrait le team (suffixe apres le dernier '-') d'un release_name.
    Retourne '' si pas de team apparente."""
    if not release_name:
        return ""
    # Le team est ce qui suit le DERNIER tiret, et ne doit pas contenir d'espaces
    # ni etre une annee/saison. Ex: 'Foo.2024.1080p.x265-QTZ' -> 'QTZ'
    m = re.search(r"-([A-Za-z0-9]+)\s*$", release_name.strip())
    return m.group(1) if m else ""


def _name_matches(returned: str, searched: str) -> bool:
    """Vrai si le nom retourne par l'API "ressemble" assez au nom recherche.

    Critere : apres normalisation, soit egalite stricte, soit le nom recherche
    est un prefixe (cas typique : l'API retourne 'Foo.2024.1080p.BluRay-X' alors
    qu'on cherchait 'Foo.2024.1080p'). On ne tolere PAS les noms totalement
    disjoints (ex: 'Welcome.to.Demon.School' vs 'GOAT.2026') qui sont des faux
    positifs evidents quand le filtre API est ignore.
    """
    if not returned or not searched:
        return False
    a = _normalize_for_compare(returned)
    b = _normalize_for_compare(searched)
    if a == b:
        return True
    # Tolere prefixe ou inclusion partielle bidirectionnelle si chevauchement
    # significatif (au moins le titre + l'annee doivent matcher).
    if a.startswith(b) or b.startswith(a):
        return True
    # Chevauchement de tokens significatifs (titre+annee minimum)
    tokens_a = set(t for t in a.split() if len(t) >= 3)
    tokens_b = set(t for t in b.split() if len(t) >= 3)
    if not tokens_a or not tokens_b:
        return False
    overlap = tokens_a & tokens_b
    # On exige au moins 3 tokens communs (= titre + annee + au moins 1 spec)
    # pour eviter les faux positifs sur 1 ou 2 mots communs accidentels.
    return len(overlap) >= 3


# ============================================================
# EXCEPTIONS & DATACLASSES
# ============================================================

class GeminiAPIError(Exception):
    """Erreur generique cote API Gemini."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class DupConfidence(str, Enum):
    """Niveau de certitude qu'un torrent du tracker est un doublon du notre.

    Decoule du delta de taille uniquement (le nom est utilise pour le matching
    initial mais pas pour la classification de confiance).
    """
    CERTAIN = "certain"           # delta < 0.1 % : meme taille = meme contenu
    VERY_LIKELY = "very_likely"   # delta < 2 %   : tres probable, prompt utilisateur
    AMBIGUOUS = "ambiguous"       # delta < 10 %  : ambigu, prompt avec contexte
    NONE = "none"                 # delta >= 10 % : autre qualite, pas un doublon


@dataclass
class DuplicateCandidate:
    """Un torrent du tracker qui a passe le filtre initial (TMDB ou nom)."""

    torrent_id: int
    name: str
    url: str
    size_bytes: int
    delta_pct: float                        # |notre - leur| / max * 100
    confidence: DupConfidence
    info_hash: str = ""                     # purement informatif (debug)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DuplicateCheckResult:
    """Resultat de check_duplicate.

    Convention : `confidence` est le niveau le plus haut parmi les candidats.
    `candidates` est trie par delta_pct croissant (le plus proche en premier)
    et filtre pour ne contenir que les confidence != NONE.
    """

    confidence: DupConfidence = DupConfidence.NONE
    candidates: list[DuplicateCandidate] = field(default_factory=list)
    matched_via: Literal["tmdb", "name", None] = None
    note: str = ""                          # diagnostic libre (warns, mode degrade...)

    @property
    def is_duplicate(self) -> bool:
        """Vrai si on a au moins un candidat avec confidence CERTAIN ou VERY_LIKELY."""
        return self.confidence in {DupConfidence.CERTAIN, DupConfidence.VERY_LIKELY}

    @property
    def needs_review(self) -> bool:
        """Vrai si on a des candidats AMBIGUOUS qui meritent une decision humaine."""
        return self.confidence == DupConfidence.AMBIGUOUS

    @property
    def primary(self) -> DuplicateCandidate | None:
        """Le candidat le plus proche en taille (None si liste vide)."""
        return self.candidates[0] if self.candidates else None

    # Champs de retro-compatibilite : certains tests / UX historiques attendent
    # ces noms. On les expose en lecture, derives du primary.
    @property
    def existing_torrent_id(self) -> int | None:
        return self.primary.torrent_id if self.primary else None

    @property
    def existing_torrent_name(self) -> str:
        return self.primary.name if self.primary else ""

    @property
    def existing_torrent_url(self) -> str:
        return self.primary.url if self.primary else ""


@dataclass
class UploadPayload:
    """Donnees a soumettre lors d'un upload Unit3D.

    Les champs reflechtent l'API standard Unit3D (cf. doc tracker). Certains
    sont specifiques au tracker (category_id, type_id, resolution_id) et leur
    valeur exacte sera decouverte aux dry-runs ; on garde les types souples.

    Les fichiers (torrent_path, nfo_path) sont passes sous forme de Path et
    seront ouverts au moment du POST en mode binary.
    """

    name: str
    description: str
    mediainfo: str
    torrent_path: Path

    # IDs externes (TMDB et IMDB sont obligatoires sur la plupart des Unit3D ;
    # TVDB / MAL / IGDB selon le contenu)
    tmdb_id: int = 0
    imdb_id: int = 0           # numerique, sans le prefixe 'tt'
    tvdb_id: int = 0
    mal_id: int = 0
    igdb_id: int = 0

    # Categorisation cote tracker
    category_id: int = 0       # 1=Film, 2=TV (typique Unit3D, a confirmer G3MINI)
    type_id: int = 0           # ex: REMUX / Encode / WEB-DL
    resolution_id: int = 0     # ex: 1=2160p, 2=1080p (a confirmer)

    # Saison / episode (TV uniquement)
    season_number: int = 0
    episode_number: int = 0

    # Flags d'upload
    anonymous: bool = False
    stream: bool = False
    sd: bool = False
    personal_release: bool = False
    internal: bool = False
    free: bool = False
    doubleup: bool = False
    featured: bool = False
    sticky: bool = False

    # Optionnel : fichier .nfo a joindre
    nfo_path: Path | None = None

    # Champs custom potentiels (region, distributor, etc.) pour G3MINI : on
    # laisse une porte ouverte plutot que de bloquer si un champ est requis
    # qu'on n'avait pas anticipe.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_form_data(self) -> dict[str, Any]:
        """Serialise le payload en dict pret pour requests `data=`.

        Les bool sont convertis en 0/1 (convention Unit3D). Les Path ne sont
        PAS inclus ici (ils vont dans `files=`).

        IMPORTANT : `season_number` et `episode_number` ne sont inclus que pour
        les categories « Serie (TMDB) : oui » (2 Series, 6 Series Animations,
        14 Series Documentaires, 15 Emission TV — cf. TORRENT_API.txt p.4).
        Pour un film, Laravel les rejette (regle `prohibited_if`).

        R3 (audit AUDIT_2026-07-19) : avant, seule la cat 2 les envoyait, si
        bien qu'une serie d'animation/docu/emission TV (auto-detectee ou
        choisie) partait SANS meta saison/episode -> rejet API ou mauvaise
        indexation. On couvre desormais les 4 categories serie.
        """
        from ..trackers.gemini.unit3d_mapping import SERIES_META_CATEGORIES
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "mediainfo": self.mediainfo,
            "tmdb": self.tmdb_id,
            "imdb": self.imdb_id,
            "tvdb": self.tvdb_id,
            "mal": self.mal_id,
            "igdb": self.igdb_id,
            "category_id": self.category_id,
            "type_id": self.type_id,
            "resolution_id": self.resolution_id,
            "anonymous": int(self.anonymous),
            "stream": int(self.stream),
            "sd": int(self.sd),
            "personal_release": int(self.personal_release),
            "internal": int(self.internal),
            "free": int(self.free),
            "doubleup": int(self.doubleup),
            "featured": int(self.featured),
            "sticky": int(self.sticky),
        }
        # Champs TV : pour toutes les categories serie (2/6/14/15). Sur un
        # film, Laravel les rejette s'ils sont presents avec une valeur.
        # Convention : on ne met les cles dans le dict que si on est en serie.
        # On les met meme a 0 (laissera Laravel valider la presence/coherence
        # selon le sous-type episode/saison/integrale).
        if self.category_id in SERIES_META_CATEGORIES:
            d["season_number"] = self.season_number
            d["episode_number"] = self.episode_number
        d.update(self.extra)
        return d


@dataclass
class UploadResult:
    success: bool
    torrent_id: int | None = None
    torrent_url: str = ""           # URL de la page details (pour affichage)
    download_url: str = ""          # URL directe du .torrent (avec passkey embarquee)
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    # En mode dry_run : ce qu'on aurait POST. None en mode reel.
    dry_run_payload: dict[str, Any] | None = None


def _parse_torrent_id_from_url(url: str) -> int | None:
    """Extrait le torrent_id depuis une URL de download Unit3D.

    Formats observes (l'API Gemini est inconstante sur singulier/pluriel
    et sur le separateur post-id) :
    - /torrents/download/12345.torrent?passkey=...        (pluriel + .torrent + query)
    - /torrents/download/12345?passkey=...                (pluriel + sans .torrent)
    - /torrents/12345                                      (page details)
    - /torrents/download/12345/<passkey>                   (path-style passkey)
    - /torrent/download/12345.<passkey>                    (SINGULIER + . suivi de passkey
                                                            32-char — format observe
                                                            chez Gemini en v0.3.13)

    Sprint 8 hotfix v14 : on accepte aussi 'torrent' singulier et le `.`
    comme separateur post-id (cas reel Gemini). Strategie en 3 passes.
    """
    if not url:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path or ""

    # Passe 1 : pattern "/torrent[s]/<id>" ou "/torrent[s]/download/<id>"
    # (la forme la plus specifique en premier — evite de matcher d'autres
    # nombres dans le path). Accepte le pluriel ET le singulier.
    # Apres l'id, on accepte n'importe quoi qui n'est pas un digit
    # (`.passkey`, `.torrent`, `/passkey`, `?query`, `#frag`, fin).
    m = re.search(r"/torrents?/(?:download/)?(\d+)(?=\D|$)", path)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass

    # Passe 2 : pattern generique "/<id>" (id suivi de n'importe quel
    # non-digit ou fin). Utilise findall + le dernier match pour gerer
    # les paths qui contiennent plusieurs nombres (ex: /api/v2/torrents/12345
    # — on veut 12345, pas 2).
    matches = re.findall(r"/(\d+)(?=\D|$)", path)
    if matches:
        try:
            return int(matches[-1])
        except ValueError:
            pass

    # Passe 3 : echec — on log pour debug et on retourne None.
    print(
        f"[WARN] _parse_torrent_id_from_url : aucun id parsable dans le path "
        f"'{path}' (URL complete : '{url}'). Le lien 'Voir sur Gemini' ne "
        f"s'affichera pas sur la page detail. Merci de partager cette URL "
        f"pour qu'on adapte le parser."
    )
    return None


# ============================================================
# CLIENT
# ============================================================

class GeminiClient:
    """Wrapper minimaliste autour de l'API Unit3D du tracker Gemini.

    Usage :
        client = GeminiClient(api_url="https://gemini-tracker.org/api", api_key="...")
        dup = client.check_duplicate(infohash="abc...", release_name="Foo.2024.1080p...")
        if not dup.is_duplicate:
            result = client.upload_torrent(payload, dry_run=True)
    """

    DEFAULT_TIMEOUT = 30  # secondes

    def __init__(self, api_url: str, api_key: str, timeout: int | None = None):
        if not api_url:
            raise ValueError("api_url est requis (ex: https://gemini-tracker.org/api)")
        if not api_key:
            raise ValueError("api_key est requis")
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    # ------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _handle_error_response(self, resp: requests.Response, operation: str) -> None:
        """Convertit une reponse HTTP en erreur lisible."""
        body_excerpt = (resp.text or "")[:500]
        # Gemini/Unit3D renvoie parfois 404 pour signaler une erreur de
        # validation Laravel (cf. fork upload.py, gestion explicite du 404).
        # On parse le JSON pour extraire les messages champ-par-champ.
        if resp.status_code in (404, 422):
            errors_msg = self._format_validation_errors(resp)
            raise GeminiAPIError(
                f"{operation} : {resp.status_code} Validation Error. {errors_msg}",
                status_code=resp.status_code, body=body_excerpt,
            )
        if resp.status_code == 401:
            raise GeminiAPIError(
                f"{operation} : 401 Unauthorized. Cle API invalide ou expiree.",
                status_code=401, body=body_excerpt,
            )
        if resp.status_code == 403:
            raise GeminiAPIError(
                f"{operation} : 403 Forbidden. Rang utilisateur insuffisant ?",
                status_code=403, body=body_excerpt,
            )
        if resp.status_code == 429:
            raise GeminiAPIError(
                f"{operation} : 429 Too Many Requests. Ralentir le rythme.",
                status_code=429, body=body_excerpt,
            )
        if 500 <= resp.status_code < 600:
            raise GeminiAPIError(
                f"{operation} : {resp.status_code} Server Error. {body_excerpt}",
                status_code=resp.status_code, body=body_excerpt,
            )
        raise GeminiAPIError(
            f"{operation} : statut {resp.status_code} inattendu. {body_excerpt}",
            status_code=resp.status_code, body=body_excerpt,
        )

    @staticmethod
    def _format_validation_errors(resp: requests.Response) -> str:
        """Parse une reponse Laravel de validation et formate les erreurs
        champ-par-champ pour lisibilite."""
        try:
            body = resp.json()
        except ValueError:
            return (resp.text or "")[:300]
        if not isinstance(body, dict):
            return str(body)[:300]
        msg = body.get("message", "")
        # Laravel retourne typiquement {"data": {"field": ["msg1", "msg2"]}}
        # ou {"errors": {"field": [...]}}.
        errors = body.get("data") or body.get("errors") or {}
        if not isinstance(errors, dict):
            return f"{msg} | {errors}"
        if not errors:
            return msg or str(body)[:300]
        details = "; ".join(
            f"{k}: {', '.join(v) if isinstance(v, list) else v}"
            for k, v in errors.items()
        )
        return f"{msg} -> {details}" if msg else details

    # ------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------

    def check_duplicate(
        self,
        tmdb_id: int = 0,
        size_bytes: int = 0,
        release_name: str = "",
        is_tv: bool = False,
    ) -> DuplicateCheckResult:
        """Cherche un doublon en cascade : TMDB ID -> taille en confirmation.

        Strategie :

        1. Si tmdb_id > 0 : interroge `?tmdbId=X` (ou `?tvdbId=X` selon le type
           de media plus tard) et recupere TOUS les torrents lies. C'est le
           filtre le plus fiable car le tracker indexe explicitement le TMDB ID.

        2. Pour chaque candidat retourne, on calcule le delta de taille avec
           le notre. La taille est le critere de verite : un vrai doublon a
           la meme taille a l'octet pres.

        3. Classification :
              delta < DELTA_PCT_CERTAIN     -> CERTAIN
              delta < DELTA_PCT_VERY_LIKELY -> VERY_LIKELY
              delta < DELTA_PCT_AMBIGUOUS   -> AMBIGUOUS
              delta >= DELTA_PCT_AMBIGUOUS  -> NONE (autre qualite, pas un doublon)

        4. Fallback si tmdb_id absent ou aucune correspondance pertinente :
           recherche par nom (`?name=X`), avec verification fuzzy + meme
           classification par taille.

        Retourne un DuplicateCheckResult. La liste de candidats est triee par
        delta croissant (le plus proche en premier).

        Si tmdb_id == 0 ET release_name vide : leve ValueError.
        """
        if tmdb_id <= 0 and not release_name:
            raise ValueError(
                "check_duplicate: il faut au moins un tmdb_id > 0 ou un release_name"
            )

        url = f"{self.api_url}/torrents/filter"

        # 1) Filtre principal : TMDB ID
        # NOTE: Unit3D utilise `tmdbId` en camelCase (verifie sur Unit3Dup-G3MINI/pvtTracker.py).
        candidates: list[DuplicateCandidate] = []
        matched_via: Literal["tmdb", "name", None] = None
        notes: list[str] = []

        if tmdb_id > 0:
            try:
                resp = requests.get(
                    url,
                    headers=self._headers(),
                    params={"tmdbId": tmdb_id},
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                raise GeminiAPIError(
                    f"check_duplicate (tmdb) : erreur reseau : {e}"
                ) from e

            if resp.status_code == 200:
                hits = self._extract_all_matches(resp.json())
                # Verification defensive : le tracker doit retourner des torrents
                # dont le tmdb_id correspond. Sinon = filtre ignore (faux positifs).
                verified = [h for h in hits if self._extract_tmdb_id(h) == tmdb_id]
                if hits and not verified:
                    notes.append(
                        f"L'API a renvoye {len(hits)} resultat(s) sur ?tmdbId={tmdb_id} "
                        f"mais aucun n'a le bon tmdb_id (filtre probablement ignore). "
                        f"On bascule sur la recherche par nom."
                    )
                else:
                    if verified:
                        matched_via = "tmdb"
                        candidates = self._build_candidates(verified, size_bytes, our_release_name=release_name)
            elif resp.status_code != 404:
                self._handle_error_response(resp, "check_duplicate (tmdb)")

        # 2) Fallback nom : utilise si TMDB n'a rien donne ET on a un release_name
        if not candidates and release_name:
            try:
                # Astuce Unit3Dup : remplacer '-' par espace pour matcher plus largement
                # ('Foo.2024.x265-TEAM' -> 'Foo.2024.x265 TEAM' qui matche un LIKE %name%)
                search_name = release_name.replace("-", " ")
                resp = requests.get(
                    url,
                    headers=self._headers(),
                    params={"name": search_name},
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                raise GeminiAPIError(
                    f"check_duplicate (name) : erreur reseau : {e}"
                ) from e

            if resp.status_code == 200:
                hits = self._extract_all_matches(resp.json())
                # On filtre defensivement : noms qui partagent au moins le titre+annee
                name_filtered = [
                    h for h in hits
                    if _name_matches(self._extract_name(h), release_name)
                ]
                if hits and not name_filtered:
                    notes.append(
                        f"L'API a renvoye {len(hits)} resultat(s) sur ?name= mais "
                        f"aucun ne ressemble assez au release_name (filtre ignore "
                        f"ou faux positifs). Pas de doublon detecte."
                    )
                if name_filtered:
                    matched_via = "name"
                    candidates = self._build_candidates(name_filtered, size_bytes, our_release_name=release_name)
            elif resp.status_code != 404:
                self._handle_error_response(resp, "check_duplicate (name)")

        # 3) Filtrage final : ne garder que les candidats avec confidence != NONE,
        # tries par delta croissant.
        candidates = [c for c in candidates if c.confidence != DupConfidence.NONE]
        candidates.sort(key=lambda c: c.delta_pct)

        if not candidates:
            return DuplicateCheckResult(
                confidence=DupConfidence.NONE,
                candidates=[],
                matched_via=matched_via,
                note=" | ".join(notes),
            )

        return DuplicateCheckResult(
            confidence=candidates[0].confidence,    # le plus haut = le plus proche
            candidates=candidates,
            matched_via=matched_via,
            note=" | ".join(notes),
        )

    # ------------------------------------------------------------
    # Helpers d'extraction (un torrent = "hit")
    # ------------------------------------------------------------

    def _build_candidates(
        self,
        hits: list[dict[str, Any]],
        our_size_bytes: int,
        our_release_name: str = "",
    ) -> list[DuplicateCandidate]:
        """Convertit une liste de hits API en candidats classifies par delta."""
        out: list[DuplicateCandidate] = []
        for h in hits:
            their_size = self._extract_size(h)
            their_name = self._extract_name(h)
            delta_pct = _compute_delta_pct(our_size_bytes, their_size)
            confidence = _classify_delta(
                delta_pct, our_size_bytes, their_size,
                our_release_name=our_release_name,
                their_release_name=their_name,
            )
            out.append(DuplicateCandidate(
                torrent_id=self._extract_id(h) or 0,
                name=their_name,
                url=self._extract_url(h),
                size_bytes=their_size,
                delta_pct=delta_pct,
                confidence=confidence,
                info_hash=self._extract_infohash_from_hit(h),
                raw=h,
            ))
        return out

    @staticmethod
    def _extract_all_matches(body: Any) -> list[dict[str, Any]]:
        """Retourne tous les torrents dans une reponse Unit3D, peu importe le format."""
        if not isinstance(body, dict):
            return []
        data = body.get("data")
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    @staticmethod
    def _extract_first_match(body: dict[str, Any]) -> dict[str, Any] | None:
        """(legacy) Premier match seulement. Conserve pour compat des helpers."""
        matches = GeminiClient._extract_all_matches(body)
        return matches[0] if matches else None

    @staticmethod
    def _extract_size(hit: dict[str, Any]) -> int:
        """Recupere la taille en octets du torrent. 0 si absente."""
        for key in ("size", "size_bytes"):
            v = hit.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        attrs = hit.get("attributes") or {}
        if isinstance(attrs, dict):
            for key in ("size", "size_bytes"):
                v = attrs.get(key)
                if v is not None:
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        pass
        return 0

    @staticmethod
    def _extract_tmdb_id(hit: dict[str, Any]) -> int:
        """Recupere le tmdb_id d'un hit (top-level ou attributes). 0 si absent."""
        for key in ("tmdb_id", "tmdbId", "tmdb"):
            v = hit.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        attrs = hit.get("attributes") or {}
        if isinstance(attrs, dict):
            for key in ("tmdb_id", "tmdbId", "tmdb"):
                v = attrs.get(key)
                if v is not None:
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        pass
        return 0

    @staticmethod
    def _extract_infohash_from_hit(hit: dict[str, Any]) -> str:
        """Recupere l'infohash d'un torrent hit (purement informatif/debug)."""
        for key in ("info_hash", "infohash", "hash"):
            v = hit.get(key)
            if v:
                return str(v)
        attrs = hit.get("attributes") or {}
        if isinstance(attrs, dict):
            for key in ("info_hash", "infohash", "hash"):
                v = attrs.get(key)
                if v:
                    return str(v)
        return ""

    @staticmethod
    def _extract_id(hit: dict[str, Any]) -> int | None:
        v = hit.get("id") or (hit.get("attributes") or {}).get("id")
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_name(hit: dict[str, Any]) -> str:
        return (
            hit.get("name")
            or (hit.get("attributes") or {}).get("name", "")
            or ""
        )

    @staticmethod
    def _extract_url(hit: dict[str, Any]) -> str:
        return (
            hit.get("url")
            or (hit.get("attributes") or {}).get("details_link", "")
            or ""
        )

    # ------------------------------------------------------------
    # Upload + download
    # ------------------------------------------------------------

    def upload_torrent(
        self,
        payload: UploadPayload,
        dry_run: bool = False,
    ) -> UploadResult:
        """POST le .torrent + metadata vers le tracker.

        En mode dry_run, ne fait AUCUN appel reseau et retourne un
        UploadResult avec `dry_run_payload` rempli pour inspection.
        """
        if not payload.torrent_path.is_file():
            raise FileNotFoundError(
                f"Fichier .torrent introuvable : {payload.torrent_path}"
            )

        form_data = payload.to_form_data()

        if dry_run:
            preview = dict(form_data)
            preview["_torrent_file"] = str(payload.torrent_path)
            preview["_torrent_size_bytes"] = payload.torrent_path.stat().st_size
            if payload.nfo_path is not None and payload.nfo_path.is_file():
                preview["_nfo_file"] = str(payload.nfo_path)
                preview["_nfo_size_bytes"] = payload.nfo_path.stat().st_size
            return UploadResult(
                success=True,
                message="DRY-RUN : payload prepare, aucun POST envoye.",
                dry_run_payload=preview,
            )

        url = f"{self.api_url}/torrents/upload"
        files: dict[str, tuple[str, Any, str]] = {}
        torrent_handle = open(payload.torrent_path, "rb")
        try:
            files["torrent"] = (
                payload.torrent_path.name, torrent_handle, "application/x-bittorrent",
            )
            nfo_handle = None
            if payload.nfo_path is not None and payload.nfo_path.is_file():
                nfo_handle = open(payload.nfo_path, "rb")
                files["nfo"] = (
                    payload.nfo_path.name, nfo_handle, "text/x-nfo",
                )
            try:
                resp = requests.post(
                    url,
                    headers=self._headers(),
                    data=form_data,
                    files=files,
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                raise GeminiAPIError(
                    f"upload_torrent : erreur reseau : {e}"
                ) from e
            finally:
                if nfo_handle is not None:
                    nfo_handle.close()
        finally:
            torrent_handle.close()

        if resp.status_code in (200, 201):
            try:
                body = resp.json()
            except ValueError:
                body = {"raw_text": resp.text}

            torrent_id: int | None = None
            torrent_url = ""
            download_url = ""

            if isinstance(body, dict):
                data = body.get("data")

                # Format Gemini observe : `data` est une URL string (lien direct
                # vers le .torrent avec passkey). On extrait l'id depuis l'URL.
                if isinstance(data, str):
                    download_url = data
                    torrent_id = _parse_torrent_id_from_url(download_url)
                    if torrent_id is not None:
                        # Construit l'URL de la page details : on retire `/api`
                        # de l'api_url puis on append `/torrents/{id}`.
                        base = self.api_url
                        if base.endswith("/api"):
                            base = base[:-4]
                        torrent_url = f"{base.rstrip('/')}/torrents/{torrent_id}"

                # Format JSON:API legacy : data est un dict (ou liste) avec
                # id + attributes. Garde pour compat.
                elif isinstance(data, (dict, list)):
                    if isinstance(data, list) and data:
                        data = data[0]
                    if not isinstance(data, dict):
                        data = {}
                    attrs = data.get("attributes") if isinstance(data, dict) else {}
                    if not isinstance(attrs, dict):
                        attrs = {}
                    raw_id = data.get("id") or attrs.get("id") or body.get("id")
                    try:
                        torrent_id = int(raw_id) if raw_id else None
                    except (TypeError, ValueError):
                        torrent_id = None
                    torrent_url = (
                        attrs.get("details_link")
                        or data.get("url")
                        or body.get("url", "")
                        or ""
                    )

            return UploadResult(
                success=True,
                torrent_id=torrent_id,
                torrent_url=torrent_url,
                download_url=download_url,
                message=(
                    body.get("message", "Upload reussi")
                    if isinstance(body, dict) else "Upload reussi"
                ),
                raw=body if isinstance(body, dict) else {"raw_text": str(body)},
            )

        self._handle_error_response(resp, "upload_torrent")
        return UploadResult(success=False, message="Erreur upload")  # unreachable

    def download_torrent_from_url(self, url: str, dest_path: Path) -> Path:
        """Telecharge le .torrent via une URL directe (passkey embarquee).

        Utilise quand l'API d'upload retourne une URL pre-signed (cas Gemini).
        Pas d'header Authorization car la passkey est dans le query string.
        """
        if not url:
            raise ValueError("URL vide")
        try:
            resp = requests.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise GeminiAPIError(
                f"download_torrent_from_url : erreur reseau : {e}"
            ) from e
        if resp.status_code != 200:
            self._handle_error_response(resp, "download_torrent_from_url")
        content = resp.content
        if not content.startswith(b"d"):
            raise GeminiAPIError(
                "download_torrent_from_url : reponse non-bencode. Le tracker a "
                "peut-etre renvoye une page HTML d'erreur au lieu du .torrent."
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)
        return dest_path

    def download_torrent(self, torrent_id: int, dest_path: Path) -> Path:
        """Telecharge le .torrent final via GET /api/torrents/download/{id}.

        Utilise auth bearer. Fallback quand on n'a que l'id (pas l'URL pre-signed).
        Retourne le chemin du fichier ecrit (== dest_path).
        """
        if torrent_id <= 0:
            raise ValueError(f"torrent_id invalide : {torrent_id}")
        url = f"{self.api_url}/torrents/download/{torrent_id}"
        try:
            resp = requests.get(
                url, headers=self._headers(), timeout=self.timeout, stream=True,
            )
        except requests.RequestException as e:
            raise GeminiAPIError(f"download_torrent : erreur reseau : {e}") from e
        if resp.status_code != 200:
            self._handle_error_response(resp, "download_torrent")
        content = resp.content
        if not content.startswith(b"d"):
            raise GeminiAPIError(
                "download_torrent : reponse non-bencode. Le tracker a peut-etre "
                "renvoye une page HTML d'erreur au lieu du .torrent."
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)
        return dest_path

    def get_torrent(self, torrent_id: int) -> dict[str, Any]:
        """Recupere les attributes d'un torrent existant via GET /api/torrents/{id}."""
        if torrent_id <= 0:
            raise ValueError(f"torrent_id invalide : {torrent_id}")
        url = f"{self.api_url}/torrents/{torrent_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise GeminiAPIError(f"get_torrent : erreur reseau : {e}") from e
        if resp.status_code != 200:
            self._handle_error_response(resp, "get_torrent")
        try:
            body = resp.json()
        except ValueError:
            raise GeminiAPIError("get_torrent : reponse non-JSON")
        data = body.get("data") if isinstance(body, dict) else {}
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return {"_raw": body}
        attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        return {"id": data.get("id"), **attrs, "_raw": data}
