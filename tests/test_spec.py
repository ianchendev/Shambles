"""Spec loading and pointer resolution.

The pointer cases below are not hypothetical. OpenAI namespaces its JWT claims
as URLs, so the key really is ``https://api.openai.com/profile`` with ``email``
inside it -- and a resolver that split on the first dot would go looking for a
key called ``https://api``.
"""

import pytest

from shambles import providers
from shambles.providers import spec


@pytest.mark.parametrize("path, expected", [
    ("a", 1),
    ("b.c", 2),
    ("b.d.e", 3),
    ("list.0", "first"),
    ("list.1", "second"),
    ("nested.0.name", "inner"),
])
def test_pointer_walks_dicts_and_lists(path, expected):
    data = {
        "a": 1,
        "b": {"c": 2, "d": {"e": 3}},
        "list": ["first", "second"],
        "nested": [{"name": "inner"}],
    }
    assert spec.pointer(data, path) == expected


def test_pointer_prefers_the_longest_key_that_actually_exists():
    """A namespaced claim resolves whole, without escaping."""
    data = {"https://api.openai.com/profile": {"email": "a@example.com"}}
    assert spec.pointer(
        data, "https://api.openai.com/profile.email") == "a@example.com"


def test_pointer_reaches_into_a_list_inside_a_namespaced_claim():
    data = {"https://api.openai.com/auth": {
        "organizations": [{"title": "Personal"}, {"title": "Work"}]}}
    assert spec.pointer(
        data, "https://api.openai.com/auth.organizations.1.title") == "Work"


@pytest.mark.parametrize("path", [
    "missing", "a.missing", "list.9", "list.notanumber", "a.b.c", "",
])
def test_pointer_returns_the_default_rather_than_raising(path):
    data = {"a": 1, "list": ["first"]}
    assert spec.pointer(data, path, default="fallback") == "fallback"


def test_pointer_on_nothing_is_the_default():
    assert spec.pointer(None, "a.b", default=7) == 7


def test_expand_resolves_tilde_against_the_injected_home(tmp_path):
    """Never the real home. This is what keeps the suite off live credentials."""
    assert spec.expand("~/.claude.json", home=tmp_path) == tmp_path / ".claude.json"
    assert spec.expand("~", home=tmp_path) == tmp_path


def test_expand_substitutes_the_config_dir(tmp_path):
    assert spec.expand("{config_dir}/auth.json", home=tmp_path,
                       config_dir=tmp_path / ".codex") == tmp_path / ".codex/auth.json"


def test_config_dir_prefers_the_environment_override(tmp_path):
    definition = {"config_dir": {"env": "X_HOME", "default": "~/.thing"}}
    assert spec.config_dir(definition, home=tmp_path,
                           env={"X_HOME": str(tmp_path / "elsewhere")}) == \
        tmp_path / "elsewhere"


def test_an_empty_environment_override_counts_as_unset(tmp_path):
    """Both vendors treat an empty value as absent, so this must too."""
    definition = {"config_dir": {"env": "X_HOME", "default": "~/.thing"}}
    assert spec.config_dir(definition, home=tmp_path,
                           env={"X_HOME": ""}) == tmp_path / ".thing"


def test_store_block_falls_back_to_the_wildcard():
    definition = {"id": "x", "store": {"*": {"kind": "file"}}}
    assert spec.store_block(definition, "win32")["kind"] == "file"


def test_store_block_prefers_an_exact_platform_match():
    definition = {"id": "x", "store": {
        "*": {"kind": "file"}, "darwin": {"kind": "keychain"}}}
    assert spec.store_block(definition, "darwin")["kind"] == "keychain"


def test_a_provider_with_no_store_for_a_platform_says_so():
    with pytest.raises(KeyError, match="declares no store"):
        spec.store_block({"id": "x", "store": {"linux": {}}}, "darwin")


def test_mode_is_parsed_as_octal():
    assert spec.mode_of({"mode": "0600"}) == 0o600
    assert spec.mode_of({"mode": "0644"}) == 0o644
    assert spec.mode_of({}) == 0o600


def test_specs_ship_as_package_data():
    """Guards the packaging: a spec that does not ship makes every provider
    fail to load at runtime, in a binary that built and smoke-tested green."""
    assert "claude" in spec.available()
    assert "codex" in spec.available()


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
def test_every_spec_declares_what_the_loader_requires(provider_id):
    definition = spec.load(provider_id)
    for key in ("id", "display_name", "config_dir", "store", "liveness",
                "identity", "policy", "login"):
        assert key in definition, f"{provider_id} spec is missing '{key}'"
    assert definition["id"] == provider_id
    assert isinstance(definition["policy"]["rotates"], bool)
    assert isinstance(definition["policy"]["warn_days"], int)
    assert definition["login"]["hint"].strip()


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
def test_every_spec_records_how_far_it_was_verified(provider_id):
    """Uncertainty is data, not a footnote. A consumer has to be able to tell
    which claims rest on one sample or on source reading alone."""
    provenance = spec.load(provider_id)["provenance"]
    assert provenance["platforms_executed"]
    assert "platforms_from_source_only" in provenance


@pytest.mark.parametrize("provider_id, binary, command", [
    ("claude", "claude", ["claude", "auth", "login"]),
    ("codex", "codex", ["codex", "login"]),
])
def test_every_provider_declares_how_to_log_in(provider_id, binary, command):
    provider = providers.load(provider_id)
    assert provider.login_binary() == binary
    assert provider.login_command() == command


def test_login_command_starts_with_the_binary():
    """The binary is what gets probed on PATH; argv[0] must be the same thing,
    or availability and execution would disagree."""
    for provider in providers.all_providers():
        assert provider.login_command()[0] == provider.login_binary()


def test_companion_write_failure_is_a_shambles_error(tmp_path, monkeypatch):
    """_write_json backs companion_write, which switcher.switch calls outside
    its OSError guard. An unguarded failure there is a raw traceback."""
    from shambles.errors import ShamblesError
    claude = providers.load("claude")

    def refuse(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("shambles.providers.claude._write_json", refuse)
    with pytest.raises(ShamblesError):
        claude.companion_write({"oauthAccount": {}}, home=tmp_path)
