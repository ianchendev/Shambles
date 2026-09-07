"""Handing the terminal to a vendor CLI, once Textual has actually left it.

The account switcher and a vendor's own CLI cannot both own the terminal at
once. Textual tears down the alternate screen and raw mode inside
``App.run()`` -- called by
:func:`shambles.app.tui.application.run_tui` -- and only returns once that
teardown is complete. Nothing may write to this terminal, let alone replace
this process with a program that assumes a normal one, until that return has
actually happened.

:func:`replace_process` is therefore only ever safe to call after
``run_tui()`` has returned, never from inside a callback still running under
Textual -- the caller proves that by construction, since the return value it
acts on does not exist until ``run()`` produces it.

It also builds no environment of its own. ``execvp`` inherits this process's
environment unchanged, so no credential-derived value -- Claude's Keychain
selector, Codex's config directory override, anything
:func:`shambles.login.environment` computes for *that* module's own child
process -- is ever built or passed here. The vendor CLI takes over the exact
terminal and environment Shambles itself was already running in.
"""

import os
from dataclasses import dataclass

from .. import login


@dataclass(frozen=True)
class LaunchRequest:
    """Which vendor CLI to hand this terminal to.

    Produced from the TUI's own result screen, after ``run_tui()`` has
    already returned control to the entrypoint -- never while Textual is
    still running.
    """

    provider: str


def replace_process(request: LaunchRequest, *, providers,
                    execvp=os.execvp) -> None:
    """Replace this process's image with the requested vendor CLI.

    ``execvp`` does not return on success -- this process becomes the vendor
    CLI, in place, in the same terminal. Call only after ``run_tui()`` has
    returned; that return is what proves the terminal is back in cooked mode
    and safe to hand off.
    """
    try:
        provider = next(p for p in providers if p.id == request.provider)
    except StopIteration:
        known = ", ".join(sorted(p.id for p in providers))
        raise KeyError(
            f"Unknown provider '{request.provider}'. Known: {known}."
        ) from None
    argv = [login.binary(provider)]
    execvp(argv[0], argv)
