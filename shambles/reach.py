"""What a switch did not reach, so a frontend can say so (M1).

The third most common complaint about account switchers is "I switched but
nothing changed". A switch replaces the stored login; it cannot change a
program that already loaded one, or one told to sign in some other way. This
module finds the usual causes after a switch and puts each into one sentence
that says what to do. ``shambles doctor`` reports the same things.

Every claim is one the vendor's own code shows:

- **Codex.** ``AuthManager`` loads the stored login once; external changes
  are "NOT observed until ``reload()`` is called explicitly", which the
  app-server does only after a login it performed itself, and its 401
  recovery reloads only when the account on disk is the one already running
  (openai/codex, ``codex-rs/login/src/auth/manager.rs``). So a Codex process
  started before the switch stays on its account until restarted.
- **Claude Code.** Its auth-source order puts ``ANTHROPIC_AUTH_TOKEN`` and
  ``CLAUDE_CODE_OAUTH_TOKEN`` ahead of the saved login, and it says itself
  that ``ANTHROPIC_API_KEY`` "takes precedence over your claude.ai login"
  (read from 2.1.300's strings). The full list is
  :data:`shambles.diagnose.AUTH_OVERRIDES`, sourced in docs/token-storage.md.
- **A relocated config directory** is how both vendors decide where their
  login lives: the ``config_dir`` block of each provider spec.

Only looks. Nothing is stopped, restarted, unset or edited, and a variable's
value is never read into a message: only its name.
"""

import os
import re
from pathlib import Path

#: Shell start-up files a terminal may run, relative to home.
SHELL_FILES = (
    ".bashrc", ".bash_profile", ".bash_login", ".profile",
    ".zshenv", ".zprofile", ".zshrc", ".zlogin",
    ".config/fish/config.fish", ".cshrc", ".tcshrc",
)

#: Each provider's variables that put its login somewhere a switch does not
#: reach, beyond its config directory. Codex's are left out on purpose: its
#: API-key variable only applies to some entry points, and saying it always
#: does would be a claim its code does not make.
AUTH_VARIABLES = {
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
               "CLAUDE_CODE_OAUTH_TOKEN"),
}


def shell_settings(home, names) -> list:
    """``(variable, "~/file")`` for each start-up file that sets one of
    ``names``. Assignments only (``export X=``, ``X=``, fish's ``set -x X``,
    csh's ``setenv X``); comments do not count. Values are never kept."""
    if not names:
        return []
    alternatives = "|".join(re.escape(n) for n in names)
    pattern = re.compile(
        r"^\s*(?:export\s+|declare\s+-x\s+|typeset\s+-x\s+)?"
        rf"({alternatives})=|"
        r"^\s*set\s+(?:-[a-zA-Z]+\s+)*"
        rf"({alternatives})\b|"
        rf"^\s*setenv\s+({alternatives})\b",
        re.MULTILINE)
    found = []
    for relative in SHELL_FILES:
        path = Path(home) / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen = set()
        for match in pattern.finditer(text):
            name = next(g for g in match.groups() if g)
            if name not in seen:
                seen.add(name)
                found.append((name, f"~/{relative}"))
    return found


def after_switch(provider, target, *, home, env=None, running=None) -> list:
    """Sentences for what a switch to ``target`` did not reach.

    ``running`` is :func:`shambles.login.running_programs` for the
    provider's program, or None when that could not be told.
    """
    env = os.environ if env is None else env
    said = []
    name = provider.display_name

    if provider.id == "codex" and running:
        servers = [argv for argv in running if "app-server" in argv[1:]]
        sessions = len(running) - len(servers)
        if servers:
            said.append(
                "Codex's background service (codex app-server) is still "
                "running with the account it started with. Restart the app "
                f"that runs it, VS Code for one, to use {target}.")
        if sessions:
            said.append(
                f"{sessions} Codex session" + ("s" if sessions > 1 else "")
                + " already open stay" + ("" if sessions > 1 else "s")
                + " on the account they started with until you restart "
                + ("them." if sessions > 1 else "it."))

    tokens = AUTH_VARIABLES.get(provider.id, ())
    in_env = [v for v in tokens if env.get(v)]
    for variable in in_env:
        said.append(
            f"{variable} is set here, and {name} uses it ahead of any saved "
            "login, so a terminal started from here stays on that token. "
            f"Unset it to use {target}.")

    folder = (provider.spec.get("config_dir") or {}).get("env")
    for variable, where in shell_settings(home, [*tokens,
                                                 *([folder] if folder else [])]):
        if variable in in_env:
            continue
        if variable == folder:
            said.append(
                f"{where} sets {variable}, so a terminal that runs it keeps a "
                f"separate {name} login there, which this switch does not "
                "change.")
        else:
            said.append(
                f"{where} sets {variable}, so a terminal that runs it signs "
                f"{name} in with that instead of the switched account.")
    return said
