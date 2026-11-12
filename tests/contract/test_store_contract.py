"""One suite every credential store must pass, whatever platform it targets.

This is the generalisation of ``test_credentials_survive_a_round_trip_unmodified``.
That test is the load-bearing one in this project -- if a credential does not
come back byte-identical, the tool stops solving the problem it exists for --
and it should hold for the Keychain and the Windows credential manager exactly
as it holds for a file.

Parametrized rather than duplicated, so a fourth store gets the whole suite for
free and cannot quietly skip the awkward cases.
"""

import json
import os
import stat as os_stat

import pytest

from conftest import posix_modes_only
from shambles.stores import (CredentialStore, CredmanStore, FallbackStore,
                             FileStore, KeychainStore)
from shambles.stores.base import StoreLockedError, StoreUnavailableError
from shambles.stores.credman import join_chunks, parse_meta, split_payload
from tests.fakes import FakeCredman, FakeSecurity


def _file(tmp_path):
    return FileStore(tmp_path / "creds.json")


def _keychain(tmp_path):
    return KeychainStore(service="Test-credentials", account="tester",
                         run=FakeSecurity())


def _credman(tmp_path):
    return CredmanStore(service="Test-credentials", account="tester",
                        chunk_size=64, backend=FakeCredman())


def _keychain_over_file(tmp_path):
    return FallbackStore(_keychain(tmp_path), _file(tmp_path))


def _credman_over_file(tmp_path):
    return FallbackStore(_credman(tmp_path), _file(tmp_path))


STORES = {"file": _file, "keychain": _keychain, "credman": _credman,
          "keychain over file": _keychain_over_file,
          "credman over file": _credman_over_file}

#: Payloads chosen for the ways they break naive implementations: a trailing
#: newline and non-ASCII text both push ``security`` into hex output, and a
#: payload wider than the chunk size forces Windows reassembly.
PAYLOADS = {
    "plain json": b'{"a":1}',
    "trailing newline": b'{"a":1}\n',
    "embedded newlines": b'{\n  "a": 1\n}\n',
    "unicode": '{"name":"刘诺迪 ✓"}'.encode(),
    "empty object": b"{}",
    "large": json.dumps({"claudeAiOauth": {"accessToken": "x" * 500}}).encode(),
    # A login carrying several MCP server tokens. Past the 4 KB that
    # ``security -i`` reads from standard input and past one Credential
    # Manager entry, so it takes the other branch in both stores.
    "very large": json.dumps({"mcpOAuth": {f"server-{n}": {"accessToken": "y" * 700}
                                           for n in range(12)}}).encode(),
    "large unicode": json.dumps({"name": "刘诺迪 ✓" * 400},
                                ensure_ascii=False).encode(),
}


@pytest.fixture(params=sorted(STORES))
def store(request, tmp_path):
    return STORES[request.param](tmp_path)


def test_every_store_satisfies_the_protocol(store):
    assert isinstance(store, CredentialStore)


def test_reading_before_anything_is_written_is_not_an_error(store):
    assert store.read() is None


@pytest.mark.parametrize("payload", PAYLOADS.values(), ids=list(PAYLOADS))
def test_a_credential_survives_a_round_trip_unmodified(store, payload):
    store.write(payload)
    assert store.read() == payload


def test_writing_twice_replaces_rather_than_appends(store):
    store.write(b'{"first":true}')
    store.write(b'{"second":true}')
    assert store.read() == b'{"second":true}'


def test_delete_removes_the_credential(store):
    store.write(b'{"a":1}')
    store.delete()
    assert store.read() is None


def test_deleting_what_is_not_there_is_not_an_error(store):
    store.delete()
    assert store.read() is None


def test_describe_is_a_non_empty_line(store):
    assert store.describe().strip()


# -- store-specific properties ------------------------------------------------


@posix_modes_only
def test_file_store_writes_owner_only_permissions(tmp_path):
    store = FileStore(tmp_path / "creds.json", mode=0o600)
    store.write(b'{"a":1}')
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_file_store_leaves_no_temp_file_behind(tmp_path):
    store = FileStore(tmp_path / "creds.json")
    store.write(b'{"a":1}')
    assert [p.name for p in tmp_path.iterdir()] == ["creds.json"]


def test_keychain_writes_hex_and_updates_in_place(tmp_path):
    fake = FakeSecurity()
    store = KeychainStore(service="S", account="A", run=fake)
    store.write(b'{"a":1}')
    add = next(c for c in fake.stdin_commands + fake.calls
               if c[1] == "add-generic-password")
    assert "-U" in add, "must update in place, not add a duplicate item"
    assert add[add.index("-X") + 1] == b'{"a":1}'.hex()


