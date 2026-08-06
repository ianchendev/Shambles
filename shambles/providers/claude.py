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
import unicodedata
from pathlib import Path

from ..stores import CredmanStore, FileStore, KeychainStore
from . import spec as specmod
from .base import ABSENT, CLOSED, CLOSING, LIVE, UNKNOWN, Identity, Liveness

MS_PER_DAY = 86_400_000


def service_name(block: dict, *, config_dir: Path, env) -> str:
    """Reproduce Claude Code's Keychain service-name construction.

    From the shipping binary::

        `Claude Code${OAUTH_FILE_SUFFIX}${"-credentials"}${dirHash}`

    where ``dirHash`` is ``"-"`` plus the first eight hex characters of the
    SHA-256 of the NFC-normalized config directory, present **iff**
    ``CLAUDE_CONFIG_DIR`` is set and ``CLAUDE_SECURESTORAGE_CONFIG_DIR`` is not
    the empty string. The latter is undocumented and is the only way to keep the
    default service name while relocating the config.

    Verified two independent ways: deriving the hash by hand for the default
    config directory gives the same eight characters the CLI was observed to
    use when actually run with that directory set explicitly.
    """
    suppress = env.get(block.get("hash_suppress_env", ""))
    if suppress is not None:
        hashed = bool(suppress)
        source = suppress or str(config_dir)
    else:
        hashed = bool(env.get(spec_env_name(block), ""))
        source = str(config_dir)

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


def account_name(block: dict, env) -> str:
    """``$USER``, or a fixed fallback for names the vendor refuses.

    Claude Code substitutes ``claude-code-user`` for any username outside
    ``[A-Za-z0-9._-]``, and uses that literal unconditionally on Windows.
    """
    if "account" in block:
        return block["account"]
    import re
    name = env.get(block.get("account_env", "USER"), "")
    pattern = block.get("account_pattern")
    if not name or (pattern and not re.match(pattern, name)):
        return block.get("account_fallback", "claude-code-user")
    return name


class ClaudeProvider:
    def __init__(self, spec=None, env=None):
        self.spec = spec if spec is not None else specmod.load("claude")
        self.env = os.environ if env is None else env

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

    # -- where the bytes live ---------------------------------------------

    def store(self, *, home, platform: str):
        block = specmod.store_block(self.spec, platform)
        config = specmod.config_dir(self.spec, home=home, env=self.env)
        kind = block["kind"]

        if kind == "file":
            return FileStore(
                specmod.expand(block["path"], home=home, config_dir=config),
                specmod.mode_of(block))
        if kind == "keychain":
            return KeychainStore(
                service=service_name(block, config_dir=config, env=self.env),
                account=account_name(block, self.env))
        if kind == "credman":
            return CredmanStore(
                service=service_name(block, config_dir=config, env=self.env),
                account=account_name(block, self.env),
                chunk_size=block.get("chunk_size", 2000))
        raise ValueError(f"Unknown store kind '{kind}' for provider 'claude'.")

    # -- what the bytes mean ----------------------------------------------

    def liveness(self, blob: bytes | None, *, now_ms: int) -> Liveness:
        if not blob:
            return Liveness(ABSENT)

        block = self.spec["liveness"]
        expires = specmod.pointer(_parse(blob), block["pointer"])
        if not isinstance(expires, (int, float)):
            # The VS Code extension writes credentials without this field.
            # Reporting CLOSED would strand a perfectly good account.
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

    def identity(self, blob: bytes | None, *, home) -> Identity:
        """Read identity from the sidecar, not from the credential.

        The credential is opaque, so it carries no identity at all. ``blob`` is
        accepted to satisfy the protocol and deliberately unused.
        """
        block = self.spec["identity"]
        data = _read_json(specmod.expand(block["path"], home=home))
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
        config = _read_json(path)
        for key in block["keys"]:
            if key in data:
                config[key] = data[key]
            else:
                config.pop(key, None)
        _write_json(path, config)


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".shambles-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
