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


# -- the window bundle -------------------------------------------------------

#: The window ships as its own download, because Qt is three times the size
#: of everything else put together and unpacking it would slow every command.
#: So the small ``shambles`` binary has no Qt, and ``shambles gui`` hands over
#: to the bundle when one is installed.
WINDOW_NAME = "shambles-window"
#: Says exactly where the bundle is, for an install in an unusual place.
WINDOW_ENV = "SHAMBLES_WINDOW"
#: Set on the bundle's process. A bundle whose Qt will not load must report
#: that, not go looking for a bundle and find itself.
IN_WINDOW_ENV = "SHAMBLES_IN_WINDOW"


def window_bundle(*, env=None, platform=None, executable=None, home=None):
    """The installed window's executable, or None.

    Looked for, in order: where ``SHAMBLES_WINDOW`` says, beside the running
    ``shambles`` binary, then where the install scripts put it.
    """
    import sys
    from pathlib import Path

    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if env.get(IN_WINDOW_ENV):
        return None
    name = WINDOW_NAME + (".exe" if platform == "win32" else "")

    candidates = []
    if env.get(WINDOW_ENV):
        candidates.append(Path(env[WINDOW_ENV]))
    here = Path(executable or sys.executable).resolve().parent
    candidates.append(here / WINDOW_NAME / name)
    if platform == "win32":
        if env.get("LOCALAPPDATA"):
            candidates.append(Path(env["LOCALAPPDATA"]) / "Shambles"
                              / "window" / name)
    else:
        base = Path(home) if home else Path.home()
        candidates.append(base / ".local" / "share" / "shambles" / "window"
                          / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def replace_with_window(bundle, args, *, execv=os.execv, env=None) -> None:
    """Become the window. Does not return on success.

    ``args`` are the options to pass on (``--home``, ``--no-motion``). The
    bundle opens the window by default, so no subcommand is sent.
    """
    env = os.environ if env is None else env
    env[IN_WINDOW_ENV] = "1"
    execv(str(bundle), [str(bundle), *args])
