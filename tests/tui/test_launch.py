"""Entrypoint dispatch and same-terminal launch.

``selected_frontend`` decides which frontend a raw ``argv`` selects, before
any package-internal import runs -- which is why it and ``COMMANDS`` live in
``shambles.__main__`` rather than ``shambles.app.cli``: picking "gui" versus
"tui" versus "cli" has to happen before either Tkinter or Textual is
imported. ``replace_process`` is the only place ``execvp`` is called, and
only ever after Textual's ``App.run()`` has returned -- see
``shambles/app/launch.py``. These tests never actually exec anything; every
``execvp`` is a recording fake.
"""

import subprocess
import sys

import pytest

from shambles import login as login_mod
from shambles import providers
from shambles import __main__ as entrypoint
from shambles.__main__ import COMMANDS
from shambles.app.launch import LaunchRequest, replace_process


@pytest.fixture(autouse=True)
def prevent_unexpected_window(monkeypatch):
    def unexpected_window(*args, **kwargs):
        raise AssertionError("Terminal dispatch unexpectedly opened the Tk window")

    monkeypatch.setattr("shambles.gui.run", unexpected_window)


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def selected_frontend(argv):
    return entrypoint.selected_frontend(argv)


# -- replace_process ----------------------------------------------------


def test_launch_replaces_process_with_vendor_command(claude):
    calls = []
    replace_process(LaunchRequest("claude"), providers=[claude],
                    execvp=lambda file, argv: calls.append((file, argv)))
    assert calls == [("claude", ["claude"])]


def test_replace_process_picks_the_matching_provider_among_several(claude, codex):
    """Two providers are registered; the wrong one must never be launched."""
    calls = []
    replace_process(LaunchRequest("codex"), providers=[claude, codex],
                    execvp=lambda file, argv: calls.append((file, argv)))
    assert calls == [("codex", ["codex"])]

    calls.clear()
    replace_process(LaunchRequest("claude"), providers=[codex, claude],
                    execvp=lambda file, argv: calls.append((file, argv)))
    assert calls == [("claude", ["claude"])]


def test_replace_process_rejects_an_unrecognized_provider(claude):
    with pytest.raises(KeyError):
        replace_process(LaunchRequest("nope"), providers=[claude],
                        execvp=lambda file, argv: None)


def test_replace_process_never_builds_a_credential_environment(monkeypatch, claude):
    """``execvp`` is called with only ``(file, argv)`` -- no third argument,
    no keyword, and nothing here ever calls ``login.environment``, which is
    the module that computes Keychain selectors and config-dir overrides for
    the *login* subprocess. The vendor CLI inherits this process's own
    environment untouched."""

    def boom(*args, **kwargs):
        raise AssertionError(
            "replace_process must not construct a credential environment")

    monkeypatch.setattr(login_mod, "environment", boom)

    calls = []
    replace_process(LaunchRequest("claude"), providers=[claude],
                    execvp=lambda file, argv: calls.append((file, argv)))
    assert calls == [("claude", ["claude"])]


def test_replace_process_uses_the_default_execvp_signature():
    """The default ``execvp`` argument is ``os.execvp`` itself -- proven by
    inspecting the default rather than calling it, since calling the real
    ``os.execvp`` would actually replace this test process."""
    import os
    import inspect

    default = inspect.signature(replace_process).parameters["execvp"].default
    assert default is os.execvp


# -- selected_frontend ----------------------------------------------------


def test_bare_command_uses_tui_only_on_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert selected_frontend([]) == "tui"


def test_bare_command_falls_back_to_cli_off_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert selected_frontend([]) == "cli"


def test_bare_command_falls_back_to_cli_with_only_one_tty(monkeypatch):
    """Piped output (e.g. into a pager) makes stdout non-interactive even
    when stdin is still a terminal; the TUI needs both."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert selected_frontend([]) == "cli"


def test_gui_token_always_selects_gui(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert selected_frontend(["gui"]) == "gui"


def test_tui_token_selects_tui_even_off_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert selected_frontend(["tui"]) == "tui"


def test_list_and_switch_tokens_select_cli_even_on_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert selected_frontend(["list"]) == "cli"
    assert selected_frontend(["switch", "claude", "Work"]) == "cli"


def test_no_motion_flag_does_not_defeat_a_bare_interactive_invocation(monkeypatch):
    """``shambles --no-motion`` alone, on a terminal, still opens the TUI --
    it should not be indistinguishable from ``shambles --no-motion`` piped
    into a file, which correctly falls back to printing usage."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert selected_frontend(["--no-motion"]) == "tui"


