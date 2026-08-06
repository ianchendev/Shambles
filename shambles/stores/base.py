"""What a credential store is, and nothing about what it stores.

A store answers one question: give me the bytes, or put these bytes back. It
does not know the bytes are JSON, that there is a token inside, or which product
issued it. That knowledge lives one layer up, in :mod:`shambles.providers`.

Keeping the two apart is what stops the implementations multiplying. Claude uses
a different store on each operating system while Codex uses the same one
everywhere; written as one class per combination that would be six classes, four
of them near-duplicates. Split along both axes it is three stores and two
providers.

``Protocol`` rather than a base class on purpose: a test can hand any object with
these three methods to a provider, and an in-memory fake needs no inheritance.
"""

from typing import Protocol, runtime_checkable

from ..errors import ShamblesError


class StoreUnavailableError(ShamblesError):
    """The store itself could not be reached.

    Distinct from "there is no credential here", which is a ``None`` from
    :meth:`CredentialStore.read`. This means the Keychain refused, the
    credential manager is missing, or the file could not be opened for a reason
    other than absence -- conditions where continuing would be guesswork.
    """


@runtime_checkable
class CredentialStore(Protocol):
    """Somewhere a blob of bytes can be kept, per platform."""

    def read(self) -> bytes | None:
        """The stored bytes, or ``None`` if nothing is stored yet.

        ``None`` is the normal answer for a profile that has never been logged
        into. Failure to reach the store raises
        :class:`StoreUnavailableError` instead.
        """

    def write(self, payload: bytes) -> None:
        """Replace the stored bytes.

        Implementations must be atomic from a reader's point of view: a
        half-written credential must never be observable.
        """

    def delete(self) -> None:
        """Remove the stored bytes. Absence is not an error."""

    def describe(self) -> str:
        """One line naming this store, for error messages the user will read."""
