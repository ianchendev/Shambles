"""What credential bytes mean, and what else a switch has to move.

A provider knows the shape of one vendor's credential: where identity lives, how
expiry is computed, whether anything outside the credential store has to travel
with it. None of that varies by operating system -- Claude's splice of
``~/.claude.json`` is the same on macOS and Linux, and Codex's JWT decode is the
same everywhere -- which is precisely why it is separated from
:mod:`shambles.stores`.

The declarative half of each provider is a JSON file beside its module. Values
go in the JSON, because they change: research already caught the macOS Keychain
service name turning from a constant into a computed string. Algorithms stay in
Python, because they cannot be expressed as data.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Healthy: the account can be switched to and will keep working.
LIVE = "live"
#: Still usable, but the refresh window closes soon enough to mention.
CLOSING = "closing"
#: The refresh window has closed. Switching works, but the vendor will demand a
#: fresh login, so the UI must say so before the user finds out the hard way.
CLOSED = "closed"
#: No credential at all -- a profile added but never logged into.
ABSENT = "absent"
#: A credential is present but its expiry could not be determined. Claude's
#: ``refreshTokenExpiresAt`` is absent from credentials written by the VS Code
#: extension, so this is a real state and not a defensive nicety. Treated as
#: usable: refusing to switch on missing metadata would be worse than switching
#: and letting the vendor decide.
UNKNOWN = "unknown"

NEEDS_LOGIN = frozenset({CLOSED, ABSENT})


@dataclass(frozen=True)
class Identity:
    """Who a credential belongs to, in terms a person recognises."""

    email: str | None = None
    display_name: str | None = None
    org: str | None = None
    plan: str | None = None

    @property
    def known(self) -> bool:
        return bool(self.email)


@dataclass(frozen=True)
class Liveness:
    """Whether a credential still works, and for how much longer.

    ``days_left`` is kept because the countdown drives the internal threshold,
    but per DD-1 it is not what the UI puts in front of anyone -- :attr:`state`
    is. A number is meaningless for an account in daily use, whose window rolls
    forward faster than the calendar advances.
    """

    state: str
    expires_at_ms: int | None = None
    days_left: int | None = None

    @property
    def needs_login(self) -> bool:
        return self.state in NEEDS_LOGIN

    @property
    def switchable(self) -> bool:
        """Whether switching achieves anything.

        Always true. Switching to a lapsed profile is not an error -- Shambles
        copies bytes, it does not validate tokens, and the vendor prompts for
        ``/login`` which overwrites them anyway. The distinction the user needs
        is :attr:`needs_login`, not permission.
        """
        return True


@runtime_checkable
class Provider(Protocol):
    """One vendor's credential semantics, identical on every platform."""

    #: Stable key used in paths and in the spec filename.
    id: str
    #: Name shown to a person.
    display_name: str
    #: Whether the refresh token is replaced on every use. When true, a stored
    #: snapshot goes stale the moment the live credential refreshes, so it must
    #: be re-stashed after use rather than only on switch-away.
    rotates: bool
    #: Days remaining below which :data:`CLOSING` is reported. Per-provider
    #: because the windows differ by an order of magnitude -- roughly four days
    #: for Claude against ten for Codex.
    warn_days: int

    def store(self, *, home, platform: str):
        """The :class:`~shambles.stores.base.CredentialStore` for this platform."""

    def identity(self, blob: bytes | None, *, home, profile_dir=None,
                 active: bool = False) -> Identity:
        """Who this credential belongs to.

        ``profile_dir`` and ``active`` exist for providers whose identity lives
        outside the credential. Claude's does: the live ``~/.claude.json`` is
        authoritative only for the account signed in right now, so a parked
        profile must be read from its own stashed sidecar or every row shows
        the active account's email. Codex ignores both -- its identity is
        inside the token.
        """

    def liveness(self, blob: bytes | None, *, now_ms: int) -> Liveness:
        """Whether it still works."""

    def companion_read(self, *, home) -> dict:
        """Account-scoped state living outside the credential store.

        ``{}`` for a provider whose credential is self-contained.
        """

    def companion_write(self, data: dict, *, home) -> None:
        """Put :meth:`companion_read`'s output back."""

    def login_hint(self) -> str:
        """The exact command to give a user whose window has closed."""
