"""The GUI is smoke-tested only -- no display is assumed in CI."""

import pytest

tk = pytest.importorskip("tkinter")


def test_module_imports_and_exposes_run():
    from shambles import gui
    assert callable(gui.run)
    assert issubclass(gui.ShamblesApp, tk.Tk)


def test_header_text_for_each_link_state(paths):
    import os

    from helpers import make_claude_json, make_profile
    from shambles import gui, links

    make_profile(paths, "Work", email="work@example.com")
    make_claude_json(paths, email="work@example.com")

    assert "not set up" in gui.header_text(paths, links.inspect(paths)).lower()

    os.symlink(str(paths.profile_dir("Work")), str(paths.claude_dir),
               target_is_directory=True)
    text = gui.header_text(paths, links.inspect(paths))
    assert "Work" in text
    assert "work@example.com" in text


def test_header_reports_a_broken_link(paths):
    import os

    from helpers import make_profile
    from shambles import gui, links

    make_profile(paths, "Gone")
    os.symlink(str(paths.profile_dir("Gone")), str(paths.claude_dir),
               target_is_directory=True)
    for child in paths.profile_dir("Gone").iterdir():
        child.unlink()
    paths.profile_dir("Gone").rmdir()

    text = gui.header_text(paths, links.inspect(paths))
    assert "Broken" in text
