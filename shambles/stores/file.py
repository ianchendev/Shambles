"""Credentials as a file on disk, owner-readable only.

Codex uses this on every platform. Claude uses it on Linux, and on Windows only
as a fallback.
"""

import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from .base import StoreUnavailableError

#: Every temp file ends in this, so nothing mistakes one for the file it was
#: meant to become. Up to 2.1.2 it was the whole temp name, ``<file>`` plus
#: this, shared by every writer; now each write has one of its own.
TMP_SUFFIX = ".shambles-tmp"

#: A temp file older than this was left by a writer that was killed between
#: creating it and renaming it. A write takes milliseconds, so five minutes
#: is far past any writer that is still alive.
STALE_AFTER = 300

#: Windows opens descriptors in text mode by default and rewrites every "\n"
#: as "\r\n" on the way out. A credential is bytes, not text: a token
#: containing a newline would come back a different length than it went in,
#: which is precisely the round trip this project exists to keep exact.
#: O_BINARY does not exist on POSIX, where there is nothing to turn off.
BINARY_FLAG = getattr(os, "O_BINARY", 0)


def replace_file(path, payload: bytes, *, mode: int = 0o600) -> None:
    """Replace ``path`` with ``payload``, whole, readable only by its owner.

    Saved logins, the vendors' live login files and the JSON files Shambles
    keeps beside them all come through here. Raises ``OSError``;
    :class:`FileStore` turns that into a ShamblesError.

    * **A temp file of its own.** Created in the same directory under a
      random name with ``O_EXCL``, so it is always a new file and the mode
      given is the mode it has from its first byte. Two processes writing
      the same file each fill and rename their own; the file is always one
      of their payloads, never a mixture.
    * **All of it, on disk, then renamed.** ``os.write`` may write less than
      it is given, so it is called until nothing is left; ``fsync`` before
      the rename, so a power cut cannot leave an empty file at the real name.
    * **Nothing left behind.** If anything fails, or the process is
      interrupted, before the rename, the temp file is removed. One left by a
      writer that was killed outright is owner-only and never read as a
      login. The next write of the same file removes it once it is older
      than :data:`STALE_AFTER`, and a delete removes it at once.
    """
    path = Path(path)
    tmp, fd = _create_temp(path, mode)
    try:
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, mode)  # exact, whatever the umask took away
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        # Windows has no fchmod, and this is the call it does have.
        os.chmod(tmp, mode)
        # Not retried, on any system. Windows refuses to replace a file that
        # another program has open, and waiting that out would overwrite
        # whatever that program wrote meanwhile: if it was the vendor rotating
        # its token, the rotated token. The write fails and says so instead
        # (TECH_SPEC section 2.2).
        os.replace(tmp, path)
    except BaseException:
        _remove_quietly(tmp)
        raise
    _sync_directory(path.parent)
    sweep_temps(path, older_than=STALE_AFTER)


def sweep_temps(path, *, older_than: float | None = None) -> None:
    """Remove temp files left beside ``path`` by earlier writes of it.

    Only temps of ``path`` itself, by either naming. ``older_than`` spares
    any that a live writer may still be about to rename. Best effort: a temp
    that cannot be removed now is tried again next time.
    """
    path = Path(path)
    mine = re.compile(re.escape(f".{path.name}.") + r"[0-9a-f]{16}"
                      + re.escape(TMP_SUFFIX))
    legacy = path.name + TMP_SUFFIX
    try:
        entries = list(os.scandir(path.parent))
    except OSError:
        return
    now = time.time()
    for entry in entries:
        if not (entry.name == legacy or mine.fullmatch(entry.name)):
            continue
        try:
            if older_than is not None:
                if now - entry.stat(follow_symlinks=False).st_mtime < older_than:
                    continue
            os.unlink(entry.path)
        except OSError:
            continue


def _create_temp(path: Path, mode: int):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | BINARY_FLAG
    for _ in range(100):
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}{TMP_SUFFIX}")
        try:
            return tmp, os.open(tmp, flags, mode)
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create a temp file beside {path}")


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _sync_directory(directory: Path) -> None:
    """Make the rename itself durable. POSIX only, and never a failure."""
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@dataclass(frozen=True)
class FileStore:
    path: Path
    mode: int = 0o600

    def read(self) -> bytes | None:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not read {self.path}:\n{exc}") from exc

    def write(self, payload: bytes) -> None:
        """Replace the file with ``payload`` through :func:`replace_file`.

        Also keeps the directory owner-only where the system can express it.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass  # Windows cannot express this; the file mode still applies
            replace_file(self.path, payload, mode=self.mode)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not write {self.path}:\n{exc}") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not remove {self.path}:\n{exc}") from exc
        # Whatever their age: after a delete, no copy of this login is left
        # here. A writer racing the delete loses its rename, not a login.
        sweep_temps(self.path)

    def describe(self) -> str:
        return str(self.path)
