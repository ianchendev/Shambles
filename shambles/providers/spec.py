"""Loading provider specs and resolving the pointers inside them.

Specs ship as package data, read through :mod:`importlib.resources` rather than
``__file__``. That matters: this project releases a PyInstaller single-file
binary, where ``__file__`` points inside a temporary extraction directory and
path arithmetic against it is unreliable.
"""

import json
import os
from importlib import resources
from pathlib import Path

SPEC_SUFFIX = ".json"


def load(provider_id: str) -> dict:
    """Read one provider's spec out of package data."""
    source = resources.files(__package__) / f"{provider_id}{SPEC_SUFFIX}"
    return json.loads(source.read_text(encoding="utf-8"))


def available() -> list[str]:
    """Every provider id that ships a spec, sorted for stable ordering."""
    found = []
    for entry in resources.files(__package__).iterdir():
        name = entry.name
        if name.endswith(SPEC_SUFFIX) and not name.startswith(("_", "schema")):
            found.append(name[: -len(SPEC_SUFFIX)])
    return sorted(found)


def pointer(data, path: str, default=None):
    """Follow a dotted path through nested dicts and lists.

    At each dict level the **longest** dot-joined prefix that is actually a key
    wins. That is not fussiness: OpenAI's JWT claims are namespaced URLs, so the
    real key is ``https://api.openai.com/profile`` and the field inside it is
    ``email``. Splitting naively at the first dot would look for a key called
    ``https://api`` and find nothing. Longest-prefix matching lets a spec write
    ``https://api.openai.com/profile.email`` with no escaping.

    A numeric segment indexes a list, which is what lets a spec point at
    ``...organizations.0.title``.
    """
    # An empty pointer is a malformed spec, not a request for the whole
    # document. Returning the root would hand a caller expecting a string an
    # entire config file, and the mistake would surface far from its cause.
    if data is None or not path:
        return default

    current = data
    remaining = path
    while remaining:
        if isinstance(current, dict):
            parts = remaining.split(".")
            for size in range(len(parts), 0, -1):
                candidate = ".".join(parts[:size])
                if candidate in current:
                    current = current[candidate]
                    remaining = ".".join(parts[size:])
                    break
            else:
                return default
        elif isinstance(current, list):
            head, _, remaining = remaining.partition(".")
            try:
                current = current[int(head)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current if current is not None else default


def config_dir(spec: dict, *, home: Path, env=None) -> Path:
    """Where this provider keeps its configuration.

    The environment variable wins when set and non-empty; an empty value is
    treated as unset, matching how both vendors read theirs.
    """
    env = os.environ if env is None else env
    block = spec.get("config_dir") or {}
    override = env.get(block.get("env", ""), "")
    if override:
        return Path(override).expanduser()
    return expand(block.get("default", ""), home=home)


def expand(template: str, *, home: Path, config_dir: Path | None = None) -> Path:
    """Resolve a spec path template against an injectable home.

    ``~`` expands to the *passed* home rather than the real one, which is what
    lets the whole suite run against ``tmp_path`` and never touch a live
    credential.
    """
    text = str(template)
    if config_dir is not None:
        text = text.replace("{config_dir}", str(config_dir))
    if text.startswith("~/"):
        return Path(home) / text[2:]
    if text == "~":
        return Path(home)
    return Path(text)


def store_block(spec: dict, platform: str) -> dict:
    """The store definition for one platform.

    Falls back to the ``"*"`` entry, which is how a provider says "the same
    everywhere" without repeating itself three times.
    """
    stores = spec.get("store") or {}
    block = stores.get(platform) or stores.get("*")
    if block is None:
        raise KeyError(
            f"Provider '{spec.get('id')}' declares no store for platform "
            f"'{platform}'.")
    return block


def mode_of(block: dict, default: int = 0o600) -> int:
    """Parse a spec's octal file mode, written as a string like ``"0600"``."""
    raw = block.get("mode")
    return int(raw, 8) if isinstance(raw, str) else default


_MISSING = object()


def emptied_token(spec: dict, parsed) -> bool:
    """Whether this credential carries a token field that has been emptied.

    Present-but-empty, never merely absent. A vendor clearing a login writes
    ``""`` in place and leaves the expiry, scopes and plan around it intact,
    so the file still looks like a healthy credential to anything that reads
    only the deadline. A partial credential that never carried the field is a
    different thing entirely and is not evidence of anything.
    """
    block = spec.get("token")
    if not block:
        return False
    value = pointer(parsed, block["pointer"], default=_MISSING)
    if value is _MISSING or value is None:
        return False
    return isinstance(value, str) and not value.strip()
