"""Everything a native shell needs to render, computed once, in one call.

The view model in the MVVM sense, and deliberately a plain function rather
than an object: a menu bar panel is rebuilt each time it opens, so there is no
view state to hold. That is the same discipline the Tk window already follows.

Everything a shell displays is decided **here**, in Python, where it is
tested. A shell must not re-derive any of it: if Swift computes "can I switch
to this" from an expiry timestamp, that rule has two implementations and only
one of them has tests.

Reads through the same :mod:`shambles.profiles` and :mod:`shambles.state` the
window uses, so the panel and the window cannot disagree about what is on disk.
"""

from dataclasses import dataclass, field

from .. import profiles as profiles_mod
from .. import state as state_mod
from .. import switcher

#: Bumped when the JSON shape changes incompatibly. A shell that meets an
#: unfamiliar version must say "update Shambles" rather than guess -- the app
#: bundle and the CLI ship separately and can drift.
CONTRACT_VERSION = 1


@dataclass(frozen=True)
class Surface:
    """One application a switch moves.

    Shown as a pill, because the coupling is the one thing a person cannot
    infer: Terminal and VS Code share a credential store, so switching either
    switches both, and Codex takes ChatGPT.app with it as well.
    """

    id: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Window:
    label: str
    used_percent: int | None
    resets_at_ms: int | None = None
    resets_label: str | None = None
    age_label: str | None = None
    stale: bool = False


@dataclass(frozen=True)
class Account:
    name: str
    email: str | None = None
    display_name: str | None = None
    plan: str | None = None
    active: bool = False
    state: str = ""
    needs_login: bool = False
    login_hint: str | None = None
    usage: list = field(default_factory=list)


@dataclass(frozen=True)
class Notice:
    """Something true about a provider that its accounts cannot show.

    ``code`` is stable and is what a frontend keys its own next step off --
    the terminal UI's key, the CLI's command. ``message`` says what is true
    and ``remedy`` what to do, in words that hold for any frontend.
    """

    code: str
    message: str
    remedy: str = ""
    #: The saved account the notice is about, when there is one.
    account: str | None = None


@dataclass(frozen=True)
class Group:
    provider: str
    display_name: str
    surfaces: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    #: :func:`shambles.state.inspect`'s kind for this provider.
    state: str = ""
    #: Who is actually signed in, whoever the marker names.
    live_email: str | None = None
    #: A live login no saved account holds, which saving would keep.
    can_save: bool = False
    notices: list = field(default_factory=list)


@dataclass(frozen=True)
class Snapshot:
    version: int
    groups: list = field(default_factory=list)


def build(*, paths, providers, platform: str, now_ms: int) -> Snapshot:
    """Describe every profile of every provider for display."""
    return Snapshot(CONTRACT_VERSION,
                    [_group(paths, p, platform=platform, now_ms=now_ms)
                     for p in providers])


def _group(paths, provider, *, platform: str, now_ms: int) -> Group:
    surfaces = [Surface(s.get("id", ""), s.get("label", ""), s.get("detail", ""))
                for s in provider.spec.get("surfaces", [])
                if isinstance(s, dict)]

    active = state_mod.read_active(paths, provider.id)
    found = profiles_mod.discover(paths, provider, active, now_ms,
                                  platform=platform)
    current = state_mod.inspect(paths, provider, platform=platform)
    unreadable = _store_error(paths, provider, platform=platform)
    live_login = unreadable is None and _has_login(paths, provider,
                                                   platform=platform)
    owner = (state_mod.owner_of_live(paths, provider, platform=platform)
             if current.kind == state_mod.DRIFTED else None)
    can_save = live_login and current.kind != state_mod.MANAGED and not owner

    accounts = []
    for profile in found:
        lapsed = profiles_mod.needs_login(profile)
        email = profile.email
        if profile.active and current.kind == state_mod.DRIFTED:
            # The marked profile's own address. The live one is somebody
            # else's, and showing it under this name is how a stranger's
            # login came to read as "Work" in the list.
            email = current.expected_email
        accounts.append(Account(
            name=profile.name,
            email=email,
            plan=profile.plan,
            active=profile.active,
            state=profile.liveness.state,
            needs_login=lapsed,
            # Carried only when it is actionable. A hint attached to a healthy
            # account is noise a shell would then have to decide to hide.
            login_hint=provider.login_hint() if lapsed else None,
            usage=_windows(profile, now_ms=now_ms),
        ))
    return Group(provider.id, provider.display_name, surfaces, accounts,
                 state=current.kind, live_email=current.live_email,
                 can_save=can_save,
                 notices=_notices(paths, provider, current, owner=owner,
                                  can_save=can_save, unreadable=unreadable))


