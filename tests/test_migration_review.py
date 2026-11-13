"""What an independent review of the migration fixes found.

Each test here failed against the first version of this branch. Some are
defects that version introduced (a login refreshed between a failed attempt
and the retry was dropped; a dangling link sent a pre-1.0 store down the
v1.0 path; one unreadable backup held every account back). Others were
already on main and only became visible once the fixtures stopped giving
every profile identical bytes: above all that the conversion left the
richest profile's login live under the linked profile's name, so the first
switch afterwards overwrote a saved token.
"""

import errno
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from helpers import (NOW, account, credentials, make_claude_json,
                     make_legacy_profile, make_live_claude_login, make_profile,
                     make_v1_profile, write_json)
from shambles import providers as _providers
from shambles import configjson, migrate, state, switcher
from shambles.errors import ShamblesError

CLAUDE = _providers.load("claude")


def _old_login(paths, name):
    return paths.legacy_profiles_dir / name / ".credentials.json"


def _fails(error):
    def fail(*args, **kwargs):
        raise error
    return fail


def _legacy(paths, linked, richest):
    """Two pre-1.0 profiles with distinct tokens; ~/.claude -> ``linked``."""
    other = "Beta" if richest == "Alpha" else "Alpha"
    make_legacy_profile(paths, richest, email=f"{richest.lower()}@example.test",
                        sessions=3)
    make_legacy_profile(paths, other, email=f"{other.lower()}@example.test",
                        sessions=1)
    for name in ("Alpha", "Beta"):
        write_json(_old_login(paths, name),
                   credentials(access_token=f"old-{name}"))
    os.symlink(paths.legacy_profiles_dir / linked, paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email=f"{linked.lower()}@example.test")


def test_login_refreshed_after_a_failed_swap_is_the_one_filed(paths,
                                                                 monkeypatch):
    """Swap (rename) fails -> link restored -> vendor refreshes the linked
    login through the link -> retry. The store must hold the refreshed one."""
    _legacy(paths, linked="Alpha", richest="Beta")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", _fails(OSError("device busy")))
        with pytest.raises(migrate.MigrationError):
            migrate.run(paths, now_ms=NOW)
    assert migrate.needed(paths)

    # Claude Code, still running through the link, rotates the token.
    write_json(paths.claude_dir / ".credentials.json",
               credentials(access_token="refreshed"))
    refreshed = _old_login(paths, "Alpha").read_bytes()
    assert b"refreshed" in refreshed

    migrate.run(paths, now_ms=NOW)

    live = (paths.claude_dir / ".credentials.json").read_bytes()
    stored = paths.credentials("claude", "Alpha").read_bytes()
    assert refreshed in (live, stored), (
        "the only current token for Alpha is neither live nor in the store")


def test_same_with_marker_write_failing(paths, monkeypatch):
    _legacy(paths, linked="Alpha", richest="Beta")
    with monkeypatch.context() as patch:
        patch.setattr(state, "write_active", _fails(OSError("disk full")))
        with pytest.raises(migrate.MigrationError):
            migrate.run(paths, now_ms=NOW)
    write_json(paths.claude_dir / ".credentials.json",
               credentials(access_token="refreshed"))
    refreshed = _old_login(paths, "Alpha").read_bytes()
    migrate.run(paths, now_ms=NOW)
    live = (paths.claude_dir / ".credentials.json").read_bytes()
    stored = paths.credentials("claude", "Alpha").read_bytes()
    assert refreshed in (live, stored)

def test_live_login_after_migration_is_the_linked_accounts(paths):
    """The user was signed in as the linked profile. After the migration the
    live credential must still be that account's."""
    _legacy(paths, linked="Alpha", richest="Beta")
    alpha = _old_login(paths, "Alpha").read_bytes()

    migrate.run(paths, now_ms=NOW)

    assert state.read_active(paths, "claude") == "Alpha"
    live = CLAUDE.store(home=paths.home, platform="linux").read()
    assert live == alpha, "marker says Alpha but the live token is Beta's"


def test_first_switch_after_migration_keeps_every_token(paths):
    _legacy(paths, linked="Alpha", richest="Beta")
    alpha = _old_login(paths, "Alpha").read_bytes()
    beta = _old_login(paths, "Beta").read_bytes()

    migrate.run(paths, now_ms=NOW)
    assert state.inspect(paths, CLAUDE, platform="linux").kind == state.MANAGED
    switcher.switch(paths, CLAUDE, "Beta", platform="linux",
                    now_ms_fn=lambda: NOW, sleep=lambda _: None)

    assert paths.credentials("claude", "Beta").read_bytes() == beta
    assert paths.credentials("claude", "Alpha").read_bytes() == alpha, (
        "Alpha's saved token was overwritten with Beta's")

