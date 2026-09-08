"""The command line, which is also the contract native shells speak.

Two jobs in one surface, on purpose. The CLI has to exist anyway -- a Windows
tray app manages a different Claude Code install from the one inside WSL, and
only a CLI running inside WSL can reach that one. Since it must exist, the
native shells consume it rather than embedding a Python runtime or standing up
a local server.

The boundary is therefore observable by hand: whatever the menu bar shows,
``shambles list --json`` prints the same thing, so a rendering bug and a logic
bug can be told apart without a debugger.

Switching goes through :class:`shambles.app.service.ShamblesService`, which
delegates to the shared switcher. The Tk window still calls the core directly
until its migration. Sharing the switcher preserves the ordering that stops a
failed switch destroying the account it switched away from.
"""

import argparse
import json
import sys

from .. import providers as registry
from .. import settings
from ..paths import Paths
from . import snapshot as snapshot_mod
from .launch import LaunchRequest, replace_process
from .service import ShamblesService

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

#: Every setting ``config`` will read or write. One so far, and the list is
#: printed verbatim when somebody names a key that is not in it, so a typo
#: gets told what to type instead of what went wrong.
CONFIG_KEYS = (settings.UPDATE_CHECK,)

#: What ``true`` and ``false`` are allowed to look like: exactly those two
#: words. :func:`shambles.settings.update_check_enabled` counts only a JSON
#: ``true`` as on, so accepting ``yes`` or ``1`` here would write a file that
#: reads back as off -- the CLI would report success for a switch it had not
#: thrown.
CONFIG_BOOLEANS = {"true": True, "false": False}

CONFIG_USAGE = """\
shambles config get update.check   print whether update checks are on
shambles config set update.check true|false
"""

#: Said once, at the moment somebody turns the network on. Naming who is
#: asked, how often and what is sent is the whole difference between an opt-in
#: and a surprise.
UPDATE_CHECK_ON = (
    "Update checks are on. Shambles will ask GitHub for the latest release "
    "tag at most once a day, and sends nothing about you or your accounts."
)

UPDATE_CHECK_OFF = "Update checks are off. Shambles will not contact GitHub."


def _paths(args) -> Paths:
    override = getattr(args, "home", None)
    return Paths.for_home(override) if override else Paths.real()


def _service(args):
    return ShamblesService(paths=_paths(args),
                           providers=registry.all_providers(),
                           platform=sys.platform)


def cmd_tui(args) -> int:
    from .tui.application import run_tui

    service = _service(args)
    encoding = (sys.stdout.encoding or "").lower().replace("-", "")
    provider = run_tui(
        service,
        motion=not getattr(args, "no_motion", False),
        unicode=encoding in ("utf8", "utf"),
    )
    # run_tui returns only after Textual restores the terminal. Keep the
    # process handoff here; the TUI itself returns only a provider ID.
    if provider is not None:
        replace_process(LaunchRequest(provider), providers=service.providers)
    return EXIT_OK


def cmd_gui(args) -> int:
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        from shambles.__main__ import TK_MISSING
        sys.stderr.write(TK_MISSING)
        return EXIT_FAILED

    from ..gui import run
    return run(paths=_paths(args))


def cmd_list(args) -> int:
    snap = _service(args).snapshot()
    payload = snapshot_mod.to_dict(snap)

    if args.json:
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return EXIT_OK

    for group in payload["groups"]:
        surfaces = ", ".join(s["label"] for s in group["surfaces"])
        print(f"{group['display_name']}  ({surfaces})")
        if not group["accounts"]:
            print("    no accounts yet")
        for account in group["accounts"]:
            mark = "*" if account["active"] else " "
            bits = [account["email"] or "unknown"]
            if account["plan"]:
                bits.append(account["plan"])
            if account["needs_login"]:
                bits.append("needs login")
            for window in account["usage"]:
                percent = window["used_percent"]
                bits.append(f"{window['label']} "
                            + (f"{percent}%" if percent is not None else "—"))
            print(f"  {mark} {account['name']:<14} {'  ·  '.join(bits)}")
        print()
    return EXIT_OK


def cmd_switch(args) -> int:
    try:
        result = _service(args).switch(args.provider, args.account)
    except KeyError as exc:
        return _fail(args, "unknown_provider", str(exc).strip("'"))

    if not result.ok:
        return _fail(args, "refused", result.error.message)

    switched = next((
        account
        for group in (result.snapshot.groups if result.snapshot else ())
        if group.provider == args.provider
        for account in group.accounts
        if account.name == args.account
    ), None)
    if args.json:
        json.dump({"version": snapshot_mod.CONTRACT_VERSION, "ok": True,
                   "provider": args.provider, "switched_to": args.account,
                   "needs_login": switched.needs_login if switched else None,
                   "warnings": list(result.warnings)}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"Switched {args.provider} to {args.account}.")
        if switched and switched.needs_login and switched.login_hint:
            print(f"  {switched.login_hint}")
        for warning in result.warnings:
            print(f"  {warning}")
    return EXIT_OK


