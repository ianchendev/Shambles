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
from dataclasses import dataclass, field
from pathlib import Path

from . import configjson, state
from .errors import ShamblesError

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


class MigrationError(ShamblesError):
    """The migration could not run safely."""


@dataclass
class Plan:
    base: str | None = None
    others: list = field(default_factory=list)
    merged_files: int = 0
    skipped_files: int = 0
    bytes_to_copy: int = 0
    credentials_found: list = field(default_factory=list)


def needed(paths) -> bool:
    return paths.claude_dir.is_symlink()


def _session_count(profile_dir: Path) -> int:
    projects = profile_dir / "projects"
    if not projects.is_dir():
        return 0
    return sum(1 for _ in projects.rglob("*.jsonl"))


def survey(paths) -> Plan:
    """Work out what a migration would do, without touching anything."""
    names = state.profile_names(paths)
    if not names:
        raise MigrationError("No profiles found to migrate.")

    ranked = sorted(names, key=lambda n: _session_count(paths.profile_dir(n)),
                    reverse=True)
    plan = Plan(base=ranked[0], others=ranked[1:])

    base_dir = paths.profile_dir(plan.base)
    for name in names:
        if (paths.profile_dir(name) / ".credentials.json").exists():
            plan.credentials_found.append(name)

    for name in plan.others:
        src_root = paths.profile_dir(name)
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
    """Copy files that are not already at ``dest``. Never overwrites."""
    merged = skipped = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dest / path.relative_to(src)
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        merged += 1
    return merged, skipped


def _merge_jsonl(src: Path, dest: Path) -> int:
    """Fold ``src``'s lines into ``dest``, keeping order and dropping repeats.

    Prompt history is append-only and each line stands alone, so concatenating
    the two and removing exact duplicates is faithful. Unparseable lines are
    carried across verbatim rather than dropped.
    """
    if not src.is_file():
        return 0
    existing = dest.read_text(encoding="utf-8").splitlines() if dest.is_file() else []
    seen = {line for line in existing if line.strip()}
    added = [line for line in src.read_text(encoding="utf-8").splitlines()
             if line.strip() and line not in seen]
    if not added:
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(existing + added).rstrip("\n") + "\n",
                    encoding="utf-8")
    return len(added)


def run(paths, *, now_ms: int) -> Plan:
    """Perform the migration. Additive: nothing is deleted."""
    if not needed(paths):
        raise MigrationError("~/.claude is not a symlink; nothing to migrate.")

    plan = survey(paths)
    base_dir = paths.profile_dir(plan.base)
    if not base_dir.is_dir():
        raise MigrationError(f"Base profile '{plan.base}' is missing.")

    # 1. Merge everyone else's machine-scoped state into the base.
    merged = skipped = 0
    for name in plan.others:
        src_root = paths.profile_dir(name)
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
    for name in state.profile_names(paths):
        old_creds = paths.profile_dir(name) / ".credentials.json"
        old_sidecar = paths.profile_dir(name) / ".shambles.json"
        identities[name] = (
            old_creds.read_bytes() if old_creds.exists() else None,
            configjson.read_sidecar(old_sidecar),
        )

    active = None
    target = os.path.realpath(paths.claude_dir)
    for name in state.profile_names(paths):
        if os.path.realpath(paths.profile_dir(name)) == target:
            active = name
            break

    # The active profile's live identity is the one in ~/.claude.json, which is
    # fresher than any sidecar.
    if active:
        live = configjson.extract_account_keys(
            configjson.load(paths.claude_json))
        if live.get("oauthAccount"):
            identities[active] = (identities[active][0], live)

    # 3. Replace the symlink with the real merged directory. Guarded: if the
    #    rename fails, put the symlink back rather than leaving no ~/.claude
    #    at all. Both operations are metadata-only, so the window is tiny.
    link_target = os.readlink(paths.claude_dir)
    paths.claude_dir.unlink()
    try:
        base_dir.rename(paths.claude_dir)
    except OSError as exc:
        os.symlink(link_target, paths.claude_dir, target_is_directory=True)
        raise MigrationError(
            f"Could not move '{plan.base}' into place, so nothing was "
            f"changed and ~/.claude was restored:\n{exc}") from exc

    # 4. Leave ~/.claude looking like a stock install: the sidecar's contents
    #    are already captured in `identities` above.
    (paths.claude_dir / LEGACY_SIDECAR).unlink(missing_ok=True)

    # 5. Write the slim profile store.
    for name, (creds, account) in identities.items():
        paths.ensure_profile(name)
        if creds is not None:
            paths.credentials(name).write_bytes(creds)
            os.chmod(paths.credentials(name), 0o600)
        configjson.write_sidecar(paths.account(name), account, now_ms)

    if active:
        state.write_active(paths, active)
    return plan
