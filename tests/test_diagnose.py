"""What ``shambles doctor`` says, and when.

Each case here is a way a switch can report success and change nothing. The
checks are looks, never changes, so every test also has nothing to clean up.
"""

import json
import sys

import pytest

from shambles import diagnose, providers
from shambles.app import cli
from shambles.diagnose import INFO, PROBLEM, WARNING
from shambles.providers.codex import CodexProvider
from shambles.stores.base import StoreUnavailableError
from tests.fakes import FakeCredman


def run(paths, *, env=None, platform="linux", which=None, wsl=False,
        only=None, credman=None):
    env = env or {}
    found = diagnose.diagnose(
        paths,
        [providers.load("claude", env=env),
         CodexProvider(env=env, system_root=paths.home / "root")],
        platform=platform, env=env, wsl=wsl,
        which=which or (lambda name: f"/usr/local/bin/{name}"),
        credman=FakeCredman() if credman is None else credman)
    return [f for f in found if only is None or f.code == only]


def codes(findings):
    return {(f.provider, f.code, f.level) for f in findings}


def test_a_plain_linux_machine_has_nothing_wrong(paths):
    found = run(paths)
    assert not [f for f in found if f.level != INFO]
    assert ("claude", "store", INFO) in codes(found)
    assert ("codex", "store", INFO) in codes(found)


def test_it_names_where_each_login_is_kept(paths):
    stores = {f.provider: f.message for f in run(paths, only="store")}
    assert str(paths.home / ".claude" / ".credentials.json") in stores["claude"]
    assert str(paths.home / ".codex" / "auth.json") in stores["codex"]


@pytest.mark.parametrize("variable, provider", [
    ("ANTHROPIC_API_KEY", "claude"),
    ("ANTHROPIC_AUTH_TOKEN", "claude"),
    ("CLAUDE_CODE_OAUTH_TOKEN", "claude"),
    ("CLAUDE_CODE_USE_BEDROCK", "claude"),
    ("CODEX_ACCESS_TOKEN", "codex"),
    ("CODEX_API_KEY", "codex"),
])
def test_a_login_supplied_by_the_environment_is_a_problem(
        paths, variable, provider):
    """The vendor ignores its stored login when one of these is set, so a
    switch succeeds and the same account keeps answering."""
    found = run(paths, env={variable: "x"}, only="auth_override")
    assert [(f.provider, f.level) for f in found] == [(provider, PROBLEM)]
    assert variable in found[0].message and "Unset" in found[0].message


def test_an_empty_override_variable_is_not_an_override(paths):
    assert run(paths, env={"ANTHROPIC_API_KEY": ""}, only="auth_override") == []


def test_the_windows_install_reached_from_wsl_is_a_problem(paths):
    """WSL appends the Windows PATH to its own. With nothing installed
    inside the distribution, ``claude`` resolves to the Windows program,
    whose login lives in the Windows profile -- somewhere a switch made in
    this Linux home never reaches."""
    def which(name):
        if name == "claude":
            return "/mnt/c/Users/example/.local/bin/claude.exe"
        return "/usr/local/bin/codex"

    found = run(paths, which=which, wsl=True, only="vendor_is_windows_install")
    assert [(f.provider, f.level) for f in found] == [("claude", PROBLEM)]
    assert "Install Claude Code inside WSL" in found[0].message
    # The same path on a machine that is not WSL is just a path.
    assert run(paths, which=which, wsl=False,
               only="vendor_is_windows_install") == []


@pytest.mark.parametrize("path, expected", [
    ("/mnt/c/Users/example/.local/bin/claude.exe", True),
    ("/mnt/c/Program Files/nodejs/claude", True),
    ("/mnt/d/tools/codex.cmd", True),
    ("/home/example/.local/bin/claude", False),
    ("/usr/local/bin/codex", False),
    ("/mnt/wsl/shared/claude", False),
    ("/mnt/data/bin/claude", False),
    (None, False),
])
def test_telling_a_windows_program_from_a_linux_one(path, expected):
    assert diagnose.is_windows_binary_under_wsl(path) is expected


def test_wsl_is_said_once_so_the_boundary_is_not_a_surprise(paths):
    found = run(paths, wsl=True, only="wsl")
    assert len(found) == 1 and found[0].level == INFO
    assert run(paths, wsl=False, only="wsl") == []


def test_wsl_is_recognised_from_the_kernel_string(tmp_path):
    version = tmp_path / "version"
    version.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2\n")
    assert diagnose.is_wsl({}, proc_version=str(version))
    version.write_text("Linux version 6.8.0-generic\n")
    assert not diagnose.is_wsl({}, proc_version=str(version))
    assert diagnose.is_wsl({"WSL_DISTRO_NAME": "Ubuntu"},
                           proc_version=str(tmp_path / "missing"))


def test_a_missing_vendor_program_is_a_warning_not_a_problem(paths):
    """Saved accounts still switch; only adding one needs the program."""
    found = run(paths, which=lambda name: None, only="vendor_missing")
    assert {(f.provider, f.level) for f in found} == {
        ("claude", WARNING), ("codex", WARNING)}


