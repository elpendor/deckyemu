#!/usr/bin/env python3
"""A game that runs on a port is filed as a port, not as its system.

    python scripts/tests/test_port_shelf.py

A port declares a system so the game keeps the right name and artwork, and the
shelf is the one thing that must not follow it: a port is not an emulator for
that system, and a collection holding both says the wrong thing about each. So
the platform half of a collection name is read from what runs the game.

Every port and every emulator here is made up.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import platforms  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = []
plugin._install = None

_SETTINGS = {
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    "collection_per_platform": True,
    "collection_template": "[{name}] {platform}",
    "platform_names": "short",
}

_EMULATOR = {
    "id": "emu:someemu",
    "display_name": "SomeEmu",
    "system_name": "GameCube",
    "databases": ["Nintendo - GameCube"],
}

#: The same system, reached by a program that plays one game on it.
_PORT = dict(_EMULATOR, id="emu:someport", display_name="SomePort", port=True)


section("the shelf follows what runs the game")

check("an emulator files its game under the system",
      Plugin._entry_platform(_SETTINGS, _EMULATOR), "GameCube")
check("a port files its game under Ports",
      Plugin._entry_platform(_SETTINGS, _PORT), platforms.PORTS)
check("which is the collection it lands in",
      Plugin._collection_name(_SETTINGS, Plugin._entry_platform(_SETTINGS, _PORT)),
      "[DeckyEmu] Ports")

# The long naming style renames every system; a port has one name either way,
# because "Ports" is what it is rather than a system it could be called two
# things.
_long = dict(_SETTINGS, platform_names="full")
check("and it reads the same under long system names",
      Plugin._entry_platform(_long, _PORT), platforms.PORTS)

# Read from the core, so a record written before any of this -- or one whose
# port was removed and installed again -- is filed by what it runs on now.
check("a record's stored platform does not override it",
      Plugin._entry_platform(_SETTINGS, _PORT, {"platform": "GameCube"}),
      platforms.PORTS)

# Nothing runs it any more: the core is gone, and the record is all there is.
check("a game whose port is uninstalled keeps the shelf it was on",
      Plugin._entry_platform(_SETTINGS, None, {"platform": "Ports"}), "Ports")


section("a core entry built from a record knows which it is")

# The hole the checks above could not see. They hand `_entry_platform` a core
# dict written here with `port` already on it, while the plugin builds that dict
# from a registered record -- and the builder was not setting it, so a game
# added through the panel was filed under its system after all.

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402
from emulator_catalog import imported, ports  # noqa: E402

_LIST = json.dumps({"format": 1, "ports": [{
    "id": "shelf-port",
    "name": "Shelf Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/shelf-port",
               "asset": "^ShelfPort-linux-x86_64\.AppImage$"},
    "args": "",
    "root": ".local/share/SomeStudio/ShelfPort",
    "databases": ["Nintendo - GameCube"],
    "needs": {"what": "the game's own disc image", "extensions": ["iso"]},
    "game_config": {"format": "json-flat",
                    "path": ".local/share/SomeStudio/ShelfPort/config.json",
                    "keys": {"backend.gamePath": "{rom}"}},
}]})

try:
    ports.save(_LIST, [])
    emulator_catalog.reload_imported()

    _record = {"id": "shelf-port", "name": "Shelf Port", "kind": "path",
               "target": "/tmp/ShelfPort.AppImage", "args": "",
               "databases": ["Nintendo - GameCube"], "extensions": ["iso"]}
    _core = emulators.to_core_entry(_record)
    check("the core entry says it is a port", _core.get("port"), True)
    check("so a game added on it lands on the ports shelf",
          Plugin._entry_platform(_SETTINGS, _core), platforms.PORTS)

    _plain = dict(_record, id="not-in-catalog")
    check("and an emulator's entry says it is not",
          emulators.to_core_entry(_plain).get("port"), False)
finally:
    imported.remove("shelf-port")
    emulator_catalog.reload_imported()


if __name__ == "__main__":
    summary()
