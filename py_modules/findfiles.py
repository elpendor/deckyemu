"""Listing files without `glob`, which decky's bundle does not carry.

Measured on a Deck running decky v3.2.9: `glob` is not in the executable at all,
and `import glob` works only because SteamOS's own Python 3.13 sits on
`sys.path` behind the bundle -- `/usr/lib/python3.13/glob.py` is the file that
loads. That is luck. The same luck ran out for `http.server` when a dependency
bump stopped pulling it in, and the plugin would not load at all (see
`httpshim`); a module-level `import glob` in `ra_cores` or `steam_shortcuts`
would take the core scan and the Steam library with it.

`os.scandir` is built into the interpreter, so this borrows nothing. The
patterns here were every one the plugin used: a suffix in a directory, and one
fixed path under each subdirectory of a root.
"""

import os


def in_directory(directory, suffix="", prefix=""):
    """Files directly in `directory`, sorted, as absolute paths.

    Case-insensitive on both ends, because the patterns this replaced were
    matching filenames somebody else wrote -- `RetroArch*.AppImage` next to
    `retroarch*.AppImage` was two globs for that reason alone.
    """
    suffix, prefix = suffix.lower(), prefix.lower()
    found = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name.lower()
                if not name.startswith(prefix) or not name.endswith(suffix):
                    continue
                try:
                    if entry.is_file():
                        found.append(entry.path)
                except OSError:
                    continue
    except OSError:
        # A directory that is not there yet is not an error: several of these
        # are folders the plugin or an emulator creates on first use.
        return []
    return sorted(found)


def under_each(root, *tail):
    """`root/<any subdirectory>/tail...`, for the paths that exist.

    The shape of `settings/*/library.json` and of every Steam account's
    `userdata/<id>/config/shortcuts.vdf`.
    """
    found = []
    try:
        with os.scandir(root) as entries:
            directories = [entry.path for entry in entries if entry.is_dir()]
    except OSError:
        return []
    for directory in sorted(directories):
        path = os.path.join(directory, *tail)
        if os.path.exists(path):
            found.append(path)
    return found
