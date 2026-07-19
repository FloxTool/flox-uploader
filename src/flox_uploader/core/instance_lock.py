"""Verrou single-instance (R4, audit AUDIT_2026-07-19).

Empeche deux instances de Flox Uploader de tourner sur le MEME data dir
(double lancement accidentel de l'exe). Sans ce verrou, les deux schedulers
preparent en parallele sur les memes fichiers et `_reconcile_stuck_jobs`
marque « failed » les jobs en cours de l'autre instance.

On utilise un verrou de fichier au niveau OS (fcntl.flock sur POSIX,
msvcrt.locking sur Windows), tenu ouvert pour toute la vie du process. Il
est libere automatiquement quand le process meurt (crash inclus) — donc pas
de lock zombie a nettoyer, contrairement a un simple fichier PID.

NB : dev (data/ du repo) et prod (%LOCALAPPDATA%) ont des data dirs
differents -> chacun son verrou -> ils cohabitent sans probleme. Seules deux
instances sur le MEME data dir sont bloquees.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOCK_NAME = ".flox-instance.lock"
_lock_handle = None  # garde le fd ouvert pour la vie du process


def _try_lock(fh) -> bool:
    """Tente un verrou exclusif non-bloquant sur le handle. True si obtenu."""
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def acquire_single_instance_lock(data_dir: Path) -> bool:
    """Acquiert le verrou single-instance pour `data_dir`.

    Retourne True si obtenu (aucune autre instance sur ce data dir), False si
    une autre instance le tient deja. Le handle reste ouvert (global) tant que
    le process vit.
    """
    global _lock_handle
    if _lock_handle is not None:
        return True  # deja acquis par ce process
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / _LOCK_NAME
    fh = open(lock_path, "a+", encoding="utf-8")
    if not _try_lock(fh):
        fh.close()
        return False
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
    except OSError:
        pass
    _lock_handle = fh
    return True


def release_single_instance_lock() -> None:
    """Libere le verrou (fermeture du handle). Idempotent."""
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            try:
                _lock_handle.seek(0)
                msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        _lock_handle.close()
    except Exception:
        pass
    finally:
        _lock_handle = None
