"""Reading Steam's own list of non-Steam shortcuts.

The plugin knows which games it added because it keeps a registry. When that
registry is lost -- a reset, a restored backup, a half-finished add -- Steam
still has the shortcuts, and nothing in the plugin could see them: every check
in the audit starts from a registry entry and asks whether the other half is
still there. Both halves gone is invisible, which is exactly the state a reset
leaves behind.

So this reads the other side. `shortcuts.vdf` is Steam's binary key-value file
and it holds the appid, the name and the executable of every non-Steam game.
Anything whose executable is one of our launcher scripts is ours, whatever the
registry remembers.

Read here rather than in the frontend because there is no supported call that
enumerates shortcuts with their executables: `appStore` looks one up by id, and
the shortcut's path is not on the overview it returns. The file is the only
place the two are written down together.

The file is Steam's, and this only ever reads it. Removing a shortcut is still
the frontend's job through `SteamClient.Apps.RemoveShortcut` -- editing Steam's
file underneath a running Steam would be overwritten at best.
"""

import glob
import os
import struct

import decky

import launchers
import sysenv

#: Binary VDF type markers.
_MAP = 0x00
_STRING = 0x01
_INT32 = 0x02
_MAP_END = 0x08


def _cstring(data, index):
    """(text, next index) for the NUL-terminated string at `index`."""
    end = data.index(b"\x00", index)
    return data[index:end].decode("utf-8", "replace"), end + 1


def _parse_map(data, index):
    """({key: value}, next index) for the map whose body starts at `index`.

    Keys are lowercased: Steam has written both `AppName` and `appname`
    depending on version, and a reader that matches one of them silently finds
    nothing on a client that writes the other.
    """
    out = {}
    while index < len(data):
        marker = data[index]
        index += 1
        if marker == _MAP_END:
            return out, index
        if marker == _MAP:
            key, index = _cstring(data, index)
            value, index = _parse_map(data, index)
            out[key.lower()] = value
        elif marker == _STRING:
            key, index = _cstring(data, index)
            value, index = _cstring(data, index)
            out[key.lower()] = value
        elif marker == _INT32:
            key, index = _cstring(data, index)
            # Unsigned: Steam stores a shortcut's appid as a signed int32, and
            # every id the frontend uses is that same bit pattern read as
            # unsigned. Reading it signed produces negative ids that match
            # nothing and would report every shortcut as unknown.
            (value,) = struct.unpack("<I", data[index:index + 4])
            index += 4
            out[key.lower()] = value
        else:
            # An unknown marker means the format moved or the file is damaged.
            # Stopping returns what was read rather than guessing at alignment
            # and inventing entries.
            break
    return out, index


def parse_shortcuts(data):
    """Every shortcut in a `shortcuts.vdf`, as a list of dicts.

    Never raises: a truncated or unfamiliar file returns what could be read, so
    a cleanup screen degrades to offering less rather than to an error.
    """
    try:
        root, _ = _parse_map(data, 0)
    except (ValueError, struct.error, IndexError):
        decky.logger.exception("Could not parse shortcuts.vdf")
        return []

    shortcuts = root.get("shortcuts")
    if not isinstance(shortcuts, dict):
        return []
    # Keyed by position ("0", "1", ...), which carries no meaning worth keeping.
    return [entry for entry in shortcuts.values() if isinstance(entry, dict)]


def shortcuts_files():
    """Every user's shortcuts.vdf on this device.

    More than one is normal: a Deck can have several Steam accounts, each with
    its own userdata directory and its own shortcuts.
    """
    home = sysenv.user_home()
    pattern = os.path.join(home, ".steam", "steam", "userdata", "*", "config", "shortcuts.vdf")
    return sorted(glob.glob(pattern))


def _exe_path(entry):
    """The executable a shortcut runs, unquoted.

    Steam quotes the path when it contains a space and does not when it does
    not, so both forms turn up in the same file.
    """
    return str(entry.get("exe") or "").strip().strip('"')


def ours():
    """[{app_id, title, exe, launcher, launcher_exists}] for shortcuts we made.

    Ownership is the executable sitting inside our launcher directory, never
    the name. Two shortcuts called "Super Mario 3D World" could be one of ours
    and one real Steam entry, and a cleanup that matched on names would offer
    to delete somebody's actual game.
    """
    found = []
    for path in shortcuts_files():
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as error:
            decky.logger.warning("Could not read %s: %s", path, error)
            continue

        for entry in parse_shortcuts(data):
            exe = _exe_path(entry)
            if not exe:
                continue
            directory = os.path.dirname(exe)
            if os.path.normpath(directory) != os.path.normpath(launchers.LAUNCHER_DIR):
                continue
            found.append(
                {
                    "app_id": int(entry.get("appid") or 0),
                    "title": str(entry.get("appname") or ""),
                    "exe": exe,
                    "launcher": os.path.basename(exe),
                    "launcher_exists": os.path.exists(exe),
                }
            )
    return found
