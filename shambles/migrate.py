"""Converting the 1.x layout, where each profile held a full ~/.claude.

That design gave every account its own ``projects/`` directory, so switching
accounts also switched your session history and weeks of transcripts appeared
to vanish. Claude Code keys history by project path, not by account, and shares
it across logins; this migration restores that.

The plan, in order, and never destructive:

1. Pick the richest profile as the base for the shared ~/.claude.
2. Merge every other profile's history into it, skipping files already there.
3. Extract each profile's credentials and identity into the slim store.
4. Replace the ~/.claude symlink with the real merged directory.

Nothing is deleted. The old profile directories are left on disk for the user
to remove once satisfied.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import configjson, profiles, state
from .errors import ShamblesError
from .paths import ACCOUNT_NAME, CREDENTIALS_NAME
from .stores import FileStore, StoreUnavailableError

#: Directories inside a profile that hold machine-scoped state and must be
#: merged rather than picked from one profile. ``plugins`` belongs here for the
#: same reason ``projects`` does: a plugin installed while the second account
#: was active would otherwise be stranded in a directory nothing reads.
MERGE_DIRS = ("projects", "file-history", "todos", "shell-snapshots",
              "session-env", "plans", "plugins", "statsig", "sessions")

#: Line-oriented files where both profiles hold real entries, so picking one
#: copy would silently drop the other's. Merged by line, deduplicated.
MERGE_JSONL = ("history.jsonl",)

#: Shambles' own sidecar from the old layout. The identity it held moves into
#: the profile store during migration, after which it is redundant -- and
#: ~/.claude should look exactly like a stock install.
LEGACY_SIDECAR = ".shambles.json"

#: Where a pre-1.0 profile, and so the merged ``~/.claude``, keeps its login.
LEGACY_CREDENTIALS = ".credentials.json"

#: Suffix of a file still being written. Renamed away on success.
TMP_SUFFIX = ".shambles-tmp"

#: The provider every pre-1.0 and v1.0 profile belongs to. There was only one;
#: both migrations file everything they find under it.
V1_PROVIDER = "claude"


class MigrationError(ShamblesError):
    """The migration could not run safely."""


#: A run that stopped before ``~/.claude`` was touched. Everything up to that
#: point is additive and safe to repeat, and :func:`needed` is still true,
#: which is what makes the last sentence a promise the window keeps.
NOT_CONVERTED = (
    "The old layout could not be converted, and ~/.claude is still the link "
    "it was:\n{error}\n\n"
    "Nothing was deleted. Shambles will try again the next time it starts."
)


@dataclass
class Plan:
    base: str | None = None
    others: list = field(default_factory=list)
    merged_files: int = 0
    skipped_files: int = 0
    bytes_to_copy: int = 0
    credentials_found: list = field(default_factory=list)


def needed(paths) -> bool:
    """Whether ``~/.claude`` is the pre-1.0 layout: a link into the old store.

    A symlink alone is not evidence. People link ``~/.claude`` themselves,
    from a dotfile manager or to keep it on another drive, and that link is
    not ours to replace. Only one that points at a profile's place directly
    inside ``~/.claude-profiles`` is the layout this module converts.

    At a profile's *place*, not at a profile that still exists. A link left
    dangling because its profile directory was removed is still the old
    layout, and the logins in the store beside it still have to be brought
    across: answering no hands that store to :func:`migrate_store`, which
    looks for the v1.0 file names, finds none, and declares the job done
    with every login left behind. A hidden name was never a profile.

    Both sides are resolved as far as they go, so a relative link, or a home
    that is itself reached through a link, still compares. With no profile
    left in the store there is nothing to convert, and the answer is no.
    """
    try:
        if not paths.claude_dir.is_symlink():
            return False
        target = Path(os.path.realpath(paths.claude_dir))
        store = Path(os.path.realpath(paths.legacy_profiles_dir))
    except OSError:
        return False
    return (target.parent == store and not target.name.startswith(".")
            and bool(legacy_names(paths)))


def _session_count(profile_dir: Path) -> int:
    projects = profile_dir / "projects"
    if not projects.is_dir():
        return 0
    return sum(1 for _ in projects.rglob("*.jsonl"))


def legacy_names(paths) -> list[str]:
    """Profile directories in the **pre-1.0** store.

    Not :func:`state.profile_names`: that reads the provider-scoped store this
    migration is trying to reach, which is empty at the point this runs. These
    profiles live in ``~/.claude-profiles/<Name>/``, each a full copy of
    ``~/.claude``.
    """
    try:
        entries = sorted(p for p in paths.legacy_profiles_dir.iterdir()
                         if p.is_dir())
    except OSError:
        return []
    return [p.name for p in entries if not p.name.startswith(".")]


def survey(paths) -> Plan:
    """Work out what a migration would do, without touching anything."""
    names = legacy_names(paths)
    if not names:
        raise MigrationError("No profiles found to migrate.")

    ranked = sorted(names,
                    key=lambda n: _session_count(paths.legacy_profiles_dir / n),
                    reverse=True)
    plan = Plan(base=ranked[0], others=ranked[1:])

    base_dir = paths.legacy_profiles_dir / plan.base
    for name in names:
        if (paths.legacy_profiles_dir / name / ".credentials.json").exists():
            plan.credentials_found.append(name)

    for name in plan.others:
        src_root = paths.legacy_profiles_dir / name
        for sub in MERGE_DIRS:
            src = src_root / sub
            if not src.is_dir():
                continue
            for path in src.rglob("*"):
                if not path.is_file():
                    continue
                dest = base_dir / sub / path.relative_to(src)
                if dest.exists():
                    plan.skipped_files += 1
                else:
                    plan.merged_files += 1
                    try:
                        plan.bytes_to_copy += path.stat().st_size
                    except OSError:
                        pass
    return plan


def _merge_tree(src: Path, dest: Path) -> tuple[int, int]:
    """Copy files that are not already at ``dest``. Never overwrites.

    Each file arrives under a temporary name and is renamed into place. A
    copy cut short by a full disk would otherwise leave a truncated file at
    the real name, and "already there" is exactly what the retry skips.
    """
    merged = skipped = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dest / path.relative_to(src)
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + TMP_SUFFIX)
        try:
            shutil.copy2(path, tmp)
            os.replace(tmp, target)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        merged += 1
    return merged, skipped


def _merge_jsonl(src: Path, dest: Path) -> int:
    """Fold ``src``'s lines into ``dest``, keeping order and dropping repeats.

    Prompt history is append-only and each line stands alone, so concatenating
    the two and removing exact duplicates is faithful. Unparseable lines are
    carried across verbatim rather than dropped.

    Read and written as bytes, which is what makes that last sentence true.
    As text, a final line cut inside a multi-byte character (the writer was
    killed mid-append) fails to decode and takes the whole migration with it,
    and ``str.splitlines`` breaks a line at U+2028, which JSON allows inside a
    string, leaving two halves that are no longer JSON. Bytes split only at
    the newline the writer put there.

    Written beside ``dest`` and renamed over it. ``dest`` is the base
    profile's own history, the only copy of it, and writing in place empties
    it first: a full disk at that moment lost every prompt it held.
    """
    if not src.is_file():
        return 0
    existing = dest.read_bytes().splitlines() if dest.is_file() else []
    seen = {line for line in existing if line.strip()}
    added = [line for line in src.read_bytes().splitlines()
             if line.strip() and line not in seen]
    if not added:
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + TMP_SUFFIX)
    try:
        tmp.write_bytes(b"\n".join(existing + added).rstrip(b"\n") + b"\n")
        os.replace(tmp, dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return len(added)


def run(paths, *, now_ms: int) -> Plan:
    """Perform the migration. Additive: nothing is deleted.

    Every login is filed before ``~/.claude`` is touched, and replacing the
    link comes after. Until that happens :func:`needed` stays true, so a run
    cut short by a full disk or a crash is simply run again at the next
    start, and everything before the swap is safe to repeat.

    The user ends up signed in as the account they were signed in as. The
    merged directory is the richest profile's, and it arrives with that
    profile's login inside it, so when the link pointed somewhere else the
    linked login is put in its place straight after the swap.
    """
    if not needed(paths):
        raise MigrationError(
            "~/.claude is not a link into the old profile store; nothing to "
            "migrate.")

    plan = survey(paths)
    base_dir = paths.legacy_profiles_dir / plan.base
    if not base_dir.is_dir():
        raise MigrationError(f"Base profile '{plan.base}' is missing.")

    try:
        active, live_login = _prepare(paths, plan, base_dir, now_ms)
        link_target = os.readlink(paths.claude_dir)
        paths.claude_dir.unlink()
    except (OSError, StoreUnavailableError, ValueError) as exc:
        # ValueError is a file that is not valid text. Not ours to repair,
        # and a traceback at every start is not a way to say so.
        raise MigrationError(NOT_CONVERTED.format(error=exc)) from exc

    # 4. Replace the symlink with the real merged directory. Guarded: if the
    #    rename fails, put the symlink back rather than leaving no ~/.claude
    #    at all. Both operations are metadata-only, so the window is tiny.
    try:
        base_dir.rename(paths.claude_dir)
    except OSError as exc:
        try:
            os.symlink(link_target, paths.claude_dir, target_is_directory=True)
        except OSError as undo:
            raise MigrationError(
                f"Could not move '{plan.base}' into place, and the ~/.claude "
                f"link could not be put back either:\n{undo}\n\n"
                f"Nothing was deleted. ~/.claude was a link to {link_target}, "
                f"and everything it held is still there.") from exc
        raise MigrationError(
            f"Could not move '{plan.base}' into place, so nothing was "
            f"changed and ~/.claude was restored:\n{exc}") from exc

    # 5. Keep the user on the account they were on. The conversion is
    #    complete by now, so nothing below is reported as a failure of it.
    if active and active != plan.base:
        _keep_signed_in(paths, plan.base, live_login)

    # 6. Leave ~/.claude looking like a stock install: the sidecar's contents
    #    were filed in step 3. A file that will not go is left behind.
    try:
        (paths.claude_dir / LEGACY_SIDECAR).unlink(missing_ok=True)
    except OSError:
        pass
    return plan


def _keep_signed_in(paths, base: str, live_login) -> None:
    """Put the linked profile's login where the merged directory's was.

    ``~/.claude`` is now the richest profile's directory, login included,
    while the marker and ``~/.claude.json`` both name the profile the link
    pointed at. Left like that the next switch files the base's token under
    the linked profile's name and its own saved token is gone. The base's
    login is already filed in the store, so replacing it here loses nothing.

    If the login cannot be written, the marker is moved to the base instead:
    whichever way it goes, the marker and the live login name one account.
    """
    live = FileStore(paths.claude_dir / LEGACY_CREDENTIALS, 0o600)
    try:
        if live_login:
            live.write(live_login)
        else:
            live.delete()   # the linked profile was signed out, so stay so
    except (OSError, StoreUnavailableError):
        try:
            state.write_active(paths, V1_PROVIDER, base)
        except OSError:
            pass


def _prepare(paths, plan, base_dir, now_ms):
    """Steps 1 to 3: everything that happens before ``~/.claude`` changes.

    Returns the profile the link points at, if any, and its login as read at
    the last moment.
    """
    # 1. Merge everyone else's machine-scoped state into the base.
    merged = skipped = 0
    for name in plan.others:
        src_root = paths.legacy_profiles_dir / name
        for sub in MERGE_DIRS:
            src = src_root / sub
            if src.is_dir():
                got, missed = _merge_tree(src, base_dir / sub)
                merged += got
                skipped += missed
        for name_jsonl in MERGE_JSONL:
            merged += _merge_jsonl(src_root / name_jsonl, base_dir / name_jsonl)
    plan.merged_files, plan.skipped_files = merged, skipped

    # 2. Stash each profile's identity into the slim store, reading the old
    #    locations before anything is rearranged.
    identities = {}
    for name in legacy_names(paths):
        old_creds = paths.legacy_profiles_dir / name / LEGACY_CREDENTIALS
        old_sidecar = paths.legacy_profiles_dir / name / LEGACY_SIDECAR
        identities[name] = (
            old_creds.read_bytes() if old_creds.exists() else None,
            configjson.read_sidecar(old_sidecar),
        )

    active = None
    target = os.path.realpath(paths.claude_dir)
    for name in legacy_names(paths):
        if os.path.realpath(paths.legacy_profiles_dir / name) == target:
            active = name
            break

    # The active profile's live identity is the one in ~/.claude.json, which is
    # fresher than any sidecar.
    if active:
        live = configjson.extract_account_keys(
            configjson.load(paths.claude_json))
        if live.get("oauthAccount"):
            identities[active] = (identities[active][0], live)

    # 3. Write the slim profile store, provider-scoped. Everything the pre-1.0
    #    layout held was a Claude login -- there was no second provider.
    for name in identities:
        if name != active:
            _file_profile(paths, name, *identities[name], now_ms)

    # The linked profile last, and from a read made now. Its login is the
    # live one: Claude Code refreshes it through the link, including between
    # a run that failed and the retry. So unlike the others it replaces what
    # an earlier run filed -- that copy is the same login, only older, and
    # keeping it would leave the refreshed one neither live nor saved once
    # the link is gone.
    live_login = None
    if active:
        linked = paths.legacy_profiles_dir / active / LEGACY_CREDENTIALS
        live_login = (linked.read_bytes() if linked.exists() else None) or None
        _file_profile(paths, active, live_login, identities[active][1], now_ms,
                      refresh=True)
        state.write_active(paths, V1_PROVIDER, active)
    return active, live_login


def _file_profile(paths, name, creds, account, now_ms, *,
                  refresh: bool = False) -> None:
    """File one pre-1.0 profile's login and identity in the slim store.

    Safe to repeat, because a migration that was cut short is run again from
    the top. A login already in the store wins, the rule :func:`migrate_store`
    documents: on a retry it is the same bytes, and otherwise a newer Shambles
    saved it and has kept it current, which nothing did for the copy in the
    old directory. The write is atomic, so a half-written credential can never
    be the one that wins, and an empty file is not a login and does not win
    either.

    ``refresh`` is for the linked profile, whose old directory holds the live
    login: there the copy being filed is the newer one.

    The identity is only filed beside the login it came with. Next to a login
    that was kept instead, it would put one account's address on another
    account's token. And an identity already there is not replaced by an old
    profile that has none to offer.
    """
    paths.ensure_profile(V1_PROVIDER, name)
    store = FileStore(paths.credentials(V1_PROVIDER, name), 0o600)
    held = store.read() or None
    if creds and (held is None or (refresh and held != creds)):
        # Through save_credential, which keeps what it replaces: what an
        # earlier run filed is the same login, but older, and if Claude Code
        # rotated it in between it may still be the only copy of something.
        profiles.save_credential(paths, _claude(), name, creds)
        held = creds
    if held != (creds or None):
        return

    sidecar = paths.account(V1_PROVIDER, name)
    if (configjson.read_sidecar(sidecar).get("oauthAccount")
            and not account.get("oauthAccount")):
        return
    configjson.write_sidecar(sidecar, account, now_ms)


#: Files a v1.0 profile could hold. Anything else in there was not ours.
V1_PROFILE_FILES = (CREDENTIALS_NAME, ACCOUNT_NAME)

#: What the directories a v1.0 store is assembled in are called, inside
#: ``~/.shambles``, until one is renamed to ``claude``. Hidden, so nothing
#: lists one as a provider or a profile. Each run makes its own with a unique
#: suffix: two windows opening at once would otherwise share one, and the
#: second clearing "the leftover" would empty the copy the first is about to
#: rename into place.
STAGING_PREFIX = f".{V1_PROVIDER}.migrating."


@dataclass
class StorePlan:
    profiles: list = field(default_factory=list)
    active: str | None = None
    backups: int = 0
    source: Path | None = None
    dest: Path | None = None


def store_migration_needed(paths) -> bool:
    """Whether a v1.0 store exists and has not been migrated yet.

    The presence of ``~/.shambles/claude`` is the "already done" signal,
    deliberately rather than the absence of the old store: the migration
    copies, so the old store is still there afterwards and would otherwise
    retrigger forever.

    It is the Claude provider directory and not the library root.
    ``~/.shambles`` is also created by saving a setting, by the update-check
    cache and by a Codex account, and none of those says anything about
    whether the v1.0 profiles, every one a Claude login, were brought across.
    """
    return (paths.legacy_profiles_dir.is_dir()
            and not paths.provider_dir(V1_PROVIDER).exists()
            # While ~/.claude is still a pre-1.0 link, that store is the
            # pre-1.0 one, whose logins are under other file names. Copying
            # it as a v1.0 store files none of them and then reports success.
            and not needed(paths))


def migrate_store(paths) -> StorePlan:
    """Copy ~/.claude-profiles/<Name>/ to ~/.shambles/claude/<Name>/.

    Copies rather than moves. Every profile directory holds a refresh token
    recoverable only through a fresh verification email, so the old store stays
    on disk for the user to remove once they are satisfied -- the same posture
    as the pre-1.0 history merge and as Eject.

    Never overwrites: a file already present in the new store wins, which is
    what makes running this twice a no-op.

    ``~/.shambles/claude`` existing is what :func:`store_migration_needed`
    reads as "done", so it must never exist half-made. When it is not there
    yet the copy is assembled in a hidden staging directory beside it and
    renamed into place as the last step: a run that fails or dies before then
    leaves no provider directory, and the next start begins again. When it is
    already there -- or appears while this is copying -- the copy is made in
    place, as it always was, and a profile that already holds a login is
    left exactly as it is.

    The old config snapshots come across last and as far as they will. They
    are a convenience, and never a reason to hold the logins back.
    """
    plan = StorePlan(source=paths.legacy_profiles_dir,
                     dest=paths.library_dir)
    if not paths.legacy_profiles_dir.is_dir():
        return plan

    staging = None
    try:
        if paths.provider_dir(V1_PROVIDER).exists():
            _copy_store(paths, V1_PROVIDER, plan)
        else:
            paths.ensure_store()
            staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX,
                                            dir=paths.library_dir))
            _copy_store(paths, staging.name, plan)
            try:
                staging.rename(paths.provider_dir(V1_PROVIDER))
            except OSError:
                # Something else made the provider directory while this was
                # copying: another window, or an account saved from the
                # terminal. That directory now reads as "done", so giving up
                # here would leave every profile behind for good. Fill in
                # what it lacks instead, in place, which never overwrites.
                if not paths.provider_dir(V1_PROVIDER).is_dir():
                    raise
                plan.profiles.clear()
                plan.active = None
                _copy_store(paths, V1_PROVIDER, plan)
                shutil.rmtree(staging, ignore_errors=True)
    except OSError as exc:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        # Only promised when it is true: the window asks again exactly when
        # the provider directory is still missing.
        again = (" Shambles will try again the next time it starts."
                 if store_migration_needed(paths) else "")
        raise MigrationError(
            f"Your saved accounts could not be moved to {plan.dest}:\n{exc}"
            f"\n\nNothing was deleted. The old store is still at "
            f"{plan.source}.{again}") from exc

    _copy_backups(paths, plan)
    if staging is not None:
        _clear_staging(paths)
    return plan


def _copy_store(paths, provider_id: str, plan: StorePlan) -> None:
    """Copy the v1.0 profiles, marker and backups, filling in ``plan``.

    ``provider_id`` names the directory inside ``~/.shambles`` the profiles
    go under: the Claude provider itself for a copy in place, or a staging
    directory. Either way the :class:`Paths` helpers build the same layout
    beneath it, owner-only. Never overwrites.
    """
    paths.ensure_provider(provider_id)

    for entry in sorted(paths.legacy_profiles_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        directory = paths.ensure_profile(provider_id, entry.name)
        plan.profiles.append(entry.name)
        # A login already there wins, and it keeps its own address with it:
        # the old account.json describes the old login, and beside a
        # different one it would be one account's name on another's token.
        kept = _differs(entry / CREDENTIALS_NAME, directory / CREDENTIALS_NAME)
        for filename in V1_PROFILE_FILES:
            source = entry / filename
            dest = directory / filename
            if source.is_file() and not dest.exists() and not kept:
                shutil.copy2(source, dest)
                _lock_down(dest)

    # A marker naming a profile that did not come across would surface as
    # MISSING_PROFILE on a brand-new layout, which is a confusing thing to
    # greet someone with after an automatic migration.
    marked = None
    try:
        if paths.legacy_active_marker.is_file():
            marked = (paths.legacy_active_marker.read_text(encoding="utf-8")
                      .strip() or None)
    except ValueError:
        marked = None  # not text: a torn write, and it names nobody
    if marked in plan.profiles:
        plan.active = marked
        if not paths.active_marker(provider_id).exists():
            paths.active_marker(provider_id).write_text(
                marked + "\n", encoding="utf-8")
            _lock_down(paths.active_marker(provider_id))


def _differs(source: Path, dest: Path) -> bool:
    """Whether ``dest`` already holds a credential other than ``source``'s."""
    try:
        held = dest.read_bytes()
    except OSError:
        return False
    try:
        return held != source.read_bytes()
    except OSError:
        return True