def test_codex_in_keyring_mode_is_a_problem_with_the_fix_in_it(paths):
    (paths.home / ".codex").mkdir()
    (paths.home / ".codex" / "config.toml").write_text(
        'cli_auth_credentials_store = "keyring"\n', encoding="utf-8")
    found = run(paths, only="store_unsupported")
    assert [(f.provider, f.level) for f in found] == [("codex", PROBLEM)]
    assert 'cli_auth_credentials_store = "file"' in found[0].message


def test_a_moved_config_directory_is_explained(paths):
    alt = paths.home / "alt"
    alt.mkdir()
    found = run(paths, env={"CLAUDE_CONFIG_DIR": str(alt)},
                only="config_dir_override")
    assert [(f.provider, f.level) for f in found] == [("claude", WARNING)]
    assert "VS Code" in found[0].message


def test_a_relative_config_directory_cannot_be_followed(paths):
    found = run(paths, env={"CLAUDE_CONFIG_DIR": "alt"},
                only="config_dir_relative")
    assert [(f.provider, f.level) for f in found] == [("claude", PROBLEM)]


def test_a_codex_home_that_does_not_exist_stops_codex_itself(paths):
    found = run(paths, env={"CODEX_HOME": str(paths.home / "nowhere")},
                only="config_dir_missing")
    assert [(f.provider, f.level) for f in found] == [("codex", PROBLEM)]


def test_a_mac_whose_login_is_in_the_file_is_told_so(paths):
    """Not a fault: it is where Claude Code puts the login when the
    Keychain refuses, and saying so explains why the Keychain looks empty."""
    from shambles.stores import FallbackStore, FileStore

    class Empty:
        def read(self):
            return None

        def describe(self):
            return "macOS Keychain item 'Claude Code-credentials'"

    file_store = FileStore(paths.home / ".claude" / ".credentials.json")
    file_store.write(b"{}")

    class Provider:
        id = "claude"
        display_name = "Claude Code"
        spec = {}

        def store(self, *, home, platform):
            return FallbackStore(Empty(), file_store)

        def login_binary(self):
            return "claude"

    found = diagnose.diagnose(paths, [Provider()], platform="darwin", env={},
                              which=lambda name: "/usr/local/bin/claude")
    assert ("claude", "store_fallback_in_use", INFO) in codes(found)


def test_problems_come_first(paths):
    found = run(paths, env={"ANTHROPIC_API_KEY": "x"}, wsl=True)
    assert found[0].level == PROBLEM
    assert [f.level for f in found] == sorted(
        (f.level for f in found),
        key=[PROBLEM, WARNING, INFO].index)


def test_doctor_checks_and_changes_nothing(paths):
    before = sorted(p for p in paths.home.rglob("*"))
    run(paths, env={"ANTHROPIC_API_KEY": "x"}, wsl=True)
    assert sorted(p for p in paths.home.rglob("*")) == before


# -- the command ----------------------------------------------------------------


@pytest.fixture
def quiet_environment(monkeypatch):
    for variables in diagnose.AUTH_OVERRIDES.values():
        for variable, _what in variables:
            monkeypatch.delenv(variable, raising=False)
    for variable in ("CLAUDE_CONFIG_DIR", "CODEX_HOME",
                     "CLAUDE_SECURESTORAGE_CONFIG_DIR"):
        monkeypatch.delenv(variable, raising=False)


