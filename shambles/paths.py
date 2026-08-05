"""Every path Shambles touches, derived from an injectable home root.

``Path.home()`` is called in exactly one place -- :meth:`Paths.real` -- so the
test suite can point the entire application at a temporary directory.
"""

from dataclasses import dataclass
from pathlib import Path

CLAUDE_DIRNAME = ".claude"
CLAUDE_JSON_NAME = ".claude.json"
PROFILES_DIRNAME = ".claude-profiles"
BACKUP_DIRNAME = ".shambles-backups"
SIDECAR_NAME = ".shambles.json"
TMP_LINK_NAME = ".claude.shambles-tmp"


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def for_home(cls, home) -> "Paths":
        return cls(home=Path(home).expanduser())

    @classmethod
    def real(cls) -> "Paths":
        return cls.for_home(Path.home())

    @property
    def claude_dir(self) -> Path:
        return self.home / CLAUDE_DIRNAME

    @property
    def claude_json(self) -> Path:
        return self.home / CLAUDE_JSON_NAME

    @property
    def profiles_dir(self) -> Path:
        return self.home / PROFILES_DIRNAME

    @property
    def backup_dir(self) -> Path:
        return self.profiles_dir / BACKUP_DIRNAME

    @property
    def tmp_link(self) -> Path:
        return self.home / TMP_LINK_NAME

    def profile_dir(self, name: str) -> Path:
        return self.profiles_dir / name

    def sidecar(self, name: str) -> Path:
        return self.profile_dir(name) / SIDECAR_NAME
