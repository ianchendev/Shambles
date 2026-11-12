"""The window as its own download: finding it, handing over to it."""

import importlib.util
from pathlib import Path

import pytest

from shambles.app import cli, launch

ROOT = Path(__file__).resolve().parents[2]


def bundle_at(folder: Path, name="shambles-window") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    return target


# -- finding the bundle ------------------------------------------------------


def test_the_bundle_is_found_where_the_installer_puts_it(tmp_path):
    installed = bundle_at(tmp_path / ".local/share/shambles/window")

    assert launch.window_bundle(env={}, platform="linux",
                                executable=tmp_path / "bin/shambles",
                                home=tmp_path) == installed


def test_on_windows_the_bundle_lives_under_localappdata(tmp_path):
    installed = bundle_at(tmp_path / "Shambles/window",
                          name="shambles-window.exe")

    assert launch.window_bundle(
        env={"LOCALAPPDATA": str(tmp_path)}, platform="win32",
        executable=tmp_path / "elsewhere/shambles.exe") == installed


def test_a_bundle_beside_the_binary_wins_over_the_installed_one(tmp_path):
    """A release unpacked into one folder should run as it is."""
    bundle_at(tmp_path / ".local/share/shambles/window")
    beside = bundle_at(tmp_path / "bin/shambles-window")

    assert launch.window_bundle(env={}, platform="linux",
                                executable=tmp_path / "bin/shambles",
                                home=tmp_path) == beside


def test_an_explicit_path_wins_over_everything(tmp_path):
    bundle_at(tmp_path / "bin/shambles-window")
    chosen = bundle_at(tmp_path / "custom", name="win")

    assert launch.window_bundle(
        env={launch.WINDOW_ENV: str(chosen)}, platform="linux",
        executable=tmp_path / "bin/shambles", home=tmp_path) == chosen


def test_no_bundle_is_none_not_an_error(tmp_path):
    assert launch.window_bundle(env={}, platform="linux",
                                executable=tmp_path / "bin/shambles",
                                home=tmp_path) is None


def test_the_bundle_never_goes_looking_for_itself(tmp_path):
    """A bundle whose Qt fails to load must say so, not exec itself forever."""
    bundle_at(tmp_path / ".local/share/shambles/window")

    assert launch.window_bundle(
        env={launch.IN_WINDOW_ENV: "1"}, platform="linux",
        executable=tmp_path / "bin/shambles", home=tmp_path) is None


def test_handing_over_marks_the_new_process_and_passes_the_options():
    seen = {}
    env = {}

    bundle = Path("/opt/w/shambles-window")
    launch.replace_with_window(
        bundle, ["--home", "/tmp/x"],
        execv=lambda path, argv: seen.update(path=path, argv=argv), env=env)

    # str(bundle), not the literal: Windows spells the same path with
    # backslashes, and it is the spelling the OS is handed that matters.
    assert seen == {"path": str(bundle),
                    "argv": [str(bundle), "--home", "/tmp/x"]}
    assert env[launch.IN_WINDOW_ENV] == "1"


# -- the CLI hands over when it has no Qt ------------------------------------


def no_qt():
    raise ImportError("No module named 'PySide6'")


def test_without_qt_the_cli_hands_over_to_an_installed_bundle(
        monkeypatch, tmp_path, home):
    bundle = bundle_at(tmp_path / "w")
    handed = {}
    monkeypatch.setattr(cli, "_window_entry", no_qt)
    monkeypatch.setattr(launch, "window_bundle", lambda **kw: bundle)
    monkeypatch.setattr(
        launch, "replace_with_window",
        lambda path, args, **kw: handed.update(path=path, args=args))

    cli.main(["--no-motion", "gui", "--new", "--home", str(home)])

    assert handed == {"path": bundle,
                      "args": ["--home", str(home), "--no-motion"]}


def test_without_qt_or_a_bundle_the_cli_explains(monkeypatch, capsys, home):
    monkeypatch.setattr(cli, "_window_entry", no_qt)
    monkeypatch.setattr(launch, "window_bundle", lambda **kw: None)

    assert cli.main(["gui", "--new", "--home", str(home)]) == cli.EXIT_FAILED
    assert "shambles[gui]" in capsys.readouterr().err


# -- the bundle's own entry point --------------------------------------------


def entry():
    spec = importlib.util.spec_from_file_location(
        "window_entry", ROOT / "packaging" / "window_entry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bundle_opens_the_window_by_default_and_passes_options_on():
    arguments = entry().arguments

    assert arguments([]) == ["gui", "--new"]
    assert arguments(["--home", "/tmp/x"]) == ["gui", "--new", "--home",
                                               "/tmp/x"]


@pytest.mark.parametrize("flag", ["--version", "-V", "--help", "-h"])
def test_the_bundle_still_answers_version_and_help(flag):
    assert entry().arguments([flag]) == [flag]


def test_the_spec_bundles_what_is_read_from_disk_at_runtime():
    """A bundle missing these builds green and opens nothing."""
    spec = (ROOT / "packaging" / "window.spec").read_text(encoding="utf-8")

    for needed in ('"providers" / "*.json"', '"tui" / "*.tcss"',
                   '"qml" / "*.qml"', '"fonts" / "*"', "libEGL.so.1"):
        assert needed in spec, f"window.spec no longer bundles {needed}"


# -- licences ------------------------------------------------------------------


def test_the_window_ships_the_licences_of_what_it_bundles():
    """Qt is LGPL-3.0: the download has to carry the text and say where the
    source is. A bundle without them is one the project may not distribute."""
    licences = ROOT / "packaging" / "licenses"
    spec = (ROOT / "packaging" / "window.spec").read_text(encoding="utf-8")

    assert "GNU LESSER GENERAL PUBLIC LICENSE" in \
        (licences / "LGPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in \
        (licences / "GPL-3.0.txt").read_text(encoding="utf-8")
    notice = (licences / "NOTICE.txt").read_text(encoding="utf-8")
    for needed in ("LGPL-3.0.txt", "download.qt.io", "replace those libraries",
                   "OFL-Inter.txt", "LICENSE-Shambles.txt"):
        assert needed in notice, f"NOTICE.txt no longer mentions {needed}"
    for copied in ('"packaging" / "licenses"', "LICENSE-Shambles.txt",
                   "OFL-Inter.txt"):
        assert copied in spec, f"window.spec no longer ships {copied}"


def test_the_window_stays_a_folder_of_separate_libraries():
    """The LGPL lets a user swap in their own Qt. In a one-file build they
    cannot, so the spec must keep COLLECT and never pack the binaries into
    the executable."""
    spec = (ROOT / "packaging" / "window.spec").read_text(encoding="utf-8")

    assert "COLLECT(" in spec
    assert "exclude_binaries=True" in spec
