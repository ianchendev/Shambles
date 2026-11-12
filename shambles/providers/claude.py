"""Claude Code's credential semantics.

Two things make this the more awkward of the two providers, and both are visible
in the methods below.

Its tokens are **opaque**, so a credential tells you nothing about who owns it.
Identity has to be read from a separate file, ``~/.claude.json``, which is why
:meth:`ClaudeProvider.companion_read` exists at all and why an interrupted
switch can leave a token and a displayed email disagreeing.

Its macOS Keychain service name is **computed, not constant**. Hardcoding
``Claude Code-credentials`` works right up until the user has ever set
``CLAUDE_CONFIG_DIR``, at which point the real item carries an eight-character
hash suffix and the hardcoded lookup silently finds nothing.
"""

import hashlib
import json
import math
import os
import re
import unicodedata
from pathlib import Path

from .. import configjson
from ..stores import CredmanStore, FallbackStore, FileStore, KeychainStore
from ..stores.base import StoreUnavailableError
from . import spec as specmod
from .base import (ABSENT, CLOSED, CLOSING, LIVE, SIGNED_OUT, UNKNOWN,
                   Identity, Liveness)

MS_PER_DAY = 86_400_000


def service_name(block: dict, *, config_dir: Path, env) -> str:
    """Reproduce Claude Code's secure-storage service-name construction.

    From the shipping binary::

        `Claude Code${OAUTH_FILE_SUFFIX}${"-credentials"}${dirHash}`

    where ``dirHash`` is ``"-"`` plus the first eight hex characters of the
    SHA-256 of the NFC-normalized config directory, present **iff**
    ``CLAUDE_CONFIG_DIR`` is set and ``CLAUDE_SECURESTORAGE_CONFIG_DIR`` is not
    the empty string. The latter is undocumented and is the only way to keep the
    default service name while relocating the config. The same name is used
    for the macOS Keychain item and the Windows Credential Manager target.

    **The hash is taken over the variable exactly as it was typed.** Claude
    Code hashes the raw string, so ``/home/me/alt/`` and ``/home/me/alt`` are
    two different items to it, as are ``C:/Users/me/alt`` and
    ``C:\\Users\\me\\alt``. A tidied path -- which is what ``config_dir`` is,
    having been through :class:`pathlib.Path` -- hashes to something the
    vendor never wrote, and the lookup silently finds nothing.

    Verified two independent ways: deriving the hash by hand for the default
    config directory gives the same eight characters the CLI was observed to
    use when actually run with that directory set explicitly.
    """
    suppress = env.get(block.get("hash_suppress_env", ""))
    raw = env.get(spec_env_name(block), "")
    if suppress is not None:
        hashed = bool(suppress)
        source = suppress
    else:
        hashed = bool(raw)
        source = raw or str(config_dir)

    suffix = ""
    if hashed:
        normalized = unicodedata.normalize("NFC", source)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        suffix = f"-{digest[:8]}"

    oauth = ""
    if env.get(block.get("oauth_suffix_env", ""), ""):
        oauth = block.get("oauth_suffix_when_set", "")

    return block["service_template"].format(
        oauth_suffix=oauth, config_dir_hash=suffix)


def spec_env_name(block: dict) -> str:
    """The config-dir variable whose presence triggers the hash suffix."""
    return block.get("config_dir_env", "CLAUDE_CONFIG_DIR")


def account_name(block: dict, env, *, os_user=None) -> str:
    """``$USER``, then the operating system's own answer, then a fixed name.

    Claude Code reads ``process.env.USER || os.userInfo().username`` and
    substitutes ``claude-code-user`` for any name outside ``[A-Za-z0-9._-]``.
    On Windows it uses that literal unconditionally.

    The middle step matters. A process started by launchd, cron or a desktop
    launcher can have no ``USER`` at all, and stopping at the variable would
    send it to the ``claude-code-user`` item while the vendor, asking the
    system instead, went on using the real one.
    """
    if "account" in block:
        return block["account"]
    name = env.get(block.get("account_env", "USER"), "")
    if not name:
        name = (os_user or _os_user)()
    pattern = block.get("account_pattern")
    if not name or (pattern and not re.match(pattern, name)):
        return block.get("account_fallback", "claude-code-user")
    return name


