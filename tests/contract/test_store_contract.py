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
from shambles.stores import CredentialStore, CredmanStore, FileStore, KeychainStore
from shambles.stores.base import StoreUnavailableError
from shambles.stores.credman import join_chunks, split_payload
from tests.fakes import FakeCredman, FakeSecurity


def _file(tmp_path):
    return FileStore(tmp_path / "creds.json")


def _keychain(tmp_path):
    return KeychainStore(service="Test-credentials", account="tester",
                         run=FakeSecurity())


def _credman(tmp_path):
    return CredmanStore(service="Test-credentials", account="tester",
                        chunk_size=64, backend=FakeCredman())


STORES = {"file": _file, "keychain": _keychain, "credman": _credman}

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
    add = next(c for c in fake.calls if c[1] == "add-generic-password")
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


def test_credman_splits_and_rejoins_across_chunks():
    payload = b"x" * 5000
    chunks = split_payload(payload, chunk_size=2000)
    assert len(chunks) == 3
    assert join_chunks(chunks) == payload


def test_credman_refuses_to_return_a_truncated_credential():
    backend = FakeCredman()
    store = CredmanStore(service="S", account="A", chunk_size=8,
                         backend=backend)
    store.write(b"0123456789012345678")
    # Simulate a partially-lost credential family.
    missing = next(k for k in backend.entries if k.endswith("#1"))
    del backend.entries[missing]
    with pytest.raises(Exception, match="truncated|missing chunk"):
        store.read()


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
