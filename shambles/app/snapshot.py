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
class Group:
    provider: str
    display_name: str
    surfaces: list = field(default_factory=list)
    accounts: list = field(default_factory=list)


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

    accounts = []
    for profile in found:
        lapsed = profiles_mod.needs_login(profile)
        accounts.append(Account(
            name=profile.name,
            email=profile.email,
            plan=profile.plan,
            active=profile.active,
            state=profile.liveness.state,
            needs_login=lapsed,
            # Carried only when it is actionable. A hint attached to a healthy
            # account is noise a shell would then have to decide to hide.
            login_hint=provider.login_hint() if lapsed else None,
            usage=_windows(profile, now_ms=now_ms),
        ))
    return Group(provider.id, provider.display_name, surfaces, accounts)


def _windows(profile, *, now_ms: int) -> list:
    """Quota bars, flattened to the wire shape.

    Stashed figures are marked rather than hidden: a parked profile's last
    known usage is worth showing, but not worth reading as current.
    """
    usage = getattr(profile, "usage", None)
    if not usage:
        return []
    stale = usage.is_stale(now_ms)
    return [Window(bar.label, bar.percent, stale=stale) for bar in usage.bars]


def to_dict(snapshot: Snapshot) -> dict:
    """The wire form. These field names are the cross-language contract."""
    return {
        "version": snapshot.version,
        "groups": [
            {
                "provider": group.provider,
                "display_name": group.display_name,
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