def test_keychain_survives_the_hex_fallback_that_w_falls_back_to(tmp_path):
    """The specific failure this whole design guards against.

    A payload with a trailing newline comes back from ``security -w`` as a hex
    dump, not as text. A reader that only stripped the newline would hand a
    string of hex digits to the JSON parser.
    """
    fake = FakeSecurity()
    store = KeychainStore(service="S", account="A", run=fake)
    payload = b'{"a":1}\n'
    store.write(payload)
    raw = fake([  # what the real tool would print
        "/usr/bin/security", "find-generic-password", "-a", "A", "-s", "S", "-w",
    ], capture_output=True).stdout
    assert raw != payload + b"\n", "fixture must actually exercise hex output"
    assert store.read() == payload


def test_keychain_keeps_a_small_credential_out_of_the_process_table():
    """``security`` takes the data as an argument, where ``ps`` shows it to
    every user on the machine. Its interactive mode reads the same command
    from standard input instead, which is what Claude Code uses when the
    command fits."""
    fake = FakeSecurity()
    store = KeychainStore(service="S", account="A", run=fake)
    payload = b'{"refreshToken":"secret"}'
    store.write(payload)
    assert payload.hex() not in " ".join(
        arg for call in fake.calls for arg in call)
    assert store.read() == payload


def test_keychain_writes_by_argument_when_stdin_did_not_take():
    """Interactive mode that exits 0 having stored nothing must not read as
    a successful write. The item is read back, and the argument form is used
    when it does not hold what was sent."""
    fake = FakeSecurity(interactive=False)
    store = KeychainStore(service="S", account="A", run=fake)
    store.write(b'{"a":1}')
    assert store.read() == b'{"a":1}'
    assert any(call[1] == "add-generic-password" for call in fake.calls)


def test_keychain_sends_a_large_credential_by_argument():
    """``security -i`` stops reading a line at about 4 KB."""
    fake = FakeSecurity()
    store = KeychainStore(service="S", account="A", run=fake)
    payload = b'{"k":"' + b"x" * 3000 + b'"}'
    store.write(payload)
    assert not any(call[1] == "-i" for call in fake.calls)
    assert store.read() == payload


def test_a_locked_keychain_is_told_apart_from_a_broken_one():
    """Exit 36 is what SSH into a Mac gets: the keychain is fine, there is
    just nobody to show an unlock dialog to. The layered store needs to know
    that is what happened."""
    store = KeychainStore(service="S", account="A", run=FakeSecurity(locked=True))
    with pytest.raises(StoreLockedError, match="locked"):
        store.read()
    with pytest.raises(StoreLockedError):
        store.write(b"{}")


# -- Windows Credential Manager, in Claude Code's layout ----------------------


def test_credman_keeps_a_small_credential_in_one_entry():
    """What Claude Code writes for a login of 2400 bytes or fewer: one entry
    named for the account, holding the JSON as it is. A reader that only
    looked for pieces found nothing."""
    backend = FakeCredman()
    store = CredmanStore(service="Claude Code-credentials",
                         account="claude-code-user", backend=backend)
    store.write(b'{"claudeAiOauth":{}}')
    assert backend.entries == {
        "Claude Code-credentials/claude-code-user": b'{"claudeAiOauth":{}}'}


def test_credman_splits_a_large_credential_the_way_the_vendor_does():
    """Base64 first, then 2400-character pieces, then a JSON count.

    Checked against an install: with Credential Manager forced on, a 3.6 KB
    login was reported as ``#m`` of 16 bytes and two pieces of 2400. The
    numbers below are that shape.
    """
    backend = FakeCredman()
    store = CredmanStore(service="Claude Code-credentials",
                         account="claude-code-user", backend=backend)
    payload = b'{"k":"' + b"x" * 3590 + b'"}'
    store.write(payload)

    prefix = "Claude Code-credentials/claude-code-user"
    assert sorted(backend.entries) == [f"{prefix}#0", f"{prefix}#1", f"{prefix}#m"]
    assert backend.entries[f"{prefix}#m"] == b'{"n":2,"l":4800}'
    assert len(backend.entries[f"{prefix}#0"]) == 2400
    assert len(backend.entries[f"{prefix}#1"]) == 2400
    import base64
    assert base64.b64decode(backend.entries[f"{prefix}#0"]
                            + backend.entries[f"{prefix}#1"]) == payload
    assert store.read() == payload