def cmd_config(args) -> int:
    """``config`` with no action is not a command; say what the two are."""
    sys.stderr.write(CONFIG_USAGE)
    return EXIT_USAGE


def cmd_config_get(args) -> int:
    if args.key not in CONFIG_KEYS:
        return _unknown_key(args.key)
    print("true" if settings.update_check_enabled(_paths(args)) else "false")
    return EXIT_OK


def cmd_config_set(args) -> int:
    """Write one setting, and say what turning it on signed the user up for.

    The value is checked before anything is written, so a refused command
    leaves the file exactly as it found it -- including not creating one.
    """
    if args.key not in CONFIG_KEYS:
        return _unknown_key(args.key)
    if args.value not in CONFIG_BOOLEANS:
        sys.stderr.write(
            f"{args.value!r} is not a value for {args.key}: "
            "write true or false.\n")
        return EXIT_USAGE

    enabled = CONFIG_BOOLEANS[args.value]
    settings.set_update_check(_paths(args), enabled)
    print(UPDATE_CHECK_ON if enabled else UPDATE_CHECK_OFF)
    return EXIT_OK


def _unknown_key(key: str) -> int:
    """Name the settings that do exist, rather than the one that does not."""
    sys.stderr.write(f"Unknown setting {key!r}. Shambles has: "
                     + ", ".join(CONFIG_KEYS) + ".\n")
    return EXIT_USAGE


def _fail(args, code: str, message: str) -> int:
    """Report a failure on the channel the caller asked for.

    A refusal exits non-zero *and* prints its reason, because the exit code
    only says something went wrong while the message says what to do about it.
    """
    if getattr(args, "json", False):
        json.dump({"version": snapshot_mod.CONTRACT_VERSION, "ok": False,
                   "error": {"code": code, "message": message}}, sys.stdout)
        sys.stdout.write("\n")
    else:
        sys.stderr.write(message.rstrip() + "\n")
    return EXIT_FAILED


def build_parser() -> argparse.ArgumentParser:
    # --home points the whole command at a synthetic home. Shared through a
    # parent parser so it is accepted on either side of the subcommand, and
    # default=SUPPRESS because an argument defined on both parent and
    # subparser is written twice -- the subparser's default would otherwise
    # overwrite what the top level captured, so `--home X list` silently lost X
    # while `list --home X` worked.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("--no-motion", action="store_true",
                        default=argparse.SUPPRESS,
                        help="disable nonessential terminal motion")

    parser = argparse.ArgumentParser(
        prog="shambles", parents=[common],
        description="Switch between Claude and Codex accounts.")
    sub = parser.add_subparsers(dest="command")

    terminal = sub.add_parser("tui", parents=[common],
                              help="open the terminal interface")
    terminal.set_defaults(func=cmd_tui)

    graphical = sub.add_parser("gui", parents=[common],
                               help="open the graphical interface")
    graphical.set_defaults(func=cmd_gui)

    listing = sub.add_parser("list", parents=[common],
                             help="show every account and its state")
    listing.add_argument("--json", action="store_true",
                         help="emit the machine-readable contract")
    listing.set_defaults(func=cmd_list)

    switching = sub.add_parser("switch", parents=[common],
                               help="make an account the one every surface uses")
    switching.add_argument("provider", help="claude or codex")
    switching.add_argument("account", help="the profile name to switch to")
    switching.add_argument("--json", action="store_true",
                           help="emit the machine-readable result")
    switching.set_defaults(func=cmd_switch)

    # `config` carries a func of its own so a bare `shambles config` explains
    # its two actions rather than printing the whole program's help; parsing a
    # get/set below replaces it, because a subparser's defaults are applied
    # after its parent's.
    configuring = sub.add_parser("config", parents=[common],
                                 help="read or change a setting")
    configuring.set_defaults(func=cmd_config)
    actions = configuring.add_subparsers(dest="action")

    reading = actions.add_parser("get", parents=[common],
                                 help="print a setting's current value")
    reading.add_argument("key", help="update.check")
    reading.set_defaults(func=cmd_config_get)

    writing = actions.add_parser("set", parents=[common],
                                 help="change a setting")
    writing.add_argument("key", help="update.check")
    writing.add_argument("value", help="true or false")
    writing.set_defaults(func=cmd_config_set)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)
