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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import emulators  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_PORT = {
    "id": "shipshape",
    "name": "Shipshape",
    "kind": "path",
    "target": "/home/deck/deckyemu/emulators/shipshape/shipshape.AppImage",
    "port": True,
    "databases": ["Nintendo - Nintendo 64"],
}

_SETTINGS = {
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    "collection_per_platform": True,
    "collection_template": "[{name}] {platform}",
}

# `is_port` asks the catalog, not the record, and every port is an imported
# definition -- nothing bundled is one. Answered here for this id alone so the
# test stays about `collection_targets`.
_real_is_port = emulators.is_port
emulators.is_port = lambda one: one == _PORT["id"] or _real_is_port(one)

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = [_PORT]
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


store.set_settings(_SETTINGS)
store.clear_library()
store.remember_games({
    900: {
        "app_id": 900, "title": "Sunken Keep", "core_id": "emu:shipshape",
        "system": "Nintendo - Nintendo 64", "collection": "[DeckyEmu] Ports",
        "rom_path": "/home/deck/deckyemu/roms/n64/keep.z64", "launcher_path": "",
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
# collections being switched off means, and the check would offer to take the
# game off the shelf it is correctly on.
check("the game has no target at all", "900" in _gone["targets"], False)
check("and no title is offered for it", "900" in _gone["titles"], False)


section("a game whose core is simply unknown is still answered")

# Only an emulator id is skipped. A libretro game with a core that is not
# installed still belongs on its system's shelf, and always did.
store.remember_games({
    901: {
        "app_id": 901, "title": "Marsh Cart", "core_id": "mupen64plus_next_libretro",
        "system": "Nintendo - Nintendo 64", "collection": "", "rom_path": "",
        "launcher_path": "",
    },
})
_mixed = run(plugin.collection_targets())
check("the libretro game keeps its shelf", _mixed["targets"].get("901"), "[DeckyEmu] N64")
check("and the port with no emulator is still skipped", "900" in _mixed["targets"], False)


section("and it comes back with the port")

plugin._emulators = [_PORT]
_back = run(plugin.collection_targets())
check("the skip is not sticky", _back["targets"].get("900"), "[DeckyEmu] Ports")

store.clear_library()
emulators.is_port = _real_is_port
plugin.loop.close()


if __name__ == "__main__":
    summary()
