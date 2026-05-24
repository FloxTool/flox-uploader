"""Background runner pour les jobs `prepare` et `upload`.

Architecture (Lot F.2 — Vague 3) : scheduler thread daemon custom avec
priorite UPLOAD > PREPARE. Avant on utilisait un `ThreadPoolExecutor`
single-worker FIFO, ce qui faisait attendre les uploads derriere une
longue file de preparations — pas pratique quand on prepare 50 fichiers
et qu'on veut uploader 1 fichier deja pret.

Maintenant :
- 1 seul worker thread (toujours sequentiel, contention TMDB/cache evitee)
- 2 queues internes : `_upload_queue` (deque) et logique de pioche prepare
  via `jobs_db.get_next_pending_job()` (qui respecte is_paused + priority_order)
- Le scheduler tire dans cet ordre :
    1. Si upload en attente -> execute upload
    2. Sinon -> execute prepare suivant
- Quand un job termine, le scheduler re-pioche immediatement (sans attente).

Capture stdout/stderr dans le fichier log du job (`data/jobs/<id>.log`)
pour permettre le suivi via SSE. Le contenu ecrit passe par un
`SecretScrubber` qui masque les passkeys / API keys connues.
"""
from __future__ import annotations

import contextlib
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Optional

from ..core import jobs_db
from ..core.log_scrubber import ScrubbingWriter, SecretScrubber
from ..core.package_state import read_state


@contextlib.contextmanager
def _scrubbed_log(log_file_handle):
    """Context manager qui redirige stdout/stderr vers le log via un scrubber.

    Construit un nouveau `SecretScrubber` a chaque entree (les secrets ont pu
    changer, ex: wizard qui vient d'ajouter une cle).
    """
    scrubber = SecretScrubber()
    writer = ScrubbingWriter(log_file_handle, scrubber)
    with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
        yield


# ============================================================
# Lot F.2 : Scheduler thread custom (remplace ThreadPoolExecutor FIFO)
# ============================================================

# Upload pending : deque de tuples (package_dir, dry_run, force_upload,
# force_existing_id, anonymous). Le scheduler les pioche en priorite
# absolue sur les prepare.
_upload_queue: deque = deque()
_upload_queue_lock = threading.Lock()

# Event pour reveiller le scheduler quand on submit un nouveau job
# (evite le polling fort, le scheduler dort jusqu'au prochain signal).
_scheduler_wake = threading.Event()

# Thread daemon qui consomme les queues
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_running = False

# Permet au shutdown de stopper proprement
_shutdown_requested = False


# ============================================================
# Lot post-NOTES round 5 F1 : Cancellation hard (kill subprocess)
# ============================================================
#
# `_run_prepare_job` execute la pipeline DANS LE THREAD du scheduler.
# Pour le cas reel d'un torrent de serie qui prend 30+ minutes a se
# creer, l'utilisateur doit pouvoir cliquer "Cancel" et tuer
# IMMEDIATEMENT le job (pas attendre que torf.generate finisse).
#
# Comme Python ne sait pas killer un thread cleanly, on lance la prepa
# dans un SUBPROCESS (`python -m flox_uploader.cli prepare ...`). On
# stocke le handle Popen pour pouvoir l'envoyer `kill()` depuis l'API.
# Une fois kille, on nettoie le dossier upload_packages cree partiellement.

import subprocess
import sys

_running_procs: dict[int, subprocess.Popen] = {}
_running_procs_lock = threading.Lock()
# Snapshot des dirs upload_packages AVANT le launch d'un job, pour
# pouvoir diff apres kill et trouver le partial dir a supprimer.
_pre_launch_pkg_snapshot: dict[int, set[str]] = {}
# Flag par job_id : True si l'utilisateur a cancel pendant l'exec
# (utilise par `_run_prepare_job` apres le wait pour decider le status
# "cancelled" vs "failed").
_cancelled_job_ids: set[int] = set()


