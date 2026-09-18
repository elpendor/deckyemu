#!/usr/bin/env python3
"""The run that sets a port up, and only that run.

    python scripts/tests/test_first_run.py

A port that builds its own archive from the game takes the game on the command
line: handed it, Ship of Harkinian extracts and never asks its "no archive
found, build one?" question. Handed it again on a later launch it has a
different question -- "that archive exists, extract again?" -- so the argument
goes only while the file it builds is missing.

The first attempt at this answered the questions instead, through a stand-in for
`zenity`. It did nothing: those prompts are drawn inside the game window, and
zenity is only what the file picker uses.

Every port and every file here is made up.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import launchers  # noqa: E402
from emulator_catalog import schema  # noqa: E402

_PORT = {
    "id": "building-port",
    "name": "Building Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/building",
               "asset": "^Building\\.AppImage$"},
    "args": "",
    "port": True,
    "root": ".local/share/SomeStudio/Building",
    "platform": "Nintendo GameCube",
    "first_run": {"args": "{rom}", "unless": ["game.archive"]},
}


section("the game is handed over once")

_shell = launchers.first_run_argv(_PORT, "/home/deck/roms/n64/Some Game.z64")
check("an entry that declares none gets nothing",
      launchers.first_run_argv({"id": "plain"}, "/r/a.z64"), "")
check("and so does a launch with no game", launchers.first_run_argv(_PORT, ""), "")
check("the file it builds is what decides", "[ ! -f game.archive ]" in _shell, True)
check("and the game is quoted, since its path has spaces",
      "'/home/deck/roms/n64/Some Game.z64'" in _shell, True)


section("what the shell actually does")

# Run the block for real, in a directory with and without the file, and report
# what it would pass on. `set --` is what carries it, so "$@" is the answer.
_folder = os.path.join(TMP, "firstrun")
os.makedirs(_folder, exist_ok=True)


def _passed():
    script = _shell + '\nprintf "%s" "$*"\n'
    return subprocess.run(["sh", "-c", script], cwd=_folder,
                          capture_output=True, text=True).stdout


check("with nothing built yet, the game is passed",
      _passed(), "/home/deck/roms/n64/Some Game.z64")

with open(os.path.join(_folder, "game.archive"), "w", encoding="utf-8") as _handle:
    _handle.write("built")
check("once it is built, nothing is passed", _passed(), "")


section("a first run has to say what it builds")

_no_rom = dict(_PORT, first_run={"args": "--extract", "unless": ["game.archive"]})
check("arguments with no {rom} are refused",
      any("no {rom}" in problem
          for problem in schema.validate(_no_rom, known_platforms=(), imported=True)),
      True)
_no_unless = dict(_PORT, first_run={"args": "{rom}"})
check("and so is leaving out what stops it happening twice",
      any("stops it happening twice" in problem
          for problem in schema.validate(_no_unless, known_platforms=(), imported=True)),
      True)
_not_port = dict(_PORT)
del _not_port["port"]
_not_port["args"] = "{rom}"
check("an emulator has no setup run",
      any("only a port has a run" in problem
          for problem in schema.validate(_not_port, known_platforms=(), imported=True)),
      True)


if __name__ == "__main__":
    summary()
