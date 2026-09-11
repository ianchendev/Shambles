"""Fail a release whose Linux binary needs a newer glibc than we promise.

PyInstaller bundles the build machine's shared libraries. Build on Ubuntu
24.04 and the result quietly demands GLIBC_2.38, which Ubuntu 22.04, Debian
12 and RHEL 9 cannot satisfy. 2.1.0 shipped exactly that: it built green,
passed its own smoke test on the runner that made it, and then failed to
start on other people's machines with a message about libc.so.6.

Nothing about the built artifact advertises this. The outer executable
reports GLIBC_2.14 and tells you nothing about the libraries packed inside
it, so the check has to unpack the archive and look at each one.

Usage:
    python scripts/check_glibc.py dist/shambles 2.35
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: Versions appear as ``GLIBC_2.38`` in objdump's dynamic symbol table.
_VERSION = re.compile(r"GLIBC_(\d+(?:\.\d+)+)")


def parse_glibc_versions(text: str) -> set:
    """Every glibc version named in ``text``, as tuples of ints."""
    return {
        tuple(int(part) for part in match.split("."))
        for match in _VERSION.findall(text)
    }


def highest_glibc(text: str):
    """The newest glibc version named in ``text``, or None if there is none.

    Compared as integers rather than as text, because ``2.9`` sorts after
    ``2.38`` alphabetically and would hide the version that actually matters.
    """
    versions = parse_glibc_versions(text)
    return max(versions) if versions else None


def _shared_libraries(binary: Path, into: Path) -> list:
    """Unpack the PyInstaller archive and return the libraries inside it."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(binary))
    written = []
    for name in archive.toc:
        if ".so" not in name:
            continue
        try:
            data = archive.extract(name)
        except Exception:
            continue
        if not isinstance(data, bytes):
            data = data[1]
        path = into / Path(name).name
        path.write_bytes(data)
        written.append(path)
    return written


def _version_text(paths: list) -> str:
    out = []
    for path in paths:
        result = subprocess.run(["objdump", "-T", str(path)],
                                capture_output=True, text=True)
        out.append(result.stdout)
    return "\n".join(out)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    binary, allowed = Path(argv[0]), tuple(int(p) for p in argv[1].split("."))

    with tempfile.TemporaryDirectory() as tmp:
        libraries = _shared_libraries(binary, Path(tmp))
        if not libraries:
            print(f"No shared libraries found inside {binary}.", file=sys.stderr)
            return 1
        found = highest_glibc(_version_text(libraries))

    if found is None:
        print(f"{len(libraries)} libraries, none linking glibc.")
        return 0
    shown = ".".join(str(part) for part in found)
    wanted = ".".join(str(part) for part in allowed)
    if found > allowed:
        print(
            f"{binary} needs GLIBC_{shown}, above the {wanted} this release "
            f"promises.\nIt will not start on any distribution older than "
            f"that. Build on an older runner, or raise the documented floor.",
            file=sys.stderr,
        )
        return 1
    print(f"{len(libraries)} libraries, highest GLIBC_{shown}, "
          f"within the {wanted} floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
