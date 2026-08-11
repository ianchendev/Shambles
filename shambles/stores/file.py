"""Credentials as a file on disk, owner-readable only.

Codex uses this on every platform. Claude uses it on Linux, and on Windows only
as a fallback.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .base import StoreUnavailableError

TMP_SUFFIX = ".shambles-tmp"

#: Windows opens descriptors in text mode by default and rewrites every "\n"
#: as "\r\n" on the way out. A credential is bytes, not text: a token
#: containing a newline would come back a different length than it went in,
#: which is precisely the round trip this project exists to keep exact.
#: O_BINARY does not exist on POSIX, where there is nothing to turn off.
BINARY_FLAG = getattr(os, "O_BINARY", 0)


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
        """Write via a same-directory temp file, then rename over the original.

        The temp file is opened with its final mode rather than chmod'd after
        the fact. Creating it at the umask and tightening it afterwards leaves
        the complete plaintext credential world-readable in between, which is
        a window, not a formality. Codex's own writer gets this half right --
        it sets 0600 only on creation, leaving an existing loose file loose --
        so this sets the mode every time.

        ``O_CREAT`` honours the ``mode`` argument only when it actually
        creates the file. A ``*.shambles-tmp`` left behind at a loose mode by
        a crashed run is opened, not created, so the mode passed to
        :func:`os.open` is silently ignored for it -- the payload would land
        at the old mode before anything fixed it. ``os.fchmod`` closes that
        because it acts on the open descriptor regardless of whether the file
        pre-existed, so it runs before the first byte is written rather than
        after the last one. Windows has no ``os.fchmod``; the trailing
        ``os.chmod`` stays so that platform keeps its previous (best-effort)
        behaviour, and is otherwise a harmless no-op once ``fchmod`` has
        already put the descriptor at the right mode.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass  # Windows cannot express this; the file mode still applies
            tmp = self.path.with_name(self.path.name + TMP_SUFFIX)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | BINARY_FLAG,
                         self.mode)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, self.mode)
                os.write(fd, payload)
            finally:
                os.close(fd)
            os.chmod(tmp, self.mode)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not write {self.path}:\n{exc}") from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not remove {self.path}:\n{exc}") from exc

    def describe(self) -> str:
        return str(self.path)
