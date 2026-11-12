"""Credentials in the Windows Credential Manager, in Claude Code's own layout.

Claude Code reaches Credential Manager through ``Bun.secrets``, and only for
accounts where it has been switched on -- by a server-side rollout flag, or by
``CLAUDE_CODE_FORCE_WINDOWS_CREDMAN=1``. Everybody else on Windows still has a
plain ``.credentials.json``. Deciding which applies is the provider's job; this
module only knows the layout, which has to be matched exactly or the vendor
reads nothing.

**The layout**, read out of the shipping Windows binary (2.1.322) and Bun's
``SecretsWindows.cpp``:

* Every entry is a generic credential whose target is ``<service>/<name>``,
  with the UTF-8 bytes of the value as its blob.
* A value of 2400 bytes or fewer is **one** entry, named for the account
  alone, holding the JSON as it is.
* Anything larger is base64-encoded and cut into 2400-character pieces,
  ``<account>#0`` onwards, with ``<account>#m`` holding
  ``{"n": pieces, "l": base64 length}``. The base64 step is what makes the
  split safe: a cut can never land inside a multi-byte character.
* ``<account>#p`` is a marker written before the pieces and removed after
  them. It records how many pieces may exist, so an interrupted write can
  still be cleaned up by whoever comes next.

A reader that assumes one entry gets nothing for a large credential, and one
that assumes pieces gets nothing for a small one. Both are handled here.

Bound with ``ctypes`` against ``advapi32`` rather than the ``keyring`` package,
because this project ships with no third-party dependencies beyond its
terminal UI and as a single-file binary; adding one for a store most Windows
users do not have switched on yet is a poor trade.
"""

import base64
import binascii
import ctypes
import json
import math
from ctypes import wintypes
from dataclasses import dataclass, field

from .base import StoreUnavailableError

#: Claude Code's piece width, in bytes for a whole value and in base64
#: characters for a split one. Credential Manager caps a blob at 2560 bytes.
CHUNK_SIZE = 2400

#: The most pieces Claude Code will write or believe.
MAX_CHUNKS = 256

#: Entries that carry bookkeeping rather than payload.
PENDING_MARKER = "#p"
META_MARKER = "#m"

#: How ``Bun.secrets`` turns (service, name) into a Windows target name.
TARGET_TEMPLATE = "{service}/{name}"

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def split_payload(encoded: bytes, chunk_size: int = CHUNK_SIZE) -> list[bytes]:
    """Cut base64 text into the pieces Credential Manager will accept."""
    return [encoded[i:i + chunk_size]
            for i in range(0, len(encoded), chunk_size)]


def join_chunks(chunks) -> bytes:
    """Reassemble pieces written by :func:`split_payload`.

    Takes an ordered sequence; ordering is the caller's job because the entry
    names carry the index.
    """
    return b"".join(chunks)


