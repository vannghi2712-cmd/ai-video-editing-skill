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
7. Pre-replace recheck: destination parent must not be a symlink or reparse point.
8. os.replace(temp, destination).
9. Re-read destination and verify expected SHA-256.
10. Cleanup temp file on failure before replace.

WriterLock
----------
Exclusive per-entry writer lock via os.O_CREAT | os.O_EXCL on a lock file.
Bounded timeout. Random ownership token (UUID) written to lock file.
Release is token-verified: only the process that wrote the token may delete it.
Stale-lock removal requires proof that the owning PID is not running.
Foreign locks (unrecognized format, PID alive, PID unverifiable) are never deleted.

Path Safety
-----------
check_path_ancestors(path) inspects every existing component from the drive root
down to (but not including) the leaf, rejecting symlinks and Windows reparse points.
This must be called before lock creation and before any write.

Windows notes
-------------
- os.fsync() may raise OSError(errno.EINVAL) on FAT/network filesystems.
  This is caught and treated as "not supported"; all other errors propagate.
- Directory-level fsync is not attempted (not supported on Windows).
- os.replace() is atomic on the same NTFS volume.
- FILE_ATTRIBUTE_REPARSE_POINT (0x400) is checked via os.lstat().st_file_attributes.
"""
from __future__ import annotations

import errno
import hashlib
import os
import pathlib
import stat as _stat
import tempfile
import time
import uuid


# ── Exceptions ────────────────────────────────────────────────────────────────

class ArtifactIntegrityError(OSError):
    """Raised when a re-read artifact SHA-256 does not match expected value."""


class WriterLockError(OSError):
    """Raised when a writer lock cannot be acquired within the timeout."""


class PathSafetyError(OSError):
    """Raised when a path component is a symlink or Windows reparse point."""


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


# ── Path safety ───────────────────────────────────────────────────────────────

_REPARSE_FLAG = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_component_unsafe(p: pathlib.Path) -> bool:
    """Return True if p is a symlink or Windows reparse point (checked via lstat)."""
    if p.is_symlink():
        return True
    try:
        lst = p.lstat()
        win_attrs = getattr(lst, "st_file_attributes", 0)
        if win_attrs & _REPARSE_FLAG:
            return True
    except (OSError, AttributeError):
        pass
    return False


def check_path_ancestors(path: pathlib.Path) -> None:
    """Check every existing ancestor component of *path* for symlink/reparse.

    Raises PathSafetyError if any existing ancestor (up to but NOT including
    the leaf) is a symlink or Windows reparse point.

    Call this before acquiring a lock and before any write to *path*.
    """
    parts = path.parts
    # Iterate from root down to (but not including) the leaf component
    for i in range(1, len(parts)):
        ancestor = pathlib.Path(*parts[:i])
        if not ancestor.exists():
            break  # Deeper components don't exist yet; safe
        if _is_component_unsafe(ancestor):
            raise PathSafetyError(
                f"Symlink or reparse point detected at path ancestor: {ancestor!s}"
            )


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

    Raises
    ------
    PathSafetyError
        If the destination or its parent is a symlink/reparse point immediately
        before the os.replace() call (pre-replace TOCTOU check).
    ArtifactIntegrityError
        If post-replace SHA-256 does not match expected_sha256.
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

    # Pre-replace TOCTOU check: parent and existing destination must not be symlinks/reparse
    try:
        if _is_component_unsafe(parent):
            tmp.unlink(missing_ok=True)
            raise PathSafetyError(
                f"Pre-replace: destination parent is a symlink or reparse point: {parent!s}"
            )
        if destination.exists() and _is_component_unsafe(destination):
            tmp.unlink(missing_ok=True)
            raise PathSafetyError(
                f"Pre-replace: destination is a symlink or reparse point: {destination.name}"
            )
    except PathSafetyError:
        raise
    except OSError:
        pass  # lstat failed; proceed with replace (OS will catch it)

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

    Each lock instance uses a random UUID ownership token written to the lock
    file alongside the writer PID:  ``{token}:{pid}``

    Release is token-verified: _release() reads the lock file and only deletes
    it if our token appears at the start.  A foreign token is never deleted.

    Stale-lock removal is conservative:
    - The lock must be older than _STALE_SECONDS.
    - The token must be parseable.
    - The owning PID must be provably dead (os.kill(pid, 0) raises
      ProcessLookupError).
    - If any of these conditions cannot be verified, the lock is left in place.

    Usage
    -----
    with WriterLock(directory, timeout=10.0):
        # ... exclusive write operations ...
    """

    _LOCK_FILENAME = ".writer_lock"
    _STALE_SECONDS = 30.0
    _POLL_INTERVAL = 0.05

    def __init__(self, directory: pathlib.Path, timeout: float = 10.0) -> None:
        self._lock_path = directory / self._LOCK_FILENAME
        self._timeout = timeout
        self._token = str(uuid.uuid4())   # random ownership token
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
                    content = f"{self._token}:{os.getpid()}"
                    os.write(fd, content.encode("ascii"))
                finally:
                    os.close(fd)
                self._acquired = True
                return
            except FileExistsError:
                # Attempt conservative stale-lock removal (proof of dead PID required)
                self._try_remove_dead_lock()
                if time.monotonic() >= deadline:
                    raise WriterLockError(
                        f"Could not acquire writer lock at {self._lock_path.name} "
                        f"within {self._timeout:.1f}s"
                    )
                time.sleep(self._POLL_INTERVAL)

    def _try_remove_dead_lock(self) -> None:
        """Remove the lock ONLY when the owning PID is provably not running.

        Conservative rules:
        - Lock file must be older than _STALE_SECONDS.
        - Content must parse as ``{token}:{pid}``.
        - PID must not exist on this system (os.kill raises ProcessLookupError).
        - On any ambiguity, leave the lock in place.
        """
        try:
            mtime = self._lock_path.stat().st_mtime
            if time.time() - mtime < self._STALE_SECONDS:
                return  # Not yet stale; leave it

            content = self._lock_path.read_text(encoding="ascii", errors="replace").strip()
            colon_idx = content.find(":")
            if colon_idx < 1:
                return  # Unrecognized format — do not touch foreign lock

            token_part = content[:colon_idx]
            pid_str = content[colon_idx + 1:]
            try:
                pid = int(pid_str)
            except ValueError:
                return  # Can't parse PID — do not touch

            # Check if PID is still alive
            try:
                os.kill(pid, 0)
                return  # PID is running — do not touch the lock
            except ProcessLookupError:
                pass    # PID is dead — safe to attempt removal
            except PermissionError:
                return  # PID exists but we can't signal — treat as alive; do not touch
            except OSError:
                return  # Cannot verify — do not touch (conservative)

            # PID is provably dead; attempt to remove the stale lock
            # Use unlink() carefully — another process may have already replaced it
            try:
                self._lock_path.unlink()
            except OSError:
                pass    # Already gone or replaced; that's fine

        except (OSError, AttributeError, ValueError):
            pass  # Any failure in stale-lock detection: do not touch

    def _release(self) -> None:
        """Release the lock only if our token matches the lock file content."""
        if not self._acquired:
            return
        try:
            content = self._lock_path.read_text(
                encoding="ascii", errors="replace"
            ).strip()
            # Only delete if the file still contains our token
            if content.startswith(f"{self._token}:"):
                self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass  # Lock file may already be gone; that's acceptable
        finally:
            self._acquired = False
