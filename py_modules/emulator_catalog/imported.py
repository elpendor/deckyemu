"""Emulator definitions that did not come from this repository.

The bundled catalog needs a plugin release to grow. That is the right trade for
the emulators this project installs -- a recipe it ships is one it has tested --
but it leaves out every emulator it will not distribute or link to, and those
are exactly the ones a user is most likely to already have on the device.

So a definition can also arrive as a file. The user sends `<name>.deckyemu.json`
the same way they send a BIOS, the panel offers to import it, and from then on
that emulator behaves like any other in the catalog: it appears in the add-game
picker with the right system and extensions, its controller bindings are seeded,
and its firmware requirements are listed.

**An imported definition is not trusted.** A catalog entry is not data the plugin
reads, it is a list of actions the plugin performs: install this, write there,
delete that, run this. `schema.validate(..., imported=True)` bounds which of
those it may ask for.

It **may install the emulator it describes**, by any of the three source kinds.
Refusing that would be friction rather than safety: the alternative is the user
downloading a build by hand and re-pointing at it on every update, which does
not change who they decided to trust. What is refused is everything that is not
"install the emulator you asked for" -- deleting trees, fetching firmware,
fetching a second binary beside the emulator (see FORBIDDEN_WHEN_IMPORTED) --
and every write is confined to the one directory the entry declares as `root`.

Those bound what a definition can reach. They cannot say whether it is honest
about which emulator it installs, which is why the panel says so before
anything is fetched. docs/emulator-definitions.md is the same list for a reader
who is deciding whether to import one.

JSON rather than Python. A Python definition would let an imported entry look
exactly like a bundled one, and would also be a code-execution hole that no
amount of validation could close: importing the module *is* running it.
"""

import json
import os

import decky

from . import deck_gyro
from . import schema

#: Imported definitions live beside the plugin's other settings rather than in
#: the user's home, so a reset that clears emulators does not silently discard
#: definitions the user supplied and may not be able to obtain again.
STORE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "emulators.d")

#: What the transfer panel offers to import. Distinctive enough that a stray
#: `.json` in the inbox is not mistaken for one.
SUFFIX = ".deckyemu.json"

#: Bumped when the on-disk shape changes in a way an older file cannot satisfy.
FORMAT = 1

MAX_BYTES = 256 * 1024


def store_dir():
    """The definitions directory, created if it is not there yet."""
    os.makedirs(STORE, exist_ok=True)
    return STORE


def parse(text, known_platforms=()):
    """(entry, error) for one definition's text. `entry` is None on any problem.

    Every failure here is reported to the user rather than logged, because the
    file is something they chose to send and a silent refusal looks like the
    import button doing nothing.
    """
    try:
        data = json.loads(text)
    except ValueError as error:
        return None, "That is not valid JSON: %s" % error

    if not isinstance(data, dict):
        return None, "A definition has to be a JSON object, not a %s." % type(data).__name__

    version = data.pop("format", FORMAT)
    if not isinstance(version, int) or version > FORMAT:
        return None, (
            "This definition says format %s, and this version of the plugin "
            "understands up to %d. Update the plugin." % (version, FORMAT)
        )

    problems = schema.validate(data, known_platforms, imported=True)
    if problems:
        return None, "\n".join(problems)

    data["imported"] = True

    # **`{"dsu": true}` becomes the real thing here, and only here.**
    #
    # An imported definition may say it speaks the DSU protocol but may not name
    # the server -- see `schema.validate`, where that is refused as the power
    # `helper` is refused for. Expanding the flag at the one point every
    # definition passes through means nothing downstream has to know the
    # difference: `emu_install.motion_server`, `tools_report` and the launcher
    # writer all read `motion["server"]` exactly as they do for a bundled entry.
    #
    # No `verify` counterpart. A bundled entry names a file to look in to say
    # whether the emulator is really pointed at the server; deriving one for an
    # arbitrary definition would mean guessing at its config format, and a wrong
    # guess reports a working setup as broken.
    if (data.get("motion") or {}).get("dsu"):
        data["motion"] = {"server": deck_gyro.DSU_SERVER}

    return data, ""


def load(known_platforms=()):
    """(entries, problems) for every definition on disk.

    A bad file is skipped and reported rather than raising: one unreadable
    definition must not take the catalog -- and with it every bundled emulator
    -- down with it.
    """
    entries, problems = [], []
    try:
        names = sorted(os.listdir(STORE))
    except OSError:
        return entries, problems

    for name in names:
        if not name.endswith(SUFFIX):
            continue
        path = os.path.join(STORE, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read(MAX_BYTES + 1)
        except OSError as failure:
            problems.append("%s could not be read: %s" % (name, failure))
            continue
        if len(text) > MAX_BYTES:
            problems.append("%s is larger than %dKB." % (name, MAX_BYTES // 1024))
            continue
        entry, error = parse(text, known_platforms)
        if error:
            problems.append("%s was not loaded:\n%s" % (name, error))
            continue
        entry["source_file"] = name
        entries.append(entry)

    if problems:
        for problem in problems:
            decky.logger.warning("Imported emulator: %s", problem)
    return entries, problems


def path_for(entry_id):
    """Where the definition for `entry_id` is kept."""
    return os.path.join(STORE, "%s%s" % (entry_id, SUFFIX))


def save(text, known_platforms=(), replace=False):
    """Validate a definition and keep it. Returns (entry, error).

    `replace` has to be asked for. Importing a second definition with an id
    already in use is far more likely to be a mistake than an update, and
    silently overwriting one the user cannot re-obtain is not recoverable.
    """
    entry, error = parse(text, known_platforms)
    if error:
        return None, error

    destination = path_for(entry["id"])
    if os.path.exists(destination) and not replace:
        return None, (
            "A definition for %r is already imported. Remove it first, or "
            "choose Replace." % entry["id"]
        )

    store_dir()
    temporary = destination + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, destination)
    entry["source_file"] = os.path.basename(destination)
    return entry, ""


def remove(entry_id):
    """Forget an imported definition. Returns (removed, error)."""
    path = path_for(entry_id)
    if not os.path.isfile(path):
        return False, "There is no imported definition for %r." % entry_id
    try:
        os.remove(path)
    except OSError as error:
        return False, "Could not remove it: %s" % error
    return True, ""
