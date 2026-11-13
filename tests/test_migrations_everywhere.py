"""Every interface brings an old store up to date before it reads it (D6).

The Tk window and the Qt window run both migrations at startup. The terminal
interface -- the default -- and the CLI ran neither, so somebody upgrading
from 1.0 who never opened a window saw no accounts at all, and on the pre-1.0
layout every Claude switch was refused with "run the migration", which no
command in front of them could do. All of them now go through
``ShamblesService.run_migrations``.
"""

import json
import os

import pytest

from helpers import make_claude_json, make_legacy_profile, make_v1_profile
from shambles import migrate, state
from shambles.app import cli
from shambles.app.service import ShamblesService
from shambles import providers


def test_listing_brings_a_1_0_store_across(paths, capsys):
    make_v1_profile(paths, "Work", email="w@example.test", active=True)

    assert cli.main(["list", "--home", str(paths.home)]) == 0

    out, err = capsys.readouterr()
    assert "Work" in out
    assert "moved" in err
    assert not migrate.store_migration_needed(paths)


def test_the_machine_readable_listing_stays_machine_readable(paths, capsys):
    """Notices go to stderr; stdout is the contract the macOS app parses."""
    make_v1_profile(paths, "Work", email="w@example.test", active=True)

    assert cli.main(["list", "--json", "--home", str(paths.home)]) == 0

    out, err = capsys.readouterr()
    names = [a["name"] for g in json.loads(out)["groups"] for a in g["accounts"]]
    assert names == ["Work"]
    assert "moved" in err


def test_switching_on_the_pre_1_0_layout_converts_it_first(paths, capsys):
    make_legacy_profile(paths, "Work", email="w@example.test", sessions=2)
    make_legacy_profile(paths, "Personal", email="p@example.test", sessions=1)
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="w@example.test")

    code = cli.main(["switch", "claude", "Personal", "--home", str(paths.home)])

    out, err = capsys.readouterr()
    assert code == 0, err
    assert not paths.claude_dir.is_symlink()
    assert state.read_active(paths, "claude") == "Personal"


def test_a_home_that_needs_nothing_says_nothing(paths, capsys):
    assert cli.main(["list", "--home", str(paths.home)]) == 0
    assert capsys.readouterr().err == ""


async def test_the_terminal_interface_brings_a_1_0_store_across(paths):
    from shambles.app.tui.application import ShamblesTUI

    make_v1_profile(paths, "Work", email="w@example.test", active=True)
    service = ShamblesService(paths=paths,
                              providers=providers.all_providers(env={}),
                              platform="linux")

    app = ShamblesTUI(service, motion=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        names = [a.name for g in app.snapshot.groups for a in g.accounts]
        status = str(app.query_one("#refresh-status").render())

    assert names == ["Work"]
    assert "moved" in status
