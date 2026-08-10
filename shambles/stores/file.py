"""Credentials as a file on disk, owner-readable only.

Codex uses this on every platform. Claude uses it on Linux, and on Windows only
as a fallback.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from .base import StoreUnavailableError

TMP_SUFFIX = ".shambles-tmp"


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

        The mode is applied to the temp file *before* the rename, so the
        credential is never briefly visible at the default umask. Codex's own
        writer gets this half right -- it sets 0600 only when creating, leaving
        an existing loose-permissioned file loose -- so this deliberately
        chmods every time rather than matching that behaviour.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + TMP_SUFFIX)
            tmp.write_bytes(payload)
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