def test_no_motion_flag_alone_off_a_tty_still_falls_back_to_cli(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert selected_frontend(["--no-motion"]) == "cli"


def test_commands_names_every_recognized_subcommand():
    assert COMMANDS == ("list", "switch", "tui", "gui")


# -- shambles.__main__.main dispatch --------------------------------------


def test_bare_interactive_invocation_dispatches_to_the_tui_subcommand(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    calls = []
    monkeypatch.setattr("shambles.app.cli.main",
                        lambda argv: calls.append(list(argv)) or 0)

    from shambles.__main__ import main
    assert main([]) == 0
    assert calls == [["tui"]]


def test_noninteractive_bare_invocation_prints_help_and_exits_usage(monkeypatch,
                                                                 capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    from shambles.__main__ import main
    from shambles.app.cli import EXIT_USAGE

    assert main([]) == EXIT_USAGE
    assert "usage: shambles" in capsys.readouterr().out


def test_explicit_tui_token_is_passed_through_unmodified(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    calls = []
    monkeypatch.setattr("shambles.app.cli.main",
                        lambda argv: calls.append(list(argv)) or 0)

    from shambles.__main__ import main
    assert main(["tui", "--home", "/tmp/x"]) == 0
    assert calls == [["tui", "--home", "/tmp/x"]]


def test_explicit_gui_token_opens_the_tk_window_directly(monkeypatch):
    calls = []
    monkeypatch.setattr("shambles.gui.run",
                        lambda **kw: calls.append("ran") or 0)

    from shambles.__main__ import main
    assert main(["gui"]) == 0
    assert calls == ["ran"]


def test_list_and_switch_still_go_straight_to_cli(monkeypatch):
    """Unaffected by the tui/gui dispatch changes: unchanged tokens, argv
    passed through untouched."""
    calls = []
    monkeypatch.setattr("shambles.app.cli.main",
                        lambda argv: calls.append(list(argv)) or 0)

    from shambles.__main__ import main
    assert main(["list", "--json"]) == 0
    assert calls == [["list", "--json"]]


# -- shambles.app.cli's own tui dispatch -----------------------------------


def test_cli_tui_command_launches_the_chosen_provider(monkeypatch, home):
    from shambles.app import cli

    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: "codex")
    calls = []
    monkeypatch.setattr(cli, "replace_process",
                        lambda request, **kw: calls.append((request, kw)))

    assert cli.main(["--home", str(home), "tui"]) == cli.EXIT_OK
    assert len(calls) == 1
    request, kwargs = calls[0]
    assert request == LaunchRequest("codex")
    assert {p.id for p in kwargs["providers"]} == {"claude", "codex"}


def test_cli_tui_command_does_not_launch_when_nothing_was_chosen(monkeypatch, home):
    from shambles.app import cli

    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: None)
    calls = []
    monkeypatch.setattr(cli, "replace_process", lambda *a, **k: calls.append((a, k)))

    assert cli.main(["--home", str(home), "tui"]) == cli.EXIT_OK
    assert calls == []


def test_cli_tui_command_defaults_motion_on(monkeypatch, home):
    from shambles.app import cli

    seen = {}
    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: seen.update(kw) or None)

    assert cli.main(["--home", str(home), "tui"]) == cli.EXIT_OK
    assert seen == {"motion": True}


def test_cli_tui_command_honours_no_motion_after_the_subcommand(monkeypatch, home):
    from shambles.app import cli

    seen = {}
    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: seen.update(kw) or None)

    assert cli.main(["--home", str(home), "tui", "--no-motion"]) == cli.EXIT_OK
    assert seen == {"motion": False}


def test_cli_tui_command_honours_no_motion_before_the_subcommand(monkeypatch, home):
    from shambles.app import cli

    seen = {}
    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: seen.update(kw) or None)

    assert cli.main(["--no-motion", "--home", str(home), "tui"]) == cli.EXIT_OK
    assert seen == {"motion": False}


@pytest.mark.parametrize("argv", [
    ["switch", "claude", "gui"],
    ["switch", "claude", "tui"],
    ["--home", "gui", "list"],
    ["--home", "tui", "list"],
])
def test_frontend_words_in_argument_values_do_not_open_a_frontend(argv):
    assert selected_frontend(argv) == "cli"


@pytest.mark.parametrize("stdin_tty,stdout_tty", [(False, True), (True, False)])
def test_bare_command_requires_both_terminal_streams(monkeypatch, stdin_tty,
                                                     stdout_tty):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_tty)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_tty)
    assert selected_frontend([]) == "cli"


def test_bare_no_motion_reaches_tui_with_the_synthetic_home(monkeypatch, home):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    seen = []
    monkeypatch.setattr("shambles.app.tui.application.run_tui",
                        lambda service, **kw: seen.append((service.paths.home, kw)))

    assert entrypoint.main(["--no-motion", "--home", str(home)]) == 0
    assert seen == [(home, {"motion": False})]


def test_vendor_exec_happens_after_the_tui_returns(monkeypatch, home):
    from shambles.app import cli

    events = []

    def run_tui(service, **kwargs):
        assert service.paths.home == home
        events.append("terminal restored")
        return "claude"

    def execvp(file, argv):
        assert events == ["terminal restored"]
        events.append((file, argv))

    monkeypatch.setattr("shambles.app.tui.application.run_tui", run_tui)
    monkeypatch.setattr(cli, "replace_process", lambda request, **kwargs:
                        replace_process(request, execvp=execvp, **kwargs),
                        raising=False)

    assert entrypoint.main(["tui", "--home", str(home)]) == 0
    assert events == ["terminal restored", ("claude", ["claude"])]


def test_a_failed_tui_run_never_launches_a_vendor(monkeypatch, home):
    from shambles.app import cli

    def failed_run(service, **kwargs):
        raise RuntimeError("TUI failed")

    calls = []
    monkeypatch.setattr("shambles.app.tui.application.run_tui", failed_run)
    monkeypatch.setattr(cli, "replace_process", lambda *args, **kw:
                        calls.append(args), raising=False)

    with pytest.raises(RuntimeError, match="TUI failed"):
        entrypoint.main(["tui", "--home", str(home)])
    assert calls == []


@pytest.mark.parametrize("argv,expected_status", [
    ([], 2),
    (["--help"], 0),
    (["--version"], 0),
    (["list", "--json"], 0),
    (["switch", "unknown", "Work", "--json"], 1),
])
def test_headless_commands_do_not_import_either_frontend(home, argv,
                                                        expected_status):
    script = """
import builtins
import sys
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in ('tkinter', 'textual'):
        raise AssertionError('headless command imported ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from shambles.__main__ import main
raise SystemExit(main(sys.argv[1:]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "--home", str(home), *argv],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