def test_dangling_link_does_not_strand_pre_1_0_logins(paths):
    """~/.claude links to a profile directory that is gone. origin/main
    converted this; here needed() is False, and the v1.0 store migration
    then files empty profiles and marks the job done."""
    make_legacy_profile(paths, "Alpha", email="alpha@example.test", sessions=2)
    make_legacy_profile(paths, "Beta", email="beta@example.test", sessions=1)
    for name in ("Alpha", "Beta"):
        write_json(_old_login(paths, name),
                   credentials(access_token=f"old-{name}"))
    logins = {n: _old_login(paths, n).read_bytes() for n in ("Alpha", "Beta")}
    os.symlink(paths.legacy_profiles_dir / "Gone", paths.claude_dir,
               target_is_directory=True)

    # What the window does at startup, in order.
    if migrate.needed(paths):
        migrate.run(paths, now_ms=NOW)
    if migrate.store_migration_needed(paths):
        migrate.migrate_store(paths)

    for name, login in logins.items():
        cred = paths.credentials("claude", name)
        assert cred.exists() and cred.read_bytes() == login, (
            f"{name} is listed with no login; needed()="
            f"{migrate.needed(paths)}, store_migration_needed()="
            f"{migrate.store_migration_needed(paths)}")

def test_sidecar_that_is_not_text_does_not_crash_startup(paths):
    """The window only catches ShamblesError. Anything else out of run() is
    a traceback at every start, because needed() stays true."""
    _legacy(paths, linked="Alpha", richest="Alpha")
    (paths.legacy_profiles_dir / "Beta" / ".shambles.json").write_bytes(
        b'{"oauthAccount": {"emailAddress": "caf\xc3')   # cut mid-character

    try:
        migrate.run(paths, now_ms=NOW)
    except ShamblesError:
        pass


def test_claude_json_that_is_not_text_does_not_crash_startup(paths):
    _legacy(paths, linked="Alpha", richest="Alpha")
    paths.claude_json.write_bytes(b'{"oauthAccount": {"emailAddress": "caf\xc3')
    try:
        migrate.run(paths, now_ms=NOW)
    except ShamblesError:
        pass

def test_disk_full_while_merging_prompt_history_loses_nothing(paths,
                                                                 monkeypatch):
    """open('wb') truncates before the first byte is written. ENOSPC there
    left the base's own prompt history empty, and the base is the only copy
    of those lines. The merge now writes a temp file and renames it, so a
    full disk while writing leaves the old history where it was."""
    _legacy(paths, linked="Alpha", richest="Alpha")
    base = paths.legacy_profiles_dir / "Alpha" / "history.jsonl"
    base.write_bytes(b'{"display":"alpha one"}\n{"display":"alpha two"}\n')
    (paths.legacy_profiles_dir / "Beta" / "history.jsonl").write_bytes(
        b'{"display":"beta one"}\n')

    from shambles.stores import file as filemod
    real = filemod.replace_file

    def disk_full_on_history(path, payload, **kwargs):
        if Path(path).name == "history.jsonl":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(filemod, "replace_file", disk_full_on_history)
        with pytest.raises((migrate.MigrationError, OSError)):
            migrate.run(paths, now_ms=NOW)

    assert b"alpha one" in base.read_bytes(), "the base's history was emptied"


def test_disk_full_mid_copy_does_not_leave_a_truncated_session(
        paths, monkeypatch):
    """A copy that fails partway must not leave a file at the real name: the
    retry would see it 'already there' and never complete it."""
    _legacy(paths, linked="Alpha", richest="Alpha")
    session = (paths.legacy_profiles_dir / "Beta" / "projects" /
               "-some-project" / "Beta-0.jsonl")
    session.write_bytes(b'{"type":"user"}\n' * 100)
    from shambles.stores import file as filemod
    real_write = os.write
    calls = {"n": 0}

    def write(fd, data):
        # The first write of the session's bytes runs out of space halfway.
        if b'{"type":"user"}' in bytes(data) and calls["n"] == 0:
            calls["n"] += 1
            real_write(fd, bytes(data)[:10])
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", write)
        with pytest.raises((migrate.MigrationError, OSError)):
            migrate.run(paths, now_ms=NOW)

    migrate.run(paths, now_ms=NOW)   # the promised retry, disk space freed

    merged = paths.claude_dir / "projects" / "-some-project" / "Beta-0.jsonl"
    assert merged.read_bytes() == session.read_bytes()

