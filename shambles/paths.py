"""Every path Shambles touches, derived from an injectable home root.

``Path.home()`` is called in exactly one place -- :meth:`Paths.real` -- so the
test suite can point the entire application at a temporary directory.

The store is provider-scoped: ``~/.shambles/<provider>/<Name>/``. It was
``~/.claude-profiles/<Name>/`` before there was a second provider, and that
name became a lie the moment it could hold Codex tokens. :mod:`shambles.migrate`
moves the old layout across.

Where a *live* credential lives is deliberately not here any more. That is a
provider-and-platform fact, and it comes from ``provider.store()``. What
remains below is Shambles' own storage, plus the two Claude paths the pre-1.0
migration and Claude's companion splice still need by name.
"""

import os
from dataclasses import dataclass
from pathlib import Path

LIBRARY_DIRNAME = ".shambles"
BACKUP_DIRNAME = ".backups"

#: Shambles' own preferences, as opposed to any provider's config. It sits in
#: the library root rather than beside the profiles because it belongs to no
#: provider -- see :mod:`shambles.settings`.
SETTINGS_NAME = "settings.json"

#: Per-profile files. Small: tokens and, for providers whose identity lives
#: outside the credential, a stashed copy of it.
CREDENTIALS_NAME = "credentials.json"
ACCOUNT_NAME = "account.json"

#: Records which profile a provider's live login belongs to. One per provider.
ACTIVE_NAME = "active"

#: The v1.0 layout, read only while migrating out of it.
LEGACY_PROFILES_DIRNAME = ".claude-profiles"
LEGACY_BACKUP_DIRNAME = ".shambles-backups"

#: Claude-specific, and deliberately the only two vendor paths still named
#: here. ``claude_dir`` is needed to detect the pre-1.0 symlink layout;
#: ``claude_json`` is Claude's companion file. Everything else comes from a
#: provider spec.
CLAUDE_DIRNAME = ".claude"
CLAUDE_JSON_NAME = ".claude.json"


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def for_home(cls, home) -> "Paths":
        return cls(home=Path(home).expanduser())

    @classmethod
    def real(cls) -> "Paths":
        return cls.for_home(Path.home())

    # -- Shambles' own storage -------------------------------------------

    @property
    def library_dir(self) -> Path:
        return self.home / LIBRARY_DIRNAME

    @property
    def backup_dir(self) -> Path:
        return self.library_dir / BACKUP_DIRNAME

    @property
    def settings_path(self) -> Path:
        return self.library_dir / SETTINGS_NAME

    def provider_dir(self, provider_id: str) -> Path:
        return self.library_dir / provider_id

    def profile_dir(self, provider_id: str, name: str) -> Path:
        return self.provider_dir(provider_id) / name

    def credentials(self, provider_id: str, name: str) -> Path:
        return self.profile_dir(provider_id, name) / CREDENTIALS_NAME

    def account(self, provider_id: str, name: str) -> Path:
        return self.profile_dir(provider_id, name) / ACCOUNT_NAME

    def active_marker(self, provider_id: str) -> Path:
        return self.provider_dir(provider_id) / ACTIVE_NAME

    # -- creation, locked down -------------------------------------------

    def ensure_store(self) -> Path:
        """Create the library root, readable only by its owner.

        It holds OAuth refresh tokens. The credential files are written 600
        regardless, but a plain ``mkdir`` under the usual 022 umask leaves the
        directories 755, so this closes that off too. On Windows ``chmod``
        cannot express this and is skipped -- the file modes still apply.
        """
        return _locked_mkdir(self.library_dir)

    def ensure_provider(self, provider_id: str) -> Path:
        self.ensure_store()
        return _locked_mkdir(self.provider_dir(provider_id))

    def ensure_profile(self, provider_id: str, name: str) -> Path:
        self.ensure_provider(provider_id)
        return _locked_mkdir(self.profile_dir(provider_id, name))

    # -- Claude's own locations ------------------------------------------

    @property
    def claude_dir(self) -> Path:
        return self.home / CLAUDE_DIRNAME

    @property
    def claude_json(self) -> Path:
        return self.home / CLAUDE_JSON_NAME

    # -- the v1.0 layout, read only during migration ---------------------

    @property
    def legacy_profiles_dir(self) -> Path:
        return self.home / LEGACY_PROFILES_DIRNAME

    @property
    def legacy_active_marker(self) -> Path:
        return self.legacy_profiles_dir / ACTIVE_NAME

    @property
    def legacy_backup_dir(self) -> Path:
        return self.legacy_profiles_dir / LEGACY_BACKUP_DIRNAME


def _locked_mkdir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory
