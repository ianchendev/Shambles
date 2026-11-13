"""The suite never reaches a real login, whatever the shell exports.

Several tests build providers from the process environment, and a provider
reads CLAUDE_CONFIG_DIR, CLAUDE_SECURESTORAGE_CONFIG_DIR and CODEX_HOME to
decide where the live login is. Exported in a developer's shell, those would
point a test's switch at that developer's real credential, which is the one
thing this project's tests must never do. conftest clears them.
"""

import os

import pytest

from shambles import providers

VENDOR_LOCATIONS = ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR",
                    "CODEX_HOME")


@pytest.mark.parametrize("name", VENDOR_LOCATIONS)
def test_no_vendor_location_reaches_a_test(name):
    assert name not in os.environ


def test_a_provider_built_from_the_environment_stays_in_the_test_home(paths):
    for provider in providers.all_providers():
        path = getattr(provider.store(home=paths.home, platform="linux"),
                       "path", None)
        assert path is None or paths.home in path.parents, (provider.id, path)
