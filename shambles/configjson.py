"""Reading and patching ``~/.claude.json``.

That file is never a symlink -- Claude Code rewrites it, and a write-and-rename
would replace a link with a real file. Instead Shambles splices only the
account-scoped keys in and out, leaving projects, MCP servers, prompt history
and machine IDs untouched and in their original order.
"""

import json
import os
import shutil
from pathlib import Path

from .errors import ConfigUnreadableError

#: Account identity, carried between profiles so the UI names the right person.
ACCOUNT_KEYS = ("oauthAccount",)

#: Account-scoped *caches*: cleared on every switch and never restored.
#:
#: ``cachedUsageUtilization`` is keyed by accountUuid, so leaving the outgoing
#: account's copy behind would show the wrong person's figures. Restoring the
#: incoming account's stashed copy is no better: the blob carries its own
#: ``fetchedAtMs`` and the numbers are only true as of that moment, so a profile
#: switched away from yesterday comes back reporting yesterday's usage. Neither
#: the extension nor the user can tell a stale cache from a current one.
#:
#: Deleting satisfies the original requirement -- no foreign figures -- and
#: leaves Claude Code to refetch from the server, which is the only source that
#: knows the real number.
STALE_ON_SWITCH = ("cachedUsageUtilization",)

BACKUP_RETENTION = 10
TMP_SUFFIX = ".shambles-tmp"


def load(path) -> dict:
    """Parse a JSON object, returning ``{}`` for anything unusable.

    Malformed config is never fatal: a profile with a corrupt file should still
    list in the UI, just without an email.
    """
    try:
        with Path(path).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def extract_account_keys(config: dict) -> dict:
    return {key: config[key] for key in ACCOUNT_KEYS if key in config}


def write_atomic(path, config: dict) -> None:
    """Write via a same-directory temp file, then rename over the original."""
    path = Path(path)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


CORRUPT_CONFIG_HELP = (
    "~/.claude.json could not be read, so Shambles stopped rather than "
    "overwrite it.\n\n"
    "That file holds every project, MCP server and machine ID. Claude Code "
    "rewrites it on its own schedule, so this usually means a read landed "
    "mid-write.\n\n"
    "Close any running Claude Code session and try again. A recent copy is "
    "in {backups}."
)


def load_for_write(path) -> dict:
    """Parse a config that is about to be written back.

    ``load`` answers ``{}`` for anything unusable, which is right when merely
    displaying a profile. Splicing onto that ``{}`` and writing it back would
    replace the whole config with two keys, so the write path has to tell
    "absent" apart from "unreadable" and refuse the latter.
    """
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
    except OSError as exc:
        raise ConfigUnreadableError(
            CORRUPT_CONFIG_HELP.format(backups="the backups directory")) from exc

    try:
        with path.open(encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigUnreadableError(
            CORRUPT_CONFIG_HELP.format(backups="the backups directory")) from exc

    if not isinstance(config, dict):
        raise ConfigUnreadableError(
            CORRUPT_CONFIG_HELP.format(backups="the backups directory"))
    return config


def apply_account_keys(path, account: dict) -> None:
    """Splice ``account`` into the config at ``path``.

    Identity keys missing from ``account`` are deleted rather than left holding
    the previous profile's -- Claude Code re-fetches them on next start. Cache
    keys are always deleted; see :data:`STALE_ON_SWITCH`.
    """
    config = load_for_write(path)
    for key in ACCOUNT_KEYS:
        if key in account:
            config[key] = account[key]
        else:
            config.pop(key, None)
    for key in STALE_ON_SWITCH:
        config.pop(key, None)
    write_atomic(path, config)


def read_sidecar(path) -> dict:
    """Return the account keys stashed in a profile's ``.shambles.json``."""
    return extract_account_keys(load(path))


def write_sidecar(path, account: dict, now_ms: int) -> None:
    payload = dict(account)
    payload["stashed_at"] = now_ms
    write_atomic(path, payload)


def backup(path, backup_dir, now_ms: int) -> Path | None:
    path, backup_dir = Path(path), Path(backup_dir)
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"claude.json.{now_ms}"
    shutil.copy2(path, dest)
    prune(backup_dir)
    return dest


def prune(backup_dir, keep: int = BACKUP_RETENTION) -> None:
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return
    snaps = sorted(backup_dir.glob("claude.json.*"), key=_stamp, reverse=True)
    for stale in snaps[keep:]:
        stale.unlink(missing_ok=True)


def _stamp(path: Path) -> int:
    """Sort key from a trailing millisecond timestamp; 0 if unparseable."""
    try:
        return int(path.name.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0
