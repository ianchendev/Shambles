"""Switching accounts: the one thing this tool does.

The order below is not arbitrary. Each step is placed by a failure it prevents.

**Everything that can refuse happens before anything moves.** A missing target
or an unparseable companion file aborts while the machine is still in a state
the user recognises. Splicing onto a config that failed to parse would replace
every project, MCP server and machine ID in it with two keys.

**The outgoing login is captured before the incoming one is installed**, so
switching away can never strand an account. This is also where token rotation
is handled: Codex replaces its refresh token on every use, so whatever is live
right now may be newer than what the profile last stored, and stashing at this
moment is what keeps the snapshot valid.

**The credential is written before the identity.** Both orders leave a window
if the process dies between them, but they are not equally bad. Credential
first means you are signed in as the new account while the panel still shows
the old name -- visibly wrong, harmless. Identity first means the panel shows
the new account while requests still bill the old one, and the user spends
someone else's quota believing otherwise.

**Nothing here writes to a vendor path except during the switch itself.**
:func:`sync_active` runs whenever the panel opens and writes only inside the
profile library, so keeping snapshots fresh never races the session that may be
running.
"""

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ShamblesError
from . import snapshot as snapshot_mod

BACKUP_DIRNAME = ".backups"
BACKUP_RETENTION = 10


class SwitchRefused(ShamblesError):
    """A precondition failed. Nothing was moved."""


class SwitchFailed(ShamblesError):
    """A step failed partway. The message says what state the machine is in."""


@dataclass(frozen=True)
class SwitchResult:
    provider: str
    switched_to: str
    #: True when the incoming profile has no credential, so the vendor will ask
    #: for a login. Not an error -- it is how a newly added account starts.
    needs_login: bool = False
    #: Advisory notes worth surfacing but not worth failing over.
    warnings: list = field(default_factory=list)


def now_ms() -> int:
    return int(time.time() * 1000)


# -- keeping the active profile's snapshot current ---------------------------


def sync_active(provider, *, home, platform: str) -> bool:
    """Copy the live credential into the active profile if it has changed.

    Codex mints a replacement refresh token on every use and invalidates the
    old one, so a snapshot taken at the last switch goes stale the moment the
    user runs Codex again. Restoring that snapshot later would present an
    already-dead token and quietly cost them a login.

    Cheap enough to run on every panel open: a read and a comparison, with a
    write only when the bytes differ. Writes land inside the profile library
    and never on a vendor path, so this cannot race a running session.

    Returns whether anything was written.
    """
    name = snapshot_mod.active_name(home, provider.id)
    if not name:
        return False
    directory = snapshot_mod.library_root(home) / provider.id / name
    if not directory.is_dir():
        return False

    try:
        live = provider.store(home=home, platform=platform).read()
    except ShamblesError:
        return False
    if live is None:
        return False

    target = directory / snapshot_mod.CREDENTIAL_NAME
    try:
        if target.exists() and target.read_bytes() == live:
            return False
    except OSError:
        pass

    _write_secret(target, live)
    _stash_companion(provider, home=home, directory=directory)
    return True


# -- the switch --------------------------------------------------------------


