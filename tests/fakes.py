"""Stand-ins for the two platform stores that cannot be exercised here.

The Keychain fake is not a stub. It reproduces the one behaviour of
``/usr/bin/security`` that actually bites: ``find-generic-password -w`` prints
the password as text when it is entirely printable ASCII, and falls back to a
hex dump otherwise, adding a trailing newline either way. Measured against the
real tool on macOS 15.5 -- a 7-byte JSON payload came back as 8 bytes of text,
while the same payload with a trailing newline came back as 17 bytes of hex.

Encoding that here means the round-trip test would have caught a reader that
assumed ``-w`` was byte-transparent, which is exactly the bug this fake exists
to prevent regressing.
"""

import subprocess

PRINTABLE = set(range(0x20, 0x7F))


def _security_prints_hex(payload: bytes) -> bool:
    """Whether the real tool would fall back to a hex dump for this payload."""
    return any(byte not in PRINTABLE for byte in payload)


class FakeSecurity:
    """A ``subprocess.run`` replacement that behaves like ``security``."""

    def __init__(self):
        self.items = {}
        self.calls = []

    def __call__(self, args, capture_output=False, **kwargs):
        self.calls.append(list(args))
        verb = args[1]
        flags = _parse_flags(args[2:])
        key = (flags.get("-s"), flags.get("-a"))

        if verb == "add-generic-password":
            self.items[key] = bytes.fromhex(flags["-X"])
            return _done(0)

        if verb == "find-generic-password":
            payload = self.items.get(key)
            if payload is None:
                return _done(44, stderr=b"security: SecKeychainSearchCopyNext: "
                                        b"The specified item could not be found "
                                        b"in the keychain.\n")
            body = (payload.hex().encode("ascii")
                    if _security_prints_hex(payload) else payload)
            return _done(0, stdout=body + b"\n")

        if verb == "delete-generic-password":
            if key not in self.items:
                return _done(44, stderr=b"security: SecKeychainSearchCopyNext: "
                                        b"The specified item could not be found "
                                        b"in the keychain.\n")
            del self.items[key]
            return _done(0)

        raise AssertionError(f"unexpected security verb: {verb}")


class FakeCredman:
    """An in-memory Windows Credential Manager, keyed by target name."""

    def __init__(self):
        self.entries = {}

    def read(self, target):
        return self.entries.get(target)

    def write(self, target, payload):
        self.entries[target] = payload

    def delete(self, target):
        self.entries.pop(target, None)


#: ``security`` flags that take no value. Pairing naively without these shifts
#: every later flag onto the wrong value.
STANDALONE_FLAGS = frozenset({"-U", "-w", "-g", "-A"})


def _parse_flags(argv) -> dict:
    flags = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in STANDALONE_FLAGS:
            flags[token] = True
            index += 1
        elif token.startswith("-"):
            flags[token] = argv[index + 1] if index + 1 < len(argv) else None
            index += 2
        else:
            index += 1
    return flags


def _done(returncode, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)