def _store_error(paths, provider, *, platform):
    """Where the live store is, when it cannot be read; None when it can.

    The location only, never the exception's text: what a Keychain or
    credential manager says when it refuses is not something this contract
    has vetted for secrets, and the snapshot goes to stdout.
    """
    from ..errors import ShamblesError
    try:
        store = provider.store(home=paths.home, platform=platform)
    except ShamblesError:
        return "its credential store"
    try:
        store.read()
    except ShamblesError:
        return store.describe()
    return None


def _has_login(paths, provider, *, platform) -> bool:
    """Whether a credential is live, readable or not attributable to anyone.

    Read from the store rather than from ``live_email``: Claude with no
    ``~/.claude.json`` yet has a login worth saving and no address.
    """
    from ..errors import ShamblesError
    try:
        return provider.store(home=paths.home, platform=platform).read() is not None
    except ShamblesError:
        return False


def _notices(paths, provider, current, *, owner, can_save, unreadable):
    name = provider.display_name
    notices = []
    if unreadable:
        notices.append(Notice(
            "store_unreadable",
            f"Can't read the {name} login in {unreadable}.",
            "Unlock the credential store or fix the file's permissions, then "
            "refresh. Switching is unavailable until it can be read."))
    if current.kind == state_mod.MISSING_PROFILE:
        notices.append(Notice(
            "missing_profile",
            f"'{current.profile}' is marked active but is no longer on disk.",
            "Save the current login, or switch to a saved account.",
            account=current.profile))
    if owner:
        notices.append(Notice(
            "signed_in_elsewhere",
            f"Signed in as {current.live_email or 'another account'}, which "
            f"is saved as '{owner}', but '{current.profile}' is marked "
            "active.",
            f"Switch to '{owner}' to settle it. Nothing is lost either way.",
            account=owner))
    if can_save:
        who = current.live_email
        lead = (f"Signed in as {who}, which is not saved yet." if who else
                f"Signed in to {name} with a login that is not saved yet.")
        if current.kind == state_mod.DRIFTED and current.profile:
            lead += (f" '{current.profile}' is "
                     f"{current.expected_email or 'a different account'}.")
        notices.append(Notice(
            "unsaved_login", lead,
            "Save it as an account before switching, or switching away will "
            "replace it with no copy kept."))
    override = state_mod.config_dir_override(
        provider, home=paths.home, env=getattr(provider, "env", None))
    if override:
        variable = (provider.spec.get("config_dir") or {}).get("env", "")
        notices.append(Notice(
            "config_override",
            f"{variable} is set to {override}. A terminal with it set reads "
            "its own login there, so switching here does not change that "
            "terminal. VS Code is unaffected.",
            f"Unset {variable} in your shell profile to switch that terminal "
            "too."))
    return notices


def _windows(profile, *, now_ms: int) -> list:
    """Quota bars, flattened to the wire shape.

    Stashed figures are marked rather than hidden: a parked profile's last
    known usage is worth showing, but not worth reading as current.
    """
    usage = getattr(profile, "usage", None)
    if not usage:
        return []
    stale = usage.is_stale(now_ms)
    return [Window(bar.label, bar.percent,
                   resets_label=bar.resets_label(),
                   age_label=usage.age_label(now_ms),
                   stale=stale)
            for bar in usage.bars]


def to_dict(snapshot: Snapshot) -> dict:
    """The wire form. These field names are the cross-language contract."""
    return {
        "version": snapshot.version,
        "groups": [
            {
                "provider": group.provider,
                "display_name": group.display_name,
                "state": group.state,
                "live_email": group.live_email,
                "can_save": group.can_save,
                "notices": [{"code": n.code, "message": n.message,
                             "remedy": n.remedy, "account": n.account}
                            for n in group.notices],
                "surfaces": [{"id": s.id, "label": s.label, "detail": s.detail}
                             for s in group.surfaces],
                "accounts": [
                    {
                        "name": a.name,
                        "email": a.email,
                        "display_name": a.display_name,
                        "plan": a.plan,
                        "active": a.active,
                        "state": a.state,
                        "needs_login": a.needs_login,
                        "login_hint": a.login_hint,
                        "usage": [
                            {
                                "label": w.label,
                                "used_percent": w.used_percent,
                                "resets_at_ms": w.resets_at_ms,
                                "resets_label": w.resets_label,
                                "age_label": w.age_label,
                                "stale": w.stale,
                            }
                            for w in a.usage
                        ],
                    }
                    for a in group.accounts
                ],
            }
            for group in snapshot.groups
        ],
    }
