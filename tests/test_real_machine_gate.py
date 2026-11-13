"""The rule that decides when the real-machine result blocks a pull request.

The machines run on every pull request. Their result counts only when the
change touches a listed path; otherwise a failure is shown and does not block.
The last job, the one branch protection requires, reports either way. These
tests pin the rule and the few lines of the workflow that make a required
check safe.
"""

import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / ".github" / "real-machine-paths.txt"
SCRIPT = ROOT / ".github" / "scripts" / "real_machine_required.py"
WORKFLOW = ROOT / ".github" / "workflows" / "real-machine.yml"


@pytest.fixture(scope="module")
def rule():
    spec = importlib.util.spec_from_file_location("real_machine_required", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", [
    "shambles/stores/keychain.py",
    "shambles/stores/credman.py",
    "shambles/providers/claude.json",
    "shambles/providers/codex.py",
    "shambles/paths.py",
    "scripts/install.sh",
    "scripts/install.ps1",
    "tests/real/test_real_machine.py",
    ".github/workflows/real-machine.yml",
    ".github/real-machine-paths.txt",
    ".github/scripts/real_machine_required.py",
    ".github/actions/build-binary/action.yml",
    "macos/Sources/ShamblesKit/CLIService.swift",
])
def test_a_change_here_needs_real_machines(rule, path):
    assert rule.relevant([path], rule.load(LIST)) == [path]


@pytest.mark.parametrize("path", [
    "README.md",
    "CHANGELOG.md",
    "docs/token-storage.md",
    "shambles/gui.py",
    "shambles/app/tui/application.py",
    "tests/test_widgets.py",
    # A directory entry is a directory, not a prefix of a name.
    "shambles/stores_notes.md",
    "scripts.md",
    "shambles/paths.py.bak",
])
def test_a_change_here_does_not(rule, path):
    assert rule.relevant([path], rule.load(LIST)) == []


def test_every_listed_path_exists():
    """A renamed directory must not silently stop counting."""
    spec = importlib.util.spec_from_file_location("real_machine_required", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [entry for entry in module.load(LIST)
               if not (ROOT / entry).exists()]
    assert not missing, f"listed but not in the repository: {missing}"


def run(changed, list_path=LIST):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(list_path)],
        input=changed, capture_output=True, text=True)


def test_the_script_says_yes_no_and_cannot_tell_apart(tmp_path):
    assert run("README.md\nscripts/install.sh\n").returncode == 0
    assert run("README.md\n").returncode == 1
    # The workflow runs the machines on anything but 0 or 1, so a rule that
    # cannot be read must not look like "nothing relevant changed".
    assert run("README.md\n", tmp_path / "missing.txt").returncode == 2
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing listed\n", encoding="utf-8")
    assert run("README.md\n", empty).returncode == 2


def test_the_script_prints_what_matched():
    done = run("README.md\nshambles/stores/file.py\n")
    assert done.stdout.split() == ["shambles/stores/file.py"]


def job(name):
    """The text of one job in the workflow, by its key."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"\n  {name}:\n")
    following = [text.find(f"\n  {other}:\n", start + 1)
                 for other in ("changes", "machine", "cannot-run-here",
                               "swift-app", "result")]
    ends = [index for index in following if index > start]
    return text[start:min(ends)] if ends else text[start:]


def test_the_required_job_always_reports():
    """Skipped counts as passed in branch protection, so it must never skip."""
    result = job("result")
    assert "    name: real-machine\n" in result
    assert "    if: always()\n" in result
    assert "needs: [changes, machine, cannot-run-here, swift-app]" in result


def test_the_machines_run_on_every_pull_request():
    """Advisory outside the listed paths means run and show, not skip."""
    for name in ("machine", "cannot-run-here", "swift-app"):
        text = job(name)
        assert "needs:" not in text, name
        assert "\n    if:" not in text, name


def test_only_a_decided_irrelevant_change_may_ignore_a_failure():
    """An undecided change, like a relevant one, needs every machine."""
    result = job("result")
    assert '[ "$CHANGES" = "success" ] && [ "$REQUIRED" = "false" ]' in result
    assert result.rstrip().endswith("exit 1")


def test_the_trigger_has_no_path_filter():
    """With one, the required check would not report on other pull requests."""
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger = text[text.index("\non:\n"):text.index("\npermissions:\n")]
    assert "  pull_request:\n" in trigger
    assert "paths" not in trigger


def test_the_rule_is_read_from_the_branch_being_merged_into():
    assert "ref: ${{ github.event.pull_request.base.sha || github.sha }}" in job("changes")
