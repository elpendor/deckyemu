#!/usr/bin/env python3
"""Removing an emulator must not rewrite its games into something else.

    python scripts/tests/test_rebuild_emulator_gone.py

`rebuild_launchers` writes a launcher even when pieces are missing, on purpose:
the launcher is what reports a missing ROM or a missing core, so refusing to
write it refuses to write the explanation. For a libretro game that is safe --
the argv is the same whether or not the core file is there.

For an emulator game it is not. With no record, the writer takes the libretro
branch, and `core_path` on such a game is the emulator's *own* target -- so
RetroArch was told to load a flatpak id, or an AppImage, as a core. The shortcut
stopped being a launcher for that game: a nonsense command, and no emulator name
left in it for the missing-piece dialog to say.

Found on a Deck. A port was uninstalled, another emulator was installed a minute
later, its install rebuilt every launcher, and the port's game came out as a
RetroArch command pointing `-L` at the AppImage that had just been deleted.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import launchers  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_ROMS = os.path.join(TMP, "emulator-gone-roms")
os.makedirs(_ROMS, exist_ok=True)

_ROM = os.path.join(_ROMS, "standalone.iso")
with open(_ROM, "wb") as _handle:
    _handle.write(b"\x00" * 8)

_EMULATOR = {
    "id": "pcsx2",
    "name": "PCSX2",
    "kind": "flatpak",
    "target": "net.pcsx2.PCSX2",
    "args": "-nogui -- {rom}",
    "fullscreen_args": "-fullscreen",
    "extensions": ["iso"],
    "databases": ["Sony - PlayStation 2"],
}

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = [_EMULATOR]
# Present, so nothing here is skipped for want of it -- the point is what
# happens when RetroArch is available and gets handed a job it should not have.
plugin._install = {"kind": "native", "exe": "/usr/bin/retroarch"}


def run(coro):
    return plugin.loop.run_until_complete(coro)


store.clear_library()
store.remember_games({
    801: {
        "app_id": 801, "title": "Standalone Game", "rom_path": _ROM,
        "core_id": "emu:pcsx2", "core_path": "net.pcsx2.PCSX2",
        "launcher_path": "", "collection": "",
    },
})


section("while the emulator is registered")

_first = run(plugin.rebuild_launchers())
_script = launchers.launcher_path("Standalone Game", _ROM)
check("its game is rebuilt", (_first["rebuilt"], _first["skipped"]), (1, []))
with open(_script, "r", encoding="utf-8") as _handle:
    _good = _handle.read()
check("and the launcher runs the emulator", "net.pcsx2.PCSX2" in _good, True)
check("not RetroArch", "-L " in _good, False)


section("once it is gone")

plugin._emulators = []
_after = run(plugin.rebuild_launchers())
check("the game is skipped, by name", _after["skipped"], ["Standalone Game"])
check("and nothing is rebuilt", _after["rebuilt"], 0)

with open(_script, "r", encoding="utf-8") as _handle:
    _now = _handle.read()
# The last correct launcher, byte for byte. Its preflight already refuses the
# launch and names the emulator, which is the behaviour the rewrite destroyed.
check("the launcher on disk is untouched", _now == _good, True)
check("so it still names the emulator it needs", "PCSX2" in _now, True)
# The shape of the damage, checked directly: RetroArch loading a flatpak id as
# though it were a libretro core.
check("and was never turned into a RetroArch command",
      "-L net.pcsx2.PCSX2" in _now, False)


section("and comes back when the emulator does")

plugin._emulators = [_EMULATOR]
_back = run(plugin.rebuild_launchers())
check("the skip is not sticky", (_back["rebuilt"], _back["skipped"]), (1, []))

store.clear_library()
plugin.loop.close()


if __name__ == "__main__":
    summary()
