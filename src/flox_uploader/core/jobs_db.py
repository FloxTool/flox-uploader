"""Persistence des jobs pending (SQLite).

Un "job" represente un fichier video qui a ete ajoute a la queue mais qui
n'est pas encore prepare (ou en cours de preparation). Une fois prepare, le
package_state.json prend le relais.

Lifecycle d'un job :
    pending → preparing → done (le package_state.json existe maintenant)
                       → failed (preparation a echoue)

Stockage : `data/jobs.db` (SQLite). Schema simple, pas de migrations
sophistiquees pour l'instant.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .. import config


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class PendingJob:
    id: int
    file_path: str
    status: str               # "pending" / "preparing" / "done" / "failed"
    force_fr: str             # vide ou VFF/VOF/etc.
    created_at: str           # ISO-8601
    updated_at: str
    package_dir: str          # rempli quand prepare termine (= dossier package)
    release_name: str         # rempli quand prepare termine
    log_path: str             # fichier log de la preparation (data/jobs/<id>.log)
    error: str                # message si status=failed
    append_fr_title: bool = False  # ajouter '(Titre FR)' au release_name.txt
    tmdb_id_override: int = 0      # ID TMDB force (0 = recherche par titre)
    manual_release_name: str = ""  # release_name override complet (vide = pipeline normal)
    # Lot F.2 : controle de la file de preparation
    is_paused: bool = False          # le scheduler skip les jobs pauses
    priority_order: int = 0          # tri ascendant ; 0 = utilise id (insertion order)
    # Sprint C.1 v0.5.0 : hint categorie choisi par l'user dans la modal Inbox.
    # 0 = pas de hint (auto-detect via extension dans early_category_guess).
    category_id_hint: int = 0
    # Sprint D.9 v0.5.0 : overrides livre saisis dans la section Re-preparer
    # pour les packages cat 12. Surchargent l'extraction locale EPUB/PDF/CBZ
    # avant l'enrichissement BnF/Google Books/OpenLibrary.
    manual_isbn: str = ""        # ISBN-13 ou ISBN-10 (auto-detect du type)
    manual_author: str = ""      # auteur principal force (1 seul)
    manual_book_title: str = ""  # titre du livre force
    # Sprint D.11 v0.5.0 : annee de publication forcee (utilisee dans
    # release_name livre 'Auteur.Titre.YEAR.Langue.Format-TEAM').
    manual_book_year: int = 0
    # Sprint D.40 v0.5.0 : URL Google Books fournie par l'user (typiquement
    # collee depuis https://books.google.com/books/edition/.../<volumeId>).
    # On en extrait le volumeId pour bypasser la recherche par titre et
    # alimenter le lookup direct Google Books.
    manual_google_books_url: str = ""
    # Sprint D.48 v0.5.0 (feedback Louis batch upload) : source forcee pour
    # les releases amateurs qui n'ont ni NFO scene ni source dans le nom
    # d'origine. Charte Gemini : SOURCE obligatoire dans le release_name
    # (Titre.Annee.LANG.RES.SOURCE.AUDIO.VCODEC-TEAM). Valeurs : "" (auto),
    # "BluRay", "WEB-DL", "WEBRip", "HDTV", "DVDRip", "BDRip", "REMUX", etc.
    # Cf. rules.json:source_tokens.
    manual_source: str = ""


# ============================================================
# DB SETUP
# ============================================================

def db_path() -> Path:
    return config.data_dir() / "jobs.db"


def jobs_log_dir() -> Path:
    p = config.data_dir() / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    force_fr     TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    package_dir  TEXT NOT NULL DEFAULT '',
    release_name TEXT NOT NULL DEFAULT '',
    log_path     TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_status ON pending_jobs(status);
CREATE INDEX IF NOT EXISTS idx_created ON pending_jobs(created_at DESC);
"""


