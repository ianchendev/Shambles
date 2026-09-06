"""The command line, which is also the contract native shells speak.

Two jobs in one surface, on purpose. The CLI has to exist anyway -- a Windows
tray app manages a different Claude Code install from the one inside WSL, and
only a CLI running inside WSL can reach that one. Since it must exist, the
native shells consume it rather than embedding a Python runtime or standing up
a local server.

The boundary is therefore observable by hand: whatever the menu bar shows,
``shambles list --json`` prints the same thing, so a rendering bug and a logic
bug can be told apart without a debugger.

Switching goes through :class:`shambles.app.service.ShamblesService`, the same
boundary the window uses. A second implementation of the switch would be a
second chance to get the ordering wrong, and the ordering is what stops a
failed switch destroying the account it switched away from.
"""

import argparse
import json
import sys

from .. import providers as registry
from ..paths import Paths
from . import snapshot as snapshot_mod
from .service import ShamblesService

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _paths(args) -> Paths:
    override = getattr(args, "home", None)
    return Paths.for_home(override) if override else Paths.real()


def _service(args):
    return ShamblesService(paths=_paths(args),
                           providers=registry.all_providers(),
                           platform=sys.platform)


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

    switched = next(
        account
        for group in result.snapshot.groups
        if group.provider == args.provider
        for account in group.accounts
        if account.name == args.account
    )
    if args.json:
        json.dump({"version": snapshot_mod.CONTRACT_VERSION, "ok": True,
                   "provider": args.provider, "switched_to": args.account,
                   "needs_login": switched.needs_login,
                   "warnings": list(result.warnings)}, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(f"Switched {args.provider} to {args.account}.")
        if switched.needs_login and switched.login_hint:
            print(f"  {switched.login_hint}")
    return EXIT_OK


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

    parser = argparse.ArgumentParser(
        prog="shambles", parents=[common],
        description="Switch between Claude and Codex accounts.")
    sub = parser.add_subparsers(dest="command")

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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)