def request_job_cancel(job_id: int) -> bool:
    """Kill le subprocess du job (s'il tourne) et marque le job comme
    cancelled. Le scheduler nettoiera le partial dir au retour de wait().
    Retourne True si on a kille quelque chose, False si rien a tuer.
    """
    with _running_procs_lock:
        proc = _running_procs.get(job_id)
    if proc is None:
        return False
    _cancelled_job_ids.add(job_id)
    try:
        proc.kill()  # SIGKILL Linux / TerminateProcess Windows
    except (OSError, ProcessLookupError):
        pass  # deja mort
    return True


def _scheduler_loop() -> None:
    """Boucle principale du scheduler.

    Tire dans cet ordre de priorite :
    1. Upload pending (deque) — toujours en premier
    2. Prepare pending non-pause (DB, trie par priority_order)

    Si rien a faire : attend `_scheduler_wake` (signal envoye par
    submit_prepare_job / submit_upload_job).

    1 seul job s'execute a la fois (sequentiel) pour eviter la contention
    sur le cache TMDB / OMDb partage.
    """
    global _scheduler_running
    _scheduler_running = True
    while not _shutdown_requested:
        # 1. Upload pending en premier
        upload_args = None
        with _upload_queue_lock:
            if _upload_queue:
                upload_args = _upload_queue.popleft()
        if upload_args is not None:
            try:
                _run_upload_job(*upload_args)
            except Exception:
                # Garde le scheduler vivant meme si un upload crashe brutalement
                traceback.print_exc()
            continue  # repique immediatement (re-check upload puis prepare)

        # 2. Prepare suivant (respect is_paused + priority_order)
        next_job = None
        try:
            next_job = jobs_db.get_next_pending_job()
        except Exception:
            traceback.print_exc()
        if next_job is not None:
            try:
                _run_prepare_job(next_job.id)
            except Exception:
                traceback.print_exc()
            continue

        # 3. Rien a faire : attend un signal (ou timeout 2s par securite).
        # Le timeout sert de garde-fou si le signal est rate (atomicite).
        _scheduler_wake.clear()
        _scheduler_wake.wait(timeout=2.0)
    _scheduler_running = False


def _ensure_scheduler_started() -> None:
    """Demarre le scheduler thread si pas deja en cours. Idempotent."""
    global _scheduler_thread
    if _scheduler_thread is None or not _scheduler_thread.is_alive():
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="job-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()


def shutdown_executor(wait: bool = True) -> None:
    """Stoppe le scheduler thread (appele au shutdown de l'app)."""
    global _shutdown_requested
    _shutdown_requested = True
    _scheduler_wake.set()
    if wait and _scheduler_thread is not None:
        _scheduler_thread.join(timeout=5.0)


def submit_prepare_job(job_id: int) -> None:
    """Soumet un job de preparation. Non-bloquant. Le scheduler le pioche
    selon priority_order quand il est libre."""
    _ensure_scheduler_started()
    _scheduler_wake.set()


def get_executor():
    """Compat retro : ancien code appelait `get_executor().submit(...)`.
    Plus utilise depuis le refactor scheduler Lot F.2. Pour eviter de
    casser d'eventuels appels obsoletes, on retourne un objet stub qui
    delegue submit() au scheduler en passant le 1er arg comme job_id.
    En pratique : code dead-letter, ne doit plus etre appele."""
    class _StubExecutor:
        def submit(self_, fn, *args, **kwargs):  # noqa
            # On ignore fn et on tente de deviner si c'est prepare ou upload
            # via les args. Pas de garantie : prefer submit_prepare_job /
            # submit_upload_job directement.
            return None
    return _StubExecutor()


# ============================================================
# Upload jobs (Phase 3b.4) : memoire en process, pas de DB.
# Un upload est simple a tracker : etat dans package_state.json + log
# fichier texte. Pas besoin d'une table SQLite separee.
# ============================================================

