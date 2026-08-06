"""Every path Shambles touches, derived from an injectable home root.

``Path.home()`` is called in exactly one place -- :meth:`Paths.real` -- so the
test suite can point the entire application at a temporary directory.

``~/.claude`` is an ordinary directory here and is never replaced. Only the
login inside it is account-scoped; session history, plugins, file history and
settings are machine-scoped and stay shared, which is how Claude Code itself
behaves.
"""

import os
from dataclasses import dataclass
from pathlib import Path

CLAUDE_DIRNAME = ".claude"
CLAUDE_JSON_NAME = ".claude.json"
PROFILES_DIRNAME = ".claude-profiles"
BACKUP_DIRNAME = ".shambles-backups"

#: Claude Code's own name for the live login inside ~/.claude.
LIVE_CREDENTIALS_NAME = ".credentials.json"

#: Per-profile files. Small: tokens and the account identity, nothing else.
CREDENTIALS_NAME = "credentials.json"
ACCOUNT_NAME = "account.json"

#: Records which profile the live login belongs to.
ACTIVE_NAME = "active"

#: Pre-1.0 layout, where ~/.claude was a symlink into a full profile copy.
LEGACY_SIDECAR_NAME = ".shambles.json"
LEGACY_CREDENTIALS_NAME = ".credentials.json"


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
    def live_credentials(self) -> Path:
        return self.claude_dir / LIVE_CREDENTIALS_NAME

    @property
    def profiles_dir(self) -> Path:
        return self.home / PROFILES_DIRNAME

    @property
    def backup_dir(self) -> Path:
        return self.profiles_dir / BACKUP_DIRNAME

    @property
    def active_marker(self) -> Path:
        return self.profiles_dir / ACTIVE_NAME

    def ensure_store(self) -> Path:
        """Create the profile store, readable only by its owner.

        It holds OAuth refresh tokens. The credentials files are written 600
        regardless, but a plain ``mkdir`` under the usual 022 umask leaves the
        directories 755, so this closes that off too. On Windows ``chmod``
        cannot express this and is skipped -- the file modes still apply.
        """
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.profiles_dir, 0o700)
        except OSError:
            pass
        return self.profiles_dir

    def ensure_profile(self, name: str) -> Path:
        """Create one profile's directory inside a locked-down store."""
        self.ensure_store()
        directory = self.profile_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        return directory

    def profile_dir(self, name: str) -> Path:
        return self.profiles_dir / name

    def credentials(self, name: str) -> Path:
        return self.profile_dir(name) / CREDENTIALS_NAME

    def account(self, name: str) -> Path:
        return self.profile_dir(name) / ACCOUNT_NAME

    # -- legacy layout, read only during migration -----------------------

    def legacy_credentials(self, name: str) -> Path:
        return self.profile_dir(name) / LEGACY_CREDENTIALS_NAME

    def legacy_sidecar(self, name: str) -> Path:
        return self.profile_dir(name) / LEGACY_SIDECAR_NAME