def _copy_backups(paths, plan: StorePlan) -> None:
    """Bring the old config snapshots across, as far as they will come.

    After the profiles, and never a reason to fail. They are copies of
    ``~/.claude.json`` kept for convenience; one that cannot be copied used
    to hold every login back with it, at every start, for good.
    """
    try:
        if not paths.legacy_backup_dir.is_dir():
            return
        paths.backup_dir.mkdir(parents=True, exist_ok=True)
        snapshots = sorted(paths.legacy_backup_dir.glob("claude.json.*"))
    except OSError:
        return
    for snapshot in snapshots:
        dest = paths.backup_dir / snapshot.name
        try:
            if not dest.exists():
                shutil.copy2(snapshot, dest)
                plan.backups += 1
        except OSError:
            continue


def _clear_staging(paths) -> None:
    """Remove staging directories left behind by runs that died.

    Called once this run's own copy is in place, and not before. A leftover
    cannot be told from the staging directory of a second window that is
    still copying, and clearing that one first would let it rename a
    directory with accounts missing into place. Afterwards it is harmless:
    a rename cannot replace a directory that holds anything, so with the
    provider directory in place the other run fails instead of committing.
    Best effort, because the migration has already succeeded.
    """
    try:
        leftovers = list(paths.library_dir.glob(STAGING_PREFIX + "*"))
    except OSError:
        return
    for leftover in leftovers:
        shutil.rmtree(leftover, ignore_errors=True)


def _lock_down(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _claude():
    """The provider every pre-1.0 and v1.0 profile belongs to."""
    from .providers import load
    return load(V1_PROVIDER)