def _add_column_idempotent(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    """ALTER TABLE ADD COLUMN avec garde anti-duplicate.

    Sprint 4 PLAN-V1.md fix : sur Python 3.12 specifiquement, on a observe
    en CI des `OperationalError: duplicate column name` malgre la verif
    `if col not in cols` qui PRECEDAIT l'ALTER. Vraisemblablement lie aux
    changements sqlite3 dans 3.12 (executescript commit explicite, etc.).

    On enveloppe l'ALTER dans try/except specifique : si SQLite nous dit
    'duplicate column', on swallow. Pour tout autre OperationalError on
    re-raise (ne pas masquer un vrai bug schema).
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path()))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        # Migrations idempotentes : ajout de colonnes si absentes.
        # On lit d'abord les colonnes existantes pour eviter l'ALTER inutile.
        # `_add_column_idempotent` est defensif au cas ou (Python 3.12 / race).
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pending_jobs)")}
        if "append_fr_title" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "append_fr_title",
                                   "INTEGER NOT NULL DEFAULT 0")
        if "tmdb_id_override" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "tmdb_id_override",
                                   "INTEGER NOT NULL DEFAULT 0")
        if "manual_release_name" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_release_name",
                                   "TEXT NOT NULL DEFAULT ''")
        # Lot F.2 : pause/reordonner
        if "is_paused" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "is_paused",
                                   "INTEGER NOT NULL DEFAULT 0")
        if "priority_order" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "priority_order",
                                   "INTEGER NOT NULL DEFAULT 0")
        # Sprint C.1 v0.5.0 : hint categorie choisi par l'user dans la modal Inbox.
        if "category_id_hint" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "category_id_hint",
                                   "INTEGER NOT NULL DEFAULT 0")
        # Sprint D.9 v0.5.0 : overrides livre (ISBN/auteur/titre).
        if "manual_isbn" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_isbn",
                                   "TEXT NOT NULL DEFAULT ''")
        if "manual_author" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_author",
                                   "TEXT NOT NULL DEFAULT ''")
        if "manual_book_title" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_book_title",
                                   "TEXT NOT NULL DEFAULT ''")
        # Sprint D.11 v0.5.0 : annee livre forcee.
        if "manual_book_year" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_book_year",
                                   "INTEGER NOT NULL DEFAULT 0")
        # Sprint D.40 v0.5.0 : URL Google Books forcee.
        if "manual_google_books_url" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_google_books_url",
                                   "TEXT NOT NULL DEFAULT ''")
        # Sprint D.48 v0.5.0 : source forcee (BluRay/WEB-DL/etc.).
        if "manual_source" not in cols:
            _add_column_idempotent(conn, "pending_jobs", "manual_source",
                                   "TEXT NOT NULL DEFAULT ''")
        # Migration one-shot via PRAGMA user_version pour s'executer
        # une seule fois. Sinon (round 4 bug) on ecraserait les valeurs
        # priority_order=0 valides posees par move_job('top').
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version < 1:
            # Init priority_order=id pour les jobs existants qui ont
            # priority_order=0 (cas DBs creees avant ce fix).
            conn.execute(
                "UPDATE pending_jobs SET priority_order = id "
                "WHERE priority_order = 0",
            )
            conn.execute("PRAGMA user_version = 1")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_job(row: sqlite3.Row) -> PendingJob:
    # Acces tolerant a append_fr_title (peut ne pas exister dans les vieilles DBs)
    try:
        append_fr_title = bool(row["append_fr_title"])
    except (IndexError, KeyError):
        append_fr_title = False
    try:
        tmdb_id_override = int(row["tmdb_id_override"] or 0)
    except (IndexError, KeyError, ValueError, TypeError):
        tmdb_id_override = 0
    try:
        manual_release_name = row["manual_release_name"] or ""
    except (IndexError, KeyError):
        manual_release_name = ""
    try:
        is_paused = bool(row["is_paused"])
    except (IndexError, KeyError):
        is_paused = False
    try:
        priority_order = int(row["priority_order"] or 0)
    except (IndexError, KeyError, ValueError, TypeError):
        priority_order = 0
    # Sprint C.1 : hint categorie pour les bases pre-v0.5.0 (defaut 0 = auto)
    try:
        category_id_hint = int(row["category_id_hint"] or 0)
    except (IndexError, KeyError, ValueError, TypeError):
        category_id_hint = 0
    # Sprint D.9 v0.5.0 : overrides livre (bases pre-D.9 = vides)
    try:
        manual_isbn = row["manual_isbn"] or ""
    except (IndexError, KeyError):
        manual_isbn = ""
    try:
        manual_author = row["manual_author"] or ""
    except (IndexError, KeyError):
        manual_author = ""
    try:
        manual_book_title = row["manual_book_title"] or ""
    except (IndexError, KeyError):
        manual_book_title = ""
    # Sprint D.11 : annee livre forcee (bases pre-D.11 = 0).
    try:
        manual_book_year = int(row["manual_book_year"] or 0)
    except (IndexError, KeyError, ValueError, TypeError):
        manual_book_year = 0
    # Sprint D.40 : URL Google Books forcee (bases pre-D.40 = "").
    try:
        manual_google_books_url = row["manual_google_books_url"] or ""
    except (IndexError, KeyError):
        manual_google_books_url = ""
    # Sprint D.48 : source forcee (bases pre-D.48 = "").
    try:
        manual_source = row["manual_source"] or ""
    except (IndexError, KeyError):
        manual_source = ""
    return PendingJob(
        id=row["id"],
        file_path=row["file_path"],
        status=row["status"],
        force_fr=row["force_fr"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        package_dir=row["package_dir"] or "",
        release_name=row["release_name"] or "",
        log_path=row["log_path"] or "",
        error=row["error"] or "",
        append_fr_title=append_fr_title,
        tmdb_id_override=tmdb_id_override,
        manual_release_name=manual_release_name,
        is_paused=is_paused,
        priority_order=priority_order,
        category_id_hint=category_id_hint,
        manual_isbn=manual_isbn,
        manual_author=manual_author,
        manual_book_title=manual_book_title,
        manual_book_year=manual_book_year,
        manual_google_books_url=manual_google_books_url,
        manual_source=manual_source,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# API publique
# ============================================================

def add_job(
    file_path: str,
    force_fr: str = "",
    append_fr_title: bool = False,
    tmdb_id_override: int = 0,
    manual_release_name: str = "",
    category_id_hint: int = 0,
    manual_isbn: str = "",
    manual_author: str = "",
    manual_book_title: str = "",
    manual_book_year: int = 0,
    manual_google_books_url: str = "",
    manual_source: str = "",
) -> PendingJob:
    """Cree un nouveau job en status 'pending'.

    Args:
        category_id_hint : Sprint C.1 — categorie Gemini choisie par l'user dans la
            modal Inbox (0 = auto-detect via extension dans early_category_guess).
        manual_isbn / manual_author / manual_book_title / manual_book_year :
            Sprint D.9 + D.11 — overrides livre saisis dans la section
            Re-preparer. Vides / 0 par defaut.
    """
    now = _now_iso()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO pending_jobs "
            "(file_path, status, force_fr, append_fr_title, tmdb_id_override, "
            "manual_release_name, category_id_hint, "
            "manual_isbn, manual_author, manual_book_title, manual_book_year, "
            "manual_google_books_url, manual_source, "
            "created_at, updated_at) "
            "VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_path, force_fr, 1 if append_fr_title else 0,
             int(tmdb_id_override or 0), manual_release_name,
             int(category_id_hint or 0),
             manual_isbn or "", manual_author or "", manual_book_title or "",
             int(manual_book_year or 0),
             manual_google_books_url or "",
             manual_source or "",
             now, now),
        )
        job_id = cur.lastrowid
        log_path = str(jobs_log_dir() / f"{job_id}.log")
        # Lot F.2 fix : initialise priority_order = id pour que chaque
        # job ait une valeur unique. Sinon le swap "monter/descendre"
        # echangerait 0 contre 0 = aucun changement visible. Avec
        # priority_order=id, l'ordre par defaut = ordre d'insertion,
        # et le swap fonctionne (chaque job a une valeur differente).
        conn.execute(
            "UPDATE pending_jobs SET log_path = ?, priority_order = ? "
            "WHERE id = ?",
            (log_path, job_id, job_id),
        )
        row = conn.execute(
            "SELECT * FROM pending_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row)


def get_job(job_id: int) -> PendingJob | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row else None


def list_jobs(
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[PendingJob]:
    """Liste les jobs dans l'ordre du SCHEDULER : preparing en premier,
    puis pending par priority_order ASC, puis le reste (done/failed) par
    id DESC.

    Lot post-NOTES round 4 : avant on triait par id DESC partout, ce qui
    rendait les fleches monter/descendre INVISIBLES (l'ordre visuel ne
    correspondait pas a l'ordre de traitement du scheduler). Maintenant
    la liste reflete exactement ce que va voir le scheduler.

    Ordre :
      1. status='preparing'  (le job en cours)
      2. status='pending'    tries par priority_order ASC, id ASC
      3. status='done'/'failed'  tries par id DESC (recents en premier)
    """
    with _connect() as conn:
        # ORDER BY clause complexe via CASE pour mixer les criteres :
        # - status='preparing' = priorite 1
        # - status='pending'   = priorite 2 (puis priority_order ASC, id ASC)
        # - autres             = priorite 3 (puis id DESC)
        order_clause = (
            "ORDER BY "
            "CASE status "
            "  WHEN 'preparing' THEN 1 "
            "  WHEN 'pending' THEN 2 "
            "  ELSE 3 "
            "END ASC, "
            "CASE WHEN status = 'pending' THEN priority_order END ASC, "
            "CASE WHEN status = 'pending' THEN id END ASC, "
            "CASE WHEN status NOT IN ('preparing', 'pending') THEN id END DESC"
        )
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            rows = conn.execute(
                f"SELECT * FROM pending_jobs WHERE status IN ({placeholders}) "
                f"{order_clause} LIMIT ?",
                (*statuses, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM pending_jobs {order_clause} LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_job(r) for r in rows]


def update_job(job_id: int, **fields) -> PendingJob | None:
    """Met a jour un ou plusieurs champs d'un job. Met automatiquement a jour
    updated_at. Champs inconnus rejetes."""
    allowed = {
        "status", "force_fr", "package_dir", "release_name",
        "log_path", "error", "append_fr_title",
        "tmdb_id_override", "manual_release_name",
        "is_paused", "priority_order",
    }
    invalid = set(fields) - allowed
    if invalid:
        raise ValueError(f"Champs invalides : {invalid}")
    if not fields:
        return get_job(job_id)
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with _connect() as conn:
        conn.execute(
            f"UPDATE pending_jobs SET {set_clause} WHERE id = ?", values,
        )
    return get_job(job_id)


def delete_job(job_id: int) -> bool:
    """Supprime un job. Retourne True si supprime, False si pas trouve."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM pending_jobs WHERE id = ?", (job_id,),
        )
        return cur.rowcount > 0


def pause_job(job_id: int) -> bool:
    """Lot F.2 : marque un job comme pause. Le scheduler le skip jusqu'a
    `resume_job`. Operation idempotente."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE pending_jobs SET is_paused = 1, updated_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now_iso(), job_id),
        )
        return cur.rowcount > 0


def resume_job(job_id: int) -> bool:
    """Lot F.2 : enleve le flag pause. Idempotent."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE pending_jobs SET is_paused = 0, updated_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (_now_iso(), job_id),
        )
        return cur.rowcount > 0


