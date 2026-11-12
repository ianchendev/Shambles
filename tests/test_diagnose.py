"""What ``shambles doctor`` says, and when.

Each case here is a way a switch can report success and change nothing. The
checks are looks, never changes, so every test also has nothing to clean up.
"""

import json

import pytest

from shambles import diagnose, providers
from shambles.app import cli
from shambles.diagnose import INFO, PROBLEM, WARNING
from shambles.providers.codex import CodexProvider


def run(paths, *, env=None, platform="linux", which=None, wsl=False,
        only=None):
    env = env or {}
    found = diagnose.diagnose(
        paths,
        [providers.load("claude", env=env),
         CodexProvider(env=env, system_root=paths.home / "root")],
        platform=platform, env=env, wsl=wsl,
        which=which or (lambda name: f"/usr/local/bin/{name}"))
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
