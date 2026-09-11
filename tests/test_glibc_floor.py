"""The Linux binaries must run on more than the machine that built them.

2.1.0 shipped a Linux build made on Ubuntu 24.04. PyInstaller bundled that
system's libpython, libcrypto and libX11, every one of them needing
GLIBC_2.38, so the binary refused to start on Ubuntu 22.04, Debian 12 and
RHEL 9. It built green and passed its own smoke test, because the runner that
made it was the only machine it was ever tried on.

These cover the parsing; the workflow runs the scan itself against the real
binary.
"""

import pytest

from scripts.check_glibc import highest_glibc, parse_glibc_versions


def test_versions_are_read_out_of_objdump_output():
    text = "0000 DF *UND* GLIBC_2.4  fopen\n0000 DF *UND* GLIBC_2.38  strtod\n"
    assert parse_glibc_versions(text) == {(2, 4), (2, 38)}


def test_nothing_found_is_not_a_failure():
    """A pure-Python library links nothing, which is fine, not suspicious."""
    assert parse_glibc_versions("no symbols here") == set()
    assert highest_glibc("no symbols here") is None


def test_the_highest_version_wins_numerically_not_alphabetically():
    """2.9 sorts after 2.38 as text, which would hide the real floor."""
    text = "GLIBC_2.9 GLIBC_2.38 GLIBC_2.4"
    assert highest_glibc(text) == (2, 38)


def test_a_three_part_version_is_read_in_full():
    assert highest_glibc("GLIBC_2.34.1 GLIBC_2.34") == (2, 34, 1)
