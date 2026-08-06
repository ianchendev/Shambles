"""The command line, which is also the contract native shells speak.

Two jobs in one surface, on purpose. The CLI has to exist anyway -- a Windows
tray app manages a different Claude Code install from the one inside WSL, and
only a CLI running inside WSL can reach that one. Since it must exist, the
native shells consume it rather than embedding a Python runtime or standing up
a local server.

The boundary is therefore observable by hand: whatever the menu bar shows,
``shambles list --json`` prints the same thing, so a rendering bug and a logic
bug can be told apart without a debugger.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from . import snapshot as snapshot_mod

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 1


def _platform() -> str:
    return sys.platform


def _now_ms() -> int:
    return int(time.time() * 1000)


def cmd_list(args) -> int:
    override = getattr(args, "home", None)
    home = Path(override).expanduser() if override else Path.home()
    snap = snapshot_mod.build(home=home, platform=_platform(),
                              now_ms=_now_ms())
    payload = snapshot_mod.to_dict(snap)

    if args.json:
        json.dump(payload, sys.stdout, indent=None)
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
                            f"{percent}%" if percent is not None
                            else f"{window['label']} —")
            print(f"  {mark} {account['name']:<14} {'  ·  '.join(bits)}")
        print()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    # --home points the whole command at a synthetic home directory. Shared
    # through a parent parser so it is accepted on either side of the
    # subcommand; the test suite passes it to keep every run off the real
    # ~/.claude, and it is the only way to exercise the CLI safely.
    common = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing, not tidiness. A shared argument defined
    # on both the parent and the subparser is written twice during parsing, and
    # the subparser's default overwrites whatever the top level captured -- so
    # `shambles --home X list` silently lost X while `shambles list --home X`
    # worked. Suppressing the default means the name only appears once it has
    # actually been supplied, from either position.
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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)
