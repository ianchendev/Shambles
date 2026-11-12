import os, stat, subprocess, textwrap
from pathlib import Path
import pytest

@pytest.fixture
def fake_release(tmp_path, monkeypatch):
    """Minimal static file server stand-in: pre-seed a 'downloaded' binary via
    rewriting PATH to a curl stub that copies a fixture file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload = tmp_path / "payload"
    payload.write_bytes(b"#!/bin/sh\necho fake-shambles\n")
    payload.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        # ignore args; always emit the fixture binary to -o target
        out=""
        while [ $# -gt 0 ]; do
          if [ \"$1\" = \"-o\" ]; then out=$2; shift 2; continue; fi
          shift
        done
        cp {payload} \"$out\"
        """), encoding="utf-8")
    curl.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path

@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_writes_local_bin(fake_release, monkeypatch):
    # Point the script at a local 'API' by exporting SHAMBLES_RELEASE_BASE
    # (installer must honor this override for tests — see implementation).
    monkeypatch.setenv("SHAMBLES_RELEASE_BASE", "https://example.test")
    monkeypatch.setenv("SHAMBLES_FORCE_ASSET", "shambles-linux-x86_64")
    monkeypatch.setenv("SHAMBLES_SKIP_SMOKE", "1")
    script = Path("scripts/install.sh").resolve()
    subprocess.run(["bash", str(script)], check=True)
    dest = Path(os.environ["HOME"]) / ".local/bin/shambles"
    assert dest.is_file()
    assert dest.stat().st_mode & stat.S_IXUSR


# -- the window archive -------------------------------------------------------


