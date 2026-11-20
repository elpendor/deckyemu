#!/usr/bin/env python3
"""PS1 cores launch with a DualShock plugged in.

    python scripts/tests/test_ps1_dualshock.py

The cores default to a digital pad, and a game that needs analog stops at its
"DUALSHOCK required" screen. RetroArch ignores `input_libretro_device_pN` in a
config and reads it from a remap, so a PS1 core gets a core remap in
RetroArch's own remap folder, once and only where it has none. Measured on a Deck: the device set in an appended config left
the core on "PlayStation Controller"; the same line in a remap made it
"DualShock" and the game started.
"""

import io
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import launchers  # noqa: E402
import ra_overrides  # noqa: E402


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _config_dir(name, remaps=None):
    where = os.path.join(TMP, "ra-%s" % name)
    os.makedirs(where, exist_ok=True)
    with io.open(os.path.join(where, "retroarch.cfg"), "w", encoding="utf-8") as handle:
        handle.write('video_driver = "gl"\n')
    for rel in remaps or []:
        path = os.path.join(where, "config", "remaps", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    return where


def _remap(config_dir, name):
    return os.path.join(config_dir, "config", "remaps", name, name + ".rmp")


section("each PS1 core gets its own DualShock id")

ra_overrides.WRITTEN = os.path.join(TMP, "dualshock-remaps.json")
plain = _config_dir("plain")
for core, (name, device) in sorted(ra_overrides.DUALSHOCK_CORES.items()):
    path = ra_overrides.write_core_remap("/cores/%s_libretro.so" % core, plain)
    check("%s's remap is a core remap in RetroArch's own folder" % core,
          path, _remap(plain, name))
    remap = _read(path)
    check("%s's remap plugs in device %d" % (core, device),
          'input_libretro_device_p1 = "%d"' % device in remap, True)
    check("%s's remap covers player 2" % core,
          'input_libretro_device_p2 = "%d"' % device in remap, True)

check("SwanStation's DualShock is 261, not the 517 the others use",
      ra_overrides.DUALSHOCK_CORES["swanstation"][1], 261)


section("other cores get nothing")

check("a SNES core", ra_overrides.write_core_remap("/cores/snes9x_libretro.so", plain), "")
check("no core", ra_overrides.write_core_remap("", plain), "")
check("no RetroArch config", ra_overrides.write_core_remap(
    "/cores/swanstation_libretro.so", ""), "")


section("the user's remaps win, and ours is written once")

theirs = _config_dir("theirs", ["Beetle PSX HW/Beetle PSX HW.rmp"])
check("their Beetle PSX HW core remap is left alone",
      (ra_overrides.write_core_remap("/cores/mednafen_psx_hw_libretro.so", theirs),
       _read(_remap(theirs, "Beetle PSX HW"))), ("", ""))
game_only = _config_dir("game-only", ["SwanStation/Made Up Disc.rmp"])
check("a game remap alone still lets the core have ours",
      bool(ra_overrides.write_core_remap("/cores/swanstation_libretro.so", game_only)), True)
with io.open(_remap(plain, "SwanStation"), "w", encoding="utf-8") as handle:
    handle.write('input_libretro_device_p1 = "1"\n')
check("a remap the user changed and saved is not overwritten",
      (ra_overrides.write_core_remap("/cores/swanstation_libretro.so", plain),
       _read(_remap(plain, "SwanStation"))), ("", 'input_libretro_device_p1 = "1"\n'))
os.remove(_remap(plain, "SwanStation"))
check("nor put back once the user removed it",
      (ra_overrides.write_core_remap("/cores/swanstation_libretro.so", plain),
       os.path.exists(_remap(plain, "SwanStation"))), ("", False))

custom = _config_dir("custom")
with io.open(os.path.join(custom, "retroarch.cfg"), "a", encoding="utf-8") as handle:
    handle.write('input_remapping_directory = ":/my-remaps"\n')
check("a remap folder set in retroarch.cfg is the one written to",
      ra_overrides.write_core_remap("/cores/pcsx_rearmed_libretro.so", custom),
      os.path.join(custom, "my-remaps", "PCSX-ReARMed", "PCSX-ReARMed.rmp"))


section("a launcher writes it and passes RetroArch one config")

fresh = _config_dir("fresh")
install = {"kind": "flatpak", "exe": "/usr/bin/flatpak", "config_dir": fresh}
rom = os.path.join(TMP, "roms", "ps1", "Made Up Disc.cue")
os.makedirs(os.path.dirname(rom), exist_ok=True)
open(rom, "w").close()
script = _read(launchers.write_launcher(
    install, "Made Up Disc", "/cores/mednafen_psx_hw_libretro.so", rom, hide_osd="all",
    path=os.path.join(TMP, "made-up-disc.sh")))
check("writing the launcher wrote the core remap",
      os.path.isfile(_remap(fresh, "Beetle PSX HW")), True)
argv = shlex.split([line for line in script.splitlines() if "--appendconfig=" in line][0])
append = [arg for arg in argv if arg.startswith("--appendconfig=")][0].split("=", 1)[1]
check("one appended config, and no remap folder of ours", "|" in append, False)

summary()
