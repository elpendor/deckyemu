#!/usr/bin/env python3
"""A rebuild honours what each game chose, not just what its emulator did.

    python scripts/tests/test_rebuild_per_game.py

`rebuild_launchers` is the one launcher writer that took the emulator's own
record and wrote it to every game. `prepare_shortcut` and `update_game` both
resolve through `emulators.for_game` first; this one did not -- and it is the
one `set_workaround` calls, so switching a workaround on for an emulator
rewrote all of its launchers and discarded whatever each game had chosen.

It went unnoticed because the emulator record already carries a *resolved*
`env`, so the launchers still looked right for anyone who had never set a game
differently. What made it visible is a workaround that decides which binary
runs: the patched build is only ever named per game, so an emulator-level
toggle produced a launcher still pointing at the stock one -- the switch said
on, and nothing had changed.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emu_patch  # noqa: E402
import launchers  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_HOME = os.path.join(TMP, "per-game")
os.makedirs(_HOME, exist_ok=True)


def _file(name, body=b"\x00" * 8):
    path = os.path.join(_HOME, name)
    with open(path, "wb") as handle:
        handle.write(body)
    return path


_ROM_FOLLOWS = _file("follows.vpk")
_ROM_OPTS_OUT = _file("opts-out.vpk")

# The stock build and the patched one, side by side, which is how they sit on a
# Deck: `emu_patch.refresh` writes the second beside the first at install and
# neither is ever written over the other.
_STOCK = _file("Vita3K-x86_64.AppImage")
_PATCHED = _file(emu_patch.patched_name("Vita3K-x86_64.AppImage", "vita-motion"))

# The catalog id matters: it is the only route back to the entry that describes
# the workaround, and a hand-registered emulator has none.
_EMULATOR = {
    "id": "vita3k",
    "name": "Vita3K",
    "kind": "path",
    "target": _STOCK,
    "args": "{rom}",
    "fullscreen_args": "--fullscreen",
    "extensions": ["vpk"],
    "databases": [],
    "platform": "Sony - PlayStation Vita",
    # Motion on for the emulator, which is what the user switched.
    "workarounds_off": [],
}

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = [_EMULATOR]
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


store.clear_library()
store.remember_games({
    801: {
        "app_id": 801, "title": "Follows Emulator", "rom_path": _ROM_FOLLOWS,
        "core_id": "emu:vita3k", "core_path": _STOCK,
        "launcher_path": "", "collection": "",
    },
    # The case the bug erased. An id absent from a game's options follows the
    # emulator; one set to False is a decision, and a rebuild must keep it.
    802: {
        "app_id": 802, "title": "Opts Out", "rom_path": _ROM_OPTS_OUT,
        "core_id": "emu:vita3k", "core_path": _STOCK,
        "launcher_path": "", "collection": "",
        "options": {"workarounds": {"vita-motion": False}},
    },
})

_result = run(plugin.rebuild_launchers())
check("both launchers were rebuilt", _result["rebuilt"], 2)


def _body(title, rom):
    with open(launchers.launcher_path(title, rom), "r", encoding="utf-8") as handle:
        return handle.read()


_follows = _body("Follows Emulator", _ROM_FOLLOWS)
_opted_out = _body("Opts Out", _ROM_OPTS_OUT)


section("the game that follows the emulator gets the fix")

# The whole point: the patched build is named per game and reaches the launcher
# only through `for_game`.
check("its launcher runs the patched build",
      os.path.basename(_PATCHED) in _follows, True)
check("and carries the motion environment with it",
      "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD" in _follows, True)


section("the game that opted out is left alone")

check("its launcher runs the stock build",
      os.path.basename(_PATCHED) in _opted_out, False)
check("which is still the emulator, not nothing",
      os.path.basename(_STOCK) in _opted_out, True)
check("and none of the motion environment came with it",
      "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD" in _opted_out, False)


section("and with no patched build on disk, the stock one runs")

# The fallback that makes a refused patch safe: the fix is lost, the emulator is
# not. Nothing here should notice beyond the binary that runs.
os.remove(_PATCHED)
run(plugin.rebuild_launchers())
_fallback = _body("Follows Emulator", _ROM_FOLLOWS)
check("the launcher falls back to the stock build",
      (os.path.basename(_PATCHED) in _fallback,
       os.path.basename(_STOCK) in _fallback),
      (False, True))
check("and the rest of the workaround still applies",
      "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD" in _fallback, True)

if __name__ == "__main__":
    summary()