@pytest.fixture
def release_with_window(fake_release):
    """The same stand-in ``curl``, now also serving a window archive.

    Anything whose URL ends ``.tar.gz`` gets a real archive holding a
    ``shambles-window`` folder; set ``WINDOW_BROKEN=1`` to serve junk instead,
    which is what a release from before the window existed looks like once
    GitHub's 404 page has been saved to disk.
    """
    import tarfile

    bundle = fake_release / "build" / "shambles-window"
    bundle.mkdir(parents=True)
    launcher = bundle / "shambles-window"
    launcher.write_text("#!/bin/sh\necho fake-window\n", encoding="utf-8")
    launcher.chmod(0o755)
    (bundle / "_internal").mkdir()
    (bundle / "_internal" / "marker").write_text("new", encoding="utf-8")
    (bundle / "shambles.png").write_bytes(b"png")
    archive = fake_release / "window.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(bundle, arcname="shambles-window")

    payload = fake_release / "payload"
    curl = fake_release / "bin" / "curl"
    curl.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        out=""; url=""
        while [ $# -gt 0 ]; do
          if [ "$1" = "-o" ]; then out=$2; shift 2; continue; fi
          url=$1; shift
        done
        case "$url" in
          *.tar.gz)
            if [ -n "$WINDOW_BROKEN" ]; then echo "Not Found" > "$out"; exit 0; fi
            cp {archive} "$out" ;;
          *) cp {payload} "$out" ;;
        esac
        """), encoding="utf-8")
    curl.chmod(0o755)
    return fake_release


def _install(monkeypatch, **env):
    monkeypatch.setenv("SHAMBLES_RELEASE_BASE", "https://example.test")
    monkeypatch.setenv("SHAMBLES_FORCE_ASSET", "shambles-linux-x86_64")
    monkeypatch.setenv("SHAMBLES_SKIP_SMOKE", "1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    script = Path("scripts/install.sh").resolve()
    return subprocess.run(["bash", str(script)], check=True,
                          capture_output=True, text=True)


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_unpacks_the_window_where_shambles_looks_for_it(
        release_with_window, monkeypatch):
    from shambles.app import launch

    result = _install(monkeypatch)

    home = Path(os.environ["HOME"])
    window = home / ".local/share/shambles/window/shambles-window"
    assert window.is_file() and window.stat().st_mode & stat.S_IXUSR
    assert (home / ".local/share/shambles/window/_internal/marker").is_file()
    assert "Installed the window" in result.stdout
    assert launch.window_bundle(env={}, platform="linux",
                                executable=home / ".local/bin/shambles",
                                home=home) == window, \
        "the installer and the launcher disagree about where the window goes"


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_replaces_an_older_window_completely(release_with_window,
                                                        monkeypatch):
    """A file left over from the previous version must not survive inside the
    new one, where the new Qt would try to load it."""
    old = Path(os.environ["HOME"]) / ".local/share/shambles/window"
    (old / "_internal").mkdir(parents=True)
    (old / "_internal" / "stale-library.so").write_text("old")

    _install(monkeypatch)

    assert not (old / "_internal" / "stale-library.so").exists()
    assert (old / "_internal" / "marker").read_text() == "new"


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_a_release_with_no_window_still_installs_and_keeps_the_old_one(
        release_with_window, monkeypatch):
    old = Path(os.environ["HOME"]) / ".local/share/shambles/window"
    old.mkdir(parents=True)
    (old / "shambles-window").write_text("previous")

    result = _install(monkeypatch, WINDOW_BROKEN="1")

    assert (Path(os.environ["HOME"]) / ".local/bin/shambles").is_file()
    assert (old / "shambles-window").read_text() == "previous", \
        "a failed download destroyed the window that was installed"
    assert "classic window" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_can_skip_the_window(release_with_window, monkeypatch):
    _install(monkeypatch, SHAMBLES_NO_WINDOW="1")

    home = Path(os.environ["HOME"])
    assert (home / ".local/bin/shambles").is_file()
    assert not (home / ".local/share/shambles").exists()


# -- the launcher entry ---------------------------------------------------------


def _desktop_entry(home: Path) -> dict:
    text = (home / ".local/share/applications/shambles.desktop").read_text()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_adds_a_launcher_entry_that_points_at_the_window(
        release_with_window, monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    _install(monkeypatch)

    home = Path(os.environ["HOME"])
    entry = _desktop_entry(home)
    window = home / ".local/share/shambles/window"

    assert entry["Type"] == "Application" and entry["Name"] == "Shambles"
    assert entry["Terminal"] == "false"
    # Quoted, so a home directory with a space in it still launches.
    assert entry["Exec"] == f'"{window}/shambles-window"'
    assert Path(entry["Exec"].strip('"')).is_file()
    assert Path(entry["Icon"]).is_file(), \
        "the launcher names an icon the window does not ship"


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_no_launcher_entry_without_a_window_to_launch(release_with_window,
                                                      monkeypatch):
    """An entry pointing at nothing is a dead icon in somebody's menu."""
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = Path(os.environ["HOME"])

    _install(monkeypatch, WINDOW_BROKEN="1")
    assert not (home / ".local/share/applications/shambles.desktop").exists()

    _install(monkeypatch, SHAMBLES_NO_WINDOW="1")
    assert not (home / ".local/share/applications/shambles.desktop").exists()


@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_the_launcher_entry_can_be_skipped(release_with_window, monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    _install(monkeypatch, SHAMBLES_NO_DESKTOP="1")

    home = Path(os.environ["HOME"])
    assert (home / ".local/share/shambles/window/shambles-window").is_file()
    assert not (home / ".local/share/applications").exists()


def test_install_ps1_adds_a_start_menu_shortcut_to_the_window():
    """Read, not run: there is no PowerShell here. What can be held is that
    the shortcut is per-user, points at the window, and cannot fail the
    install."""
    text = Path("scripts/install.ps1").read_text(encoding="utf-8")
    start = text.index("# A Start menu shortcut")
    block = text[start:text.index("} catch {", start) + 200]

    assert "GetFolderPath('Programs')" in block, "must be the per-user menu"
    assert "shambles-window.exe" in block
    assert "Shambles.lnk" in block
    assert "SHAMBLES_NO_DESKTOP" in block
    assert "Could not add a Start menu shortcut" in block
