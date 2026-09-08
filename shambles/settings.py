"""Shambles' own preferences, in ``~/.shambles/settings.json``.

There is one preference so far and it is the one that decides whether this
program may talk to the internet at all, so it gets a file of its own rather
than a corner of some provider's config. Absent, unparseable, or holding
something that merely looks like a yes all read the same way: off.

Keys are flat and dotted -- ``"update.check"``, not ``{"update": {"check":
true}}`` -- so the string in the file, the string in ``shambles config set
update.check true`` and the string in the README are the same string. A nested
tree would need translating in three places to say one thing.

Writes go through :func:`shambles.configjson.write_atomic`, which is where the
owner-only write-and-rename discipline already lives. Nothing stored here is
secret, but the directory around it holds OAuth refresh tokens, and one file
left at the umask's mercy in the middle of that is not worth saving three
lines over.
"""

from . import configjson

#: Whether Shambles may ask GitHub for the latest release tag. Off unless the
#: user says otherwise -- see :mod:`shambles.update_check`.
UPDATE_CHECK = "update.check"


def load_settings(paths) -> dict:
    """Every stored preference, or ``{}`` when there is nothing usable there.

    A settings file is a convenience, not a credential. Corruption costs the
    user their preferences, which is annoying; refusing to start over it would
    be worse.
    """
    return configjson.load(paths.settings_path)


def save_settings(paths, data: dict) -> None:
    """Replace the settings file with ``data``.

    The store is created first, so no caller has to remember to. Changing one
    key means reading, updating and passing the whole mapping back --
    :func:`set_update_check` is the worked example -- which is what keeps a key
    written by a newer version from vanishing when an older one toggles
    something.
    """
    paths.ensure_store()
    configjson.write_atomic(paths.settings_path, data)


def update_check_enabled(paths) -> bool:
    """Whether the user has turned update checks on.

    Only a JSON ``true`` counts. ``"true"``, ``1`` and ``"yes"`` are somebody
    guessing at the format, and the safe reading of a guess about a network
    switch is "off".
    """
    return load_settings(paths).get(UPDATE_CHECK) is True


def set_update_check(paths, enabled: bool) -> None:
    data = load_settings(paths)
    data[UPDATE_CHECK] = bool(enabled)
    save_settings(paths, data)