def _os_user() -> str:
    """The login name the system holds for this process, or ``""``."""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError, OSError):
        return ""


def secure_dir(spec: dict, *, home, env) -> Path:
    """The directory holding Claude Code's plaintext ``.credentials.json``.

    Not always the config directory. ``CLAUDE_SECURESTORAGE_CONFIG_DIR``
    takes over when it is set at all: its value when it has one, and the
    *default* directory -- not ``CLAUDE_CONFIG_DIR`` -- when it is set but
    empty. From the binary::

        if (e !== undefined) return (e || join(homedir(), ".claude"))
        return configDir()
    """
    block = spec.get("secure_dir") or {}
    override = env.get(block.get("env", ""))
    if override is None:
        return specmod.config_dir(spec, home=home, env=env)
    if override:
        return Path(unicodedata.normalize("NFC", override))
    return specmod.expand(block.get("when_empty", "~/.claude"), home=home)


def config_root(spec: dict, *, home, env) -> Path:
    """Where ``.claude.json`` sits: the config directory if one is set,
    otherwise the home directory itself."""
    override = env.get((spec.get("config_dir") or {}).get("env", ""), "")
    return Path(override) if override else Path(home)


def gate_open(spec: dict, gate: dict | None, *, home, env) -> bool:
    """Whether a store that the vendor only uses when told to is in use.

    Windows Credential Manager is the case. Claude Code consults it only
    when ``CLAUDE_CODE_FORCE_WINDOWS_CREDMAN=1`` or when its own cached copy
    of a server-side flag says so, and reads that flag from the legacy
    ``.config.json`` if that file has anything in it, otherwise from
    ``.claude.json``. The same two files are read here, in the same order,
    with the same outcome for a file that is missing or unparsable: off.

    Guessing "on" would be the dangerous direction. With the gate closed the
    vendor never looks at Credential Manager, so a credential written there
    is a switch that reports success and changes nothing.
    """
    if not gate:
        return True
    if env.get(gate.get("env", ""), "") == gate.get("env_value", "1"):
        return True

    config = specmod.config_dir(spec, home=home, env=env)
    root = config_root(spec, home=home, env=env)
    text = ""
    for template in gate.get("flag_files", ()):
        path = Path(str(template)
                    .replace("{config_dir}", str(config))
                    .replace("{config_root}", str(root)))
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            continue
        except (OSError, UnicodeDecodeError):
            return False
        if text:
            break
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return specmod.pointer(data, gate.get("flag", "")) is True


def _system_home() -> Path | None:
    """The home directory this process really has, or ``None`` if unknown."""
    try:
        return Path.home()
    except (RuntimeError, OSError):
        return None


