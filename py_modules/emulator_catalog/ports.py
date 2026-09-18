"""A list of native ports, sent as one file.

A port is a catalog entry like any imported emulator -- installed from a
release, set up, launched from a Steam shortcut -- that plays one game rather
than a system. The list arrives as `<name>.deckyports.json` through Transfer,
is shown and confirmed like a definition, and each port in it is kept as its own
definition file in `imported.STORE`, marked `port`. So removing one, listing
them and launching them is the machinery definitions already have.

The list lives outside the repository on purpose: a port names its game, and
the tree names none.
"""

import hashlib
import json

from . import imported

#: What the transfer panel offers to import as a ports list.
SUFFIX = ".deckyports.json"

#: The list's own shape. Each entry inside is a definition at `imported.FORMAT`.
FORMAT = 1

MAX_BYTES = 1024 * 1024


def parse(text, known_platforms=()):
    """(ports, problems) for a ports list's text.

    `ports` holds every entry that validated, already marked `port`; `problems`
    names each one that did not, so one bad entry does not cost the rest.
    """
    try:
        data = json.loads(text)
    except ValueError as failure:
        return [], ["That is not valid JSON: %s" % failure]
    if not isinstance(data, dict) or not isinstance(data.get("ports"), list):
        return [], ["A ports list is a JSON object with a \"ports\" list."]
    version = data.get("format", FORMAT)
    if not isinstance(version, int) or version > FORMAT:
        return [], ["This list says format %s, and this version of the plugin "
                    "understands up to %d. Update the plugin." % (version, FORMAT)]

    ports, problems, seen = [], [], set()
    for index, item in enumerate(data["ports"]):
        if not isinstance(item, dict):
            problems.append("Entry %d is not an object." % (index + 1))
            continue
        item = dict(item, port=True)
        entry, error = imported.parse(json.dumps(item), known_platforms)
        label = item.get("name") or item.get("id") or "Entry %d" % (index + 1)
        if error:
            problems.append("%s was not loaded:\n%s" % (label, error))
            continue
        if entry["id"] in seen:
            problems.append("%s appears twice in the list." % entry["id"])
            continue
        seen.add(entry["id"])
        entry["_text"] = json.dumps(item, indent=2)
        ports.append(entry)
    return ports, problems


def save(text, known_platforms=()):
    """Keep every valid port in the list. Returns (saved, problems).

    A port already imported is replaced: a list sent again is how it is updated.
    An id already used by an imported emulator that is not a port is refused,
    because overwriting that would quietly turn somebody's emulator into a port.
    """
    ports, problems = parse(text, known_platforms)
    saved = []
    for entry in ports:
        existing = _existing(entry["id"])
        if existing is not None and not existing.get("port"):
            problems.append("%s was not loaded: %r is already an imported emulator."
                            % (entry.get("name", entry["id"]), entry["id"]))
            continue
        kept, error = imported.save(entry.pop("_text"), known_platforms, replace=True)
        if error:
            problems.append("%s was not loaded:\n%s" % (entry.get("name", entry["id"]), error))
            continue
        saved.append(kept)
    return saved, problems


def _existing(entry_id):
    """The imported definition stored under `entry_id`, or None."""
    try:
        with open(imported.path_for(entry_id), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def is_replacing(entry_id):
    """Whether importing `entry_id` would replace a port already imported."""
    existing = _existing(entry_id)
    return existing is not None and bool(existing.get("port"))


#: The file's own bytes say this is the game the port plays.
ITS_GAME = "its game"

#: Nothing contradicts it: the port names no id, or the file could not be read
#: that far. Offered, because hiding a port for a file it may well play costs
#: more than showing one row too many.
UNKNOWN = "unknown"

#: The file reads as a different game. Not offered at all.
NOT_ITS_GAME = "not its game"

#: The file is the right game, dumped in a way the port refuses. Offered, and
#: the panel says so: this is the one verdict the user can act on, because the
#: answer is another dump of a game they already have.
WRONG_DUMP = "wrong dump"


def _sha1_of(path):
    """The file's SHA-1, or "" if it could not be read."""
    reader = hashlib.sha1()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                reader.update(block)
    except OSError:
        return ""
    return reader.hexdigest()


def verdict(entry, rom_path):
    """What a port's `needs` says about `rom_path`: one of the three above.

    `needs.id` is a check on the file's own bytes, and the strongest evidence
    there is about a particular file -- every other term in the ordering is
    about its extension or the folder it sits in. So a match is not merely
    allowed through: it is the answer.

    The check runs for every extension the port lists, so a list declares an
    `id` only where all of them keep it at that offset. Nothing here can tell a
    compressed image from a raw one.

    `needs.sha1` then says which dumps of that game the port will actually take,
    and these projects publish the list. It is checked **after** the id and only
    when the id matched, which is what keeps it cheap: a file that is a
    different game entirely is already refused, so nothing reads a 40MB
    cartridge -- let alone a disc -- to find that out. Without it the port does
    the checking itself, after the game is added and a first launch has spent
    minutes building an archive it then throws away.
    """
    needs = entry.get("needs") or {}
    identity = needs.get("id") or {}
    wanted = [value for value in (identity.get("is") or ()) if value]
    if not wanted:
        return _dump_verdict(needs, rom_path, UNKNOWN)
    try:
        with open(rom_path, "rb") as handle:
            handle.seek(identity.get("at") or 0)
            raw = handle.read(max(len(value) for value in wanted))
    except OSError:
        return UNKNOWN
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return UNKNOWN
    if not any(text.startswith(value) for value in wanted):
        return NOT_ITS_GAME
    return _dump_verdict(needs, rom_path, ITS_GAME)


def _dump_verdict(needs, rom_path, matched):
    """`matched`, unless the hashes say this dump is one the port refuses.

    A file that could not be read is not a wrong dump -- it is a file nothing
    can say anything about, and the port is still offered, which is what every
    other unreadable case here does.
    """
    digests = [value.lower() for value in (needs.get("sha1") or ()) if value]
    if not digests:
        return matched
    got = _sha1_of(rom_path)
    if not got:
        return matched
    return matched if got in digests else WRONG_DUMP


def wanted_file(entry):
    """The line naming the file this port wants, or "" for one that says none."""
    return (entry.get("needs") or {}).get("what", "")