def test_doctor_exits_zero_and_says_so_when_nothing_is_wrong(
        paths, capsys, quiet_environment, monkeypatch):
    monkeypatch.setattr(diagnose, "is_wsl", lambda env=None, **kw: False)
    monkeypatch.setattr(diagnose.shutil, "which", lambda name: f"/bin/{name}")
    assert cli.main(["doctor", "--home", str(paths.home)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "No problems found." in out


def test_doctor_exits_non_zero_on_a_problem_and_prints_it(
        paths, capsys, quiet_environment, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
    assert cli.main(["doctor", "--home", str(paths.home)]) == cli.EXIT_FAILED
    out = capsys.readouterr().out
    assert "PROBLEM [claude]" in out and "ANTHROPIC_API_KEY" in out
    assert "sk-not-a-real-key" not in out, "a credential was printed"


def test_doctor_json_is_one_object_a_program_can_read(
        paths, capsys, quiet_environment, monkeypatch):
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "x")
    assert cli.main(["doctor", "--json", "--home", str(paths.home)]) == cli.EXIT_FAILED
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert {"level", "provider", "code", "message"} <= set(payload["findings"][0])
    assert any(f["code"] == "auth_override" and f["provider"] == "codex"
               for f in payload["findings"])


# -- what Shambles 2.1.2 and older left in Credential Manager -----------------

OLD = "Claude Code-credentials/claude-code-user"


def left_by_2_1_2(backend, service="Claude Code-credentials", pieces=2):
    """What 2.1.2 wrote on a switch: raw pieces, then a bare count."""
    base = f"{service}/claude-code-user"
    for index in range(pieces):
        backend.write(f"{base}#{index}", b'{"claudeAiOauth": "piece"}')
    backend.write(f"{base}#m", str(pieces).encode("ascii"))
    return base


def test_entries_left_by_2_1_2_are_reported_on_windows(paths):
    backend = FakeCredman()
    left_by_2_1_2(backend)
    before = dict(backend.entries)

    found = run(paths, platform="win32", credman=backend,
                only="credman_leftovers")

    assert [(f.provider, f.level) for f in found] == [("claude", WARNING)]
    message = found[0].message
    for name in (f"{OLD}#0", f"{OLD}#1", f"{OLD}#m"):
        assert f"  {name}\n" in message
    assert "has not changed or deleted anything" in message
    assert "safe to delete once no copy of Shambles 2.1.2 or older" in message
    assert f"Do not remove '{OLD}' itself" in message
    assert backend.entries == before, "doctor must only look"


def test_they_are_not_a_problem(paths):
    """Switching works with them there, so doctor still exits 0."""
    backend = FakeCredman()
    left_by_2_1_2(backend)
    found = run(paths, platform="win32", credman=backend)
    assert not [f for f in found if f.level == PROBLEM]


def test_claude_codes_own_entries_are_not_reported(paths):
    """A single entry, or pieces with Claude Code's JSON count, are its login."""
    backend = FakeCredman()
    backend.write(OLD, b'{"claudeAiOauth": {}}')
    backend.write("Claude Code-credentials-0123abcd/claude-code-user#0", b"QUJD")
    backend.write("Claude Code-credentials-0123abcd/claude-code-user#m",
                  b'{"n":1,"l":4}')
    assert run(paths, platform="win32", credman=backend,
               only="credman_leftovers") == []


def test_a_write_under_way_is_not_reported(paths):
    """A ``#p`` marker means pieces are being written by somebody now."""
    backend = FakeCredman()
    base = left_by_2_1_2(backend)
    backend.write(base + "#p", b"2")
    assert run(paths, platform="win32", credman=backend,
               only="credman_leftovers") == []


def test_every_service_name_2_1_2_could_have_used_is_found(paths):
    backend = FakeCredman()
    left_by_2_1_2(backend, "Claude Code-credentials-0123abcd", pieces=1)
    left_by_2_1_2(backend, "Claude Code-custom-oauth-credentials", pieces=3)
    left_by_2_1_2(backend, "Claude Code-staging-credentials", pieces=1)
    backend.write("Other/claude-code-user#m", b"1")

    message = run(paths, platform="win32", credman=backend,
                  only="credman_leftovers")[0].message

    assert "holds 6 entries" in message
    assert "Claude Code-credentials-0123abcd/claude-code-user#0" in message
    assert "Claude Code-custom-oauth-credentials/claude-code-user#2" in message
    assert "staging" not in message and "Other/" not in message


def test_pieces_are_listed_in_order_and_the_count_last(paths):
    backend = FakeCredman()
    left_by_2_1_2(backend, pieces=11)
    message = run(paths, platform="win32", credman=backend,
                  only="credman_leftovers")[0].message
    listed = [line.strip() for line in message.splitlines()
              if line.startswith("  ")]
    assert listed == [f"{OLD}#{i}" for i in range(11)] + [f"{OLD}#m"]


@pytest.mark.parametrize("count", [b"0", b"-1", b"2x", b"", b"\xff", b"999"])
def test_a_count_2_1_2_could_not_have_written_is_not_reported(paths, count):
    backend = FakeCredman()
    backend.write(OLD + "#0", b"piece")
    backend.write(OLD + "#m", count)
    assert run(paths, platform="win32", credman=backend,
               only="credman_leftovers") == []


def test_nothing_is_looked_for_off_windows(paths):
    backend = FakeCredman()
    left_by_2_1_2(backend)
    for platform in ("linux", "darwin"):
        found = run(paths, platform=platform, credman=backend)
        assert not [f for f in found if f.code.startswith("credman")]


def test_a_credential_manager_that_cannot_be_listed_is_said_plainly(paths):
    class Refusing(FakeCredman):
        def targets(self, prefix):
            raise StoreUnavailableError("access denied (error 5)")

    found = run(paths, platform="win32", credman=Refusing())
    unchecked = [f for f in found if f.code == "credman_leftovers_unchecked"]
    assert [(f.provider, f.level) for f in unchecked] == [("claude", INFO)]
    assert "access denied" in unchecked[0].message


@pytest.mark.skipif(sys.platform == "win32", reason="needs a system without advapi32")
def test_without_credential_manager_doctor_says_so_instead_of_failing(paths):
    found = diagnose.diagnose(
        paths, [providers.load("claude", env={})], platform="win32", env={},
        wsl=False, which=lambda name: None)
    assert "credman_leftovers_unchecked" in {f.code for f in found}

