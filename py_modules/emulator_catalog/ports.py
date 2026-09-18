"""What a port wants, and whether a file is it.

A port is a catalog entry like any imported emulator -- installed from a
release, set up, launched from a Steam shortcut -- that plays one game rather
than a system. It is stored, listed and removed by `imported`, exactly as an
emulator definition is; `port` in the entry is the whole difference.

What is here is the part that has no equivalent for an emulator: deciding
whether a particular file is the game this port plays.
"""

import hashlib


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