class ClaudeProvider:
    def __init__(self, spec=None, env=None, real_home=_system_home):
        self.spec = spec if spec is not None else specmod.load("claude")
        self.env = os.environ if env is None else env
        #: Answers "which directory is this user's actual home". Injected so
        #: a test can declare its temporary directory to be the real one;
        #: nothing else should replace it.
        self.real_home = real_home

    # -- identification ---------------------------------------------------

    @property
    def id(self) -> str:
        return self.spec["id"]

    @property
    def display_name(self) -> str:
        return self.spec["display_name"]

    @property
    def rotates(self) -> bool:
        return bool(self.spec["policy"]["rotates"])

    @property
    def warn_days(self) -> int:
        return int(self.spec["policy"]["warn_days"])

    def login_hint(self) -> str:
        return self.spec["login"]["hint"]

    def login_binary(self) -> str:
        """The executable to probe on PATH before offering this provider."""
        return self.spec["login"]["binary"]

    def login_command(self) -> list[str]:
        """The vendor's own login command. It opens the browser itself and
        runs its own OAuth callback -- Shambles never handles a token in
        flight, which is what keeps DD-2's structural argument intact."""
        return list(self.spec["login"]["command"])

    # -- where the bytes live ---------------------------------------------

    def store(self, *, home, platform: str):
        """The store Claude Code itself would read on this platform.

        A file on Linux. On macOS the Keychain, layered over that same file.
        On Windows the file -- unless Credential Manager has been switched on
        for this account, in which case Credential Manager layered over the
        file. See :class:`~shambles.stores.FallbackStore` for the layering.

        For a ``home`` that is not the user's real one, always the file:
        see :meth:`_is_real_home`.
        """
        block = specmod.store_block(self.spec, platform)
        primary = self._single_store(block, home=home)
        fallback = block.get("fallback")
        if not fallback:
            return primary

        plain = self._single_store(fallback, home=home)
        if not self._is_real_home(home):
            return plain
        if not gate_open(self.spec, block.get("enabled_by"),
                         home=home, env=self.env):
            return plain
        return FallbackStore(primary, plain)

    def _is_real_home(self, home) -> bool:
        """Whether ``home`` is the home directory of the user running this.

        The Keychain and the Credential Manager belong to the *user*, not to
        a directory. ``shambles --home /tmp/scratch`` exists so the program
        can be tried without risking a real login, and every file path obeys
        it -- but a Keychain lookup made on behalf of a scratch home still
        lands in the one real Keychain. So for any home but the real one,
        only the file is used.

        That is also what the vendor does: run with ``HOME`` pointed
        elsewhere, Claude Code's Keychain lookup finds nothing and it falls
        back to the file under that home.

        Unknown is treated as "not real". The cost is a file where a
        Keychain item was wanted; the alternative is a guess that overwrites
        somebody's login.
        """
        actual = self.real_home() if callable(self.real_home) else self.real_home
        if actual is None:
            return False
        try:
            return Path(home).expanduser().resolve() == Path(actual).resolve()
        except OSError:
            return False

    def _single_store(self, block: dict, *, home):
        config = specmod.config_dir(self.spec, home=home, env=self.env)
        kind = block["kind"]

        if kind == "file":
            path = str(block["path"]).replace(
                "{secure_dir}",
                str(secure_dir(self.spec, home=home, env=self.env)))
            return FileStore(
                specmod.expand(path, home=home, config_dir=config),
                specmod.mode_of(block))
        if kind == "keychain":
            return KeychainStore(
                service=service_name(block, config_dir=config, env=self.env),
                account=account_name(block, self.env))
        if kind == "credman":
            return CredmanStore(
                service=service_name(block, config_dir=config, env=self.env),
                account=account_name(block, self.env),
                chunk_size=block.get("chunk_size", 2400))
        raise ValueError(f"Unknown store kind '{kind}' for provider 'claude'.")

    # -- what the bytes mean ----------------------------------------------

    def has_login(self, blob: bytes | None) -> bool:
        token = specmod.pointer(_parse(blob), self.spec["token"]["pointer"])
        return isinstance(token, str) and bool(token.strip())

    def same_login(self, older: bytes | None, newer: bytes | None) -> bool:
        return specmod.same_lineage(self.spec, _parse(older), _parse(newer))

    def liveness(self, blob: bytes | None, *, now_ms: int) -> Liveness:
        if not blob:
            return Liveness(ABSENT)

        block = self.spec["liveness"]
        parsed = _parse(blob)

        # A cleared login keeps its deadline. Checked before the arithmetic
        # because that arithmetic would happily report three weeks left on a
        # credential that cannot sign in at all.
        if specmod.emptied_token(self.spec, parsed):
            return Liveness(SIGNED_OUT)

        expires = specmod.pointer(parsed, block["pointer"])
        if not specmod.finite(expires):
            # The VS Code extension writes credentials without this field.
            # Reporting CLOSED would strand a perfectly good account. A value
            # that is not a usable number is no better known than a missing
            # one.
            return Liveness(UNKNOWN)

        expires = int(expires)
        # Floor rather than truncate, so a window twelve hours past its close
        # reads as one day gone rather than as closing today.
        days = math.floor((expires - now_ms) / MS_PER_DAY)
        if expires <= now_ms:
            state = CLOSED
        elif days <= self.warn_days:
            state = CLOSING
        else:
            state = LIVE
        return Liveness(state, expires_at_ms=expires, days_left=days)

    def identity(self, blob: bytes | None, *, home, profile_dir=None,
                 active: bool = False) -> Identity:
        """Read identity from a file, never from the credential.

        Claude's tokens are opaque, so they carry no identity at all -- ``blob``
        is accepted to satisfy the protocol and deliberately unused.

        Which file depends on whether this profile is the live one.
        ``~/.claude.json`` describes only the account signed in right now, so
        reading it for a parked profile labels every row with the active
        account's email. Parked profiles come from the copy stashed beside
        their credential.
        """
        block = self.spec["identity"]
        if active or profile_dir is None:
            data = _read_json(specmod.expand(block["path"], home=home))
        else:
            data = _read_json(Path(profile_dir) / "account.json")
        return Identity(
            email=specmod.pointer(data, block["email"]),
            display_name=specmod.pointer(data, block["display_name"]),
            org=specmod.pointer(data, block["org"]),
            plan=specmod.pointer(data, block["plan"]),
        )

    # -- what else has to move --------------------------------------------

    def companion_read(self, *, home) -> dict:
        block = self.spec["companion"]
        data = _read_json(specmod.expand(block["path"], home=home))
        return {key: data[key] for key in block["keys"] if key in data}

    def companion_write(self, data: dict, *, home) -> None:
        """Splice the account keys into ``~/.claude.json``, preserving the rest.

        Keys absent from the incoming profile are **deleted** rather than left
        holding the previous account's identity, which would display the wrong
        email after a switch. Claude Code re-fetches them on next start.
        """
        block = self.spec["companion"]
        path = specmod.expand(block["path"], home=home)
        # load_for_write, not _read_json. _read_json answers {} for anything
        # unusable -- right when reading a credential for display, fatal here:
        # splicing two identity keys onto {} and writing it back replaces
        # every project, MCP server and machine ID in the file. Claude Code
        # rewrites this path on its own schedule, so a read landing mid-write
        # is the case to survive, and refusing leaves the switch to be run
        # again rather than silently truncating the user's config.
        config = configjson.load_for_write(path)
        stale = set(block.get("stale_on_switch", ()))
        for key in block["keys"]:
            # Stashed for the card, never restored. A usage cache carried
            # across a switch describes what the account was doing whenever it
            # was last active and would read as current.
            if key in stale:
                config.pop(key, None)
            elif key in data:
                config[key] = data[key]
            else:
                config.pop(key, None)
        try:
            _write_json(path, config)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not write {path}:\n{exc}") from exc


def _parse(blob: bytes | None) -> dict:
    """Parse a credential blob, treating anything unusable as empty.

    A corrupt credential should still let its profile list in the UI, just
    without an expiry -- so this never raises.
    """
    if not blob:
        return {}
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> dict:
    try:
        return _parse(Path(path).read_bytes())
    except OSError:
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomic, owner-only write of a companion file.

    Raises :class:`StoreUnavailableError` rather than ``OSError``:
    ``switcher.switch`` calls ``companion_write`` outside its own ``OSError``
    guard, so a bare one would reach the user as a stderr traceback and look
    like the switch silently did nothing.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".shambles-tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            # A leftover *.shambles-tmp from a crashed run is opened, not
            # created, so O_CREAT's mode argument does not apply to it --
            # fchmod fixes the descriptor itself before the first byte lands.
            # No os.fchmod on Windows; the trailing os.chmod covers that
            # platform and is a harmless no-op elsewhere.
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            os.write(fd, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        raise StoreUnavailableError(f"Could not write {path}:\n{exc}") from exc
