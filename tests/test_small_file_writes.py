"""The small files Shambles writes beside the logins are replaced whole too.

#43 put every login write through ``stores.file.replace_file``: a private temp
file of its own, written in full and synced, then renamed over the old one.
The files below hold no login, but each was rewritten in place or copied at
the umask, so a reader (another window) could see it torn, a crash could
leave it half written, and a snapshot could exist world-readable for a moment.
"""

import os
import stat

import pytest

from conftest import posix_modes_only
from helpers import make_claude_json, make_profile
from shambles import configjson, state


# -- the active-account marker -------------------------------------------------

def test_the_marker_is_replaced_whole_never_rewritten_in_place(paths):
    """Rewritten in place, the marker is empty between the truncate and the
    write, and a reader then sees nobody marked. Replaced whole, a reader
    sees the old name or the new one."""
    make_profile(paths, "claude", "Work", active=True)
    before = paths.active_marker("claude").stat().st_ino

    state.write_active(paths, "claude", "Other")

    assert state.read_active(paths, "claude") == "Other"
    assert paths.active_marker("claude").stat().st_ino != before


@posix_modes_only
def test_the_marker_is_owner_only(paths):
    old = os.umask(0o022)
    try:
        state.write_active(paths, "claude", "Work")
    finally:
        os.umask(old)

    mode = stat.S_IMODE(paths.active_marker("claude").stat().st_mode)
    assert mode == 0o600


def test_forgetting_the_marker_still_removes_it(paths):
    state.write_active(paths, "claude", "Work")
    state.write_active(paths, "claude", None)
    assert not paths.active_marker("claude").exists()


# -- the snapshot of ~/.claude.json taken before each splice -------------------

@posix_modes_only
def test_a_snapshot_is_private_from_its_first_byte(paths, monkeypatch):
    """copy2 gives the snapshot the source's mode and a chmod afterwards
    tightens it. Where that chmod does nothing (Windows) or fails, a loose
    source left a loose snapshot of the account's details."""
    make_claude_json(paths, email="w@example.test")
    os.chmod(paths.claude_json, 0o644)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)

    dest = configjson.backup(paths.claude_json, paths.backup_dir, 1)

    assert stat.S_IMODE(dest.stat().st_mode) == 0o600


def test_a_snapshot_is_the_whole_file(paths):
    make_claude_json(paths, email="w@example.test")

    dest = configjson.backup(paths.claude_json, paths.backup_dir, 1)

    assert dest.read_bytes() == paths.claude_json.read_bytes()


# -- the history merge of the pre-1.0 migration -------------------------------

def test_merged_session_files_keep_their_times(paths):
    """Moving onto a fresh temp file must not stamp merged sessions with
    the time of the migration: they are listed by when they were written."""
    from shambles import migrate

    src = paths.home / "src" / "projects"
    dest = paths.home / "dest" / "projects"
    (src / "p").mkdir(parents=True)
    session = src / "p" / "a.jsonl"
    session.write_text('{"type":"user"}\n', encoding="utf-8")
    long_ago = 1_700_000_000
    os.utime(session, (long_ago, long_ago))

    migrate._merge_tree(src, dest)

    copied = dest / "p" / "a.jsonl"
    assert copied.read_bytes() == session.read_bytes()
    assert int(copied.stat().st_mtime) == long_ago


def test_merges_use_a_temp_file_of_their_own(paths, monkeypatch):
    """A fixed temp name is shared by two windows migrating at once, and two
    writers filling one file can leave a mixture. Every write goes through
    replace_file, which makes its own."""
    from shambles import migrate
    from shambles.stores import file as filemod

    written = []
    real = filemod.replace_file
    monkeypatch.setattr(filemod, "replace_file",
                        lambda path, payload, **k: (written.append(path),
                                                    real(path, payload, **k)))
    src = paths.home / "src"
    (src / "projects" / "p").mkdir(parents=True)
    (src / "projects" / "p" / "a.jsonl").write_text("x\n", encoding="utf-8")
    (src / "history.jsonl").write_text('{"display":"two"}\n', encoding="utf-8")
    dest = paths.home / "dest"
    dest.mkdir()
    (dest / "history.jsonl").write_text('{"display":"one"}\n', encoding="utf-8")

    migrate._merge_tree(src / "projects", dest / "projects")
    migrate._merge_jsonl(src / "history.jsonl", dest / "history.jsonl")

    assert dest / "projects" / "p" / "a.jsonl" in written
    assert dest / "history.jsonl" in written
