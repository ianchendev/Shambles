import pytest

from shambles.paths import Paths


@pytest.fixture
def home(tmp_path):
    """A synthetic home directory. Never the real one."""
    return tmp_path


@pytest.fixture
def paths(home):
    return Paths.for_home(home)
