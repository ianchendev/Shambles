"""Everything the panel needs to render, computed once, in one call.

This is the view model in the MVVM sense, and deliberately a plain function
rather than an object: there is no view state to hold. The panel is rebuilt
each time it opens, which is what makes a data-binding layer unnecessary --
the same discipline the existing Tk window already committed to with "re-read
everything from disk, no cached view state, ever".

Everything the UI displays is decided **here**, in Python, where it is tested.
A shell must not re-derive any of it. If Swift computes "can I switch to this"
from an expiry timestamp, it has just created a second implementation of the
rule that the contract tests guard -- the exact drift this whole layering
exists to prevent.

Serialised through :func:`to_dict`, this becomes the ``shambles list --json``
contract that native shells decode.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .. import providers as provider_registry
from ..providers import ABSENT, NEEDS_LOGIN
from . import usage as usage_mod

#: Bumped when the JSON shape changes incompatibly. A shell that does not
#: recognise the version must say "update Shambles" rather than guess -- the
#: app bundle and the CLI ship separately and can drift.
CONTRACT_VERSION = 1

#: Provisional profile layout, pending the flow redesign. Kept in one place so
#: moving it is a single edit.
LIBRARY_DIRNAME = ".shambles"
CREDENTIAL_NAME = "credential"
ACTIVE_NAME = "active"


@dataclass(frozen=True)
class Surface:
    """One application a switch moves. The UI shows these as pills so that
    "switching Codex also changes ChatGPT.app" needs no explanation."""

    id: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Account:
    name: str
    email: str | None = None
    display_name: str | None = None
    plan: str | None = None
    active: bool = False
    state: str = ABSENT
    needs_login: bool = False
    login_hint: str | None = None
    usage: list = field(default_factory=list)


@dataclass(frozen=True)
class Group:
    """One credential store, with every surface it controls.

    A group is the unit of switching. Terminal and VS Code share one store, so
    they are one group and cannot hold different accounts -- a fact the panel
    conveys by listing both surfaces on the group, not by explaining it.
    """

    provider: str
    display_name: str
    surfaces: list = field(default_factory=list)
    accounts: list = field(default_factory=list)


@dataclass(frozen=True)
class Snapshot:
    version: int
    groups: list = field(default_factory=list)


def library_root(home) -> Path:
    return Path(home) / LIBRARY_DIRNAME


def profile_names(home, provider_id: str) -> list[str]:
    root = library_root(home) / provider_id
    try:
        found = [p.name for p in root.iterdir()
                 if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return []
    return sorted(found, key=str.casefold)


def active_name(home, provider_id: str) -> str | None:
    marker = library_root(home) / provider_id / ACTIVE_NAME
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def build(*, home, platform: str, now_ms: int, env=None,
          providers=None) -> Snapshot:
    """Read every profile of every provider and describe it for display."""
    chosen = providers if providers is not None else \
        provider_registry.all_providers(env=env)

    groups = []
    for provider in chosen:
        groups.append(_group_for(provider, home=home, platform=platform,
                                 now_ms=now_ms))
    return Snapshot(CONTRACT_VERSION, groups)


def _group_for(provider, *, home, platform, now_ms) -> Group:
    surfaces = [Surface(s.get("id", ""), s.get("label", ""), s.get("detail", ""))
                for s in provider.spec.get("surfaces", [])
                if isinstance(s, dict)]

    live = active_name(home, provider.id)
    reader = usage_mod.source_for(provider.id)
    accounts = []

    for name in profile_names(home, provider.id):
        directory = library_root(home) / provider.id / name
        blob = _read_credential(directory)
        is_active = (name == live)

        liveness = provider.liveness(blob, now_ms=now_ms)
        identity = provider.identity(blob, home=home, profile_dir=directory,
                                     active=is_active)
        quota = reader.read(home=home, profile_dir=directory,
                            active=is_active) if reader else None

        accounts.append(Account(
            name=name,
            email=identity.email,
            display_name=identity.display_name,
            plan=identity.plan,
            active=is_active,
            state=liveness.state,
            needs_login=liveness.state in NEEDS_LOGIN,
            login_hint=provider.login_hint()
            if liveness.state in NEEDS_LOGIN else None,
            usage=list(quota.windows) if quota else [],
        ))

    return Group(provider.id, provider.display_name, surfaces, accounts)


def _read_credential(directory: Path) -> bytes | None:
    """The stashed credential for a profile, or ``None`` if never logged in."""
    try:
        return (directory / CREDENTIAL_NAME).read_bytes()
    except OSError:
        return None


def to_dict(snapshot: Snapshot) -> dict:
    """The wire form. Field names here are the cross-language contract."""
    return {
        "version": snapshot.version,
        "groups": [
            {
                "provider": group.provider,
                "display_name": group.display_name,
                "surfaces": [
                    {"id": s.id, "label": s.label, "detail": s.detail}
                    for s in group.surfaces
                ],
                "accounts": [
                    {
                        "name": account.name,
                        "email": account.email,
                        "display_name": account.display_name,
                        "plan": account.plan,
                        "active": account.active,
                        "state": account.state,
                        "needs_login": account.needs_login,
                        "login_hint": account.login_hint,
                        "usage": [
                            {
                                "label": window.label,
                                "used_percent": window.used_percent,
                                "resets_at_ms": window.resets_at_ms,
                                "stale": window.stale,
                            }
                            for window in account.usage
                        ],
                    }
                    for account in group.accounts
                ],
            }
            for group in snapshot.groups
        ],
    }