def move_job(job_id: int, direction: str) -> bool:
    """Lot F.2 : monte / descend un job dans la file (priority_order).

    direction : 'up' | 'down' | 'top' | 'bottom'

    Les jobs `pending` sont tries par (priority_order ASC, id ASC).
    Les jobs `preparing` (en cours) ne bougent jamais.

    Algorithme :
    - 'top' : priority_order = (min des autres) - 1
    - 'bottom' : priority_order = (max des autres) + 1
    - 'up' : swap avec le job immediatement au-dessus
    - 'down' : swap avec le job immediatement en-dessous
    """
    if direction not in ("up", "down", "top", "bottom"):
        return False
    with _connect() as conn:
        target = conn.execute(
            "SELECT id, priority_order FROM pending_jobs "
            "WHERE id = ? AND status = 'pending'",
            (job_id,),
        ).fetchone()
        if not target:
            return False
        target_po = int(target["priority_order"] or 0)

        # Liste des autres jobs pending tries
        others = conn.execute(
            "SELECT id, priority_order FROM pending_jobs "
            "WHERE status = 'pending' AND id != ? "
            "ORDER BY priority_order ASC, id ASC",
            (job_id,),
        ).fetchall()
        if not others:
            return False  # rien a swapper, tout seul dans la file

        if direction == "top":
            min_po = min(int(o["priority_order"] or 0) for o in others)
            new_po = min_po - 1
        elif direction == "bottom":
            max_po = max(int(o["priority_order"] or 0) for o in others)
            new_po = max_po + 1
        else:
            # Trouve la position actuelle du target dans la liste triee
            # (incluant target lui-meme).
            all_jobs = conn.execute(
                "SELECT id, priority_order FROM pending_jobs "
                "WHERE status = 'pending' "
                "ORDER BY priority_order ASC, id ASC"
            ).fetchall()
            idx = next(
                (i for i, j in enumerate(all_jobs) if j["id"] == job_id), -1,
            )
            if idx < 0:
                return False
            if direction == "up" and idx > 0:
                neighbor = all_jobs[idx - 1]
            elif direction == "down" and idx < len(all_jobs) - 1:
                neighbor = all_jobs[idx + 1]
            else:
                return False  # deja en haut / en bas
            neighbor_po = int(neighbor["priority_order"] or 0)
            # Swap les priority_order
            conn.execute(
                "UPDATE pending_jobs SET priority_order = ?, updated_at = ? "
                "WHERE id = ?",
                (target_po, _now_iso(), neighbor["id"]),
            )
            new_po = neighbor_po

        conn.execute(
            "UPDATE pending_jobs SET priority_order = ?, updated_at = ? "
            "WHERE id = ?",
            (new_po, _now_iso(), job_id),
        )
        return True


def flush_pending_jobs() -> int:
    """Lot F.2 : supprime tous les jobs `pending` (y compris les pauses).
    Ne touche PAS aux jobs `preparing` (en cours). Retourne le nb supprime."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM pending_jobs WHERE status = 'pending'",
        )
        return cur.rowcount


def get_next_pending_job() -> PendingJob | None:
    """Lot F.2 : retourne le prochain job a executer (status='pending' ET
    non pause), trie par priority_order ASC puis id ASC. None si rien."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_jobs "
            "WHERE status = 'pending' AND is_paused = 0 "
            "ORDER BY priority_order ASC, id ASC LIMIT 1"
        ).fetchone()
        return _row_to_job(row) if row else None


def find_job_for_package(package_dir: str) -> PendingJob | None:
    """Retrouve le job le plus recent qui a produit ce package_dir.

    Utile pour la page detail (Phase 3b.3) : on a besoin du file_path source
    pour relancer une preparation avec des overrides differents.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_jobs WHERE package_dir = ? "
            "ORDER BY id DESC LIMIT 1",
            (package_dir,),
        ).fetchone()
        return _row_to_job(row) if row else None
