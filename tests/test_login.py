import ast
import os
import pathlib
import threading

import pytest

from conftest import posix_only
from shambles import login, providers

#: Modules that can put bytes on a wire. None of them belongs in a tool whose
#: security argument is that it only moves files around on one machine.
NETWORK_MODULES = {"socket", "urllib", "requests", "http", "ssl", "ftplib",
                   "telnetlib", "smtplib", "asyncio"}

#: The one exemption, and the single module it buys. Opt-in update checks
#: (off by default) need one GitHub Releases lookup, and it lives in exactly
#: one file so that reviewing the network surface means reading one file.
#: Paths are relative to the repository root so the scan does not depend on
#: where pytest was started from.
ALLOWED_NETWORK_IMPORTS = {
    pathlib.Path("shambles/update_check.py"): {"urllib"},
}

#: Found through an imported module rather than assumed to sit under the
#: working directory, so the scan covers the package the tests actually ran
#: against wherever pytest was started from.
PACKAGE_DIR = pathlib.Path(login.__file__).resolve().parent


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

    # Ten seconds against the fake's thirty-second sleep is the real
    # assertion: it only completes because cancel actually stopped the child.
    assert done.wait(timeout=10)
    assert process.running is False
    assert codes, "the exit callback must still fire for a cancelled login"
    # Deliberately not asserting a non-zero code. terminate() signals the
    # shell wrapping the fake, and what a shell reports after SIGTERM while
    # waiting on a child differs between dash, bash and their versions -- it
    # was 0 on Ubuntu/3.10 and non-zero on 3.12 with the same code under test.
    # The exit code of a stand-in is not the behaviour worth pinning.


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


def _networking_imports(package_dir, allowed):
    """Every networking import under ``package_dir`` the allowlist does not buy.

    ``allowed`` maps a repository-relative file to the module names that one
    file may import; anything else it imports still counts as an offence, so
    the exemption cannot quietly widen into "and whatever else it likes".
    """
    package_dir = pathlib.Path(package_dir).resolve()
    exempt = {(package_dir.parent / path).resolve(): names
              for path, names in allowed.items()}

    offenders = []
    for source in sorted(package_dir.rglob("*.py")):
        permitted = exempt.get(source.resolve(), set())
        named = source.relative_to(package_dir.parent).as_posix()
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            offenders += [
                f"{named}:{node.lineno} imports {name}"
                for name in names
                if name in NETWORK_MODULES and name not in permitted]

    return offenders


def test_the_package_imports_no_networking_module():
    """The README's load-bearing security claim, asserted mechanically.

    Task 9 adds subprocess, which DD-2 permits. It does not add network
    reach, and that is the half the security argument rests on. The one
    exemption is the opt-in update check; see
    :data:`ALLOWED_NETWORK_IMPORTS` and the test below it.
    """
    offenders = _networking_imports(PACKAGE_DIR, ALLOWED_NETWORK_IMPORTS)
    assert offenders == [], "\n".join(offenders)


def test_the_networking_exemption_is_one_file_and_one_module():
    """Stated as its own assertion so widening it is a visible edit here,
    not a quiet addition to a dict somebody skims past."""
    assert ALLOWED_NETWORK_IMPORTS == {
        pathlib.Path("shambles/update_check.py"): {"urllib"}}


def test_the_networking_scan_still_catches_everything_else(tmp_path):
    """A non-vacuous check on the scan above.

    An allowlist is only worth having if the thing it carves an exception out
    of still bites, so this runs the same scan over a fake package: the
    exempted file may import ``urllib`` and nothing more, and its neighbour
    may import neither.
    """
    package = tmp_path / "fake_pkg"
    package.mkdir()
    (package / "exempt.py").write_text(
        "import urllib.request\nimport socket\n", encoding="utf-8")
    (package / "ordinary.py").write_text("import urllib.request\n",
                                         encoding="utf-8")

    offenders = _networking_imports(
        package, {pathlib.Path("fake_pkg/exempt.py"): {"urllib"}})

    assert offenders == ["fake_pkg/exempt.py:2 imports socket",
                         "fake_pkg/ordinary.py:1 imports urllib"]


def _imported_names(source_path):
    """Every name a module imports, as the bare final segment.

    Covers both ``import x.y`` and ``from ..pkg import y`` (relative or not)
    -- ``rsplit(".", 1)[-1]`` collapses ``shambles.switcher`` and
    ``..switcher`` and a bare ``switcher`` down to the same ``"switcher"``,
    which is what a caller actually wants to ban regardless of how the
    import spells its path.
    """
    import ast

    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return {name.rsplit(".", 1)[-1] for name in names if name}


