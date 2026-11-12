"""Which account is logged in for one provider, and whether Shambles knows it.

The active profile is recorded in ``~/.shambles/<provider>/active`` and then
*verified* against the identity actually present in the provider's own store,
so a login performed outside Shambles is detected rather than silently
mistrusted.

One provider at a time. Two providers have two independent active profiles and
no operation on one can affect the other, which is why every function here
takes a provider rather than looping over them.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ShamblesError
from .providers import Identity
from .providers import spec as specmod

#: The marker names a profile, and the live identity matches it.
MANAGED = "managed"
#: No profiles exist yet for this provider.
UNMANAGED = "unmanaged"
#: A profile is marked active but is no longer on disk.
MISSING_PROFILE = "missing-profile"
#: The live login belongs to some account other than the marked profile,
#: which is what a manual login looks like from here.
DRIFTED = "drifted"
#: Profiles exist but none is marked active.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class State:
    kind: str
    provider: str | None = None
    profile: str | None = None
    #: Email of whoever is actually logged in, regardless of the marker.
    live_email: str | None = None
    #: Email the marked profile expects, when that differs from live_email.
    expected_email: str | None = None


def config_dir_override(provider, *, home, env=None) -> str | None:
    """The foreign config directory this provider's environment points at.

    Returns ``None`` when unset, empty, or pointing at the very directory the
    provider uses by default -- setting it explicitly to its own default
    changes nothing and must not raise a false alarm.

    Only a terminal is affected: neither VS Code extension host inherits shell
    environment variables, which is why this tool exists at all.
    """
    env = os.environ if env is None else env
    block = provider.spec.get("config_dir") or {}
    name = block.get("env")
    raw = env.get(name, "").strip() if name else ""
    if not raw:
        return None
    default = specmod.expand(block.get("default", ""), home=home)
    try:
        if Path(raw).expanduser().resolve() == Path(default).resolve():
            return None
    except OSError:
        return raw
    return raw


def read_active(paths, provider_id: str) -> str | None:
    try:
        name = paths.active_marker(provider_id).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        # ValueError is a marker that is not text: a torn write. It names
        # nobody, which is what no marker means.
        return None
    return name or None


def write_active(paths, provider_id: str, name: str | None) -> None:
    paths.ensure_provider(provider_id)
    if name is None:
        paths.active_marker(provider_id).unlink(missing_ok=True)
        return
    paths.active_marker(provider_id).write_text(name + "\n", encoding="utf-8")


def profile_names(paths, provider_id: str) -> list[str]:
    """Directories under one provider's store that hold a profile.

    A directory counts even with no credential file: that is exactly the state
    of a profile added but not yet logged in.
    """
    try:
        entries = sorted(p for p in paths.provider_dir(provider_id).iterdir()
                         if p.is_dir())
    except OSError:
        return []
    return [p.name for p in entries if not p.name.startswith(".")]


def live_identity(paths, provider, *, platform: str):
    """Who the provider's live store says is signed in, as an ``Identity``.

    Empty when the store cannot be read. A locked Keychain or a credential
    file with the wrong permissions is not evidence of anybody, and raising
    here took the window down on startup before it could say what was wrong.
    The operations that would actually move a credential read the store
    themselves, and still refuse.
    """
    try:
        blob = provider.store(home=paths.home, platform=platform).read()
    except (OSError, ShamblesError):
        return Identity()
    return provider.identity(blob, home=paths.home, active=True)


def live_email(paths, provider, *, platform: str) -> str | None:
    """Who the provider's live store says is signed in: the address only."""
    return live_identity(paths, provider, platform=platform).email


def profile_identity(paths, provider, name: str):
    """Who a stashed profile belongs to, as an ``Identity``."""
    directory = paths.profile_dir(provider.id, name)
    try:
        blob = paths.credentials(provider.id, name).read_bytes()
    except OSError:
        blob = None
    return provider.identity(blob, home=paths.home, profile_dir=directory,
                             active=False)


