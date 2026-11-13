"""How a private file is replaced: one complete payload or the old one, never a mix.

Every credential Shambles writes, and the identity files beside them, go
through :func:`shambles.stores.file.replace_file`. Two processes can write
the same file at once (the window and the terminal UI both re-stash the live
login), so each write needs a temp file of its own: with one shared temp
name, two writers truncate and fill the same file, and whichever renames it
first installs a mixture of both.
"""

import errno
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from shambles import configjson, migrate
from shambles.stores import FileStore
from shambles.stores import file as filemod
from shambles.stores.base import StoreUnavailableError

ROOT = Path(__file__).resolve().parent.parent

posix_modes_only = pytest.mark.skipif(
    os.name == "nt", reason="Windows has no POSIX permission bits")


def temps(directory):
    """Every temp file in ``directory``, by any naming Shambles has used."""
    return sorted(p.name for p in Path(directory).iterdir()
                  if p.name.endswith(filemod.TMP_SUFFIX))


# -- two processes, one file ---------------------------------------------------

WRITER = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    from shambles.stores.file import FileStore

    target, fill, size, go, rounds = sys.argv[1:6]
    payload = fill.encode() * int(size)
    go = Path(go)
    while not go.exists():
        time.sleep(0.001)
    failed = 0
    for _ in range(int(rounds)):
        try:
            FileStore(Path(target)).write(payload)
        except Exception as exc:
            failed += 1
            print(type(exc).__name__, exc, file=sys.stderr)
    print(failed)
""")

READER = textwrap.dedent("""
    import sys, time
    from pathlib import Path

    target, go, stop = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    allowed = {line.encode() for line in sys.argv[4:]}
    while not go.exists():
        time.sleep(0.001)
    reads = bad = 0
    while not stop.exists():
        try:
            data = target.read_bytes()
        except OSError:
            continue  # Windows: the file is being replaced this instant
        reads += 1
        if data[:1] * len(data) != data or data[:1] + str(len(data)).encode() not in allowed:
            bad += 1
        if sys.platform == "win32":
            # Windows will not replace a file that is open. A reader that
            # reopens it the instant it closes holds it nearly all the time,
            # which no real reader does; pause the way a real one would.
            time.sleep(0.002)
    print(reads, bad)
