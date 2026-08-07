"""Leaving cleanly, so uninstalling never costs anyone a token.

The naive way to remove Shambles is to delete the app and
``~/.claude-profiles/``. That destroys every stashed refresh token, and each
one is only recoverable through a fresh verification email. Eject exists so
that is never the required move.

Afterwards ``~/.claude`` is exactly what a stock Claude Code install expects:
signed in, with its history, plugins and settings untouched. The profile
directories are deliberately **left on disk** -- they hold the logins for the
accounts you were not using, and deleting those is the user's decision, not
this tool's.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import state, switcher
from .errors import ShamblesError

#: Shambles' own artefacts inside ~/.claude. Only ever the sidecar left by the
#: 1.x layout; everything else there belongs to Claude Code.
OWN_FILES_IN_CLAUDE = (".shambles.json",)


class EjectError(ShamblesError):
    """Ejecting could not complete safely."""


LEGACY_FIRST = (
    "~/.claude is still a symlink from an older version of Shambles.\n\n"
    "Ejecting now would leave a dangling link and no usable config. Open "
    "Shambles once to merge your history back into a real directory, then "
    "eject."
)


@dataclass
class Plan:
    #: Profile whose login is left installed in ~/.claude.
    active: str | None = None
    #: Profiles left on disk for the user to remove.
    other_profiles: list = field(default_factory=list)
    #: Whether ~/.claude ends up with a credentials file.
    credentials_kept: bool = False
    #: Bookkeeping removed.
    removed: list = field(default_factory=list)
    #: Where the untouched profile store remains.
    store: Path | None = None


def survey(paths) -> Plan:
    """Describe what ejecting would do, without touching anything."""
    active = state.read_active(paths)
    names = state.profile_names(paths)
    return Plan(
        active=active if active in names else None,
        other_profiles=[n for n in names if n != active],
        credentials_kept=(paths.live_credentials.exists()
                          or (active in names
                              and paths.credentials(active).exists())),
        store=paths.profiles_dir,
    )


def run(paths, *, sleep=time.sleep) -> Plan:
    """Restore a stock installation. Never deletes a credentials file.

    Idempotent: running it on an already-stock install is a no-op that still
    reports cleanly.
    """
    if paths.claude_dir.is_symlink():
        raise EjectError(LEGACY_FIRST)

    plan = survey(paths)

    # 1. Make sure ~/.claude is actually signed in. If the live credentials
    #    are missing but the active profile has a copy, put it back -- ejecting
    #    must never leave the user logged out.
    if not paths.live_credentials.exists() and plan.active:
        stored = paths.credentials(plan.active)
        if stored.exists():
            try:
                paths.claude_dir.mkdir(parents=True, exist_ok=True)
                # Same helper the switch path uses: one place owns the
                # chmod-600-then-atomic-replace sequence, and the retry that
                # makes it survive a momentarily locked file.
                switcher.copy_secret(stored, paths.live_credentials, sleep=sleep)
            except ShamblesError:
                raise
            except OSError as exc:
                raise EjectError(
                    f"Could not restore the login into ~/.claude:\n{exc}"
                ) from exc
    plan.credentials_kept = paths.live_credentials.exists()

    # 2. Remove Shambles' own bookkeeping. Nothing here belongs to Claude Code
    #    and nothing here is a credential.
    for name in OWN_FILES_IN_CLAUDE:
        target = paths.claude_dir / name
        if target.exists():
            target.unlink()
            plan.removed.append(str(target))
    if paths.active_marker.exists():
        paths.active_marker.unlink()
        plan.removed.append(str(paths.active_marker))

    return plan


def summary(plan: Plan) -> str:
    """User-facing description of what just happened."""
    lines = []
    if plan.credentials_kept:
        who = f" for '{plan.active}'" if plan.active else ""
        lines.append(f"~/.claude is a stock Claude Code install{who}, still "
                     "signed in. Session history, plugins and settings are "
                     "untouched.")
    else:
        lines.append("~/.claude has no credentials file, so Claude Code will "
                     "ask you to sign in. Nothing was deleted to cause that.")

    if plan.other_profiles:
        others = ", ".join(plan.other_profiles)
        lines.append(
            f"\nLogins for {others} are still in {plan.store}. They are kept "
            "because each one is only recoverable through a new verification "
            "email. Delete that folder yourself once you are sure you want to.")
    elif plan.store:
        lines.append(f"\n{plan.store} can now be deleted.")

    return "\n".join(lines)
