"""M1: say when a switch did not reach something.

Each check claims only what the vendor's own code shows:

- Codex: ``AuthManager`` loads the stored login once and does not see
  external changes until ``reload()``, which the app-server calls only after
  a login it performed itself; its 401 recovery reloads only when the account
  on disk is the one already running (openai/codex, codex-rs/login/src/auth/
  manager.rs). So any Codex process already running keeps its account.
- Claude Code (2.1.300): the auth-source order puts ``ANTHROPIC_AUTH_TOKEN``
  and ``CLAUDE_CODE_OAUTH_TOKEN`` ahead of the saved login, and its own
  message says ``ANTHROPIC_API_KEY`` "takes precedence over your claude.ai
  login". The rest of the list is diagnose.AUTH_OVERRIDES, sourced in
  docs/token-storage.md.

Nothing here stops, restarts or changes anything. It says what to do.
"""

from shambles import login, providers, reach


def claude():
    return providers.load("claude", env={})


def codex():
    return providers.load("codex", env={})


# -- running programs (login.py: the only module that may spawn) ---------------


def fake_proc(tmp_path, processes):
    root = tmp_path / "proc"
    for pid, argv in processes.items():
        (root / str(pid)).mkdir(parents=True)
        (root / str(pid) / "cmdline").write_bytes(
            b"\0".join(a.encode() for a in argv) + b"\0")
    (root / "self").mkdir(parents=True)
    (root / "stat").write_text("cpu 0\n")
    return root


def test_codex_processes_are_found_by_their_program_not_their_arguments(
        tmp_path):
    root = fake_proc(tmp_path, {
        101: ["/home/u/.vscode/extensions/openai.chatgpt/bin/codex",
              "app-server"],
        102: ["codex"],
        103: ["/usr/bin/node", "/usr/lib/node_modules/@openai/codex/bin/codex.js"],
        104: ["vim", "codex"],
        105: ["/usr/bin/python3", "-m", "shambles"],
    })

    found = login.running_programs("codex", platform="linux", proc=root)

    assert sorted(found) == [
        ["/home/u/.vscode/extensions/openai.chatgpt/bin/codex", "app-server"],
        ["codex"]]


def test_a_process_that_exits_while_being_read_is_skipped(tmp_path):
    root = fake_proc(tmp_path, {201: ["codex"]})
    (root / "202").mkdir()          # no cmdline: gone, or a kernel thread

    assert login.running_programs("codex", platform="linux",
                                  proc=root) == [["codex"]]


def test_macos_lists_programs_with_ps_and_keeps_paths_with_spaces():
    app = ("/Applications/Visual Studio Code.app/Contents/Resources/app/"
           "extensions/openai.chatgpt/bin/codex")
    calls = []

    def ps(argv, **kwargs):
        calls.append(argv)
        field = argv[-1]

        class Done:
            returncode = 0
            stdout = (f"  311 {app}\n  312 /bin/zsh\n" if field == "pid=,comm="
                      else f"  311 {app} app-server\n  312 -zsh\n")
        return Done()

    found = login.running_programs("codex", platform="darwin", run=ps)

    assert found == [[app, "app-server"]]
    assert all(call[0] == "ps" for call in calls)


def test_a_ps_that_fails_means_unknown():
    def broken(argv, **kwargs):
        raise OSError("no ps")

    assert login.running_programs("codex", platform="darwin",
                                  run=broken) is None


def test_where_programs_cannot_be_listed_the_answer_is_unknown():
    assert login.running_programs("codex", platform="win32") is None


# -- after a switch --------------------------------------------------------------


def test_a_running_codex_app_server_is_named_after_a_codex_switch():
    said = reach.after_switch(
        codex(), "Spare", home="/nonexistent", env={},
        running=[["/x/bin/codex", "app-server"]])

    assert said == ["Codex's background service (codex app-server) is still "
                    "running with the account it started with. Restart the "
                    "app that runs it, VS Code for one, to use Spare."]


def test_running_codex_sessions_are_counted():
    said = reach.after_switch(
        codex(), "Spare", home="/nonexistent", env={},
        running=[["codex"], ["/usr/local/bin/codex", "resume"]])

    assert said == ["2 Codex sessions already open stay on the account they "
                    "started with until you restart them."]


def test_nothing_is_said_when_nothing_is_running_or_unknown():
    assert reach.after_switch(codex(), "Spare", home="/nonexistent", env={},
                              running=[]) == []
    assert reach.after_switch(codex(), "Spare", home="/nonexistent", env={},
                              running=None) == []


def test_a_claude_token_in_the_environment_is_named_never_its_value():
    said = reach.after_switch(
        claude(), "Work", home="/nonexistent",
        env={"CLAUDE_CODE_OAUTH_TOKEN": "secret-sentinel"}, running=None)

    assert said == ["CLAUDE_CODE_OAUTH_TOKEN is set here, and Claude Code "
                    "uses it ahead of any saved login, so a terminal started "
                    "from here stays on that token. Unset it to use Work."]
    assert "secret-sentinel" not in " ".join(said)


