"""Leaving cleanly, so uninstalling never costs anyone a token.

The naive way to remove Shambles is to delete the app and its profile store.
That destroys every stashed refresh token, and each one is only recoverable
through a fresh verification email. Eject exists so that is never the required
move.

Afterwards each provider's config is exactly what a stock install expects:
signed in, with history, plugins and settings untouched. The profile
directories are deliberately **left on disk** -- they hold the logins for the
accounts you were not using, and deleting those is the user's decision.
"""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import state, switcher
from .errors import ShamblesError
from .stores.base import StoreUnavailableError

#: Shambles' own artefacts inside ~/.claude. Only ever the sidecar left by the
#: 1.x layout; everything else there belongs to Claude Code. Kept even though
#: migration already unlinks it -- a user who ejects before ever migrating
#: would otherwise be left with it, and the removal is idempotent.
OWN_FILES_IN_CLAUDE = (".shambles.json",)


class EjectError(ShamblesError):
    """Ejecting could not complete safely."""


@dataclass
class ProviderPlan:
    provider: str
    display_name: str
    #: Profile whose login is left installed.
    active: str | None = None
    #: Profiles left on disk for the user to remove.
    other_profiles: list = field(default_factory=list)
    #: Whether this provider ends up signed in.
    credentials_kept: bool = False


@dataclass
class Plan:
    providers: list = field(default_factory=list)
    #: Where the untouched profile store remains.
    store: Path | None = None
    #: Shambles' own bookkeeping files that were deleted from ~/.claude.
    #: Never a credential -- see OWN_FILES_IN_CLAUDE.
    removed: list = field(default_factory=list)


def survey(paths, providers, *, platform: str = sys.platform) -> Plan:
    """Describe what ejecting would do, without touching anything."""
    plan = Plan(store=paths.library_dir)
    for provider in providers:
        active = state.read_active(paths, provider.id)
        names = state.profile_names(paths, provider.id)
        if active not in names:
            active = None
        plan.providers.append(ProviderPlan(
            provider=provider.id,
            display_name=provider.display_name,
            active=active,
            other_profiles=[n for n in names if n != active],
            credentials_kept=_signed_in(paths, provider, active, platform),
        ))
    return plan


def _signed_in(paths, provider, active, platform) -> bool:
    try:
        if provider.store(home=paths.home, platform=platform).read() is not None:
            return True
    except StoreUnavailableError:
        return False
    return bool(active and paths.credentials(provider.id, active).exists())


def run(paths, providers, *, platform: str = sys.platform,
        sleep=time.sleep) -> Plan:
    """Restore a stock installation for every provider.

    Never deletes a credential. Idempotent: running it on an already-stock
    install is a no-op that still reports cleanly.
    """
    plan = survey(paths, providers, platform=platform)

    for provider, entry in zip(providers, plan.providers):
        store = provider.store(home=paths.home, platform=platform)

        # Make sure the provider is actually signed in. If the live credential
        # is missing but the active profile has a copy, put it back -- ejecting
        # must never leave the user logged out.
        try:
            if store.read() is None and entry.active:
                stashed = paths.credentials(provider.id, entry.active)
                if stashed.exists():
                    store.write(stashed.read_bytes())
            entry.credentials_kept = store.read() is not None
        except StoreUnavailableError:
            raise
        except OSError as exc:
            raise EjectError(
                f"Could not restore the {provider.display_name} login:\n{exc}"
            ) from exc

        # Remove Shambles' own bookkeeping. Nothing here belongs to the vendor
        # and nothing here is a credential.
        switcher.forget_active_marker(paths, provider)

    for name in OWN_FILES_IN_CLAUDE:
        target = paths.claude_dir / name
        if target.exists():
            target.unlink()
            plan.removed.append(str(target))

    return plan


def summary(plan: Plan) -> str:
    """User-facing description of what just happened."""
    lines = []
    for entry in plan.providers:
        if entry.credentials_kept:
            who = f" as '{entry.active}'" if entry.active else ""
            lines.append(f"{entry.display_name} is a stock install, still "
                         f"signed in{who}. History, plugins and settings are "
                         f"untouched.")
        elif entry.other_profiles or entry.active:
            lines.append(f"{entry.display_name} has no credentials, so it will "
                         f"ask you to sign in. Nothing was deleted to cause that.")

    parked = sorted({name for entry in plan.providers
                     for name in entry.other_profiles})
    if parked:
        lines.append(
            f"\nLogins for {', '.join(parked)} are still in {plan.store}. They "
            "are kept because each one is only recoverable through a new "
            "verification email. Delete that folder yourself once you are sure.")
    elif plan.store:
        lines.append(f"\n{plan.store} can now be deleted.")

    return "\n".join(lines) if lines else "Nothing to eject."
