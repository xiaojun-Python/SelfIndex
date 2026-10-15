"""Process-lifetime writer lease for one SQLite-backed archive profile."""

from __future__ import annotations

import errno
import os
import stat
import threading
import weakref
from pathlib import Path


class ProfileWriterBusyError(RuntimeError):
    """Another process owns the archive's writer lease."""


class _WriterLease:
    def __init__(self, path: Path) -> None:
        self.pid = os.getpid()
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or (hasattr(os, "getuid") and current.st_uid != os.getuid()):
                raise PermissionError("Archive writer lock must be a regular file owned by the current user.")
            os.fchmod(descriptor, 0o600)
            if os.name == "nt":
                import msvcrt

                os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise ProfileWriterBusyError(
                    f"Another SelfIndex process is writing this archive: {path.parent}"
                ) from exc
            raise
        self.descriptor = descriptor

    def __del__(self) -> None:
        descriptor = getattr(self, "descriptor", None)
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


_guard = threading.Lock()
_leases: weakref.WeakValueDictionary[str, _WriterLease] = weakref.WeakValueDictionary()


def _after_fork() -> None:
    global _guard, _leases
    _guard = threading.Lock()
    _leases = weakref.WeakValueDictionary()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def acquire_writer_lease(db_path: str | Path) -> _WriterLease:
    lock_path = Path(db_path).resolve().with_suffix(Path(db_path).suffix + ".writer.lock")
    key = str(lock_path)
    with _guard:
        lease = _leases.get(key)
        if lease is None or lease.pid != os.getpid():
            lease = _WriterLease(lock_path)
            _leases[key] = lease
        return lease