def test_codex_is_not_told_about_claudes_variables():
    assert reach.after_switch(codex(), "Spare", home="/nonexistent",
                              env={"ANTHROPIC_API_KEY": "x"},
                              running=None) == []


# -- shell start-up files ----------------------------------------------------------


def test_a_shell_file_that_relocates_claude_is_named(tmp_path):
    (tmp_path / ".zshrc").write_text(
        "# CLAUDE_CONFIG_DIR=/old\nexport CLAUDE_CONFIG_DIR=$HOME/.claude-work\n")

    said = reach.after_switch(claude(), "Work", home=tmp_path, env={},
                              running=None)

    assert said == ["~/.zshrc sets CLAUDE_CONFIG_DIR, so a terminal that "
                    "runs it keeps a separate Claude Code login there, which "
                    "this switch does not change."]


def test_a_shell_file_with_a_token_is_named(tmp_path):
    (tmp_path / ".bashrc").write_text("export ANTHROPIC_API_KEY='sk-sentinel'\n")

    said = reach.after_switch(claude(), "Work", home=tmp_path, env={},
                              running=None)

    assert said == ["~/.bashrc sets ANTHROPIC_API_KEY, so a terminal that "
                    "runs it signs Claude Code in with that instead of the "
                    "switched account."]
    assert "sk-sentinel" not in " ".join(said)


def test_fish_and_csh_spellings_count_and_comments_do_not(tmp_path):
    (tmp_path / ".config" / "fish").mkdir(parents=True)
    (tmp_path / ".config" / "fish" / "config.fish").write_text(
        "set -gx CODEX_HOME ~/.codex-work\n")
    (tmp_path / ".profile").write_text("  # export CODEX_HOME=/x\n")

    found = reach.shell_settings(tmp_path, ["CODEX_HOME"])

    assert found == [("CODEX_HOME", "~/.config/fish/config.fish")]


def test_a_variable_already_in_the_environment_is_said_once(tmp_path):
    (tmp_path / ".zshrc").write_text("export CLAUDE_CODE_OAUTH_TOKEN=x\n")

    said = reach.after_switch(claude(), "Work", home=tmp_path,
                              env={"CLAUDE_CODE_OAUTH_TOKEN": "x"},
                              running=None)

    assert len(said) == 1 and said[0].startswith("CLAUDE_CODE_OAUTH_TOKEN is set here")


def test_an_unreadable_shell_file_is_skipped(tmp_path):
    (tmp_path / ".zshrc").mkdir()        # a directory where a file should be

    assert reach.shell_settings(tmp_path, ["CLAUDE_CONFIG_DIR"]) == []


# -- the service says it with the switch; doctor says it any time -------------------


def test_a_codex_switch_says_its_background_service_kept_the_old_account(
        paths, monkeypatch):
    from helpers import make_live_codex_login, make_profile
    from shambles.app.service import ShamblesService

    make_profile(paths, "codex", "Main", email="main@example.test",
                 active=True)
    make_profile(paths, "codex", "Spare", email="spare@example.test")
    make_live_codex_login(paths, email="main@example.test")
    asked = []

    def running(name, **kwargs):
        asked.append(name)
        return [["/x/codex", "app-server"]]

    monkeypatch.setattr(login, "running_programs", running)
    app = ShamblesService(paths=paths,
                          providers=providers.all_providers(env={}),
                          platform="linux")

    result = app.switch("codex", "Spare")

    assert result.ok, result.error
    assert asked == ["codex"]
    assert any("background service" in w for w in result.warnings)


def test_a_claude_switch_does_not_list_processes(paths, monkeypatch):
    """Claude Code re-reads a changed login itself; no process is asked
    about, and nothing is said about running sessions."""
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles.app.service import ShamblesService

    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Dev", email="d@example.test")
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    monkeypatch.setattr(login, "running_programs",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    app = ShamblesService(
        paths=paths, platform="linux",
        providers=providers.all_providers(
            env={"ANTHROPIC_AUTH_TOKEN": "sentinel"}))

    result = app.switch("claude", "Dev")

    assert result.ok, result.error
    assert result.warnings == (
        "ANTHROPIC_AUTH_TOKEN is set here, and Claude Code uses it ahead of "
        "any saved login, so a terminal started from here stays on that "
        "token. Unset it to use Dev.",)


def test_doctor_reports_shell_files_and_running_codex(paths):
    from shambles import diagnose

    (paths.home / ".zshrc").write_text("export CLAUDE_CONFIG_DIR=/x\n")

    found = diagnose.diagnose(
        paths, providers.all_providers(env={}), platform="linux", env={},
        which=lambda name: f"/usr/bin/{name}", wsl=False,
        running=lambda name: [["codex", "app-server"], ["codex"]])
    codes = {(f.provider, f.code): f for f in found}

    shell = codes[("claude", "shell_sets_variable")]
    assert shell.level == diagnose.WARNING
    assert "~/.zshrc sets CLAUDE_CONFIG_DIR" in shell.message
    running = codes[("codex", "codex_running")]
    assert running.level == diagnose.WARNING
    assert "2 Codex processes are running" in running.message
    assert "background service" in running.message
