"""The operations Shambles performs on the user's Claude Code configuration."""

import os
import shutil
import time
from pathlib import Path

from . import configjson, links, profiles, retry
from .errors import (AlreadyManagedError, ForeignLinkError, ProfileNotFoundError,
                     ShamblesError)

IDE_DIRNAME = "ide"
LOCK_GLOB = "*.lock"

FOREIGN_LINK_MESSAGE = (
    "~/.claude is a symlink to {target}, which is outside ~/.claude-profiles/.\n\n"
    "Shambles will not touch a setup it did not create. Remove or re-point that "
    "link by hand first."
)


def now_ms() -> int:
    return int(time.time() * 1000)


def switch(paths, target_name: str, *, now_ms_fn=now_ms, sleep=time.sleep):
    """Make ``target_name`` the active profile.

    Stashes the outgoing account's identity, backs up ~/.claude.json, swaps the
    link atomically, splices the incoming identity in, and carries the VS Code
    lock files across. Returns the resulting :class:`~shambles.links.LinkState`.
    """
    state = links.inspect(paths)
    if state.kind == links.FOREIGN:
        raise ForeignLinkError(FOREIGN_LINK_MESSAGE.format(target=state.target))

    target_dir = paths.profile_dir(target_name)
    if not target_dir.is_dir():
        raise ProfileNotFoundError(
            f"Profile '{target_name}' no longer exists on disk."
        )

    if state.kind == links.MANAGED and state.profile == target_name:
        return state  # already there; touch nothing

    previous = state.profile if state.kind in (links.MANAGED, links.DANGLING) else None
    stamp = now_ms_fn()

    if previous and paths.profile_dir(previous).is_dir():
        outgoing = configjson.extract_account_keys(configjson.load(paths.claude_json))
        configjson.write_sidecar(paths.sidecar(previous), outgoing, stamp)

    configjson.backup(paths.claude_json, paths.backup_dir, stamp)

    links.point_to(paths, target_dir, sleep=sleep)

    incoming = configjson.read_sidecar(paths.sidecar(target_name))
    configjson.apply_account_keys(paths.claude_json, incoming)

    if previous:
        carry_ide_locks(paths.profile_dir(previous), target_dir)

    return links.inspect(paths)


def carry_ide_locks(source_dir, target_dir) -> None:
    """Copy the VS Code extension's IPC lock files into the incoming profile.

    These record a live extension host (pid, workspace, IPC token) rather than
    anything account-specific, but they live inside the swapped directory. Left
    behind, the CLI loses sight of the running extension.

    Deliberately non-fatal: a lost lock file costs a window reload, not a
    broken switch.
    """
    source = Path(source_dir) / IDE_DIRNAME
    if not source.is_dir():
        return
    destination = Path(target_dir) / IDE_DIRNAME
    try:
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        for lock in source.glob(LOCK_GLOB):
            shutil.copy2(lock, destination / lock.name)
    except OSError:
        pass


NOTHING_TO_SAVE = (
    "There is no ~/.claude directory to save.\n\n"
    "Use 'Add Empty Account' to create a profile and log in fresh."
)


def crosses_filesystem(paths) -> bool:
    """True if ~/.claude sits on a different device from its future parent.

    ``shutil.move`` silently degrades from a rename to copytree+rmtree across
    devices -- slow, and non-atomic on a directory holding live credentials.
    """
    try:
        return os.stat(paths.claude_dir).st_dev != os.stat(paths.home).st_dev
    except OSError:
        return False


def save_current_account(paths, name, *, now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Move the real ~/.claude into a profile and leave a symlink behind.

    The only operation that relocates live data. If the symlink cannot be
    created afterwards, the move is undone before the error propagates --
    without that, a Windows privilege error would leave the user with no
    ~/.claude at all.
    """
    state = links.inspect(paths)
    if state.kind == links.FOREIGN:
        raise ForeignLinkError(FOREIGN_LINK_MESSAGE.format(target=state.target))
    if state.kind in (links.MANAGED, links.DANGLING):
        raise AlreadyManagedError(
            "~/.claude is already managed by Shambles — nothing to save."
        )
    if state.kind != links.UNMANAGED:
        raise ShamblesError(NOTHING_TO_SAVE)

    clean = profiles.validate_profile_name(name, profiles.list_profile_names(paths))
    paths.profiles_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = paths.profile_dir(clean)

    shutil.move(str(paths.claude_dir), str(destination))
    try:
        target = str(destination.absolute())
        retry.with_retry(
            lambda: os.symlink(target, str(paths.claude_dir), target_is_directory=True),
            "create the ~/.claude symlink",
            sleep=sleep,
        )
    except BaseException:
        shutil.move(str(destination), str(paths.claude_dir))
        raise

    outgoing = configjson.extract_account_keys(configjson.load(paths.claude_json))
    configjson.write_sidecar(paths.sidecar(clean), outgoing, now_ms_fn())
    return clean


SETTINGS_NAME = "settings.json"

SAVE_FIRST = (
    "~/.claude is still a real directory.\n\n"
    "Use 'Save Current Account' first, so your existing login is preserved as "
    "a profile."
)


def add_empty_account(paths, name, *, seed_settings: bool = True,
                      now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Create a fresh profile and switch to it, ready for ``/login``.

    Only ``settings.json`` is ever seeded -- never ``.credentials.json``. The
    new profile is deliberately unauthenticated; plugins come back on their own
    via ``enabledPlugins`` in the copied settings.
    """
    state = links.inspect(paths)
    if state.kind == links.FOREIGN:
        raise ForeignLinkError(FOREIGN_LINK_MESSAGE.format(target=state.target))
    if state.kind == links.UNMANAGED:
        raise ShamblesError(SAVE_FIRST)

    clean = profiles.validate_profile_name(name, profiles.list_profile_names(paths))
    paths.profiles_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = paths.profile_dir(clean)
    destination.mkdir(mode=0o700)

    if seed_settings and state.kind == links.MANAGED:
        source = paths.profile_dir(state.profile) / SETTINGS_NAME
        if source.is_file():
            shutil.copy2(source, destination / SETTINGS_NAME)

    switch(paths, clean, now_ms_fn=now_ms_fn, sleep=sleep)
    return clean


def rename_profile(paths, old_name: str, new_name: str, *, sleep=time.sleep) -> str:
    """Rename a profile, re-pointing ~/.claude if it was the active one.

    The symlink stores an absolute target, so renaming the directory underneath
    it leaves it dangling until it is re-pointed.
    """
    source = paths.profile_dir(old_name)
    if not source.is_dir():
        raise ProfileNotFoundError(f"Profile '{old_name}' no longer exists on disk.")

    others = [n for n in profiles.list_profile_names(paths) if n != old_name]
    clean = profiles.validate_profile_name(new_name, others)
    if clean == old_name:
        return old_name

    state = links.inspect(paths)
    was_active = state.kind == links.MANAGED and state.profile == old_name

    destination = paths.profile_dir(clean)
    retry.with_retry(
        lambda: os.rename(source, destination),
        f"rename '{old_name}'",
        sleep=sleep,
    )
    if was_active:
        links.point_to(paths, destination, sleep=sleep)
    return clean


def remove_dangling_link(paths) -> None:
    """Delete a ~/.claude symlink whose profile has been removed."""
    state = links.inspect(paths)
    if state.kind != links.DANGLING:
        raise ShamblesError("~/.claude is not a broken link.")
    paths.claude_dir.unlink()