def test_credman_reads_what_the_vendor_wrote():
    """Entries laid down the way the binary lays them, read back whole."""
    import base64
    payload = json.dumps({"claudeAiOauth": {"refreshToken": "r" * 5000}}).encode()
    encoded = base64.b64encode(payload)
    backend = FakeCredman()
    prefix = "Claude Code-credentials/claude-code-user"
    pieces = [encoded[i:i + 2400] for i in range(0, len(encoded), 2400)]
    for index, piece in enumerate(pieces):
        backend.entries[f"{prefix}#{index}"] = piece
    backend.entries[f"{prefix}#m"] = json.dumps(
        {"n": len(pieces), "l": len(encoded)}).encode()

    store = CredmanStore(service="Claude Code-credentials",
                         account="claude-code-user", backend=backend)
    assert store.read() == payload


def test_credman_names_each_entry_as_its_own_user():
    """``Bun.secrets`` records the entry name as the credential's user name.
    Nothing reads it back, but an entry that differs from the vendor's in a
    field Windows shows in its own UI invites somebody to "clean it up"."""
    backend = FakeCredman()
    CredmanStore(service="S", account="A", backend=backend).write(b"{}")
    assert backend.usernames == {"S/A": "A"}


def test_credman_going_from_large_to_small_leaves_no_pieces_behind():
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=16,
                         backend=backend)
    store.write(b'{"big":"' + b"x" * 100 + b'"}')
    assert "S/A#m" in backend.entries
    store.write(b'{"a":1}')
    assert backend.entries == {"S/A": b'{"a":1}'}
    assert store.read() == b'{"a":1}'


def test_credman_going_from_small_to_large_removes_the_single_entry():
    """A leftover whole entry would be ignored while the count exists and
    then come back to life the moment the pieces were removed."""
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=16,
                         backend=backend)
    store.write(b'{"a":1}')
    big = b'{"big":"' + b"x" * 100 + b'"}'
    store.write(big)
    assert "S/A" not in backend.entries
    assert "S/A#p" not in backend.entries
    assert store.read() == big


def test_credman_shrinking_removes_the_surplus_pieces():
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=16,
                         backend=backend)
    store.write(b'{"big":"' + b"x" * 200 + b'"}')
    smaller = b'{"big":"' + b"x" * 40 + b'"}'
    store.write(smaller)
    count = parse_meta(backend.entries["S/A#m"], chunk_size=16)[0]
    assert sorted(k for k in backend.entries if k[4:].isdigit()) == sorted(
        f"S/A#{i}" for i in range(count))
    assert store.read() == smaller


def test_credman_delete_removes_every_entry_of_either_shape():
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=16,
                         backend=backend)
    store.write(b'{"big":"' + b"x" * 100 + b'"}')
    store.delete()
    assert backend.entries == {}
    store.write(b"{}")
    store.delete()
    assert backend.entries == {}


def test_credman_delete_clears_pieces_an_interrupted_write_left():
    """A write that died after its pieces and before its count leaves
    entries nothing describes. The pending marker says how many."""
    backend = FakeCredman()
    backend.entries.update({"S/A#p": b"3", "S/A#0": b"aa", "S/A#1": b"bb",
                            "S/A#2": b"cc"})
    CredmanStore(service="S", account="A", backend=backend).delete()
    assert backend.entries == {}


def test_credman_splits_and_rejoins_across_chunks():
    payload = b"x" * 5000
    chunks = split_payload(payload, chunk_size=2000)
    assert len(chunks) == 3
    assert join_chunks(chunks) == payload


@pytest.mark.parametrize("raw", [
    None, b"", b"3", b"not json", b"[]", b'{"n":0,"l":0}', b'{"n":257,"l":10}',
    b'{"n":1,"l":2401}', b'{"n":"2","l":10}', b'{"n":true,"l":1}',
    b'{"n":1.5,"l":10}', b"\xff\xfe",
])
def test_a_count_the_vendor_would_reject_is_rejected_here_too(raw):
    """Both programs have to agree on whether a credential is split."""
    assert parse_meta(raw) is None


def test_credman_refuses_to_return_a_truncated_credential():
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=8,
                         backend=backend)
    store.write(b"0123456789012345678")
    # Simulate a partially-lost credential family.
    missing = next(k for k in backend.entries if k.endswith("#1"))
    del backend.entries[missing]
    with pytest.raises(StoreUnavailableError, match="truncated"):
        store.read()


# -- two stores layered the way the vendor layers them ------------------------