""")


def spawn(script, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.Popen([sys.executable, "-c", script, *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)


def test_two_processes_writing_one_file_never_leave_a_mixture(tmp_path):
    """The race the review lane reproduced, made as likely as it can be.

    Two writers replace the same credentials file with large payloads of
    different lengths, each made of one repeated byte, while a third process
    reads it. Every read and the final file must be exactly one writer's
    payload: same byte throughout, at that writer's length.

    On POSIX no write may fail. Windows refuses to rename over a file that
    another process has open, and Shambles does not wait that out (TECH_SPEC
    section 2.2), so there a write may fail with a message; it must still
    leave one complete payload and no temp file, and most writes succeed.
    """
    target = tmp_path / "credentials.json"
    go, stop = tmp_path / "go", tmp_path / "stop"
    sizes = {"A": 300_000, "B": 200_000}
    FileStore(target).write(b"A" * sizes["A"])

    writers = [spawn(WRITER, target, fill, size, go, 60)
               for fill, size in sizes.items()]
    reader = spawn(READER, target, go, stop,
                   *(f"{fill}{size}" for fill, size in sizes.items()))
    go.touch()
    outcomes = [w.communicate(timeout=120) for w in writers]
    stop.touch()
    read_out, read_err = reader.communicate(timeout=60)

    for (out, err), writer in zip(outcomes, writers):
        assert writer.returncode == 0, err
        failed = int(out.strip())
        if sys.platform == "win32":
            assert failed < 30, f"{failed} of 60 writes failed:\n{err}"
            assert not err or "StoreUnavailableError" in err, err
        else:
            assert failed == 0, f"a write failed:\n{err}"
    reads, bad = map(int, read_out.split())
    assert reads > 0, read_err
    assert bad == 0, f"{bad} of {reads} reads saw a mixture of two writes"

    final = target.read_bytes()
    assert final in (b"A" * sizes["A"], b"B" * sizes["B"])
    assert temps(tmp_path) == [], "a writer left its temp file behind"


# -- what a single write does ----------------------------------------------------


def test_each_write_creates_a_temp_file_of_its_own(tmp_path, monkeypatch):
    """Exclusive creation under a fresh name, with the final mode from the
    start: never an existing file reopened, whatever its mode."""
    opened = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *args, **kwargs):
        if str(path).endswith(filemod.TMP_SUFFIX):
            opened.append((Path(path).name, flags, mode))
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    store = FileStore(tmp_path / "credentials.json", 0o600)
    store.write(b"one")
    store.write(b"two")

    assert len(opened) == 2
    (first, flags, mode), (second, _, _) = opened
    assert first != second
    assert flags & os.O_CREAT and flags & os.O_EXCL
    assert not flags & os.O_TRUNC
    assert mode == 0o600
    assert first.startswith(".credentials.json.")
    assert store.read() == b"two"


@posix_modes_only
def test_the_temp_file_is_private_before_the_first_byte(tmp_path, monkeypatch):
    seen = []
    real_write = os.write

    def spy(fd, data):
        seen.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy)
    previous = os.umask(0o000)
    try:
        FileStore(tmp_path / "credentials.json", 0o600).write(b'{"t": 1}')
    finally:
        os.umask(previous)
    assert seen and set(seen) == {0o600}


def test_a_short_write_is_finished_not_truncated(tmp_path, monkeypatch):
    """``os.write`` may write less than it was given. One call is not a write."""
    real_write = os.write
    monkeypatch.setattr(os, "write",
                        lambda fd, data: real_write(fd, bytes(data[:7])))
    payload = b'{"claudeAiOauth": {"refreshToken": "x" * 40}}'
    FileStore(tmp_path / "credentials.json").write(payload)
    assert (tmp_path / "credentials.json").read_bytes() == payload


def test_the_payload_is_on_disk_before_it_replaces_the_old_one(
        tmp_path, monkeypatch):
    """Renamed after ``fsync``, so a power cut cannot leave an empty file at
    the real name, which is what ext4 can otherwise do."""
    events = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync",
                        lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace",
                        lambda a, b: (events.append("replace"), real_replace(a, b))[1])
    FileStore(tmp_path / "credentials.json").write(b"x")
    assert events.index("fsync") < events.index("replace")


# -- interrupted writes ------------------------------------------------------------


@pytest.mark.parametrize("fail", ["write", "fsync", "replace"])
def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(
        tmp_path, monkeypatch, fail):
    target = tmp_path / "credentials.json"
    FileStore(target).write(b"old login")

    def refuse(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, fail, refuse)
    with pytest.raises(StoreUnavailableError, match="No space left"):
        FileStore(target).write(b"new login")
    monkeypatch.undo()

    assert target.read_bytes() == b"old login"
    assert temps(tmp_path) == []


def test_an_interrupt_mid_write_leaves_no_temp(tmp_path, monkeypatch):
    """Ctrl-C is not an OSError, and a temp holding a login must not outlive it."""
    target = tmp_path / "credentials.json"

    def interrupted(fd, data):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        FileStore(target).write(b"new login")
    monkeypatch.undo()

    assert not target.exists()
    assert temps(tmp_path) == []


def _left_behind(directory, name, *, age):
    """A temp file a killed writer left, ``age`` seconds old."""
    path = Path(directory) / name
    path.write_bytes(b'{"refreshToken": "from a killed write"}')
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def test_a_killed_writers_temp_is_swept_by_the_next_write(tmp_path):
    target = tmp_path / "credentials.json"
    stale = _left_behind(tmp_path, ".credentials.json.0123456789abcdef"
                         + filemod.TMP_SUFFIX, age=filemod.STALE_AFTER + 60)
    legacy = _left_behind(tmp_path, "credentials.json" + filemod.TMP_SUFFIX,
                          age=filemod.STALE_AFTER + 60)

    FileStore(target).write(b"login")

    assert not stale.exists() and not legacy.exists()
    assert target.read_bytes() == b"login"


def test_a_temp_that_may_still_be_in_use_is_left_alone(tmp_path):
    """Another process may be about to rename it. Only an old one is swept."""
    fresh = _left_behind(tmp_path, ".credentials.json.fedcba9876543210"
                         + filemod.TMP_SUFFIX, age=5)
    FileStore(tmp_path / "credentials.json").write(b"login")
    assert fresh.exists()


def test_only_this_files_temps_are_swept(tmp_path):
    other = _left_behind(tmp_path, ".account.json.0123456789abcdef"
                         + filemod.TMP_SUFFIX, age=filemod.STALE_AFTER + 60)
    unrelated = _left_behind(tmp_path, "notes.txt", age=filemod.STALE_AFTER + 60)
    FileStore(tmp_path / "credentials.json").write(b"login")
    assert other.exists() and unrelated.exists()


def test_removing_a_login_removes_its_temps_whatever_their_age(tmp_path):
    """A delete means no copy of that login is left here."""
    target = tmp_path / "credentials.json"
    FileStore(target).write(b"login")
    fresh = _left_behind(tmp_path, ".credentials.json.fedcba9876543210"
                         + filemod.TMP_SUFFIX, age=5)
    FileStore(target).delete()
    assert not target.exists() and not fresh.exists()


def test_a_temp_is_never_read_as_the_login(tmp_path):
    _left_behind(tmp_path, ".credentials.json.0123456789abcdef"
                 + filemod.TMP_SUFFIX, age=5)
    _left_behind(tmp_path, "credentials.json" + filemod.TMP_SUFFIX, age=5)
    assert FileStore(tmp_path / "credentials.json").read() is None


# -- the other writers of the same files ------------------------------------------


def test_the_json_writer_uses_the_same_write(tmp_path, monkeypatch):
    calls = []
    real = filemod.replace_file
    monkeypatch.setattr(filemod, "replace_file",
                        lambda path, payload, **kw: (calls.append(Path(path)),
                                                     real(path, payload, **kw))[1])
    configjson.write_atomic(tmp_path / "account.json", {"a": 1})
    assert calls == [tmp_path / "account.json"]
    assert temps(tmp_path) == []


def test_the_migration_copies_a_saved_login_through_the_same_write(
        tmp_path, monkeypatch):
    """The v1 migration used to copy a login straight to its final name. A
    copy cut short there is "already present" to every later run."""
    calls = []
    real = filemod.replace_file
    monkeypatch.setattr(filemod, "replace_file",
                        lambda path, payload, **kw: (calls.append(Path(path).name),
                                                     real(path, payload, **kw))[1])
    source = tmp_path / "old"
    source.mkdir()
    (source / "credentials.json").write_bytes(b'{"login": "kept"}')
    dest = tmp_path / "new" / "credentials.json"
    dest.parent.mkdir()

    migrate._copy_private(source / "credentials.json", dest)

    assert calls == ["credentials.json"]
    assert dest.read_bytes() == b'{"login": "kept"}'
    if os.name != "nt":
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600