def profile_email(paths, provider, name: str) -> str | None:
    """Who a stashed profile belongs to: the address only."""
    return profile_identity(paths, provider, name).email


def disagree(one, other) -> bool:
    """Whether two identities are provably different logins.

    A known mismatch in the address, or in the organisation or ChatGPT
    account behind it: one address can sign in to several, and each is a
    separate login with its own token. Anything unknown on either side is
    not evidence of anything -- a brand new profile has no expectation to
    violate, and a sidecar saved before a field existed is not a mismatch.
    """
    if one.email and other.email and one.email != other.email:
        return True
    return bool(one.account and other.account and one.account != other.account)


def describe(identity, other=None) -> str | None:
    """How to name ``identity`` beside ``other`` so the two read differently.

    The address, plus the organisation when the addresses are the same:
    "signed in as me@, but this profile holds me@" explains nothing. When
    the organisations have no names, or the same one, their ids tell them
    apart.
    """
    if not identity.email:
        return None
    if (other is None or other.email != identity.email
            or not disagree(identity, other)):
        return identity.email
    if identity.org and identity.org != other.org:
        return f"{identity.email} ({identity.org})"
    tag = (identity.account or "")[:8] or "unknown"
    return f"{identity.email} (organisation {tag})"


def holders_of_live_credential(paths, provider, *,
                               platform: str = sys.platform) -> list[str]:
    """Every profile whose stashed credential *is* the live one, byte for byte.

    The strongest answer available, and the only one no other process can
    forge. Addresses come from the vendor's own config file -- for Claude,
    ``~/.claude.json`` -- which Claude Code rewrites from memory while a
    session is running. A VS Code session doing that seconds after a switch
    made the window's drift correction move the marker back to the account
    the user had just left, while the token on disk was the new one the whole
    time. That is why usage updated and the address did not.

    Empty when nothing matches, which is the normal answer for a provider
    whose token rotates: Codex mints a replacement on every use, so its live
    copy legitimately differs from the stash. The address check is still
    right there, and still the fallback.

    A list because one login can be saved under two names. Callers that care
    which of them is marked must ask, not take the first.
    """
    try:
        live = provider.store(home=paths.home, platform=platform).read()
    except Exception:
        return []  # an unreadable store is not evidence of anything
    return profiles_holding(paths, provider.id, live)


def profiles_holding(paths, provider_id: str, blob) -> list[str]:
    """Every profile whose stashed credential is exactly ``blob``.

    For a caller that already has the bytes in hand and is about to act on
    them. Asking the store a second time would be asking about a different
    moment: the answer that matters is the one about *these* bytes.
    """
    if not blob:
        return []
    found = []
    for name in profile_names(paths, provider_id):
        try:
            if paths.credentials(provider_id, name).read_bytes() == blob:
                found.append(name)
        except OSError:
            continue
    return found


def holder_of_live_credential(paths, provider, *, platform: str = sys.platform):
    """One profile holding the live credential, or None.

    See :func:`holders_of_live_credential`. The marked profile is preferred
    when it is among them, so a login saved under two names never reads as a
    reason to move the marker from one to the other.
    """
    holders = holders_of_live_credential(paths, provider, platform=platform)
    marked = read_active(paths, provider.id)
    if marked in holders:
        return marked
    return holders[0] if holders else None


def profiles_continuing(paths, provider, blob) -> list[str]:
    """Every profile whose saved login ``blob`` is a refresh of.

    Lineage, as the provider defines it: Claude's sign-in deadline, which a
    refresh recomputes to within a second or so; Codex's account and the
    address inside the token. A credential with no token in it continues
    nothing -- a login cleared in place keeps its deadline.
    """
    if not blob or not provider.has_login(blob):
        return []
    found = []
    for name in profile_names(paths, provider.id):
        try:
            saved = paths.credentials(provider.id, name).read_bytes()
        except OSError:
            continue
        if provider.same_login(saved, blob):
            found.append(name)
    return found