def parse_meta(raw: bytes | None, *, chunk_size: int = CHUNK_SIZE):
    """``(pieces, base64 length)`` from a ``#m`` entry, or ``None``.

    The same acceptance test Claude Code applies. Anything it would reject is
    rejected here too, so both programs agree on whether a credential is
    split -- an entry one side honours and the other ignores is how the two
    end up reading different logins.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    count, length = data.get("n"), data.get("l")
    for value in (count, length):
        if isinstance(value, bool) or not isinstance(value, int):
            return None
    if not (0 < count <= MAX_CHUNKS and 0 < length <= count * chunk_size):
        return None
    return count, length


@dataclass(frozen=True)
class CredmanStore:
    service: str
    account: str
    chunk_size: int = CHUNK_SIZE
    #: Injected so the layout can be tested without Windows.
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

    def _name(self, suffix="") -> str:
        return f"{self.account}{suffix}"

    def _target(self, suffix="") -> str:
        return TARGET_TEMPLATE.format(service=self.service,
                                      name=self._name(suffix))

    def _meta(self, api):
        return parse_meta(api.read(self._target(META_MARKER)),
                          chunk_size=self.chunk_size)

    def read(self) -> bytes | None:
        api = self._api()
        meta = self._meta(api)
        if meta is None:
            return api.read(self._target())

        count, length = meta
        pieces = [api.read(self._target(f"#{index}")) for index in range(count)]
        missing = [index for index, piece in enumerate(pieces) if piece is None]
        encoded = join_chunks(piece or b"" for piece in pieces)
        if missing or len(encoded) != length:
            raise StoreUnavailableError(
                f"Credential '{self.service}' is incomplete in the Windows "
                f"Credential Manager: {len(encoded)} of {length} characters "
                f"across {count} pieces. Refusing to return a truncated "
                "credential.")
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StoreUnavailableError(
                f"Credential '{self.service}' in the Windows Credential "
                "Manager is not readable; it may have been written by a "
                "different version.") from exc

    def write(self, payload: bytes) -> None:
        api = self._api()
        old = self._meta(api)
        old_count = old[0] if old else 0

        if len(payload) <= self.chunk_size:
            api.write(self._target(), payload, username=self._name())
            if old:
                # The whole entry now wins every read, so the pieces behind
                # it are leftovers. Marked before they go so that a crash in
                # the middle still says how many there were.
                api.write(self._target(PENDING_MARKER),
                          str(old_count).encode("ascii"),
                          username=self._name(PENDING_MARKER))
                api.delete(self._target(META_MARKER))
                for index in range(old_count):
                    _quietly(api.delete, self._target(f"#{index}"))
                _quietly(api.delete, self._target(PENDING_MARKER))
            return

        encoded = base64.b64encode(payload)
        count = math.ceil(len(encoded) / self.chunk_size)
        if count > MAX_CHUNKS:
            raise StoreUnavailableError(
                f"This credential is too large for the Windows Credential "
                f"Manager ({len(payload)} bytes).")

        api.write(self._target(PENDING_MARKER),
                  str(max(old_count, count)).encode("ascii"),
                  username=self._name(PENDING_MARKER))
        for index, piece in enumerate(split_payload(encoded, self.chunk_size)):
            api.write(self._target(f"#{index}"), piece,
                      username=self._name(f"#{index}"))
        # The count goes last: until it lands, a reader still sees whatever
        # described the previous credential.
        api.write(self._target(META_MARKER),
                  json.dumps({"n": count, "l": len(encoded)},
                             separators=(",", ":")).encode("ascii"),
                  username=self._name(META_MARKER))

        _quietly(api.delete, self._target())
        for index in range(count, old_count):
            _quietly(api.delete, self._target(f"#{index}"))
        _quietly(api.delete, self._target(PENDING_MARKER))

    def delete(self) -> None:
        api = self._api()
        meta = self._meta(api)
        known = meta[0] if meta else 0

        api.delete(self._target())
        # Count first, so a crash mid-delete leaves no count pointing at
        # pieces that are already gone.
        api.delete(self._target(META_MARKER))
        for index in range(known):
            api.delete(self._target(f"#{index}"))

        # An interrupted write leaves pieces no count describes. The marker
        # says how many; without one, walk until a gap.
        total = max(known, _pending_count(api.read(self._target(PENDING_MARKER))))
        if total == 0:
            while (total < MAX_CHUNKS
                   and api.read(self._target(f"#{total}")) is not None):
                total += 1
        for index in range(known, total):
            api.delete(self._target(f"#{index}"))
        api.delete(self._target(PENDING_MARKER))

    def describe(self) -> str:
        return (f"Windows Credential Manager entry '{self._target()}'")


def _pending_count(raw: bytes | None) -> int:
    try:
        return min(max(int((raw or b"0").decode("ascii")), 0), MAX_CHUNKS)
    except (UnicodeDecodeError, ValueError):
        return 0


def _quietly(action, *args) -> None:
    """Run a clean-up step whose failure changes nothing a reader sees."""
    try:
        action(*args)
    except StoreUnavailableError:
        pass


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
        # Declared rather than left to ctypes' int defaults: a pointer passed
        # as a 32-bit int is truncated on 64-bit Windows.
        pointer = ctypes.POINTER(_CREDENTIAL)
        self._dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                        wintypes.DWORD, ctypes.POINTER(pointer)]
        self._dll.CredReadW.restype = wintypes.BOOL
        self._dll.CredWriteW.argtypes = [pointer, wintypes.DWORD]
        self._dll.CredWriteW.restype = wintypes.BOOL
        self._dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                          wintypes.DWORD]
        self._dll.CredDeleteW.restype = wintypes.BOOL
        self._dll.CredFree.argtypes = [ctypes.c_void_p]
        self._dll.CredFree.restype = None

    def read(self, target: str) -> bytes | None:
        pointer = ctypes.POINTER(_CREDENTIAL)()
        ok = self._dll.CredReadW(target, CRED_TYPE_GENERIC, 0,
                                 ctypes.byref(pointer))
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                return None
            raise StoreUnavailableError(
                f"Windows Credential Manager could not read '{target}': "
                f"{_describe(code)}")
        try:
            blob = pointer.contents
            return ctypes.string_at(blob.CredentialBlob,
                                    blob.CredentialBlobSize)
        finally:
            self._dll.CredFree(pointer)

    def write(self, target: str, payload: bytes, *, username=None) -> None:
        buffer = ctypes.create_string_buffer(payload, len(payload))
        cred = _CREDENTIAL(
            Flags=0, Type=CRED_TYPE_GENERIC, TargetName=target, Comment=None,
            CredentialBlobSize=len(payload),
            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE, AttributeCount=0,
            Attributes=None, TargetAlias=None, UserName=username)
        if not self._dll.CredWriteW(ctypes.byref(cred), 0):
            raise StoreUnavailableError(
                f"Windows Credential Manager could not write '{target}': "
                f"{_describe(ctypes.get_last_error())}")

    def delete(self, target: str) -> None:
        if not self._dll.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            code = ctypes.get_last_error()
            if code != ERROR_NOT_FOUND:
                raise StoreUnavailableError(
                    f"Windows Credential Manager could not remove "
                    f"'{target}': {_describe(code)}")


def _describe(code: int) -> str:
    """A Windows error as a sentence, falling back to its number."""
    try:
        text = ctypes.FormatError(code).strip()
    except (AttributeError, OSError):
        text = ""
    return f"{text} (error {code})" if text else f"error {code}"
