"""Two stores layered the way Claude Code layers them.

Claude Code does not keep its login in one place per platform. On macOS it is
the Keychain *with a plaintext fallback*; on Windows, once Credential Manager
is switched on for an account, it is Credential Manager *with a plaintext
fallback*. The shipping binary names these backends
``keychain-with-plaintext-fallback`` and
``windows-credman-with-plaintext-fallback``, and builds both from one
combinator. This class is that combinator, restated:

==========  ===============================================================
read        the primary if it holds anything, otherwise the fallback
write       the primary; and if the primary was empty before, clear the
            fallback so a stale file cannot be read later. If the primary
            refuses the write while empty, write the fallback instead
delete      both
==========  ===============================================================

Mirroring the vendor exactly is the point rather than a convenience. A store
that only knew about the Keychain would report "not signed in" on a Mac used
over SSH, where the login sits in ``~/.claude/.credentials.json`` -- and a
switch from that state would put the incoming credential somewhere the vendor
does not look.

**Where the replaced bytes go.** ``write`` can delete the fallback, which
looks like a second destructive step. It is not a new one: the fallback is
only cleared when the primary was empty, and in that state the fallback *was*
the live credential -- the very bytes ``read`` just returned to whoever is
about to overwrite them. Nothing is removed that a plain overwrite would have
kept.
"""

from dataclasses import dataclass

from .base import StoreLockedError, StoreUnavailableError


@dataclass(frozen=True)
class FallbackStore:
    primary: object
    fallback: object

    def read(self) -> bytes | None:
        try:
            blob = self.primary.read()
        except StoreLockedError:
            # The vendor reads a locked primary as empty and consults its
            # file. Follow it only when the file actually answers; with
            # nothing there either, "locked" is the truth worth reporting,
            # not "signed out".
            blob = self.fallback.read()
            if blob is None:
                raise
            return blob
        if blob is not None:
            return blob
        return self.fallback.read()

    def write(self, payload: bytes) -> None:
        try:
            before = self.primary.read()
        except StoreLockedError:
            if self.fallback.read() is None:
                raise
            self.fallback.write(payload)
            return

        try:
            self.primary.write(payload)
        except StoreUnavailableError:
            # A primary that already holds a login must not be shadowed by a
            # file: the vendor would go on reading the primary and the write
            # would have landed where nothing looks.
            if before is not None:
                raise
            self.fallback.write(payload)
            return

        if before is None:
            try:
                self.fallback.delete()
            except StoreUnavailableError:
                pass  # the primary now wins every read; a stale file is inert

    def delete(self) -> None:
        refusal = None
        try:
            self.primary.delete()
        except StoreUnavailableError as exc:
            refusal = exc
        had_fallback = self.fallback.read() is not None
        self.fallback.delete()
        if refusal is not None and not had_fallback:
            raise refusal

    def describe(self) -> str:
        return f"{self.primary.describe()} (or {self.fallback.describe()})"
