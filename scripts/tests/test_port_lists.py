#!/usr/bin/env python3
"""A list of native ports, sent as one file and imported like definitions.

    python scripts/tests/test_port_lists.py

Every entry is validated by the same parse an imported definition gets, marked
`port`, and kept as its own definition file -- so one bad entry costs only
itself, a list sent again updates what it holds, and an imported emulator that
is not a port is never overwritten by one.

Every port here is made up.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

import emulator_catalog  # noqa: E402
from emulator_catalog import imported, ports  # noqa: E402

KNOWN: list = []


def _port(port_id, name, **extra):
    entry = {
        "id": port_id,
        "name": name,
        "summary": "A native port of one game.",
        "source": {"kind": "github", "repo": "someone/%s" % port_id,
                   "asset": "^%s-linux-x86_64\\.AppImage$" % name.replace(" ", "")},
        "args": "",
        "root": ".local/share/SomeStudio/%s" % name.replace(" ", ""),
        "databases": ["Nintendo - GameCube"],
        "needs": {
            "what": "the game's own disc image",
            "extensions": ["iso", "gcm"],
            "id": {"at": 0, "is": ["ZZZE01"]},
        },
        "game_config": {
            "format": "json-flat",
            "path": ".local/share/SomeStudio/%s/config.json" % name.replace(" ", ""),
            "keys": {"backend.gamePath": "{rom}"},
        },
    }
    entry.update(extra)
    return entry


section("ports lists -- one file, many ports")

_created = []
try:
    text = json.dumps({"format": 1, "ports": [
        _port("first-port", "First Port"),
        _port("second-port", "Second Port"),
        {"id": "broken", "name": "Broken"},
    ]})
    found, problems = ports.parse(text, KNOWN)
    check("every valid port is read", [entry["id"] for entry in found],
          ["first-port", "second-port"])
    check("and each is marked a port", all(entry.get("port") for entry in found), True)
    check("an invalid entry is named rather than failing the list",
          len(problems) == 1 and problems[0].startswith("Broken"), True)
    check("something that is not a ports list says so",
          ports.parse(json.dumps({"id": "x"}), KNOWN)[0], [])

    saved, problems = ports.save(text, KNOWN)
    _created += ["first-port", "second-port"]
    check("saving keeps the valid ones", sorted(entry["id"] for entry in saved),
          ["first-port", "second-port"])
    emulator_catalog.reload_imported()
    in_catalog = {entry["id"]: entry for entry in emulator_catalog.CATALOG}
    check("and they reach the catalog as ports",
          (bool(in_catalog["first-port"].get("port")), bool(in_catalog["second-port"].get("port"))),
          (True, True))
    listed = {item["id"]: item for item in emulator_catalog.listing({})}
    check("the listing tells the tab it is a port", listed["first-port"]["port"], True)

    # A list sent again is how it is updated.
    renamed = json.dumps({"format": 1, "ports": [_port("first-port", "First Port Renamed")]})
    check("sending a list again replaces the port", ports.is_replacing("first-port"), True)
    saved, problems = ports.save(renamed, KNOWN)
    emulator_catalog.reload_imported()
    check("with its new details", emulator_catalog.find("first-port")["name"], "First Port Renamed")

    # An imported emulator that is not a port is somebody else's, and stays.
    plain = dict(_port("plain-emulator", "Plain Emulator"))
    del plain["game_config"]
    del plain["needs"]
    plain["args"] = "{rom}"
    imported.save(json.dumps(plain), KNOWN)
    _created.append("plain-emulator")
    saved, problems = ports.save(json.dumps({"ports": [_port("plain-emulator", "Plain Emulator")]}), KNOWN)
    check("a port never overwrites an imported emulator of the same id",
          (saved, any("already an imported emulator" in problem for problem in problems)),
          ([], True))
    section("a port is offered for its own game and no other")

    # `port` is what `parse` marks an entry with, so a fixture used without it
    # carries it here.
    _entry = dict(_port("disc-port", "Disc Port"), port=True)
    check("its extensions are what it reads, not what its system covers",
          emulator_catalog.extensions_for(_entry, {"Nintendo - GameCube": ["iso", "gcm", "rvz", "ciso"]}),
          ["gcm", "iso"])

    _folder = tempfile.mkdtemp()
    try:
        _its_game = os.path.join(_folder, "one.iso")
        with open(_its_game, "wb") as _handle:
            _handle.write(b"ZZZE01" + bytes(64))
        _another = os.path.join(_folder, "two.iso")
        with open(_another, "wb") as _handle:
            _handle.write(b"YYYP01" + bytes(64))
        _compressed = os.path.join(_folder, "three.iso")
        with open(_compressed, "wb") as _handle:
            _handle.write(bytes([0x89, 0xFF, 0x00, 0x01]))

        check("the disc it names is its game", ports.verdict(_entry, _its_game),
              ports.ITS_GAME)
        check("a disc of another game is not",
              ports.verdict(_entry, _another), ports.NOT_ITS_GAME)
        # A port lists the formats it reads, so a file it cannot identify is
        # still one it may play. Hiding it there costs more than offering it.
        check("a file too short or too compressed to read is not ruled out",
              ports.verdict(_entry, _compressed), ports.UNKNOWN)
        _no_id = dict(_port("open-port", "Open Port"), port=True)
        del _no_id["needs"]["id"]
        check("a port that names no id says nothing about the file",
              ports.verdict(_no_id, _another), ports.UNKNOWN)
        check("and what it wants is said in its own words",
              ports.wanted_file(_entry), "the game's own disc image")

        # These ports publish the dumps they take and check the hash
        # themselves -- after the game is added, and after a first launch has
        # spent minutes building an archive from a file it then refuses. Said
        # here instead, while the user is still looking at the file.
        import hashlib
        with open(_its_game, "rb") as _handle:
            _real = hashlib.sha1(_handle.read()).hexdigest()
        _hashed = dict(_entry)
        _hashed["needs"] = dict(_entry["needs"], sha1=[_real.upper()])
        check("a dump the port lists is its game", ports.verdict(_hashed, _its_game),
              ports.ITS_GAME)

        _strict = dict(_entry)
        _strict["needs"] = dict(_entry["needs"], sha1=["0" * 40])
        check("the right game dumped another way is told apart from the wrong game",
              ports.verdict(_strict, _its_game), ports.WRONG_DUMP)
        # And still refused outright when it is not even the same game: the
        # cheap check runs first, so nothing reads a 40MB cartridge to find out.
        check("a different game is refused before any hashing",
              ports.verdict(_strict, _another), ports.NOT_ITS_GAME)

        _gone = os.path.join(_folder, "vanished.iso")
        check("a file that cannot be read is not called a bad dump",
              ports.verdict(_strict, _gone), ports.UNKNOWN)
    finally:
        shutil.rmtree(_folder, ignore_errors=True)

    section("hashes only where they could mean something")

    _packed = dict(_port("packed-port", "Packed Port"), port=True)
    _packed["needs"] = dict(_packed["needs"], extensions=["iso", "rvz"],
                            sha1=["0" * 40])
    del _packed["needs"]["id"]
    from emulator_catalog import schema as _schema
    check("a hash beside a compressed format is refused",
          any("never of the dump inside it" in problem
              for problem in _schema.validate(_packed, known_platforms=(), imported=True)),
          True)
    _bad = dict(_port("bad-hash-port", "Bad Hash Port"), port=True)
    _bad["needs"] = dict(_bad["needs"], sha1=["not a hash"])
    check("and so is something that is not a SHA-1",
          any("40-character SHA-1" in problem
              for problem in _schema.validate(_bad, known_platforms=(), imported=True)),
          True)


    section("an id that could never be read is refused")

    # A compressed image keeps nothing at a fixed offset, so the check would
    # answer "unidentified, offer it anyway" for every one of them -- the port
    # back to being offered for every disc of its system, silently, over one
    # entry in an extensions list. Refused where the author can read why.
    _packed = dict(_port("packed-port", "Packed Port"), port=True)
    _packed["needs"]["extensions"] = ["iso", "rvz", "gcz"]
    _refusals = emulator_catalog.validate(_packed, imported=True)
    check("a compressed format beside an id is refused",
      any("'gcz', 'rvz'" in problem for problem in _refusals), True)
    check("and the message says what to do about it",
      any("Drop the id" in problem for problem in _refusals), True)

    _packed["needs"]["extensions"] = ["iso", "gcm"]
    check("the same entry without them is fine",
      emulator_catalog.validate(_packed, imported=True), [])

    # Only together. A port that reads compressed images and identifies
    # nothing is an ordinary port, matched on its extensions like the rest.
    _open = dict(_port("open-formats", "Open Formats"), port=True)
    _open["needs"]["extensions"] = ["iso", "rvz"]
    del _open["needs"]["id"]
    check("a compressed format without an id is allowed",
          emulator_catalog.validate(_open, imported=True), [])

    section("only a port declares the file it wants")

    _emulator = dict(_port("not-a-port", "Not A Port"))
    del _emulator["game_config"]
    _emulator["args"] = "{rom}"
    _problems = emulator_catalog.validate(_emulator, imported=True)
    check("an emulator with a needs block is refused",
          any("only a port declares" in problem for problem in _problems), True)

finally:
    for entry_id in _created:
        imported.remove(entry_id)
    emulator_catalog.reload_imported()


if __name__ == "__main__":
    summary()
