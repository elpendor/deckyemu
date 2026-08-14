#!/usr/bin/env python3
"""Switching collections off has to reach games that are already filed.

    python scripts/tests/test_collection_off.py

Renaming a collection moves the library; turning collections off did not. The
plan could not express it -- a move needed a target, so "take it out and put it
nowhere" was silently no move at all, and the switch looked inert on any library
with games in it. That is the same failure the migration was written to fix for
renames, left in the one control that turns the whole feature off.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

# Built by hand rather than through `_main`, which detects RetroArch and scans
# cores: none of that is involved in deciding where a game is filed, and a test
# that starts the whole plugin to ask one question is a test that fails for
# reasons it is not about.
plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = []
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)

_SETTINGS = {
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    "collection_per_platform": False,
    "collection_template": "[{name}] {platform}",
}


def _library(count=3):
    store.clear_library()
    entries = {}
    for index in range(count):
        app_id = 900 + index
        entries[app_id] = {
            "app_id": app_id,
            "title": "Game %d" % index,
            "core_id": "",
            "system": "Nintendo - Super Nintendo Entertainment System",
            "collection": "DeckyEmu",
        }
    store.remember_games(entries)


section("the name of the collection a game belongs in")

check("with collections on, a game belongs somewhere",
      Plugin._collection_name(dict(_SETTINGS), ""), "DeckyEmu")
# Empty is a real answer, not a missing one. The switch was read at four call
# sites and missed at the fifth, which is why it now lives in one place.
check("with collections off, it belongs nowhere",
      Plugin._collection_name(dict(_SETTINGS, add_to_collection=False), ""), "")
check("and a name cleared to nothing is the same answer",
      Plugin._collection_name(dict(_SETTINGS, collection_name="  "), ""), "")

section("turning collections off plans to take the games out")

store.set_settings(dict(_SETTINGS))
_library(3)

store.set_settings({"add_to_collection": False})
_plan = run(plugin.plan_collection_migration())["moves"]
check("every filed game is planned out of its collection", len(_plan), 3)
check("each one out of the collection it was in",
      sorted({move["from"] for move in _plan}), ["DeckyEmu"])
# The empty target is the whole point: it is what tells the frontend to remove
# without adding, and to delete the collection only if that leaves it empty.
check("and into nothing at all", sorted({move["to"] for move in _plan}), [""])

section("and turning them back on plans to file them again")

store.set_settings({"add_to_collection": True})
# A game recorded as belonging nowhere is what the frontend leaves behind after
# an unfile, so this is the state the switch is really turned back on from.
_unfiled = store.get_library()
for _entry in _unfiled.values():
    _entry["collection"] = ""
store.remember_games({int(k): v for k, v in _unfiled.items()})

_back = run(plugin.plan_collection_migration())["moves"]
check("every game is planned back into a collection", len(_back), 3)
check("out of nowhere", sorted({move["from"] for move in _back}), [""])
check("and into the collection the settings name",
      sorted({move["to"] for move in _back}), ["DeckyEmu"])

section("a library already in the right state plans nothing")

_settled = store.get_library()
for _entry in _settled.values():
    _entry["collection"] = "DeckyEmu"
store.remember_games({int(k): v for k, v in _settled.items()})
check("with collections on and everything filed", run(plugin.plan_collection_migration())["moves"], [])

store.set_settings({"add_to_collection": False})
for _entry in _settled.values():
    _entry["collection"] = ""
store.remember_games({int(k): v for k, v in _settled.items()})
# The case a naive "target != current" would get wrong: both empty is agreement,
# not a move to make on every settings read.
check("and with collections off and nothing filed",
      run(plugin.plan_collection_migration())["moves"], [])

store.clear_library()
store.set_settings(dict(_SETTINGS))
plugin.loop.close()


if __name__ == "__main__":
    summary()