def test_unreadable_backup_does_not_keep_accounts_out_forever(paths):
    """A snapshot that cannot be copied is not a reason to never bring the
    logins across. origin/main copied the profiles first."""
    make_v1_profile(paths, "Alpha", email="alpha@example.test", active=True)
    make_v1_profile(paths, "Beta", email="beta@example.test")
    paths.legacy_backup_dir.mkdir(parents=True)
    (paths.legacy_backup_dir / "claude.json.1").mkdir()   # copy2 cannot copy

    for _start in range(3):
        if migrate.store_migration_needed(paths):
            try:
                migrate.migrate_store(paths)
            except (ShamblesError, OSError):
                pass

    assert state.profile_names(paths, "claude") == ["Alpha", "Beta"], (
        "three starts later the window still lists no accounts")

def test_an_account_added_mid_migration_does_not_strand_the_old_store(
        paths, monkeypatch):
    """Another Shambles process (the terminal UI adds an account) creates
    ~/.shambles/claude while this window is still copying into staging."""
    make_v1_profile(paths, "Alpha", email="alpha@example.test", active=True)
    make_v1_profile(paths, "Beta", email="beta@example.test")
    real = migrate._copy_private
    calls = {"n": 0}

    def copy(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            make_profile(paths, "claude", "New", email="new@example.test")
        return real(src, dst)

    monkeypatch.setattr(migrate, "_copy_private", copy)
    try:
        migrate.migrate_store(paths)
    except ShamblesError:
        pass

    assert not migrate.store_migration_needed(paths)   # so: never retried
    assert sorted(state.profile_names(paths, "claude")) == [
        "Alpha", "Beta", "New"], "Alpha and Beta will never come across"

def test_copy_in_place_does_not_put_an_old_address_on_a_kept_login(paths):
    """run() files an identity only beside the login it came with.
    _copy_store's in-place path does not."""
    make_v1_profile(paths, "Alpha", email="old@example.test")
    paths.ensure_profile("claude", "Alpha")
    write_json(paths.credentials("claude", "Alpha"),
               credentials(access_token="kept-current"))   # no account.json

    migrate.migrate_store(paths)

    assert configjson.read_sidecar(paths.account("claude", "Alpha")).get(
        "oauthAccount", {}).get("emailAddress") != "old@example.test"

def _dialogs(monkeypatch):
    from shambles import gui
    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda *a, **k: shown.append(("info", str(a[1]))))
    monkeypatch.setattr(gui.messagebox, "showerror",
                        lambda *a, **k: shown.append(("error", str(a[1]))))
    return shown


def test_window_does_not_announce_accounts_it_did_not_bring(
        paths, make_app, monkeypatch):
    """The real startup path, with a link the new predicate rejects."""
    shown = _dialogs(monkeypatch)
    make_legacy_profile(paths, "Alpha", email="alpha@example.test", sessions=2)
    make_legacy_profile(paths, "Beta", email="beta@example.test", sessions=1)
    os.symlink(paths.legacy_profiles_dir / "Gone", paths.claude_dir,
               target_is_directory=True)

    app = make_app(paths)
    app.update()

    announced = [text for kind, text in shown if "account(s) are now filed" in text]
    filed = [n for n in ("Alpha", "Beta")
             if paths.credentials("claude", n).exists()]
    assert not announced or filed == ["Alpha", "Beta"], (
        f"dialog said: {announced[0].splitlines()[2]!r}; logins filed: {filed}")


def test_a_failed_conversion_is_not_followed_by_a_claim_of_success(
        paths, make_app, monkeypatch):
    """Disk full while merging history. run() reports it, and the window
    then runs the v1.0 store migration over the pre-1.0 store."""
    shown = _dialogs(monkeypatch)
    _legacy(paths, linked="Alpha", richest="Alpha")
    monkeypatch.setattr(migrate, "_merge_tree",
                        _fails(OSError(errno.ENOSPC, "No space left on device")))

    app = make_app(paths)
    app.update()

    kinds = [kind for kind, _ in shown]
    assert "error" in kinds
    announced = [text for kind, text in shown if "account(s) are now filed" in text]
    filed = [n for n in ("Alpha", "Beta")
             if paths.credentials("claude", n).exists()]
    assert not announced or filed == ["Alpha", "Beta"], (
        f"after the error dialog the window said {announced[0].splitlines()[2]!r} "
        f"with logins filed for {filed}")

def test_an_empty_file_in_the_new_store_is_not_a_login_that_wins(paths):
    """'A login already in the store wins' is decided by the file existing.
    FileStore.write renames without fsync, so a power cut can leave the
    name with no bytes; the retry then keeps nothing over a real login."""
    _legacy(paths, linked="Alpha", richest="Alpha")
    beta = _old_login(paths, "Beta").read_bytes()
    paths.ensure_profile("claude", "Beta")
    paths.credentials("claude", "Beta").write_bytes(b"")

    migrate.run(paths, now_ms=NOW)

    assert paths.credentials("claude", "Beta").read_bytes() == beta
