#!/usr/bin/env python3
"""A layer switched on for one shortcut has to reach inside a sandbox.

    python scripts/tests/test_layer_env.py

Frame generation on the Deck is `lsfg-vk`, a Vulkan layer another plugin owns.
That plugin switches it on per Steam shortcut, by setting `LSFGVK_CONFIG` in
launch options before this plugin's launcher runs -- and every game added here
is its own shortcut, so per game already works for an AppImage emulator.

`flatpak run` does not pass the host's environment on, so the same thing was
dropped for a flatpak emulator. That plugin's answer there is `flatpak
override`, which is per application: on an emulator, every game it runs.
Forwarding the variables as `--env=` is what makes the shortcut that asked the
one that gets it.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import launchers  # noqa: E402


section("only a sandbox needs it")

_flatpak = ["/usr/bin/flatpak", "run", "org.libretro.RetroArch", "-L", "core.so"]
_lines, _command = launchers.forward_layer_env(_flatpak, "unused")
check("a flatpak gets a prelude", bool(_lines), True)
check("and its argv grows the place the variables go",
      '"$@"' in _command, True)
# After `flatpak run`, before the application id: anywhere later and flatpak
# reads it as an argument for the program rather than for itself.
check("in the only position flatpak reads options",
      _command.index('"$@"') < _command.index("org.libretro.RetroArch"), True)

_plain = ["/home/deck/emu.AppImage", "game.bin"]
check("an AppImage gets nothing", launchers.forward_layer_env(_plain, "as-is"),
      ([], "as-is"))
check("and nothing at all is emitted for an empty argv",
      launchers.forward_layer_env([], "as-is"), ([], "as-is"))


section("what the prelude does")

_text = chr(10).join(_lines)
# Quoted, and built into "$@" rather than spliced as text: a config path with
# a space in it would otherwise arrive as two arguments.
for _name in launchers.LAYER_ENV:
    check("%s is forwarded when set" % _name,
          ('"--env=%s=${%s}"' % (_name, _name)) in _text, True)
check("and only when set, so an ordinary launch is unchanged",
      _text.count("if [ -n") , len(launchers.LAYER_ENV))
# The list is named rather than matched by prefix: a sandbox is meant to be a
# smaller environment than the host.
check("nothing is forwarded by pattern", "*" in _text, False)


section("the whole launcher, written out")

with tempfile.TemporaryDirectory() as home:
    import sysenv

    _real = sysenv.user_home
    sysenv.user_home = lambda: home
    try:
        install = {"kind": "flatpak", "exe": "/usr/bin/flatpak",
                   "config_dir": os.path.join(home, "ra"),
                   "core_dirs": [], "info_dirs": []}
        core = os.path.join(home, "ra", "cores", "snes9x_libretro.so")
        os.makedirs(os.path.dirname(core))
        open(core, "w", encoding="utf-8").write("x")
        rom = os.path.join(home, "My Game (USA).sfc")
        open(rom, "w", encoding="utf-8").write("x")

        body = open(launchers.write_launcher(install, "Flat", core, rom),
                    encoding="utf-8").read()
        check("the prelude is in the script", "set --" in body, True)
        # Before the exec, or the arguments are built after they were needed.
        check("ahead of the exec it builds arguments for",
              body.index("set --") < body.rindex("exec "), True)
    finally:
        sysenv.user_home = _real


if __name__ == "__main__":
    from harness import summary

    summary()
