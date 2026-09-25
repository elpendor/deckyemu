#!/usr/bin/env python3
"""A port whose emulator was removed is not reported as on the wrong shelf.

    python scripts/tests/test_collection_emulator_gone.py

`_entry_platform` reads `port` off the core, not off the record, so a port
removed and re-added lands in the same place. With the emulator deregistered
there is no core, `port` is never seen, and the port is computed as belonging
to its own system instead -- so the library check reported four ports as
missing from an N64 shelf and as sitting in a Ports collection they had left.

Both halves of that are wrong and pressing either would have moved the games.
The right answer with no record is no answer: skip the game, say nothing, and
let reinstalling the port restore it.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import emulator_catalog  # noqa: E402
import store  # noqa: E402
from emulator_catalog import imported  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_PORT = {
    "id": "shipshape",
    "name": "Shipshape",
    "kind": "path",
    "target": "/home/deck/deckyemu/emulators/shipshape/shipshape.AppImage",
    "databases": ["Nintendo - Nintendo 64"],
}

_SETTINGS = {
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    "collection_per_platform": True,
    "collection_template": "[{name}] {platform}",
}

# **A real imported definition, not a stubbed `is_port`.** Every port is one --
# nothing bundled is -- and `is_port` asks the catalog rather than the record,
# so a stub would test the skip against a port the catalog never knew.
_DEFINITION = json.dumps({"format": 1, "definitions": [{
    "id": _PORT["id"],
    "port": True,
    "name": _PORT["name"],
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/shipshape",
               "asset": r"^Shipshape-linux-x86_64\.AppImage$"},
    "args": "{rom}",
    "root": ".local/share/SomeStudio/Shipshape",
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {"what": "the game's own ROM", "extensions": ["z64"]},
}]})


def run(coro):
    return plugin.loop.run_until_complete(coro)


# **Taken out before this file ends, not at exit.** `scripts/test_backend.py`
# runs every test in one process, so a definition left in the catalog is still
# there when a later file checks that the catalog holds only the bundled
# entries -- which is how an `atexit` version of this was caught.
_saved, _refused = imported.save_many(_DEFINITION, [])
assert _saved and not _refused, (_saved, _refused)
emulator_catalog.reload_imported()

try:
    plugin = Plugin()
    plugin.loop = asyncio.new_event_loop()
    plugin._cores = []
    plugin._emulators = [_PORT]
    plugin._install = None

    store.set_settings(_SETTINGS)
    store.clear_library()
    store.remember_games({
        900: {
            "app_id": 900, "title": "Sunken Keep", "core_id": "emu:shipshape",
            "system": "Nintendo - Nintendo 64", "collection": "[DeckyEmu] Ports",
            "rom_path": "/home/deck/deckyemu/roms/n64/keep.z64",
            "launcher_path": "",
        },
    })

    section("while the port is registered")

    _filed = run(plugin.collection_targets())
    check("it is filed as a port, not as its system",
          _filed["targets"].get("900"), "[DeckyEmu] Ports")

    section("once its emulator is gone")

    plugin._emulators = []
    _gone = run(plugin.collection_targets())
    # Not "" either: an empty target reads as "belongs nowhere", which is what
    # collections being switched off means, and the check would then offer to
    # take the game off the shelf it is correctly on.
    check("the game has no target at all", "900" in _gone["targets"], False)
    check("and no title is offered for it", "900" in _gone["titles"], False)

    section("a game whose core is simply unknown is still answered")

    # Only an emulator id is skipped. A libretro game whose core is not
    # installed still belongs on its system's shelf, and always did.
    store.remember_games({
        901: {
            "app_id": 901, "title": "Marsh Cart",
            "core_id": "mupen64plus_next_libretro",
            "system": "Nintendo - Nintendo 64", "collection": "",
            "rom_path": "", "launcher_path": "",
        },
    })
    _mixed = run(plugin.collection_targets())
    check("the libretro game keeps its shelf",
          _mixed["targets"].get("901"), "[DeckyEmu] N64")
    check("and the port with no emulator is still skipped",
          "900" in _mixed["targets"], False)

    section("and it comes back with the port")

    plugin._emulators = [_PORT]
    _back = run(plugin.collection_targets())
    check("the skip is not sticky", _back["targets"].get("900"), "[DeckyEmu] Ports")

    store.clear_library()
    plugin.loop.close()
finally:
    imported.remove(_PORT["id"])
    emulator_catalog.reload_imported()


if __name__ == "__main__":
    summary()
