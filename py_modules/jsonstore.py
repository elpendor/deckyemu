"""Reading and writing the plugin's own JSON, in the plugin's own settings dir.

Seven files are kept this way -- settings, library, collections, the registered
emulators, what firmware was installed where, what was handed to an emulator's
window, the content ids a PS3 game came from, and the release cache -- and each
had its own copy of the same twelve lines. They had drifted, in two directions
that only show up on a bad day:

* **Only one of them cleaned up after itself.** A write that fails part way
  leaves `<name>.json.tmp` in the settings directory, and only the release cache
  removed it. A full disk therefore left a scatter of half-written files that
  nothing would ever read or replace.
* **Only one of them checked the shape of what it read back.** Most did
  `data if isinstance(data, dict) else {}`, which is what makes a hand-edited or
  truncated file fall back to a default rather than raise `AttributeError` on
  the first `.get`, several frames away from the cause. `store` did not.

Deliberately **not** used for the other three atomic writes in this codebase.
`emu_config` writes an emulator's own config and `imported` writes the
definition file the user sent, and those differ in ways that are the point
rather than accidents: a `.deckyemu-tmp` suffix so an emulator scanning its
config directory does not read our half-written file as one of its own,
encoding and BOM preserved from whatever was already there, and an error string
returned rather than an exception because the caller is reporting to the user.
One helper covering both would have to grow every one of those as a flag.

Writes raise; they do not report. Every caller here already had its own policy
about that -- some warn and carry on because the thing they were recording is
less important than what they just did, others let it propagate -- and that
policy belongs at the call site, not in here.
"""

import json
import os
import stat

import decky


def read_json(path, fallback):
    """`path` parsed, or `fallback` if it is missing, unreadable or the wrong shape.

    The shape check is against the type of `fallback`, so a caller asking for a
    dict cannot be handed a list by a file somebody edited by hand. That is not
    hypothetical tidiness: the failure without it is an `AttributeError` on a
    `.get` somewhere far from the file that caused it.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def write_json(path, payload, private=False, sort_keys=False):
    """Write `payload` to `path`, atomically. Raises on failure.

    Written beside and renamed over, because `os.replace` is atomic on the same
    filesystem and a half-written file is still valid JSON often enough to be
    worth not risking.

    `private` restricts the file to the owner before the rename, so it is never
    readable at its real name even briefly. Set for anything holding a
    credential -- settings.json carries the SteamGridDB key, the GitHub token
    and the RetroAchievements Connect token, which is password-equivalent. Not
    the default, and the reason is debugging rather than principle: these files
    are read over ssh as `deck` when something is wrong, and a mode that hides
    the emulator list buys nothing to pay for that.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=sort_keys)
        if private:
            try:
                os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            except OSError as error:
                # The write is worth more than the mode. Warned rather than
                # raised so a filesystem that cannot do modes -- which is every
                # one of them on the machine the tests run on -- does not lose
                # the settings it was asked to save.
                decky.logger.warning("Could not restrict %s: %s", path, error)
        os.replace(temporary, path)
    # Broad on purpose and re-raised immediately: this is not handling the
    # failure, it is refusing to leave a `.tmp` behind on the way out. A payload
    # that will not serialise raises TypeError rather than OSError, and that is
    # exactly the case that used to litter the settings directory.
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise
