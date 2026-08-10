"""Codex's credential semantics.

The mirror image of Claude. Its tokens are **JWTs**, so ``auth.json`` is
self-describing: email, plan, organisations, expiry and subscription end date
all come out of one base64 decode. There is no sidecar file, so
:meth:`CodexProvider.companion_read` returns nothing and identity can never
desynchronize from the token the way Claude's can.

The sharp edge is elsewhere. Codex **rotates its refresh token on every use**,
so a stored snapshot dies the moment the live credential refreshes. Restoring a
stale ``auth.json`` does not merely fail -- it presents an already-invalidated
refresh token and the account needs a fresh login. That is what
``policy.rotates`` in the spec exists to signal.
"""

import base64
import binascii
import json
import math
import os
from datetime import datetime, timezone

from ..stores import FileStore, KeychainStore
from . import spec as specmod
from .base import ABSENT, CLOSED, CLOSING, LIVE, UNKNOWN, Identity, Liveness

MS_PER_DAY = 86_400_000


def jwt_claims(token) -> dict:
    """Decode a JWT payload without verifying its signature.

    Verification is deliberately skipped. It would require OpenAI's public keys
    and a network round-trip, and it would answer a question nobody is asking:
    this file is already on the user's own disk, read with their own
    permissions, and nothing here is a security decision. The claims are used
    to display an email and compute a countdown. A forged token would only
    mislabel a row in a list the user themselves populated.
    """
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload)
        claims = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


class CodexProvider:
    def __init__(self, spec=None, env=None):
        self.spec = spec if spec is not None else specmod.load("codex")
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
    def warn_days(self) -> float:
        return float(self.spec["policy"].get("warn_days_floor", 1))

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
            return KeychainStore(service=block["service"],
                                 account=block["account"])
        raise ValueError(f"Unknown store kind '{kind}' for provider 'codex'.")

    # -- what the bytes mean ----------------------------------------------

    def liveness(self, blob: bytes | None, *, now_ms: int) -> Liveness:
        if not blob:
            return Liveness(ABSENT)

        data = _parse(blob)
        block = self.spec["liveness"]
        claims = jwt_claims(specmod.pointer(data, block["pointer"]))
        expires_ms = None

        exp = claims.get(block["claim"])
        if isinstance(exp, (int, float)):
            expires_ms = int(exp) * 1000
        else:
            # No parseable exp: fall back to how long ago the tokens were last
            # refreshed, which is what Codex itself does.
            expires_ms = _fallback_expiry(data, block.get("fallback"))

        if expires_ms is None:
            return Liveness(UNKNOWN)

        days = math.floor((expires_ms - now_ms) / MS_PER_DAY)
        if expires_ms <= now_ms:
            state = CLOSED
        elif days <= self.warn_days:
            state = CLOSING
        else:
            state = LIVE
        return Liveness(state, expires_at_ms=expires_ms, days_left=days)

    def identity(self, blob: bytes | None, *, home, profile_dir=None,
                 active: bool = False) -> Identity:
        """Everything comes out of the id_token.

        ``home``, ``profile_dir`` and ``active`` are all unused, which is the
        point: a self-describing token needs no sidecar and cannot fall out of
        step with the credential it accompanies.
        """
        block = self.spec["identity"]
        claims = jwt_claims(specmod.pointer(_parse(blob), block["pointer"]))
        return Identity(
            email=specmod.pointer(claims, block["email"]),
            display_name=specmod.pointer(claims, block["display_name"]),
            org=specmod.pointer(claims, block["org"]),
            plan=specmod.pointer(claims, block["plan"]),
        )

    # -- what else has to move --------------------------------------------

    def companion_read(self, *, home) -> dict:
        """Nothing. ``auth.json`` is self-contained."""
        return {}

    def companion_write(self, data: dict, *, home) -> None:
        """Nothing to write back."""


def _fallback_expiry(data: dict, fallback) -> int | None:
    if not fallback:
        return None
    stamp = specmod.pointer(data, fallback["pointer"])
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    days = fallback.get("stale_after_days", 8)
    return int(moment.timestamp() * 1000) + days * MS_PER_DAY


def _parse(blob: bytes | None) -> dict:
    if not blob:
        return {}
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
