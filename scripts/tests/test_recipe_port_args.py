#!/usr/bin/env python3
"""A recipe bump does not hand a port a ROM path it never asked for.

    python scripts/tests/test_recipe_port_args.py

A port that finds its own game declares no `args`. `emulators.py` knows an
empty `args` means empty for such a program; the recipe upgrade did not, and
wrote `{rom}` -- which would put a path on the command line of every port at
once, the first time any of their recipes moved.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


def install(entry_id, recipe, args):
    """A record as an install made under `recipe` would have left it.

    A flatpak for the reason `test_source_moved` gives: `validate` wants a
    `path` target to exist and this suite runs on Windows too.
    """
    emulators._write([{
        "id": entry_id, "name": entry_id, "kind": "flatpak",
        "target": "org.example.%s" % entry_id,
        "args": args, "extensions": ["z64"], "databases": [],
        "platform": "Nintendo - Nintendo 64", "catalog_recipe": recipe,
        "game_in_config": True,
    }])
    plugin._emulators = emulators.list_emulators()


def stored(entry_id):
    return emulators.find(entry_id) or {}


section("a port whose recipe moved keeps an empty command line")

# Any of the nine. This one takes its ROM beside the binary.
_PORT = emulator_catalog.find("shipwright")
check("the entry really declares no arguments", _PORT.get("args"), None)
check("and it finds its own game",
      emulator_catalog.finds_its_game(_PORT), True)

install("shipwright", _PORT.get("recipe", 1) - 1, "")
run(plugin._upgrade_emulator_recipes())
check("the upgrade leaves the command line empty", stored("shipwright").get("args"), "")

section("an emulator whose recipe moved still gets the path")

# The other half, or the fix would stop every emulator receiving its ROM.
_EMULATOR = emulator_catalog.find("azahar")
check("the entry declares a path", "{rom}" in (_EMULATOR.get("args") or ""), True)

emulators._write([{
    "id": "azahar", "name": "Azahar", "kind": "flatpak",
    "target": "org.azahar_emu.Azahar",
    "args": "", "extensions": ["3ds"], "databases": [],
    "platform": "Nintendo - Nintendo 3DS",
    "catalog_recipe": _EMULATOR.get("recipe", 1) - 1,
}])
plugin._emulators = emulators.list_emulators()
run(plugin._upgrade_emulator_recipes())
check("the upgrade restores its arguments", stored("azahar").get("args"),
      _EMULATOR.get("args"))

emulators._write([])
plugin.loop.close()


if __name__ == "__main__":
    summary()
