"""``shambles config``, and the cached update line ``--version`` may add.

Two halves of one promise. The setting that decides whether Shambles may talk
to the internet has to be reachable from a shell -- a feature nobody can find
is not opt-in, it is off -- and reading or printing it must never be the thing
that does the talking.

``--version`` gets the hardest version of that rule. It is the command a
script runs to ask "is this installed, and which one?", and
:data:`shambles.update_check.TIMEOUT_S` bounds one socket operation rather
than the whole lookup, so a fetch in front of it could stall an install check
for as long as DNS, connect and read take to each give up in turn. It
therefore reads the cache some earlier run wrote and stops there. The
subprocess test below is the load-bearing one: it proves the networking stack
is never so much as imported on that path.
"""

import json
import pathlib
import subprocess
import sys

import pytest

import shambles
from shambles import settings, update_check
from shambles.app import cli
from shambles.paths import Paths

REPO = str(pathlib.Path(shambles.__file__).resolve().parent.parent)


def enabled(home):
    return settings.update_check_enabled(Paths.for_home(home))


def cache_path(home):
    return Paths.for_home(home).library_dir / update_check.CACHE_NAME


def seed_cache(home, *, latest, checked_at=1_000):
    """Put a tag on disk as though some earlier run had looked one up."""
    paths = Paths.for_home(home)
    paths.ensure_store()
    (paths.library_dir / update_check.CACHE_NAME).write_text(
        json.dumps({"checked_at": checked_at, "latest": latest}),
        encoding="utf-8")


# -- config get / set --------------------------------------------------------

def test_a_fresh_home_reports_the_check_as_off(home, capsys):
    """The privacy default, asked the way a user would ask it."""
    assert cli.main(["config", "get", "update.check", "--home", str(home)]) \
        == cli.EXIT_OK
    assert capsys.readouterr().out == "false\n"


def test_turning_the_check_on_and_reading_it_back_round_trips(home, capsys):
    assert cli.main(["config", "set", "update.check", "true",
                     "--home", str(home)]) == cli.EXIT_OK
    assert enabled(home) is True
    capsys.readouterr()

    assert cli.main(["config", "get", "update.check", "--home", str(home)]) \
        == cli.EXIT_OK
    assert capsys.readouterr().out == "true\n"


def test_turning_the_check_off_again_round_trips_too(home, capsys):
    settings.set_update_check(Paths.for_home(home), True)
    assert cli.main(["config", "set", "update.check", "false",
                     "--home", str(home)]) == cli.EXIT_OK
    assert enabled(home) is False
    capsys.readouterr()

    assert cli.main(["config", "get", "update.check", "--home", str(home)]) \
        == cli.EXIT_OK
    assert capsys.readouterr().out == "false\n"


def test_what_get_prints_is_what_set_accepts(home, capsys):
    """The two halves speak the same word, so a value read out of one command
    can be piped straight back into the other without translation."""
    cli.main(["config", "set", "update.check", "true", "--home", str(home)])
    capsys.readouterr()
    cli.main(["config", "get", "update.check", "--home", str(home)])
    printed = capsys.readouterr().out.strip()

    assert cli.main(["config", "set", "update.check", printed,
                     "--home", str(home)]) == cli.EXIT_OK
    assert enabled(home) is True


def test_turning_it_on_says_what_the_user_just_agreed_to(home, capsys):
    """Consent nobody was told the shape of is not consent. The one line has
    to name who is asked, how often, and what is sent."""
    cli.main(["config", "set", "update.check", "true", "--home", str(home)])
    printed = capsys.readouterr().out

    assert "GitHub" in printed
    assert "once a day" in printed
    assert "nothing about you" in printed


def test_turning_it_off_says_the_asking_has_stopped(home, capsys):
    cli.main(["config", "set", "update.check", "false", "--home", str(home)])
    assert "off" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("key", ["update-check", "update.checks", "telemetry",
                                 "update.check.enabled", ""])
def test_an_unknown_setting_names_the_ones_that_exist(home, capsys, key):
    """A typo gets told what to type instead, not a traceback and not silence
    that reads as success."""
    assert cli.main(["config", "get", key, "--home", str(home)]) \
        == cli.EXIT_USAGE
    reported = capsys.readouterr()
    assert reported.out == ""
    assert "update.check" in reported.err
    assert "Traceback" not in reported.err


def test_an_unknown_setting_cannot_be_written_either(home, capsys):
    assert cli.main(["config", "set", "telemetry", "true",
                     "--home", str(home)]) == cli.EXIT_USAGE
    assert "update.check" in capsys.readouterr().err
    assert not Paths.for_home(home).settings_path.exists()


@pytest.mark.parametrize("value", ["yes", "1", "True", "on", "maybe", ""])
def test_a_value_that_is_not_true_or_false_is_refused(home, capsys, value):
    """``settings`` counts only a JSON ``true`` as on, so a near-miss accepted
    here would write a file that reads back as off -- the CLI would report
    success for a switch it had not thrown."""
    assert cli.main(["config", "set", "update.check", value,
                     "--home", str(home)]) == cli.EXIT_USAGE
    reported = capsys.readouterr()
    assert "true" in reported.err and "false" in reported.err
    assert enabled(home) is False
    assert not Paths.for_home(home).settings_path.exists()


def test_config_on_its_own_says_what_the_two_commands_are(home, capsys):
    assert cli.main(["config", "--home", str(home)]) == cli.EXIT_USAGE
    reported = capsys.readouterr().err
    assert "config get" in reported
    assert "config set" in reported


