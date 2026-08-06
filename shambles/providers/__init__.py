"""The registry of known providers.

A closed, in-tree set on purpose. There is no plugin loader and no entry-point
discovery: two providers do not justify the indirection, and a switcher that
could load third-party credential handlers would be a poor thing to ask anyone
to trust.
"""

from .base import (ABSENT, CLOSED, CLOSING, LIVE, NEEDS_LOGIN, UNKNOWN,
                   Identity, Liveness, Provider)
from .claude import ClaudeProvider
from .codex import CodexProvider

_REGISTRY = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}


def load(provider_id: str, *, env=None) -> Provider:
    """Build one provider by id."""
    try:
        factory = _REGISTRY[provider_id]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(
            f"Unknown provider '{provider_id}'. Known: {known}.") from None
    return factory(env=env)


def all_providers(*, env=None) -> list[Provider]:
    """Every provider, in stable id order."""
    return [load(key, env=env) for key in sorted(_REGISTRY)]


def ids() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "ABSENT", "CLOSED", "CLOSING", "LIVE", "NEEDS_LOGIN", "UNKNOWN",
    "Identity", "Liveness", "Provider",
    "ClaudeProvider", "CodexProvider",
    "load", "all_providers", "ids",
]
