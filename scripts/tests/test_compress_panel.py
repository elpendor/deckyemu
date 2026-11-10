#!/usr/bin/env python3
"""Compressing a game from the panel, through the Plugin, with chdman faked.

    python scripts/tests/test_compress_panel.py

The case that broke on the Deck: a two-disc PCSX2 set. Its record names the
playlist, which keeps its path, while its launcher runs the first disc --
the file compressing deletes. So the launcher has to be rewritten to the
first CHD even though the record's path did not change.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402

import appenv  # noqa: E402
import emu_install  # noqa: E402
import launchers  # noqa: E402
import romshelf  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from main import Plugin  # noqa: E402

FAKE_CHDMAN = '''
import shutil, sys
args = sys.argv[1:]
if args[0] == "verify":
    sys.exit(0)
with open(args[args.index("-o") + 1], "wb") as out:
    out.write(b"small")
'''

_EMULATOR = {
    "id": "pcsx2", "name": "PCSX2", "kind": "flatpak", "target": "net.pcsx2.PCSX2",
    "args": "-nogui -- {rom}", "fullscreen_args": "-fullscreen",
    "extensions": ["iso", "chd", "cue"], "databases": ["Sony - PlayStation 2"],
}

folder = os.path.join(romshelf.library_dir(create=True), "ps2")
os.makedirs(folder, exist_ok=True)
for number in (1, 2):
    with open(os.path.join(folder, "Made Up (Disc %d).iso" % number), "wb") as handle:
        handle.write(b"\x00" * 4096)
playlist = os.path.join(folder, "Made Up.m3u")
with open(playlist, "w", encoding="utf-8", newline="\n") as handle:
    handle.write("Made Up (Disc 1).iso\nMade Up (Disc 2).iso\n")
fake = os.path.join(os.path.dirname(folder), "fake_chdman.py")
with open(fake, "w", encoding="utf-8") as handle:
    handle.write(FAKE_CHDMAN)

os.makedirs(launchers.LAUNCHER_DIR, exist_ok=True)
launcher = os.path.join(launchers.LAUNCHER_DIR, "made-up-0000.sh")

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = [_EMULATOR]
plugin._install = None
plugin._compress_tools = lambda: ({"chdman": [sys.executable, "-I", fake]}, {})
# Patched for this file only; restored at the end, since suites share a process.
_installed_tool, _emit_real = emu_install.installed_tool, appenv.emit
emu_install.installed_tool = lambda name: "/fake/" + name

store.clear_library()
store.remember_games({
    901: {"app_id": 901, "title": "Made Up", "rom_path": playlist,
          "core_id": "emu:pcsx2", "core_path": "net.pcsx2.PCSX2",
          "system": "Sony - PlayStation 2", "platform": "PS2",
          "launcher_path": launcher, "collection": ""},
})

heard = []


async def _emit(event, *args):
    heard.append((event,) + args)

appenv.emit = _emit


def run(coro):
    return plugin.loop.run_until_complete(coro)


section("planning")
plan = run(plugin.compress_plan())
check("the set is offered as one game", [game["app_id"] for game in plan["games"]], [901])

section("compressing from the panel")
check("it starts", run(plugin.start_compress([901]))["ok"], True)
for _ in range(200):
    if any(one[0] == "compress_done" for one in heard):
        break
    run(asyncio.sleep(0.05))
done = next((one for one in heard if one[0] == "compress_done"), None)
check("and ends saying one game was done", done and done[1:4], (True, "", 1))
check("the ISOs are gone, the CHDs and playlist stay", sorted(os.listdir(folder)),
      ["Made Up (Disc 1).chd", "Made Up (Disc 2).chd", "Made Up.m3u"])
check("the record still names the playlist",
      store.get_library()["901"]["rom_path"], playlist)
with open(launcher, encoding="utf-8") as handle:
    script = handle.read()
check("the launcher, under its old name, now runs the first CHD",
      ("Made Up (Disc 1).chd" in script, ".iso" in script), (True, False))

emu_install.installed_tool, appenv.emit = _installed_tool, _emit_real
store.clear_library()
