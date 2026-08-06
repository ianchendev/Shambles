"""Credentials in the macOS Keychain, reached through ``/usr/bin/security``.

Claude Code stores its macOS login here and nowhere else -- ``~/.claude`` holds
no credentials file on that platform at all. Codex can be configured to use the
Keychain but does not by default.

**Why shell out rather than bind Security.framework.** This is what Claude Code
itself does: the shipping binary contains the literal
``security find-generic-password -a "`` alongside a dozen further references to
that tool. Matching it means inheriting the access posture it already
established. Binding the framework through PyObjC would add a native extension
-- a larger surface, not a smaller one -- for no behavioural gain.

**Two honest caveats.**

*The payload is visible in ``ps`` for the life of the write.* ``security`` takes
the data as a command-line argument and offers no stdin path for it, so any
process on the machine can see a credential mid-write. Claude Code has exactly
this exposure for exactly this reason. It is inherent to the tool, not a choice
made here, but it should not go unrecorded.

*The item carries no ACL.* Claude Code creates it without ``-T`` or ``-A``, so
any process running as the user can read it without a prompt. Writing to it
therefore does not worsen the existing posture -- but neither does it improve
it, and the UI should not imply otherwise.
"""

import subprocess
from dataclasses import dataclass, field

from .base import StoreUnavailableError

SECURITY = "/usr/bin/security"

#: ASCII byte values of the hex digits, for the encoding sniff below.
_HEX_BYTES = frozenset(b"0123456789abcdefABCDEF")

_NOT_FOUND_MARKERS = ("could not be found", "SecKeychainSearchCopyNext")


def decode_output(stdout: bytes) -> bytes:
    """Recover the stored bytes from ``security find-generic-password -w``.

    That flag is **not** byte-transparent, which is worth stating plainly
    because assuming otherwise silently corrupts any non-ASCII credential.
    Measured against the real tool:

    ==========================  =======  ========  ==================
    payload                     in       stdout    form
    ==========================  =======  ========  ==================
    ``{"a":1}``                 7 B      8 B       text + newline
    ``{"a":1}\\n``               8 B      17 B      **hex** + newline
    ``{"n":"...unicode..."}``   21 B     43 B      **hex** + newline
    ==========================  =======  ========  ==================

    ``security`` prints the password as text when it is entirely printable
    ASCII, and falls back to a hex dump otherwise. Both forms gain a trailing
    newline. So the reader has to sniff which one it got.

    The sniff is unambiguous for the payloads this project stores. Every
    credential here is JSON, and JSON begins with ``{`` or ``[`` -- neither is a
    hex digit, so a JSON payload can never be mistaken for a hex dump. A caller
    storing arbitrary bytes that happen to form an even-length hex string would
    get them back decoded; that case cannot arise here, and the type signature
    is not worth complicating for it.
    """
    body = stdout[:-1] if stdout.endswith(b"\n") else stdout
    if body and len(body) % 2 == 0 and all(c in _HEX_BYTES for c in body):
        return bytes.fromhex(body.decode("ascii"))
    return body


@dataclass(frozen=True)
class KeychainStore:
    service: str
    account: str
    security: str = SECURITY
    #: Injected so tests can drive this without touching the real Keychain.
    run: object = field(default=None, compare=False)

    def _run(self, args, *, check_missing=False):
        runner = self.run or subprocess.run
        try:
            done = runner([self.security, *args], capture_output=True)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not run {self.security}:\n{exc}") from exc

        if done.returncode == 0:
            return done

        stderr = (done.stderr or b"").decode("utf-8", "replace")
        if check_missing and any(m in stderr for m in _NOT_FOUND_MARKERS):
            return None
        raise StoreUnavailableError(
            f"Keychain refused the request for '{self.service}':\n"
            f"{stderr.strip() or f'exit status {done.returncode}'}")

    def read(self) -> bytes | None:
        done = self._run(
            ["find-generic-password", "-a", self.account, "-s", self.service, "-w"],
            check_missing=True)
        return None if done is None else decode_output(done.stdout)

    def write(self, payload: bytes) -> None:
        # -U updates in place rather than adding a duplicate item; -X takes the
        # data as hex, which is the only way to store bytes the tool would
        # otherwise mangle. Both match what Claude Code does.
        self._run(["add-generic-password", "-U", "-a", self.account,
                   "-s", self.service, "-X", payload.hex()])

    def delete(self) -> None:
        self._run(["delete-generic-password", "-a", self.account,
                   "-s", self.service], check_missing=True)

    def describe(self) -> str:
        return f"macOS Keychain item '{self.service}' (account '{self.account}')"
