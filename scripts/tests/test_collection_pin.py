#!/usr/bin/env python3
"""The collection layout is pinned from what the games are filed into.

    python scripts/tests/test_collection_pin.py

`collection_per_platform` defaults on, and settings are merged from the defaults
when read rather than written at install. So a one-time migration decides what
an existing library should keep -- and it used to decide from "the library is not
empty".

That is true for exactly one population, people upgrading across the release
that added per-platform collections, and false for everyone else: the key is
only ever stored by that migration or by the toggle in the panel, so any install
whose owner added a game before their first restart had the layout switched off
underneath them. A state reset reaches the same place from the other side, by
clearing settings.json and leaving the library newer than it.

The result was the exact fault the migration exists to prevent -- a library
split across both schemes, some games on `[DeckyEmu] SNES` and the next one on
`DeckyEmu`.

Every entry records the shelf it was filed into, so that is what decides it now.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import REPO_ROOT  # noqa: E402

sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
import store  # noqa: E402

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


class _Pin(main.Plugin):
    """The composed class; `_collection_name` is Plugin's, not the mixin's."""

    def _run(self, function, *args, **kwargs):
        future = LOOP.create_future()
        try:
            future.set_result(function(*args, **kwargs))
        except Exception as error:  # noqa: BLE001 - surfaced by the await
            future.set_exception(error)
        return future

    async def rebuild_launchers(self):
        return {}


def _fresh(*collections):
    """A settings file with nothing chosen, and a library filed as given."""
    for path in (store.SETTINGS_PATH, store.LIBRARY_PATH):
        try:
            os.remove(path)
        except OSError:
            pass
    for index, collection in enumerate(collections, start=1):
        entry = {
            "app_id": index, "title": "Game %d" % index, "rom_path": "/roms/g%d.sfc" % index,
            "core_id": "bsnes", "core_path": "/c.so", "launcher_path": "/l%d.sh" % index,
        }
        # None means the collection was never recorded -- games added before that
        # field existed, which is the same old install the migration is for.
        if collection is not None:
            entry["collection"] = collection
        store.remember_game(index, entry)


_plugin = _Pin()


def _pin():
    LOOP.run_until_complete(_plugin._pin_collection_layout())
    return store.get_settings()["collection_per_platform"]


section("a library already on per-system shelves keeps them")

# The case that kept happening: a fresh install, a game added before the first
# restart, so the game is filed per platform and the settings know nothing.
_fresh("[DeckyEmu] SNES")
check("the setting starts at its default", store.get_settings()["collection_per_platform"], True)
check("and a per-system library keeps the layout it is on", _pin(), True)
check("written down, so the question is not asked again",
      "collection_per_platform" in store.stored_keys(), True)

# Mixed is still per-system: one game on the shared shelf is what this fault
# produced, and the answer is to keep the layout the rest are on rather than
# ratify the split.
_fresh("[DeckyEmu] SNES", "[DeckyEmu] PS1", "DeckyEmu")
check("a library that has already been split keeps per-system", _pin(), True)


section("and a library on one shared shelf still pins to shared")

# The population this migration was written for, which must not regress: every
# game on one name, from before per-platform collections existed.
_fresh("DeckyEmu", "DeckyEmu")
check("an old shared library is pinned to shared", _pin(), False)

# Older still: filed before the collection was recorded at all. Nothing says
# per-system, so this is the same old install.
_fresh(None, None)
check("and so is one that predates the record", _pin(), False)


section("and nothing is decided without evidence")

_fresh()
check("an empty library is left alone", _pin(), True)
check("and nothing is written down for it",
      "collection_per_platform" in store.stored_keys(), False)

# A choice already made is the user's, in either direction.
_fresh("[DeckyEmu] SNES")
store.set_settings({"collection_per_platform": False})
check("a stored choice is never overridden", _pin(), False)

LOOP.close()


if __name__ == "__main__":
    summary()
