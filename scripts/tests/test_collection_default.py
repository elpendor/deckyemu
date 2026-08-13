#!/usr/bin/env python3
"""A new default must not re-file somebody's existing library.

    python scripts/tests/test_collection_default.py

`collection_per_platform` defaults on. Settings are merged from the defaults
when they are read rather than written at install, so a changed default reaches
everyone who never opened that toggle -- and this one decides which shelf a game
goes on. Left alone, an upgrade would put the next added game on a per-system
collection while every game already added stayed on the shared one: nothing
moved, and a library split across two schemes with no way to tell why.

`_pin_collection_layout` is the whole of the answer, and the two things it must
get right are that an existing library keeps what it had and a fresh install
does not get pinned to the old behaviour by accident.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
import store  # noqa: E402

section("the per-system default does not move an existing library")

plugin = main.Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


def reset(library):
    """Back to an install that has never seen the setting, with this library."""
    store.set_settings({})
    settings = store._read_json(store.SETTINGS_PATH, {})
    settings.pop("collection_per_platform", None)
    store._write_json(store.SETTINGS_PATH, settings)
    store.clear_library()
    if library:
        store.remember_game(920, {"app_id": 920, "title": "Filed Already",
                                  "collection": "DeckyEmu"})


check("a shelf per system is what a fresh install gets",
      store.DEFAULT_SETTINGS["collection_per_platform"], True)

reset(library=False)
run(plugin._pin_collection_layout())
check("nothing filed yet, so nothing is pinned",
      "collection_per_platform" in store.stored_keys(), False)
check("and the new default stands",
      store.get_settings()["collection_per_platform"], True)

reset(library=True)
run(plugin._pin_collection_layout())
# Written down rather than left to the default, so the next release changing it
# again cannot move these games either.
check("games already filed keep the layout they were filed under",
      store.get_settings()["collection_per_platform"], False)
check("recorded explicitly, not merged in", "collection_per_platform" in store.stored_keys(), True)

# The panel writes the setting when the toggle is used, and that write is what
# says the user has decided. Startup must never overrule it -- including back to
# the value it would have pinned anyway.
store.set_settings({"collection_per_platform": True})
run(plugin._pin_collection_layout())
check("a choice already made is left alone",
      store.get_settings()["collection_per_platform"], True)

store.clear_library()
plugin.loop.close()


if __name__ == "__main__":
    from harness import summary

    summary()
