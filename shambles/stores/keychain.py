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

*A large payload is visible in ``ps`` for the life of the write.* ``security``
takes the data as a command-line argument. Its interactive mode (``-i``) reads
the same command from standard input instead, which keeps the credential out
of the process table, but that mode stops reading a line at about 4 KB. So a
write goes through standard input when it fits and through the argument list
when it does not -- which is what Claude Code does, with the same limit, read
out of its 2.1.322 binary. A plain login fits; one carrying several MCP server
tokens may not. That remaining exposure is inherent to the tool, not a choice
made here, but it should not go unrecorded.

*The item carries no ACL.* Claude Code creates it without ``-T`` or ``-A``, so
any process running as the user can read it without a prompt. Writing to it
therefore does not worsen the existing posture -- but neither does it improve
it, and the UI should not imply otherwise.
"""

import subprocess
from dataclasses import dataclass, field

from .base import StoreLockedError, StoreUnavailableError

SECURITY = "/usr/bin/security"

#: ``security`` exits with the low byte of the Keychain's own status code.
#: 44 is errSecItemNotFound (-25300); 36 is errSecInteractionNotAllowed
#: (-25308), which is what a locked keychain answers when there is no desktop
#: session to show an unlock dialog in -- the normal case over SSH.
EXIT_NOT_FOUND = 44
EXIT_INTERACTION_NOT_ALLOWED = 36

#: How long ``security`` gets to answer. On a desktop it can put up a dialog
#: asking for the keychain password, so this is long enough for a person to
#: type one -- and short enough that a dialog nobody can see, or a keychain
#: daemon that has stopped answering, ends in a sentence rather than a hang.
TIMEOUT_SECONDS = 60

#: The longest command line ``security -i`` reads from standard input.
#: Claude Code uses the same figure and falls back to arguments beyond it.
STDIN_COMMAND_LIMIT = 4032

#: ASCII byte values of the hex digits, for the encoding sniff below.
_HEX_BYTES = frozenset(b"0123456789abcdefABCDEF")

#: The sentence, not the function name in front of it. ``security`` prefixes
#: *every* failure of a lookup with ``SecKeychainSearchCopyNext:``, including
#: "User interaction is not allowed", so matching on that prefix read a locked
#: keychain as an empty one -- and an empty one is an invitation to write.
_NOT_FOUND_MARKERS = ("could not be found",)


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

    def _run(self, args, *, check_missing=False, stdin=None):
        runner = self.run or subprocess.run
        try:
            if stdin is None:
                done = runner([self.security, *args], capture_output=True,
                              timeout=TIMEOUT_SECONDS)
            else:
                done = runner([self.security, *args], capture_output=True,
                              input=stdin, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise StoreUnavailableError(
                f"The macOS Keychain did not answer within {TIMEOUT_SECONDS} "
                f"seconds for '{self.service}'. It may be waiting for a "
                "password in a dialog on the Mac's own screen.") from exc
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not run {self.security}:\n{exc}") from exc

        if done.returncode == 0:
            return done

        stderr = (done.stderr or b"").decode("utf-8", "replace")
        detail = stderr.strip() or f"exit status {done.returncode}"
        # Locked is checked before missing: both are "the lookup failed", and
        # only one of them means there is nothing there.
        if done.returncode == EXIT_INTERACTION_NOT_ALLOWED:
            raise StoreLockedError(
                f"The macOS Keychain is locked, so '{self.service}' cannot be "
                f"reached from this session:\n{detail}\n\n"
                "Unlock it with 'security unlock-keychain', or run Shambles "
                "from a terminal on the Mac's own desktop.")
        if check_missing and (done.returncode == EXIT_NOT_FOUND
                              or any(m in stderr for m in _NOT_FOUND_MARKERS)):
            return None
        raise StoreUnavailableError(
            f"Keychain refused the request for '{self.service}':\n{detail}")

    def read(self) -> bytes | None:
        done = self._run(
            ["find-generic-password", "-a", self.account, "-s", self.service, "-w"],
            check_missing=True)
        return None if done is None else decode_output(done.stdout)

    def write(self, payload: bytes) -> None:
        # -U updates in place rather than adding a duplicate item; -X takes the
        # data as hex, which is the only way to store bytes the tool would
        # otherwise mangle. Both match what Claude Code does.
        encoded = payload.hex()
        command = (f'add-generic-password -U -a "{self.account}" '
                   f'-s "{self.service}" -X "{encoded}"\n')
        if len(command) <= STDIN_COMMAND_LIMIT and self._quotable():
            try:
                self._run(["-i"], stdin=command.encode("utf-8"))
                # Whether interactive mode's exit status reflects a command
                # that failed is not something this relies on. Reading the
                # item back proves it changed, and a credential write that
                # silently did not take is the one failure not worth saving
                # a subprocess over.
                if self.read() == payload:
                    return
            except StoreLockedError:
                raise  # the argument form would only be refused the same way
            except StoreUnavailableError:
                pass
        self._run(["add-generic-password", "-U", "-a", self.account,
                   "-s", self.service, "-X", encoded])

    def _quotable(self) -> bool:
        """Whether both names survive ``security -i``'s double quoting.

        A quote or backslash in either would end the argument early. Neither
        can appear in a name this project computes -- the service is a fixed
        template plus hex, the account a vetted username -- so this guards
        the general case rather than a real one, by sending such a name
        through the argument list where no quoting is involved.
        """
        return not any(c in text for text in (self.account, self.service)
                       for c in '"\\\n\r')

    def delete(self) -> None:
        self._run(["delete-generic-password", "-a", self.account,
                   "-s", self.service], check_missing=True)

    def describe(self) -> str:
        return f"macOS Keychain item '{self.service}' (account '{self.account}')"
