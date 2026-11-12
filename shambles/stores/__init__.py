"""Where credential bytes live, one implementation per platform.

Deliberately not a factory. A provider constructs its own store, because
choosing one needs knowledge only the provider has -- which environment
variable relocates its config, how its service name is templated, what its
account field is called. What lives here is the three ways bytes can be kept,
plus the layering of two of them, and nothing about whose bytes they are.
"""

from .base import CredentialStore, StoreLockedError, StoreUnavailableError
from .credman import CredmanStore
from .fallback import FallbackStore
from .file import FileStore
from .keychain import KeychainStore
from .unsupported import UnsupportedStore

__all__ = [
    "CredentialStore",
    "StoreLockedError",
    "StoreUnavailableError",
    "CredmanStore",
    "FallbackStore",
    "FileStore",
    "KeychainStore",
    "UnsupportedStore",
]
