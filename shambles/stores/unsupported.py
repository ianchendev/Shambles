"""A store that only explains why there is no store.

Some configurations put a vendor's login somewhere Shambles cannot follow --
Codex told to use the system keyring is the first. The dangerous response is
to carry on with the file store anyway: a switch then writes a credential the
vendor never opens and reports success.

Returning one of these instead means nothing can be written or removed, and
every attempt fails with the same sentence, through the path a locked
Keychain already takes.

**Reading answers "nothing here" rather than failing**, and that is a
decision, not an oversight. It is true -- there is no login in the place this
store stands in for -- and it keeps every screen that merely *lists* accounts
working. The refusal arrives at the moment somebody tries to change
something, which is the moment it matters and the moment there is a dialog
to put it in. A read that raised would instead take the window down on
start-up, before it could say anything at all.
"""

from dataclasses import dataclass

from .base import StoreUnavailableError


@dataclass(frozen=True)
class UnsupportedStore:
    #: The whole message a person sees: what is going on, and what to do.
    reason: str
    #: One line naming where the vendor keeps the login instead.
    where: str

    def read(self) -> bytes | None:
        return None

    def write(self, payload: bytes) -> None:
        raise StoreUnavailableError(self.reason)

    def delete(self) -> None:
        raise StoreUnavailableError(self.reason)

    def describe(self) -> str:
        return self.where