class _Refusing:
    """A primary store that holds nothing and will not be written to."""

    def read(self):
        return None

    def write(self, payload):
        raise StoreUnavailableError("primary refused the write")

    def delete(self):
        raise StoreUnavailableError("primary refused the delete")

    def describe(self):
        return "a store that refuses"


def _layered(tmp_path, **kwargs):
    security = FakeSecurity(**kwargs)
    primary = KeychainStore(service="S", account="A", run=security)
    fallback = FileStore(tmp_path / "creds.json")
    return FallbackStore(primary, fallback), primary, fallback, security


def test_a_layered_store_reads_the_file_when_the_primary_is_empty(tmp_path):
    """A Mac whose login was made over SSH: nothing in the Keychain, the
    login in ``.credentials.json``. That machine is signed in."""
    store, _primary, fallback, _ = _layered(tmp_path)
    fallback.write(b'{"from":"file"}')
    assert store.read() == b'{"from":"file"}'


def test_a_layered_store_prefers_the_primary(tmp_path):
    store, primary, fallback, _ = _layered(tmp_path)
    fallback.write(b'{"from":"file"}')
    primary.write(b'{"from":"keychain"}')
    assert store.read() == b'{"from":"keychain"}'


def test_writing_into_an_empty_primary_clears_the_file_it_supersedes(tmp_path):
    """What the vendor does, and for the reason it does it: a stale file left
    behind is read again the day the primary is emptied."""
    store, primary, fallback, _ = _layered(tmp_path)
    fallback.write(b'{"account":"old"}')
    store.write(b'{"account":"new"}')
    assert primary.read() == b'{"account":"new"}'
    assert fallback.read() is None
    assert store.read() == b'{"account":"new"}'


def test_writing_over_a_held_primary_leaves_the_file_alone(tmp_path):
    """The file is only cleared when it was the live credential. With the
    primary already holding one, whatever is in the file is not what this
    write replaces, and removing it would destroy bytes nobody stashed."""
    store, primary, fallback, _ = _layered(tmp_path)
    primary.write(b'{"account":"old"}')
    fallback.write(b'{"left":"alone"}')
    store.write(b'{"account":"new"}')
    assert primary.read() == b'{"account":"new"}'
    assert fallback.read() == b'{"left":"alone"}'


def test_a_refused_write_to_an_empty_primary_lands_in_the_file(tmp_path):
    """The vendor's own fallback: with the Keychain refusing, the login goes
    to the file, and that is where it will be read from."""
    fallback = FileStore(tmp_path / "creds.json")
    store = FallbackStore(_Refusing(), fallback)
    store.write(b'{"account":"new"}')
    assert fallback.read() == b'{"account":"new"}'
    assert store.read() == b'{"account":"new"}'


def test_a_refused_write_over_a_held_primary_is_an_error(tmp_path):
    """Writing the file instead would report success while the vendor went on
    reading the old login from the primary."""
    class Held(_Refusing):
        def read(self):
            return b'{"account":"old"}'

    fallback = FileStore(tmp_path / "creds.json")
    with pytest.raises(StoreUnavailableError):
        FallbackStore(Held(), fallback).write(b'{"account":"new"}')
    assert fallback.read() is None


def test_a_locked_primary_falls_through_to_a_file_that_answers(tmp_path):
    """SSH into a Mac that was signed in over SSH: the Keychain will not
    answer, the file does, and the vendor reads the file."""
    store, _primary, fallback, _ = _layered(tmp_path, locked=True)
    fallback.write(b'{"from":"file"}')
    assert store.read() == b'{"from":"file"}'
    store.write(b'{"from":"switch"}')
    assert fallback.read() == b'{"from":"switch"}'


def test_a_locked_primary_with_no_file_is_reported_as_locked(tmp_path):
    """Not as "signed out". The login may well be in the Keychain; saying
    there is none would offer to start again from nothing."""
    store, _primary, fallback, _ = _layered(tmp_path, locked=True)
    with pytest.raises(StoreLockedError):
        store.read()
    with pytest.raises(StoreLockedError):
        store.write(b"{}")
    assert fallback.read() is None


def test_deleting_a_layered_store_empties_both(tmp_path):
    store, primary, fallback, _ = _layered(tmp_path)
    primary.write(b'{"a":1}')
    fallback.write(b'{"b":2}')
    store.delete()
    assert primary.read() is None and fallback.read() is None


def test_deleting_survives_a_primary_that_refuses_when_the_file_held_the_login(
        tmp_path):
    fallback = FileStore(tmp_path / "creds.json")
    fallback.write(b'{"a":1}')
    FallbackStore(_Refusing(), fallback).delete()
    assert fallback.read() is None


