"""Process and file locking used by the engine facade.

The facade keeps compatibility wrappers around these helpers. Keeping the
mutable lock registry here makes the single-process JSON-storage constraint and
settings-file serialization independently testable without coupling them to
Engine orchestration.
"""

import fcntl
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import IO

_SETTINGS_LOCK_GUARD = threading.Lock()
_SETTINGS_THREAD_LOCKS: dict[str, threading.RLock] = {}
_FILE_ENGINE_PROCESS_GUARD = threading.Lock()
_FILE_ENGINE_PROCESS_LOCK: IO[str] | None = None
_FILE_ENGINE_PROCESS_PID: int | None = None


def acquire_file_engine_process_lock(*, use_db: Callable[[], bool], data_dir: str) -> None:
    """Reject multiple processes when the mutable engine uses JSON files."""
    global _FILE_ENGINE_PROCESS_LOCK, _FILE_ENGINE_PROCESS_PID
    if use_db():
        return
    pid = os.getpid()
    with _FILE_ENGINE_PROCESS_GUARD:
        if _FILE_ENGINE_PROCESS_LOCK is not None and _FILE_ENGINE_PROCESS_PID == pid:
            return
        if _FILE_ENGINE_PROCESS_LOCK is not None:
            # A pre-fork child must not treat the master's inherited descriptor
            # as permission to use a stale in-memory Engine snapshot.
            _FILE_ENGINE_PROCESS_LOCK.close()
            _FILE_ENGINE_PROCESS_LOCK = None
            _FILE_ENGINE_PROCESS_PID = None
        lock_path = os.path.join(data_dir, 'engine_file_mode.lock')
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        lock_file = open(lock_path, 'a', encoding='utf-8')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_file.close()
            raise RuntimeError(
                'JSON engine storage supports one process only; configure DATABASE_URL for multiple workers'
            ) from exc
        _FILE_ENGINE_PROCESS_LOCK = lock_file
        _FILE_ENGINE_PROCESS_PID = pid


@contextmanager
def settings_file_lock(path: str) -> Iterator[None]:
    """Serialize a settings-file update across threads and processes."""
    absolute = os.path.abspath(path)
    with _SETTINGS_LOCK_GUARD:
        thread_lock = _SETTINGS_THREAD_LOCKS.setdefault(absolute, threading.RLock())
    with thread_lock:
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        with open(f'{absolute}.lock', 'a', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
