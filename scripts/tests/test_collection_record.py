#!/usr/bin/env python3
"""Which collections are ours is recorded, not inferred from their names.

    python scripts/tests/test_collection_record.py

Ownership used to be decided by building a pattern out of the current naming
settings and matching collection names against it. That answers a question about
the past by reading the present, so it is wrong exactly when it matters: change
the template, turn per-system naming off, or edit the base name, and every shelf
made under the old naming stops matching. It then becomes invisible to the one
thing that would have cleared it away -- permanently, because nothing else knows
those shelves were ever ours.

So a collection is recorded the moment a game is filed into it, and that record
is what `collection_shape` hands the frontend.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

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
    "collection_per_platform": True,
    "collection_template": "[{name}] {platform}",
    "platform_names": "short",
}


def _reset():
    store.clear_library()
    store.forget_collections(store.known_collections())


_reset()
store.set_settings(dict(_SETTINGS))


section("filing a game is what makes a collection ours")

check("nothing is claimed to begin with", store.known_collections(), [])

store.remember_game(901, {"app_id": 901, "title": "A", "collection": "[DeckyEmu] SNES"})
check("recording a game records the shelf it went on",
      store.known_collections(), ["[DeckyEmu] SNES"])

# No call site has to remember to say so -- it happens where the entry is
# written, which is the only place that can know it happened.
store.remember_games({
    902: {"app_id": 902, "title": "B", "collection": "[DeckyEmu] N64"},
    903: {"app_id": 903, "title": "C", "collection": "[DeckyEmu] SNES"},
})
check("a batch records every distinct shelf in it",
      sorted(store.known_collections()), ["[DeckyEmu] N64", "[DeckyEmu] SNES"])
check("and never twice", len(store.known_collections()), 2)

store.remember_game(904, {"app_id": 904, "title": "D", "collection": ""})
check("a game on no shelf adds nothing", len(store.known_collections()), 2)


section("the record outlives the naming that produced it")

# The whole point. Under the old rule these two shelves stopped being ours the
# moment the template changed, and an empty one could never be found again.
store.set_settings({"collection_template": "{platform} ({name})"})
_shape = run(plugin.collection_shape())
check("the pattern describes the new naming",
      _shape["template"], "{platform} ({name})")
check("and the record still names the shelves made under the old one",
      sorted(_shape["known"]), ["[DeckyEmu] N64", "[DeckyEmu] SNES"])

store.set_settings({"collection_per_platform": False})
check("turning per-system naming off does not lose them either",
      len(run(plugin.collection_shape())["known"]), 2)

store.set_settings({"add_to_collection": False})
check("nor does switching collections off",
      len(run(plugin.collection_shape())["known"]), 2)

store.set_settings(dict(_SETTINGS))


section("and stops when the collection does")

_forgotten = run(plugin.forget_collections(["[DeckyEmu] SNES"]))
check("a deleted collection is no longer claimed", _forgotten["forgotten"],
      ["[DeckyEmu] SNES"])
check("the others are left alone", store.known_collections(), ["[DeckyEmu] N64"])
# Or the record only grows, and a name this plugin once used would be claimed
# again if the user later made a collection of their own by that name -- the one
# way recording ownership could be worse than deriving it.
check("forgetting one that was never claimed changes nothing",
      run(plugin.forget_collections(["Shooters I like"]))["forgotten"], [])
check("and forgetting nothing is not an error",
      run(plugin.forget_collections([]))["forgotten"], [])


section("an install from before the record existed is given one")

# The record is written as games are filed, so a library that predates it starts
# with nothing claimed -- and every shelf it made would fall back to the name
# pattern, which is the thing that loses them as soon as the naming changes.
_reset()
store.remember_games({
    905: {"app_id": 905, "title": "E", "collection": "[Old] SNES"},
    906: {"app_id": 906, "title": "F", "collection": "[Old] N64"},
})
store.forget_collections(store.known_collections())
check("nothing is claimed, as on an install that just updated",
      store.known_collections(), [])

run(plugin._claim_filed_collections())
check("startup claims what the library says it is filed into",
      sorted(store.known_collections()), ["[Old] N64", "[Old] SNES"])
# Runs every startup, so it has to settle rather than grow.
run(plugin._claim_filed_collections())
check("and claims nothing further on the next start",
      len(store.known_collections()), 2)


section("the record survives a restart, because it is on disk")

check("it is kept beside the library rather than in the settings",
      os.path.basename(store.COLLECTIONS_PATH), "collections.json")
check("and reads back what was written, in the order it was claimed",
      store.known_collections(), ["[Old] SNES", "[Old] N64"])

_reset()
plugin.loop.close()


if __name__ == "__main__":
    summary()