def proven_owners(paths, provider, blob) -> list[str]:
    """The profiles ``blob`` provably belongs to: the bytes, else the lineage.

    Proof is what no other program can produce. The address in the vendor's
    config file is not proof: any Claude Code session still running rewrites
    it from memory, and it reads as nobody while a write is half done.
    """
    return (profiles_holding(paths, provider.id, blob)
            or profiles_continuing(paths, provider, blob))


def owner_of_live(paths, provider, *, platform: str = sys.platform):
    """The saved profile this live login provably belongs to, or None.

    The bytes first, then the lineage; never the address. What this answers
    is acted on without asking -- the marker is moved to it on every refresh
    of every interface -- and the next switch files the live login under
    whatever the marker names. See :func:`owner_by_address` for the
    suggestion that may only be offered.
    """
    try:
        live = provider.store(home=paths.home, platform=platform).read()
    except Exception:
        return None  # an unreadable store is not evidence of anything
    owners = proven_owners(paths, provider, live)
    marked = read_active(paths, provider.id)
    if marked in owners:
        return marked
    return owners[0] if owners else None


def owner_by_address(paths, provider, *, platform: str = sys.platform):
    """The saved profile whose stored address the live login carries, or None.

    A suggestion, never a proof: something to name to the user, who knows
    which account they signed in as. For a new browser sign-in, whose bytes
    and lineage no profile can share yet, it is the only clue there is, and
    switching to the profile it names is how the user confirms it.
    """
    live = live_identity(paths, provider, platform=platform)
    if not live.email:
        return None
    exact, loose = [], []
    for name in profile_names(paths, provider.id):
        saved = profile_identity(paths, provider, name)
        if saved.email != live.email or disagree(saved, live):
            continue
        # The same organisation known on both sides beats one not recorded.
        (exact if saved.account and saved.account == live.account
         else loose).append(name)
    return (exact or loose or [None])[0]


def inspect(paths, provider, *, platform: str = sys.platform) -> State:
    """Classify one provider's login without touching anything."""
    names = profile_names(paths, provider.id)
    marked = read_active(paths, provider.id)
    live_id = live_identity(paths, provider, platform=platform)
    live = live_id.email

    # A marker naming a profile that is gone matters more than the store being
    # empty -- otherwise deleting the last profile reads as a clean unmanaged
    # machine and the stale marker is never surfaced.
    if marked is not None and marked not in names:
        return State(MISSING_PROFILE, provider.id, profile=marked, live_email=live)
    if not names:
        return State(UNMANAGED, provider.id, live_email=live)
    if marked is None:
        return State(UNKNOWN, provider.id, live_email=live)

    expected_id = profile_identity(paths, provider, marked)
    expected = expected_id.email

    # Ask the credential before the address, exactly as owner_of_live does.
    # The address is whatever the vendor's config file says, and for Claude
    # that file is rewritten from memory by any session still running: it can
    # lag a switch, and it can agree with the marker while the bytes in the
    # store are another profile's. A stashed credential identical to the live
    # one is proof either way.
    # The lineage next: a refresh rotates the token, so the bytes stop
    # matching within hours, but the login it continues is still known.
    try:
        blob = provider.store(home=paths.home, platform=platform).read()
    except Exception:
        blob = None
    owners = proven_owners(paths, provider, blob)
    if marked in owners:
        return State(MANAGED, provider.id, profile=marked,
                     live_email=expected or live)
    if owners:
        theirs = profile_identity(paths, provider, owners[0])
        if not theirs.email:
            theirs = live_id
        return State(DRIFTED, provider.id, profile=marked,
                     live_email=describe(theirs, expected_id),
                     expected_email=describe(expected_id, theirs))

    # Only call it drift when both sides actually name someone. A profile that
    # has never been logged into has no expectation to violate.
    if disagree(expected_id, live_id):
        return State(DRIFTED, provider.id, profile=marked,
                     live_email=describe(live_id, expected_id),
                     expected_email=describe(expected_id, live_id))

    return State(MANAGED, provider.id, profile=marked, live_email=live or expected)
