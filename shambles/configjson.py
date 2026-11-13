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
from .stores import file as filemod

#: Account identity, carried between profiles so the UI names the right person.
ACCOUNT_KEYS = ("oauthAccount",)

BACKUP_RETENTION = 10
#: How a temp file of :func:`write_atomic` ends; see ``stores.file``.
TMP_SUFFIX = filemod.TMP_SUFFIX


def load(path) -> dict:
    """Parse a JSON object, returning ``{}`` for anything unusable.

    Malformed config is never fatal: a profile with a corrupt file should still
    list in the UI, just without an email.
    """
    try:
        with Path(path).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        # ValueError, not only JSONDecodeError: a file cut inside a
        # multi-byte character fails to *decode* before it can fail to parse,
        # and UnicodeDecodeError is the other kind of ValueError.
        return {}
    return data if isinstance(data, dict) else {}


def extract_account_keys(config: dict) -> dict:
    return {key: config[key] for key in ACCOUNT_KEYS if key in config}


def write_atomic(path, config: dict) -> None:
    """Write ``config`` as JSON, owner-only, replacing the file whole.

    Through the same write as every saved login
    (:func:`shambles.stores.file.replace_file`): a temp file of its own,
    private from its first byte, renamed into place. Two windows writing the
    same account file at once each install a complete one.
    """
    payload = (json.dumps(config, indent=2) + "\n").encode("utf-8")
    filemod.replace_file(Path(path), payload, mode=0o600)


CORRUPT_CONFIG_HELP = (
    "{path} could not be read, so Shambles stopped rather than "
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
            CORRUPT_CONFIG_HELP.format(path=path, backups="the backups directory")) from exc

    try:
        with path.open(encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ConfigUnreadableError(
            CORRUPT_CONFIG_HELP.format(path=path, backups="the backups directory")) from exc

    if not isinstance(config, dict):
        raise ConfigUnreadableError(
            CORRUPT_CONFIG_HELP.format(path=path, backups="the backups directory"))
    return config


def read_sidecar(path) -> dict:
    """Return the account keys stashed in a profile's ``.shambles.json``."""
    return extract_account_keys(load(path))


def write_sidecar(path, account: dict, now_ms: int) -> None:
    payload = dict(account)
    payload["stashed_at"] = now_ms
    write_atomic(path, payload)


def backup(path, backup_dir, now_ms: int) -> Path | None:
    """Snapshot the companion config before it is spliced.

    The directory is created ``0700`` and each snapshot ``0600``, like the rest
    of the store. These are copies of ``~/.claude.json``, which carries the
    account's email, organisation and UUIDs -- no token, but not something to
    leave at the umask either. ``shutil.copy2`` preserves the source's mode,
    and Claude Code writes that file ``0600``, but a snapshot's protection
    should not depend on the vendor's choice.
    """
    path, backup_dir = Path(path), Path(backup_dir)
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass  # Windows cannot express this; the file modes still apply
    dest = backup_dir / f"claude.json.{now_ms}"
    shutil.copy2(path, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
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
