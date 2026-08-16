#!/usr/bin/env python3
"""Picking a game names it, even when SteamGridDB will not say what it is called.

    python scripts/tests/test_picked_name.py

`apply_art_candidate` fetched the artwork and then made a *second* request to
learn the game's name. That request answers "" on any failure -- no key, a
timeout, a `success: false` body -- and the empty name fell through
`titleAfterArtPick`, which cannot tell "nothing suggested" from "nothing to
change" and leaves the title alone.

So on a real device: picking the right game in the editor updated the artwork
and not the name, with nothing said about why. Half a rename, silently.

The name was never something to go and find. It is printed on the row the user
pressed, and the row is now sent along with the choice.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import libretro_meta  # noqa: E402
import sgdb  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


ART = {"capsule": "/home/deck/.art/capsule.png"}

# Restored at the end -- the suite shares one process, so a stub left behind
# answers every later file's questions too.
_real_settings = store.get_settings
_real_urls = sgdb.art_urls
_real_name = sgdb.game_name
_real_boxart = libretro_meta.boxart_url

store.get_settings = lambda: {"sgdb_api_key": "a-key"}
sgdb.art_urls = lambda key, game_id: {"capsule": "https://example.test/c.png"}
libretro_meta.boxart_url = lambda system, name: "https://example.test/%s.png" % name


async def _art(urls):
    return dict(ART)


plugin._download_art = _art


section("the name SteamGridDB gives is still the one preferred")

sgdb.game_name = lambda key, game_id: "Gravity Rush"
_got = run(plugin.apply_art_candidate("steamgriddb", "1234", "", "gravity rush (US)"))
check("its spelling wins over the row's", _got["suggested_title"], "Gravity Rush")
check("and the artwork comes with it", bool(_got["art"]), True)


section("and when it says nothing, the row the user pressed answers")

# The case seen on the device. Artwork arrived; the name did not.
sgdb.game_name = lambda key, game_id: ""
_got = run(plugin.apply_art_candidate("steamgriddb", "1234", "", "Gravity Rush"))
check("the pick is the name", _got["suggested_title"], "Gravity Rush")
check("which is what the toast reads out too", _got["art_game_name"], "Gravity Rush")

# Tidied by the same rule a filename goes through, so picking a row does not
# put a region tag in the library.
_got = run(plugin.apply_art_candidate("steamgriddb", "1234", "", "Gravity Rush (USA)"))
check("and it goes through the tidier", _got["suggested_title"], "Gravity Rush")

# Nothing from either side is not a name. Suggesting "" is how the frontend is
# told there is nothing to suggest, and it must stay distinguishable.
_got = run(plugin.apply_art_candidate("steamgriddb", "1234", "", "   "))
check("with neither, nothing is suggested", _got["suggested_title"], "")
check("but the artwork is still applied", bool(_got["art"]), True)

# A label is display text from the other side of the bridge, so it is bounded
# rather than trusted to be short.
_got = run(plugin.apply_art_candidate("steamgriddb", "1234", "", "G" * 400))
check("an absurd label is cut down", len(_got["art_game_name"]), 120)


section("the libretro row needs no fallback, because it never asks")

_got = run(plugin.apply_art_candidate("libretro", "Gravity Rush (USA)", "Sony - PlayStation Vita"))
check("the thumbnail's own name is the answer", _got["suggested_title"], "Gravity Rush")
check("with no key involved at all", _got["art_source"], "libretro")

store.get_settings = _real_settings
sgdb.art_urls = _real_urls
sgdb.game_name = _real_name
libretro_meta.boxart_url = _real_boxart
plugin.loop.close()


if __name__ == "__main__":
    summary()