def test_deleting_reports_a_primary_that_refuses_when_nothing_else_was_held(
        tmp_path):
    fallback = FileStore(tmp_path / "creds.json")
    with pytest.raises(StoreUnavailableError):
        FallbackStore(_Refusing(), fallback).delete()


def test_a_layered_store_names_both_places(tmp_path):
    store, _primary, fallback, _ = _layered(tmp_path)
    assert "Keychain" in store.describe()
    assert str(fallback.path) in store.describe()


@posix_modes_only
def test_a_credential_is_never_observable_at_loose_permissions(tmp_path, monkeypatch):
    """The temp file must be *created* 0600, not created at the umask and
    tightened afterwards. In between, a complete plaintext refresh token sits
    on disk world-readable -- a window, not a formality.

    Observed at the ``chmod`` call rather than at ``os.replace``: by replace
    time the mode is 0600 whichever way it got there, so that vantage point
    cannot tell a fixed implementation from a vulnerable one. The umask is
    pinned lax for the same reason -- under a strict umask the old code
    happened to create at 0600 and the window closed by luck.
    """
    observed = {}
    real_chmod = os.chmod

    def spy(path, mode, *args, **kwargs):
        try:
            stat = os.stat(path)
            # Regular files only: this call also tightens the parent
            # directory, and a directory's mode says nothing about whether
            # the credential inside it was ever exposed.
            if os_stat.S_ISREG(stat.st_mode) and stat.st_size:
                observed.setdefault("mode", oct(stat.st_mode)[-3:])
        except OSError:
            pass
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", spy)
    previous = os.umask(0o022)
    try:
        FileStore(tmp_path / "creds.json", 0o600).write(b'{"token": "secret"}')
    finally:
        os.umask(previous)

    assert observed.get("mode") == "600", (
        f"credential was on disk at {observed.get('mode')} before being "
        f"restricted to 0600")


@posix_modes_only
def test_the_parent_directory_is_created_owner_only(tmp_path):
    store = FileStore(tmp_path / "nested" / "creds.json", 0o600)
    store.write(b"{}")
    assert oct(os.stat(tmp_path / "nested").st_mode)[-3:] == "700"


def test_a_write_failure_is_a_shambles_error(tmp_path):
    """Never a bare OSError: the GUI renders ShamblesError only, and anything
    else reaches the user as a stderr traceback."""
    store = FileStore(tmp_path / "creds.json", 0o600)
    (tmp_path / "creds.json").mkdir()  # a directory where a file must go
    with pytest.raises(StoreUnavailableError):
        store.write(b"{}")


@posix_modes_only
def test_a_leftover_temp_file_does_not_expose_the_next_write(tmp_path, monkeypatch):
    """``O_CREAT`` honours the ``mode`` argument only when it creates the
    file. A ``*.shambles-tmp`` left behind at a loose mode by a crashed run
    is opened, not created, on the next write -- so a fix that only passes
    ``mode`` to ``os.open`` looks correct on a clean run and still leaks the
    credential on this one.

    Observed via ``os.fstat`` on the descriptor immediately after the real
    ``os.write`` returns: the one vantage point that catches the bytes at
    rest no matter which mechanism (or lack of one) is meant to have fixed
    the mode by then.
    """
    target = tmp_path / "creds.json"
    tmp = target.with_name(target.name + ".shambles-tmp")
    tmp.write_bytes(b"stale content from a crashed run")
    os.chmod(tmp, 0o644)

    observed = {}
    real_write = os.write

    def spy(fd, data):
        result = real_write(fd, data)
        observed.setdefault("mode", oct(os.fstat(fd).st_mode)[-3:])
        return result

    monkeypatch.setattr(os, "write", spy)
    previous = os.umask(0o022)
    try:
        FileStore(target, 0o600).write(b'{"token": "secret"}')
    finally:
        os.umask(previous)

    assert observed.get("mode") == "600", (
        f"credential landed at {observed.get('mode')} while a leftover "
        f"temp file's old permissions still applied")


def test_a_credential_is_written_without_newline_translation(tmp_path):
    """Windows opens descriptors in text mode and rewrites every "\\n" as
    "\\r\\n". A credential is bytes: a token containing a newline would come
    back longer than it went in, which the round-trip suite caught on Windows
    and no POSIX runner ever would."""
    store = FileStore(tmp_path / "creds.json", 0o600)
    payload = b'{\n  "token": "a\\nb"\n}\n'
    store.write(payload)
    assert store.path.read_bytes() == payload
    assert b"\r\n" not in store.path.read_bytes()