@pytest.mark.parametrize("argv", [
    ["config", "set", "update.check", "true", "--home"],
    ["--home", "%s", "config", "set", "update.check", "true"],
    ["config", "--home", "%s", "set", "update.check", "true"],
])
def test_home_is_accepted_on_either_side_of_the_subcommand(home, argv):
    """Same reasoning as every other subcommand: ``--home`` comes from the
    shared parent parser, so where it lands in the line does not matter."""
    filled = [str(home) if token == "%s" else token for token in argv]
    if filled[-1] == "--home":
        filled.append(str(home))

    assert cli.main(filled) == cli.EXIT_OK
    assert enabled(home) is True


def test_reading_or_writing_a_setting_never_looks_anything_up(home):
    """``config`` edits a local file. The update cache is written by a lookup
    and only by a lookup, so its absence here is the assertion that no lookup
    happened -- not even on the command that turns lookups on."""
    cli.main(["config", "set", "update.check", "true", "--home", str(home)])
    cli.main(["config", "get", "update.check", "--home", str(home)])

    assert not cache_path(home).exists()


def test_toggling_the_check_leaves_other_settings_alone(home):
    paths = Paths.for_home(home)
    settings.save_settings(paths, {"something.else": "kept"})

    cli.main(["config", "set", "update.check", "true", "--home", str(home)])

    assert settings.load_settings(paths) == {"something.else": "kept",
                                             "update.check": True}


# -- the version line, and the cached notice under it ------------------------

def run_version(home, capsys):
    """``shambles --version`` against a synthetic home, split into streams."""
    from shambles.__main__ import main

    code = main(["--version", "--home", str(home)])
    return code, capsys.readouterr()


def test_a_default_install_prints_a_version_and_nothing_else(home, capsys):
    code, reported = run_version(home, capsys)

    assert code == 0
    assert reported.out == f"shambles {shambles.__version__}\n"
    assert reported.err == ""


def test_a_cached_newer_release_is_repeated_under_the_version(home, capsys):
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="99.0.0")

    code, reported = run_version(home, capsys)

    assert code == 0
    assert f"Shambles 99.0.0 is available (you have {shambles.__version__})" \
        in reported.err
    assert "npm i -g shambles@latest" in reported.err


def test_the_notice_stays_off_stdout_so_scripts_can_scrape_the_version(
        home, capsys):
    """``shambles --version`` is parsed by shells and installers. A second
    line on stdout would break every one of them that reads a whole word or a
    whole stream, so the notice goes to stderr, where a person still sees it
    and a pipe does not."""
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="99.0.0")

    _, reported = run_version(home, capsys)

    assert reported.out == f"shambles {shambles.__version__}\n"
    assert reported.out.count("\n") == 1
    assert "99.0.0" not in reported.out


def test_a_cache_with_nothing_newer_adds_no_line(home, capsys):
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="0.0.1")

    _, reported = run_version(home, capsys)

    assert reported.err == ""


def test_an_opted_in_home_with_no_cache_yet_stays_quiet(home, capsys):
    """Nothing has been looked up, and ``--version`` is not the place to
    start: no cache means no notice, not a fetch."""
    settings.set_update_check(Paths.for_home(home), True)

    _, reported = run_version(home, capsys)

    assert reported.err == ""
    assert not cache_path(home).exists()


def test_a_cached_tag_stays_quiet_once_the_check_is_turned_off(home, capsys):
    """Turning the switch off silences the notice immediately, without
    needing anybody to find and delete the cache first."""
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="99.0.0")
    settings.set_update_check(Paths.for_home(home), False)

    _, reported = run_version(home, capsys)

    assert reported.err == ""


def test_printing_from_the_cache_does_not_rewrite_it(home, capsys):
    """A read is a read. Restamping here would spend a day's lookup budget on
    a command that never looked anything up."""
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="99.0.0", checked_at=1_000)

    run_version(home, capsys)

    assert json.loads(cache_path(home).read_text(encoding="utf-8")) == {
        "checked_at": 1_000, "latest": "99.0.0"}


def test_an_unorderable_cached_tag_does_not_crash_the_version_flag(
        home, capsys):
    """Whatever is in that file, ``--version`` still answers. It is the one
    command that has to work when everything else is broken."""
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="nightly")

    code, reported = run_version(home, capsys)

    assert code == 0
    assert reported.out == f"shambles {shambles.__version__}\n"
    assert reported.err == ""


def test_version_never_pulls_a_networking_stack_into_the_process(tmp_path):
    """The decisive one.

    Every other assertion here says the notice came from the cache; this one
    says the alternative was never even available. Run in a fresh interpreter
    because pytest's own dependencies import plenty of ``urllib``, with the
    check turned on and a newer tag cached -- so it is exercising the loudest
    path ``--version`` has, and still ends with nothing on a socket.
    """
    home = tmp_path / "home"
    home.mkdir()
    settings.set_update_check(Paths.for_home(home), True)
    seed_cache(home, latest="99.0.0")

    probe = (
        "import sys\n"
        "from shambles.__main__ import main\n"
        f"assert main(['--version', '--home', {str(home)!r}]) == 0\n"
        "print(sorted(m for m in sys.modules"
        " if m in ('socket', 'urllib.request', 'ssl', 'http.client')))\n"
    )
    finished = subprocess.run([sys.executable, "-c", probe], cwd=REPO,
                              capture_output=True, text=True, check=True)

    assert "99.0.0 is available" in finished.stderr
    assert finished.stdout.strip().endswith("[]")


def test_the_usage_message_says_how_to_reach_the_setting(capsys):
    """``--help`` is where somebody looks for the switch; if it is not listed
    there, an opt-in feature is one nobody opts into."""
    from shambles.__main__ import main

    assert main(["--help"]) == 0
    printed = capsys.readouterr().out

    assert "shambles config get update.check" in printed
    assert "shambles config set update.check" in printed