def switch(provider, target_name: str, *, home, platform: str) -> SwitchResult:
    """Make ``target_name`` the account every surface in this group uses."""
    library = snapshot_mod.library_root(home) / provider.id
    destination = library / target_name

    # 1. Refuse while nothing has moved.
    if not destination.is_dir():
        raise SwitchRefused(
            f"There is no {provider.display_name} account called "
            f"'{target_name}'.")

    companion = provider.spec.get("companion")
    if companion:
        _verify_companion_readable(provider, home=home)

    store = provider.store(home=home, platform=platform)
    current = snapshot_mod.active_name(home, provider.id)
    warnings = []

    # 2. Keep a copy of the companion before touching it.
    if companion:
        _backup(_companion_path(provider, home=home), library / BACKUP_DIRNAME)

    # 3. Capture the outgoing login, including any rotation since it was
    #    stashed. Skipped when the marker names a profile that is gone.
    if current and (library / current).is_dir():
        try:
            sync_active(provider, home=home, platform=platform)
        except ShamblesError as exc:
            warnings.append(f"Could not update the saved copy of "
                            f"'{current}': {exc}")

    # 4. Install the incoming credential.
    incoming = destination / snapshot_mod.CREDENTIAL_NAME
    try:
        if incoming.is_file():
            store.write(incoming.read_bytes())
            needs_login = False
        else:
            # A profile added but never signed into. Clearing rather than
            # leaving the previous credential in place is what makes the vendor
            # prompt instead of silently continuing as the old account.
            store.delete()
            needs_login = True
    except (ShamblesError, OSError) as exc:
        raise SwitchFailed(
            f"Could not install the login for '{target_name}':\n{exc}\n\n"
            f"Nothing else was changed; you are still on "
            f"'{current or 'the previous account'}'.") from exc

    # 5. Splice the identity. After the credential, deliberately: see module
    #    docstring.
    if companion:
        try:
            stored = _read_companion(destination)
            provider.companion_write(stored, home=home)
        except Exception as exc:
            raise SwitchFailed(
                f"The login was switched to '{target_name}', but its identity "
                f"could not be written:\n{exc}\n\n"
                f"You are signed in as '{target_name}'. Switch again to "
                f"repair the display.") from exc

    # 6. Record it.
    _write_active(library, target_name)
    return SwitchResult(provider.id, target_name, needs_login, warnings)


# -- pieces ------------------------------------------------------------------


def _verify_companion_readable(provider, *, home) -> None:
    """Refuse the switch if the file we would splice cannot be parsed.

    ``{}`` is a legitimate answer for a config that does not exist yet, but it
    is the wrong answer for one that exists and failed to parse -- splicing
    onto that and writing it back would replace the whole file with two keys.
    Claude Code rewrites it on its own schedule, so a read landing mid-write is
    the ordinary cause.
    """
    path = _companion_path(provider, home=home)
    if path is None or not path.exists():
        return
    try:
        if path.stat().st_size == 0:
            return
        import json
        with path.open(encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SwitchRefused(
            f"{path.name} could not be read, so nothing was changed.\n\n"
            "That file holds every project, MCP server and machine ID. Close "
            "any running session and try again.") from exc
    if not isinstance(parsed, dict):
        raise SwitchRefused(
            f"{path.name} is not in the expected format, so nothing was "
            "changed.")


def _companion_path(provider, *, home) -> Path | None:
    companion = provider.spec.get("companion")
    if not companion:
        return None
    from ..providers import spec as specmod
    return specmod.expand(companion["path"], home=home)


def _stash_companion(provider, *, home, directory: Path) -> None:
    if not provider.spec.get("companion"):
        return
    data = provider.companion_read(home=home)
    import json
    _write_atomic(directory / "account.json",
                  json.dumps(data, indent=2).encode("utf-8") + b"\n")


def _read_companion(directory: Path) -> dict:
    import json
    try:
        parsed = json.loads((directory / "account.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_secret(path: Path, payload: bytes) -> None:
    _write_atomic(path, payload, mode=0o600)


def _write_atomic(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".shambles-tmp")
    tmp.write_bytes(payload)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _write_active(library: Path, name: str) -> None:
    library.mkdir(parents=True, exist_ok=True)
    _write_atomic(library / snapshot_mod.ACTIVE_NAME,
                  name.encode("utf-8") + b"\n", mode=0o644)


def _backup(path, directory: Path) -> Path | None:
    if path is None or not Path(path).exists():
        return None
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{Path(path).name}.{now_ms()}"
    shutil.copy2(path, destination)
    _prune(directory)
    return destination


def _prune(directory: Path, keep: int = BACKUP_RETENTION) -> None:
    snaps = sorted((p for p in directory.iterdir() if p.is_file()),
                   key=lambda p: p.name, reverse=True)
    for stale in snaps[keep:]:
        stale.unlink(missing_ok=True)
