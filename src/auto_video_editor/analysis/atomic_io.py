"""Atomic file-write helpers for Phase 4 managed artifacts.

Contract
--------
Every managed write:
1. Temp file in same directory/filesystem as destination (mkstemp).
2. Unique temp name.
3. Write bytes/text.
4. flush().
5. os.fsync() — best-effort; Windows may return EINVAL on some filesystems;
   catches only documented unsupported-operation errors, not generic I/O errors.
6. Close file descriptor.
7. os.replace(temp, destination).
8. Re-read destination and verify expected SHA-256.
9. Cleanup temp file on failure before replace.

WriterLock
----------
Exclusive per-entry writer lock via os.O_CREAT | os.O_EXCL on a lock file.
Bounded timeout. Conservative stale-lock handling.
Lock file content: PID only (no secrets, no private paths).

Windows notes
-------------
- os.fsync() may raise OSError(errno.EINVAL) on FAT/network filesystems.
  This is caught and treated as "not supported"; all other errors propagate.
- Directory-level fsync is not attempted (not supported on Windows).
- os.replace() is atomic on the same NTFS volume.
"""
from __future__ import annotations

import errno
import hashlib
import os
import pathlib
import tempfile
import time


# ── Exceptions ────────────────────────────────────────────────────────────────

class ArtifactIntegrityError(OSError):
    """Raised when a re-read artifact SHA-256 does not match expected value."""


class WriterLockError(OSError):
    """Raised when a writer lock cannot be acquired within the timeout."""


# ── fsync helper ──────────────────────────────────────────────────────────────

_FSYNC_UNSUPPORTED_ERRNOS = frozenset({
    errno.EINVAL,   # Windows: invalid function on some filesystems
    errno.EROFS,    # read-only filesystem
    22,             # EINVAL on some platforms without symbolic name
})


def _try_fsync(fd: int) -> None:
    """Best-effort fsync; silently skips only documented unsupported cases."""
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno in _FSYNC_UNSUPPORTED_ERRNOS:
            return   # Not supported on this filesystem/OS — acceptable
        raise        # Real I/O error — propagate


# ── Atomic write ──────────────────────────────────────────────────────────────

def atomic_write_bytes(
    destination: pathlib.Path,
    data: bytes,
    expected_sha256: str | None = None,
) -> str:
    """Atomically write *data* to *destination*; return actual SHA-256 hex.

    Parameters
    ----------
    destination:
        Target path. Parent directory must already exist.
    data:
        Raw bytes to write.
    expected_sha256:
        If provided, verifies the re-read file matches this digest (lowercase).
        Raises ArtifactIntegrityError on mismatch.

    Returns
    -------
    Actual SHA-256 hex digest of the written data.
    """
    parent = destination.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".tmp_", suffix=destination.suffix)
    tmp = pathlib.Path(tmp_path)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            _try_fsync(f.fileno())
        # fd is now closed by context manager
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    try:
        os.replace(tmp_path, str(destination))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    # Post-replace verification — re-read and compare SHA-256
    written_data = destination.read_bytes()
    actual_sha = hashlib.sha256(written_data).hexdigest()
    if expected_sha256 is not None and actual_sha.lower() != expected_sha256.lower():
        raise ArtifactIntegrityError(
            f"Post-replace hash mismatch for {destination.name}: "
            f"expected ...{expected_sha256[-12:]}, got ...{actual_sha[-12:]}"
        )
    return actual_sha


def atomic_write_text(
    destination: pathlib.Path,
    text: str,
    encoding: str = "utf-8",
    expected_sha256: str | None = None,
) -> str:
    """Atomically write *text* to *destination*; return actual SHA-256 hex."""
    data = text.encode(encoding)
    return atomic_write_bytes(destination, data, expected_sha256)


# ── Writer lock ───────────────────────────────────────────────────────────────

class WriterLock:
    """Exclusive writer lock for a directory, implemented via O_EXCL lock file.

    Usage
    -----
    with WriterLock(directory, timeout=10.0):
        # ... exclusive write operations ...

    The lock file contains only the writer PID (no secrets, no private paths).
    Stale locks (older than _STALE_SECONDS) are removed conservatively.
    """

    _LOCK_FILENAME = ".writer_lock"
    _STALE_SECONDS = 30.0
    _POLL_INTERVAL = 0.05

    def __init__(self, directory: pathlib.Path, timeout: float = 10.0) -> None:
        self._lock_path = directory / self._LOCK_FILENAME
        self._timeout = timeout
        self._acquired = False

    def __enter__(self) -> "WriterLock":
        self._acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self._release()

    def _acquire(self) -> None:
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                self._acquired = True
                return
            except FileExistsError:
                # Check for stale lock
                try:
                    mtime = self._lock_path.stat().st_mtime
                    if time.time() - mtime > self._STALE_SECONDS:
                        try:
                            self._lock_path.unlink()
                        except OSError:
                            pass
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise WriterLockError(
                        f"Could not acquire writer lock at {self._lock_path.name} "
                        f"within {self._timeout:.1f}s"
                    )
                time.sleep(self._POLL_INTERVAL)

    def _release(self) -> None:
        if self._acquired:
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._acquired = False