# Map package_dir -> (status, message, log_lines) pour le polling depuis l'UI.
# Reset au demarrage du serveur. Cle : str(package_dir).
_upload_status: dict[str, dict] = {}


def get_upload_status(package_dir: str) -> dict | None:
    """Retourne l'etat courant d'un upload pour un package_dir donne."""
    return _upload_status.get(package_dir)


def list_upload_statuses(include_done: bool = True) -> list[dict]:
    """Retourne tous les uploads connus (en cours + termines recents).

    Tri : actifs d'abord (queued/uploading) tries par updated_at croissant
    (le plus ancien d'abord = celui qui attend depuis le plus longtemps),
    puis termines tries par updated_at decroissant (le plus recent en haut).
    updated_at est un timestamp ISO 8601 UTC -> tri lexicographique ==
    tri chronologique, sans hash() non-deterministe.
    """
    items: list[dict] = []
    for key, val in _upload_status.items():
        items.append({
            "package_dir": key,
            "package_name": Path(key).name,
            **val,
        })
    if not include_done:
        items = [x for x in items if x.get("status") not in ("done", "failed")]

    actives = sorted(
        [x for x in items if x.get("status") in ("queued", "uploading")],
        key=lambda x: x.get("updated_at", ""),
    )
    finished = sorted(
        [x for x in items if x.get("status") not in ("queued", "uploading")],
        key=lambda x: x.get("updated_at", ""),
        reverse=True,
    )
    return actives + finished


def clear_upload_status(package_dir: str) -> bool:
    """Efface l'entree d'upload pour ce package."""
    return _upload_status.pop(package_dir, None) is not None


