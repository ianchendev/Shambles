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
