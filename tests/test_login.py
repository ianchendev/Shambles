import threading

import pytest

from conftest import posix_only
from shambles import login, providers


@pytest.fixture
def codex():
    return providers.load("codex")


def test_the_command_comes_from_the_spec(codex):
    assert login.command(codex) == ["codex", "login"]


def test_an_email_is_appended_only_when_the_provider_supports_it(codex):
    claude = providers.load("claude")
    assert login.command(claude, email="a@example.com") == \
        ["claude", "auth", "login", "--email", "a@example.com"]
    # Codex declares no email flag; the address is silently not passed rather
    # than guessed at.
    assert login.command(codex, email="a@example.com") == ["codex", "login"]


@posix_only
def test_availability_follows_path(codex, fake_vendor):
    assert login.available(codex) is False
    fake_vendor("codex")
    assert login.available(codex) is True


@posix_only
def test_a_successful_login_reports_exit_zero_and_its_output(codex, fake_vendor):
    fake_vendor("codex", lines=("Visit https://example.test/auth", "Signed in"))
    lines, done = [], threading.Event()
    codes = []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lines.append,
                  on_exit=lambda code: (codes.append(code), done.set()))

    assert done.wait(timeout=10), "login process never finished"
    assert codes == [0]
    assert "Visit https://example.test/auth" in lines


@posix_only
def test_a_failed_login_reports_its_exit_code(codex, fake_vendor):
    fake_vendor("codex", exit_code=1, lines=("could not reach the server",))
    done, codes = threading.Event(), []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lambda _line: None,
                  on_exit=lambda code: (codes.append(code), done.set()))

    assert done.wait(timeout=10)
    assert codes == [1]


@posix_only
def test_cancelling_terminates_the_child(codex, fake_vendor):
    """A user who closes the dialog must not leave a vendor process holding a
    callback port open."""
    fake_vendor("codex", linger=30)
    done, codes = threading.Event(), []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lambda _line: None,
                  on_exit=lambda code: (codes.append(code), done.set()))
    process.cancel(grace=2.0)

    assert done.wait(timeout=10)
    assert process.running is False
    assert codes and codes[0] != 0


def test_a_missing_binary_raises_a_readable_error(codex, monkeypatch):
    monkeypatch.setenv("PATH", "")
    process = login.LoginProcess(login.command(codex))
    with pytest.raises(login.LoginUnavailableError) as caught:
        process.start(on_line=lambda _line: None, on_exit=lambda _code: None)
    assert "codex" in str(caught.value)


def test_the_error_reads_as_prose_not_a_traceback(codex, monkeypatch):
    """The GUI renders str(exc) straight into a dialog."""
    from shambles.errors import ShamblesError
    monkeypatch.setenv("PATH", "")
    process = login.LoginProcess(login.command(codex))
    with pytest.raises(ShamblesError) as caught:
        process.start(on_line=lambda _line: None, on_exit=lambda _code: None)
    message = str(caught.value)
    assert "Traceback" not in message
    # Sentences, not a repr. It may open with a lowercase command name --
    # "codex is not installed" is correct prose, and capitalising a binary
    # would be wrong.
    assert message.rstrip().endswith(".")
    assert "  " not in message.replace("\n\n", "")
    assert "Shambles does not sign you in itself" in message


def test_the_package_imports_no_networking_module():
    """The README's load-bearing security claim, asserted mechanically.

    Task 9 adds subprocess, which DD-2 permits. It does not add network
    reach, and that is the half the security argument rests on.
    """
    import ast
    import pathlib

    banned = {"socket", "urllib", "requests", "http", "ssl", "ftplib",
              "telnetlib", "smtplib", "asyncio"}
    offenders = []
    for source in pathlib.Path("shambles").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            offenders += [f"{source}:{node.lineno} imports {name}"
                          for name in names if name in banned]

    assert offenders == [], "\n".join(offenders)