def test_tui_modules_do_not_import_mutation_layers_directly():
    """The terminal UI's screens/widgets talk only to ``ShamblesService``.

    ``switcher``, ``login`` and ``eject`` are the modules that actually touch
    credentials on disk or spawn a vendor process. Nothing under
    ``shambles/app/tui/`` may import any of them directly -- every mutation
    the TUI performs has to go through the service boundary
    (``tests/tui/test_dashboard.py::test_widget_modules_do_not_import_mutation_layers``
    already pins this for ``widgets.py`` and ``dashboard.py``; this covers
    every module in the package, including ``application.py`` and
    ``workflows.py``, which is where a service-bypassing shortcut would most
    plausibly be added next).
    """
    import pathlib

    forbidden = {"switcher", "login", "eject"}
    offenders = []
    for source in sorted(pathlib.Path("shambles/app/tui").glob("*.py")):
        hit = _imported_names(source) & forbidden
        if hit:
            offenders.append(f"{source} imports {sorted(hit)}")

    assert offenders == [], "\n".join(offenders)


def test_launch_module_may_import_login_but_not_switcher_or_eject():
    """``app/launch.py`` is the one documented exception.

    It needs ``login.binary()`` to know which executable to ``execvp`` into
    after Textual hands the terminal back -- see its module docstring -- but
    it must never reach into ``switcher`` or ``eject``, which mutate stored
    credentials rather than just naming a command to run.
    """
    import pathlib

    names = _imported_names(pathlib.Path("shambles/app/launch.py"))
    assert "login" in names, "launch.py should still use login.binary()"
    assert not names & {"switcher", "eject"}


def test_the_ast_import_scan_actually_flags_a_forbidden_import(tmp_path):
    """A non-vacuous check on the two tests above: a fixture module that
    imports a forbidden name must actually be caught, not silently pass
    because the scan itself is a no-op."""
    sneaky = tmp_path / "sneaky.py"
    sneaky.write_text("from .. import switcher\n", encoding="utf-8")
    assert _imported_names(sneaky) & {"switcher", "login", "eject"} == {"switcher"}

    also_sneaky = tmp_path / "also_sneaky.py"
    also_sneaky.write_text("import shambles.eject\n", encoding="utf-8")
    assert _imported_names(also_sneaky) & {"switcher", "login", "eject"} == {"eject"}

    clean = tmp_path / "clean.py"
    clean.write_text("from ..service import ActionResult\n", encoding="utf-8")
    assert _imported_names(clean) & {"switcher", "login", "eject"} == set()


def test_login_process_passes_the_explicit_environment_to_the_child(
        paths, monkeypatch):
    from io import StringIO

    seen = []
    done = threading.Event()
    child_env = {"HOME": str(paths.home), "PATH": "/fake/vendor/bin"}
    monkeypatch.setattr("shambles.login.shutil.which",
                        lambda binary, **kwargs: "/fake/vendor/bin/codex")

    class Child:
        stdout = StringIO("")

        def wait(self):
            return 0

    def popen(argv, **kwargs):
        seen.append(kwargs)
        return Child()

    process = login.LoginProcess(["codex", "login"], env=child_env, popen=popen)
    process.start(on_line=lambda line: None, on_exit=lambda code: done.set())

    assert done.wait(timeout=1)
    assert seen[0]["env"] == child_env


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
@pytest.mark.parametrize("override", [False, True])
def test_login_environment_matches_the_provider_context(
        paths, monkeypatch, provider_id, override):
    from shambles.providers import spec as specmod

    config_key = "CODEX_HOME" if provider_id == "codex" else "CLAUDE_CONFIG_DIR"
    monkeypatch.setenv(config_key, str(paths.home / "unrelated-config"))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_CLIENT_ID", "unrelated-client")
    provider_env = {"USER": "test-user"}
    if override:
        provider_env[config_key] = str(paths.home / "selected-config")
        provider_env["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = ""
    provider = providers.load(provider_id, env=provider_env)
    parent_env = dict(os.environ)

    child_env = login.environment(provider, home=paths.home, platform="linux")

    assert child_env["HOME"] == str(paths.home.resolve())
    assert child_env["USERPROFILE"] == str(paths.home.resolve())
    assert child_env["USER"] == "test-user"
    assert child_env["PATH"] == parent_env["PATH"]
    assert (specmod.config_dir(provider.spec, home=paths.home, env=child_env)
            == specmod.config_dir(provider.spec, home=paths.home, env=provider_env))
    if provider_id == "claude":
        assert "CLAUDE_CODE_OAUTH_CLIENT_ID" not in child_env
        for platform in ("darwin", "win32"):
            expected = provider.store(home=paths.home, platform=platform)
            actual = providers.load("claude", env=child_env).store(
                home=paths.home, platform=platform)
            assert actual.service == expected.service
            assert actual.account == expected.account
    assert dict(os.environ) == parent_env
