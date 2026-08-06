"""Credentials in the Windows Credential Manager, split across chunks.

Claude Code reaches this through ``Bun.secrets``. A credential blob exceeds the
per-entry size cap, so it is split at 2000 characters and written as a family of
entries -- ``<account>#p``, ``<account>#m``, then ``<account>#0`` through
``<account>#n-1``. **A reader that assumes one entry gets a truncated
credential**, which is the whole reason this module exists.

Bound with ``ctypes`` against ``advapi32`` rather than the ``keyring`` package,
because this project ships with no third-party dependencies and a single-file
binary; adding one for a platform path most users never touch is a poor trade.

.. warning::

   **The chunk split and join below are verified; the target-name format is
   not.** How ``Bun.secrets`` maps a (service, name) pair onto a Windows
   ``TargetName`` is an implementation detail that could not be observed --
   there was no Windows host available, and the mapping is not in the parts of
   Claude Code that could be read. :data:`TARGET_TEMPLATE` is the assumption,
   and it is isolated on one line so that correcting it is a one-line change.

   Until it is checked against a real install, treat Windows support as
   unproven. The pure functions :func:`split_payload` and :func:`join_chunks`
   are exercised by the test suite on every platform and are not in doubt.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from .base import StoreUnavailableError

#: Claude Code's chunk width, in characters.
CHUNK_SIZE = 2000

#: Entries that carry metadata rather than payload.
PREFIX_MARKER = "#p"
META_MARKER = "#m"

#: UNVERIFIED. See the module warning.
TARGET_TEMPLATE = "{service}/{account}{suffix}"

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def split_payload(payload: bytes, chunk_size: int = CHUNK_SIZE) -> list[bytes]:
    """Cut a blob into the chunks the credential manager will accept.

    An empty payload yields a single empty chunk rather than no chunks, so that
    "stored, and empty" stays distinguishable from "not stored".
    """
    if not payload:
        return [b""]
    return [payload[i:i + chunk_size]
            for i in range(0, len(payload), chunk_size)]


def join_chunks(chunks) -> bytes:
    """Reassemble chunks written by :func:`split_payload`.

    Takes an ordered sequence; ordering is the caller's job because the entry
    names carry the index.
    """
    return b"".join(chunks)


@dataclass(frozen=True)
class CredmanStore:
    service: str
    account: str
    chunk_size: int = CHUNK_SIZE
    #: Injected so the chunking can be tested without Windows.
    backend: object = field(default=None, compare=False)

    def _api(self):
        if self.backend is not None:
            return self.backend
        try:
            return _Advapi32()
        except (AttributeError, OSError) as exc:
            raise StoreUnavailableError(
                "The Windows Credential Manager is not available on this "
                f"system:\n{exc}") from exc

    def _target(self, suffix: str) -> str:
        return TARGET_TEMPLATE.format(
            service=self.service, account=self.account, suffix=suffix)

    def read(self) -> bytes | None:
        api = self._api()
        head = api.read(self._target(META_MARKER))
        if head is None:
            return None
        try:
            count = int(head.decode("ascii"))
        except ValueError as exc:
            raise StoreUnavailableError(
                f"Credential '{self.service}' has an unreadable chunk count; "
                "it may have been written by a different version.") from exc

        chunks = []
        for index in range(count):
            piece = api.read(self._target(f"#{index}"))
            if piece is None:
                raise StoreUnavailableError(
                    f"Credential '{self.service}' is missing chunk {index} of "
                    f"{count}. Refusing to return a truncated credential.")
            chunks.append(piece)
        return join_chunks(chunks)

    def write(self, payload: bytes) -> None:
        api = self._api()
        chunks = split_payload(payload, self.chunk_size)
        # Payload first, count last: a reader that arrives mid-write sees the
        # old count and the old chunks, never a new count with missing pieces.
        for index, piece in enumerate(chunks):
            api.write(self._target(f"#{index}"), piece)
        api.write(self._target(META_MARKER), str(len(chunks)).encode("ascii"))

    def delete(self) -> None:
        api = self._api()
        head = api.read(self._target(META_MARKER))
        count = int(head.decode("ascii")) if head else 0
        # Count first, so a crash mid-delete leaves no count pointing at
        # chunks that are already gone.
        api.delete(self._target(META_MARKER))
        for index in range(count):
            api.delete(self._target(f"#{index}"))

    def describe(self) -> str:
        return (f"Windows Credential Manager entry '{self.service}' "
                f"(account '{self.account}')")


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class _Advapi32:
    """Thin ``CredRead``/``CredWrite``/``CredDelete`` binding.

    Isolated in its own class so :class:`CredmanStore` can be handed a fake and
    tested on any platform.
    """

    def __init__(self):
        self._dll = ctypes.WinDLL("advapi32", use_last_error=True)

    def read(self, target: str) -> bytes | None:
        pointer = ctypes.POINTER(_CREDENTIAL)()
        ok = self._dll.CredReadW(target, CRED_TYPE_GENERIC, 0,
                                 ctypes.byref(pointer))
        if not ok:
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise StoreUnavailableError(
                f"CredRead failed for '{target}': "
                f"error {ctypes.get_last_error()}")
        try:
            blob = pointer.contents
            return ctypes.string_at(blob.CredentialBlob,
                                    blob.CredentialBlobSize)
        finally:
            self._dll.CredFree(pointer)

    def write(self, target: str, payload: bytes) -> None:
        buffer = ctypes.create_string_buffer(payload, len(payload))
        cred = _CREDENTIAL(
            Flags=0, Type=CRED_TYPE_GENERIC, TargetName=target, Comment=None,
            CredentialBlobSize=len(payload),
            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE, AttributeCount=0,
            Attributes=None, TargetAlias=None, UserName=None)
        if not self._dll.CredWriteW(ctypes.byref(cred), 0):
            raise StoreUnavailableError(
                f"CredWrite failed for '{target}': "
                f"error {ctypes.get_last_error()}")

    def delete(self, target: str) -> None:
        if not self._dll.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != ERROR_NOT_FOUND:
                raise StoreUnavailableError(
                    f"CredDelete failed for '{target}': "
                    f"error {ctypes.get_last_error()}")
