#!/usr/bin/env python3
"""A program that reads its game from its own config, not the command line.

    python scripts/tests/test_ports_config.py

Some native ports take no game path as an argument: the disc is a key in their
own JSON settings, and a key whose name contains dots at the top level of the
file rather than a nested object. So an entry can say where the game goes
(`game_config`), launch with no path, and seed settings in that flat shape.

The entry and every path here are made up.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import emu_config  # noqa: E402
import emulators  # noqa: E402
from emulator_catalog import schema, to_emulator  # noqa: E402
import sysenv  # noqa: E402

PORT = {
    "id": "some-port",
    "name": "Some Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/some-port",
               "asset": "^SomePort-linux-x86_64\\.AppImage$"},
    "args": "",
    "port": True,
    "root": ".local/share/SomeStudio/SomePort",
    "platform": "Nintendo GameCube",
    "game_config": {
        "format": "json-flat",
        "path": ".local/share/SomeStudio/SomePort/config.json",
        "keys": {"backend.gamePath": "{rom}", "backend.verified": 0},
    },
    "setup": {
        "format": "json-flat",
        "path": ".local/share/SomeStudio/SomePort/config.json",
        "sections": {"backend.skipLauncher": True},
    },
}

section("ports -- a game path that lives in the program's own config")

check("an entry with game_config needs no {rom} and may have empty args",
      schema.validate(PORT, ["Nintendo GameCube"], imported=True), [])
_no_rom = dict(PORT, game_config=dict(PORT["game_config"], keys={"backend.gamePath": "x"}))
check("but one whose keys never carry {rom} is refused",
      any("{rom}" in problem for problem in schema.validate(_no_rom, ["Nintendo GameCube"])), True)
_outside = dict(PORT, game_config=dict(PORT["game_config"], path=".ssh/config"))
check("and an imported one may not write outside its root",
      any("outside" in problem for problem in schema.validate(
          _outside, ["Nintendo GameCube"], imported=True)), True)
_plain = dict(PORT)
del _plain["game_config"]
check("an entry without it still needs {rom}",
      any("missing required field 'args'" in problem
          for problem in schema.validate(_plain, ["Nintendo GameCube"])), True)

_home = os.path.join(TMP, "portsconfig")
_real_home = sysenv.user_home
sysenv.user_home = lambda: _home
try:
    _config = os.path.join(_home, PORT["game_config"]["path"])

    # Seeded the flat way: a dotted key stays one key at the top level.
    result = emu_config.apply_setup(PORT)
    check("setup in json-flat creates a missing config", result.get("ok"), True)
    with open(_config, encoding="utf-8") as handle:
        written = json.load(handle)
    check("and writes a dotted key literally, not as a nested object",
          written, {"backend.skipLauncher": True})

    _path, _keys = emu_config.game_config_values(PORT, "/home/deck/roms/Some Game.rvz")
    check("the game's path fills the key that carried {rom}",
          _keys, {"backend.gamePath": "/home/deck/roms/Some Game.rvz",
                  "backend.verified": 0})
    check("in the file the entry named", _path, _config)
    check("and an entry that takes its game on the command line has none",
          emu_config.game_config_values({"id": "x"}, "/roms/a.iso"), ("", {}))

    record = to_emulator(PORT, "/home/deck/deckyemu/emulators/some-port/SomePort.AppImage", {})
    check("the registered record knows its game is in config",
          (record["game_in_config"], record["args"]), (True, ""))
    argv = emulators.launch_argv(record, "/home/deck/roms/Some Game.rvz", fullscreen=False)
    check("and it launches with no game path on the command line",
          argv[-1].endswith("SomePort.AppImage"), True)
    check("while an ordinary emulator still gets one",
          emulators.launch_argv(dict(record, game_in_config=False, args="{rom}"),
                                "/r/a.iso", fullscreen=False)[-1], "/r/a.iso")
    # A flatpak target, so the check does not depend on this host's paths.
    check("a record with game_in_config passes validation with empty args",
          emulators.validate(dict(record, kind="flatpak", target="org.example.SomePort",
                                  extensions=["rvz"])), "")
    section("each game tells the program which game it is, at launch")

    # The fault this exists for: one program, one config, one key. Written when
    # the game was added, the second game added repointed the first game's
    # shortcut -- both launchers start the same program, and the program reads
    # whatever that key last said.
    import emulator_catalog  # noqa: E402
    import launchers  # noqa: E402

    _real_find = emulator_catalog.find
    emulator_catalog.find = lambda entry_id: PORT if entry_id == PORT["id"] else None
    try:
        _first = launchers.game_config_setup(record, "/home/deck/roms/First.iso")
        _second = launchers.game_config_setup(record, "/home/deck/roms/Second.iso")
        check("a port's launcher carries its own game", "First.iso" in _first, True)
        check("and the next game's launcher carries that one instead",
              ("Second.iso" in _second, "First.iso" in _second), (True, False))
        check("both name the file the entry declared", _config in _first, True)
        check("an emulator that takes a path on the command line writes nothing",
              launchers.game_config_setup(
                  dict(record, id="not-a-port"), "/home/deck/roms/First.iso"), "")
        check("and so does a launch with no game",
              launchers.game_config_setup(record, ""), "")
    finally:
        emulator_catalog.find = _real_find

finally:
    sysenv.user_home = _real_home


if __name__ == "__main__":
    summary()
