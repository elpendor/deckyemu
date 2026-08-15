#!/usr/bin/env python3
"""A Deck with no RetroArch still has its launchers rebuilt.

    python scripts/tests/test_rebuild_without_retroarch.py

`rebuild_launchers` is what carries a settings change to games that already
exist -- every option baked into a launcher reaches them through it and nowhere
else. It refused outright when RetroArch was absent, so on a Deck running only
catalog emulators every such change silently did nothing: the setting saved, the
panel said so, and no launcher moved.

That configuration is not a corner. `prepare_shortcut` needs RetroArch only when
the chosen core is a libretro one, and a Deck having none is the whole point of
the emulator catalog -- the rebuild refused for all of those games because one
kind of game needs it.

A libretro game still cannot be rebuilt without an install to run it, so those
are skipped by name, which the caller already reports.
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

_ROMS = os.path.join(TMP, "no-retroarch-roms")
os.makedirs(_ROMS, exist_ok=True)


def _rom(name):
    path = os.path.join(_ROMS, name)
    with open(path, "wb") as handle:
        handle.write(b"\x00" * 8)
    return path


_PCSX2_ROM = _rom("standalone.iso")
_SNES_ROM = _rom("libretro.sfc")

# A registered standalone emulator, which is what such a Deck runs everything
# on. Its launcher never involved RetroArch.
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
_CORE = {
    "id": "bsnes_libretro",
    "path": os.path.join(TMP, "cores", "bsnes_libretro.so"),
    "display_name": "bsnes",
    "system_name": "Super Nintendo Entertainment System",
    "databases": ["Nintendo - Super Nintendo Entertainment System"],
    "extensions": ["sfc"],
}

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = [_CORE]
plugin._emulators = [_EMULATOR]
# The whole point: no RetroArch on this device at all.
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


store.clear_library()
store.remember_games({
    701: {
        "app_id": 701, "title": "Standalone Game", "rom_path": _PCSX2_ROM,
        "core_id": "emu:pcsx2", "core_path": "net.pcsx2.PCSX2",
        "launcher_path": "", "collection": "",
    },
    702: {
        "app_id": 702, "title": "Libretro Game", "rom_path": _SNES_ROM,
        "core_id": "bsnes_libretro", "core_path": _CORE["path"],
        "launcher_path": "", "collection": "",
    },
})


section("the rebuild runs at all")

_result = run(plugin.rebuild_launchers())
# It used to answer {"ok": False, "error": "RetroArch was not found"} here, and
# every caller ignores the result -- so the refusal was invisible as well as
# wrong.
check("it does not refuse for want of RetroArch", _result["ok"], True)


section("and rebuilds what it can")

check("the standalone emulator's game is rebuilt", _result["rebuilt"], 1)
check("the libretro game is skipped, by name", _result["skipped"], ["Libretro Game"])

_script = launchers.launcher_path("Standalone Game", _PCSX2_ROM)
check("its launcher is on disk", os.path.isfile(_script), True)
with open(_script, "r", encoding="utf-8") as _handle:
    _body = _handle.read()
check("and runs the emulator, not RetroArch", "net.pcsx2.PCSX2" in _body, True)
check("with no RetroArch override appended", "--appendconfig" in _body, False)


section("with RetroArch present, both are rebuilt")

# The other direction, so this cannot pass by rebuilding nothing.
plugin._install = {"kind": "native", "exe": "/usr/bin/retroarch"}
_both = run(plugin.rebuild_launchers())
check("nothing is skipped once RetroArch is there", _both["skipped"], [])
check("and both games are rebuilt", _both["rebuilt"], 2)

store.clear_library()
plugin.loop.close()


if __name__ == "__main__":
    summary()