def submit_upload_job(
    package_dir: Path,
    dry_run: bool = False,
    force_upload: bool = False,
    force_existing_id: int | None = None,
    anonymous: bool = False,
) -> None:
    """Soumet un job d'upload. Le scheduler le pioche en PRIORITE sur les
    preparations (Lot F.2)."""
    from datetime import datetime, timezone
    key = str(package_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _upload_status[key] = {
        "status": "queued",
        "dry_run": dry_run,
        "message": "En attente du worker…",
        "log_path": "",
        "created_at": now,
        "updated_at": now,
    }
    _ensure_scheduler_started()
    with _upload_queue_lock:
        _upload_queue.append(
            (package_dir, dry_run, force_upload, force_existing_id, anonymous),
        )
    _scheduler_wake.set()


def _run_upload_job(
    package_dir: Path,
    dry_run: bool,
    force_upload: bool,
    force_existing_id: int | None,
    anonymous: bool,
) -> None:
    """Execute upload_package dans le worker thread, capture stdout/stderr."""
    import hashlib
    from ..core.upload_orchestrator import load_upload_config, upload_package
    key = str(package_dir)
    log_dir = jobs_db.jobs_log_dir()
    # md5 stable cross-process : un meme package_dir aura toujours le meme
    # nom de log, donc on ecrase au lieu de proliferer un fichier par redemarrage
    # serveur (PYTHONHASHSEED randomise hash() builtin par defaut).
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
    log_file = log_dir / f"upload_{digest}.log"
    from datetime import datetime, timezone
    _upload_status[key].update({
        "status": "uploading",
        "message": "Upload en cours…",
        "log_path": str(log_file),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    try:
        with open(log_file, "w", encoding="utf-8", buffering=1) as logf:
            with _scrubbed_log(logf):
                cfg = load_upload_config(
                    dry_run=dry_run,
                    force_upload=force_upload,
                    force_existing_id=force_existing_id,
                    anonymous=anonymous,
                    prompt=lambda dup: bool(force_upload),  # auto-confirm si force
                )
                outcome = upload_package(package_dir, cfg)
        _upload_status[key].update({
            "status": "done",
            "message": outcome.message or f"Upload {'simulé' if dry_run else 'reel'} : {outcome.final_state.value}",
            "final_state": outcome.final_state.value,
            "uploaded_torrent_id": outcome.upload.torrent_id if outcome.upload else None,
            "uploaded_torrent_url": outcome.upload.torrent_url if outcome.upload else "",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except SystemExit as e:
        msg = f"Upload echoue (exit code {e.code})"
        _append_log(log_file, f"\n[ERREUR] {msg}\n")
        _upload_status[key].update({
            "status": "failed", "message": msg,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception as e:
        tb = traceback.format_exc()
        _append_log(log_file, f"\n[EXCEPTION] {tb}\n")
        _upload_status[key].update({
            "status": "failed", "message": str(e),
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })


def _snapshot_upload_packages() -> set[str]:
    """Lot post-NOTES round 5 F1 : snapshot des package_dirs existants
    avant le launch d'un subprocess. Sert au cleanup apres kill."""
    import os
    from ..config import packages_dir
    try:
        d = packages_dir()
    except Exception:
        return set()
    if not d.exists():
        return set()
    try:
        return {entry.name for entry in d.iterdir() if entry.is_dir()}
    except OSError:
        return set()


def _cleanup_partial_package(job_id: int, snapshot: set[str]) -> str | None:
    """Apres un kill, trouve les dirs apparus dans upload_packages depuis
    le snapshot et les supprime. Retourne le nom du dir supprime (ou None)."""
    import shutil
    from ..config import packages_dir
    try:
        d = packages_dir()
    except Exception:
        return None
    if not d.exists():
        return None
    deleted = None
    for entry in d.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in snapshot:
            continue
        # Nouveau dir cree pendant ce job -> supprime
        try:
            shutil.rmtree(entry)
            deleted = entry.name
            print(f"[F1] Cleanup : supprime partial dir '{entry.name}'")
        except OSError as e:
            print(f"[F1] WARN : impossible de supprimer '{entry.name}' : {e}")
    return deleted


def _run_prepare_job(job_id: int) -> None:
    """Execute la preparation d'un job dans un SUBPROCESS pour permettre
    le hard-kill via Cancel (Lot post-NOTES round 5 F1).

    Le scheduler thread reste responsable de :
    1. Snapshot des package_dirs existants AVANT launch
    2. Spawn `python -m flox_uploader.cli prepare <file> --tracker gemini ...`
       avec redirection stdout/stderr vers le log
    3. Wait jusqu'a exit code OU kill externe (via request_job_cancel)
    4. Cleanup du partial dir si cancel
    5. Update du status DB (done / failed / cancelled)

    Status :
    - exit code 0 -> done
    - kille via Cancel -> cancelled (avec cleanup)
    - autre code -> failed
    """
    import os

    job = jobs_db.get_job(job_id)
    if not job:
        return

    jobs_db.update_job(job_id, status="preparing")

    log_file = Path(job.log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Snapshot des package_dirs pour cleanup post-kill
    snapshot = _snapshot_upload_packages()
    _pre_launch_pkg_snapshot[job_id] = snapshot

    # Construit la commande CLI subprocess.
    # IMPORTANT bundle PyInstaller : en mode .exe (`sys.frozen=True`),
    # `sys.executable` est l'.exe Flox Uploader lui-meme, pas Python.
    # Donc on ne peut pas faire `-m flox_uploader.cli` (le .exe interprete
    # ces args et argparse leve "unrecognized arguments"). On invoque
    # directement le .exe avec la sous-commande, qui est routee par
    # argparse du cli.py (build_parser() expose prepare/upload/serve).
    # En mode dev (python ou venv), on garde `-m flox_uploader.cli`.
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "prepare", str(job.file_path), "--tracker", "gemini"]
    else:
        cmd = [
            sys.executable, "-m", "flox_uploader.cli",
            "prepare", str(job.file_path),
            "--tracker", "gemini",
        ]
    if job.force_fr:
        cmd.extend(["--force-fr", job.force_fr])
    if job.tmdb_id_override:
        cmd.extend(["--tmdb-id", str(job.tmdb_id_override)])
    if job.manual_release_name:
        cmd.extend(["--release-name", job.manual_release_name])
    # Sprint C.1 : hint categorie choisi par l'user dans la modal Inbox.
    if job.category_id_hint:
        cmd.extend(["--category-hint", str(job.category_id_hint)])
    # Sprint D.9 v0.5.0 : overrides livre (ISBN/auteur/titre).
    if job.manual_isbn:
        cmd.extend(["--manual-isbn", job.manual_isbn])
    if job.manual_author:
        cmd.extend(["--manual-author", job.manual_author])
    if job.manual_book_title:
        cmd.extend(["--manual-book-title", job.manual_book_title])

    # Env override : APPEND_FR_TITLE_TO_RELEASE_NAME passe au subprocess
    subprocess_env = dict(os.environ)
    subprocess_env["APPEND_FR_TITLE_TO_RELEASE_NAME"] = (
        "1" if job.append_fr_title else "0"
    )
    # Force PYTHONUNBUFFERED pour que le log streame en temps reel via SSE
    subprocess_env["PYTHONUNBUFFERED"] = "1"

    # Sprint 8 hotfix v11 : sur Windows en mode bundle PyInstaller, le
    # subprocess (qui est l'exe lui-meme avec sous-commande prepare) ouvre
    # une fenetre console qui pop au premier plan et vole le focus. CREATE_NO_WINDOW
    # cache la console sans empecher TerminateProcess (donc kill() reste OK).
    # Pas d'effet sur les autres OS (creationflags ignore).
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        # subprocess.CREATE_NO_WINDOW = 0x08000000
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = None
    return_code = None
    try:
        with open(log_file, "w", encoding="utf-8", buffering=1) as logf:
            proc = subprocess.Popen(
                cmd,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=subprocess_env,
                **popen_kwargs,
            )
            with _running_procs_lock:
                _running_procs[job_id] = proc
            try:
                return_code = proc.wait()
            finally:
                with _running_procs_lock:
                    _running_procs.pop(job_id, None)
    except Exception as e:
        tb = traceback.format_exc()
        _append_log(log_file, f"\n[EXCEPTION SUBPROCESS] {tb}\n")
        jobs_db.update_job(job_id, status="failed", error=str(e))
        _pre_launch_pkg_snapshot.pop(job_id, None)
        _cancelled_job_ids.discard(job_id)
        return

    # Determine le status final
    was_cancelled = job_id in _cancelled_job_ids
    _cancelled_job_ids.discard(job_id)
    snapshot_used = _pre_launch_pkg_snapshot.pop(job_id, set())

    if was_cancelled:
        deleted = _cleanup_partial_package(job_id, snapshot_used)
        msg = "Annule par l'utilisateur"
        if deleted:
            msg += f" (cleanup : {deleted})"
        _append_log(log_file, f"\n[CANCEL] {msg}\n")
        jobs_db.update_job(job_id, status="failed", error=msg)
        return

    if return_code == 0:
        # Apres prepare reussi : retrouve le package_dir via le nouveau dir
        # apparu dans upload_packages (diff snapshot)
        new_dirs = _snapshot_upload_packages() - snapshot_used
        from ..config import packages_dir
        package_dir = None
        if new_dirs:
            try:
                package_dir = packages_dir() / next(iter(new_dirs))
            except Exception:
                package_dir = None
        if package_dir is None:
            # Fallback : pas de nouveau dir trouve, c'est anormal
            jobs_db.update_job(
                job_id, status="failed",
                error="Subprocess OK mais pas de package_dir trouve",
            )
            return
        try:
            _try_dedup_check(package_dir)
        except Exception as e:
            print(f"[WARN] dedup_check post-prepare a leve : {e}")
        state = read_state(package_dir)
        jobs_db.update_job(
            job_id, status="done",
            package_dir=str(package_dir),
            release_name=state.release_name if state else "",
        )
    else:
        msg = _extract_error_from_log(log_file) or f"Pipeline a echoue (exit code {return_code})"
        jobs_db.update_job(job_id, status="failed", error=msg)



def _try_dedup_check(package_dir: Path) -> None:
    """Apres process_one reussit, fait un check_duplicate cote tracker et
    persiste le resultat dans package_state. Skip silencieux si pas de
    TRACKER_API_KEY (cas user qui n'a pas encore configure)."""
    import os
    from datetime import datetime, timezone
    from ..core.gemini_api import DupConfidence, GeminiClient
    from ..core.package_state import PackageState, transition
    from ..core.upload_orchestrator import (
        load_package_bundle,
        mark_aborted_duplicate,
        try_check_duplicate,
    )

    # Si le pre-check anticipe a deja decide -> on saute (les fichiers du
    # package n'existent meme pas dans ce cas, load_package_bundle planterait).
    state_data = read_state(package_dir)
    if state_data and state_data.state == PackageState.ABORTED_DUPLICATE:
        print("[INFO] Dedup deja decide par le pre-check (ABORTED_DUPLICATE), skip.")
        return

    api_url = (os.getenv("TRACKER_API_URL") or "").strip()
    api_key = (os.getenv("TRACKER_API_KEY") or "").strip()
    if not api_url or not api_key:
        print("[INFO] Dedup check skip : TRACKER_API_URL ou TRACKER_API_KEY absent.")
        return

    try:
        bundle = load_package_bundle(package_dir)
    except SystemExit as e:
        print(f"[WARN] Dedup check skip : load_package_bundle a die() ({e})")
        return
    if bundle.tmdb_id <= 0 and bundle.size_bytes <= 0:
        print("[INFO] Dedup check skip : ni tmdb_id ni size_bytes connus.")
        return

    client = GeminiClient(api_url=api_url, api_key=api_key)
    result = try_check_duplicate(
        client,
        tmdb_id=bundle.tmdb_id,
        size_bytes=bundle.size_bytes,
        release_name=bundle.release_name,
    )
    if result is None:
        return  # warning deja loggue par try_check_duplicate

    if result.confidence == DupConfidence.CERTAIN and result.primary:
        mark_aborted_duplicate(
            package_dir, result,
            note="dedup_check pendant prepare : doublon CERTAIN",
        )
        print(f"[OK] Dedup CERTAIN : torrent ID {result.primary.torrent_id}")
    else:
        # Reste en PREPARED, mais on persiste les infos pour la UI
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        transition(
            package_dir, PackageState.PREPARED,
            note=f"dedup_check pendant prepare : {result.confidence.value}",
            existing_torrent_id=result.primary.torrent_id if result.primary else None,
            existing_torrent_url=result.primary.url if result.primary else "",
            dedup_confidence=result.confidence.value,
            dedup_checked_at=now,
        )
        print(f"[OK] Dedup pendant prepare : confiance={result.confidence.value}")


def _extract_error_from_log(log_file: Path, max_chars: int = 300) -> str:
    """Extrait le message d erreur le plus pertinent du log : derniere ligne
    qui matche [ERREUR|ERROR|FATAL|die], sinon la derniere ligne non vide."""
    try:
        if not log_file.is_file():
            return ""
        text = log_file.read_text(encoding="utf-8", errors="replace")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in reversed(lines):
            up = line.upper()
            if any(tag in up for tag in ("[ERREUR]", "[ERROR]", "[FATAL]", "ERROR :", "ERREUR :")):
                return line[:max_chars]
        if lines:
            return lines[-1][:max_chars]
        return ""
    except OSError:
        return ""


def _append_log(log_file: Path, text: str) -> None:
    """Append `text` au log apres scrubbing des secrets connus.

    Utilise pour les tracebacks d'exceptions (non scrubbees par le redirect
    stdout/stderr car elles passent directement par traceback.format_exc()).
    """
    scrubbed = SecretScrubber().scrub(text)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(scrubbed)
    except OSError:
        pass
