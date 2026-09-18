#!/usr/bin/env python3
"""Answering a port's file picker with the game it was added for.

    python scripts/tests/test_picker_shim.py

Some ports take no path and no argument: they ask, through a picker, which is a
separate program found on PATH. On a Deck that picker opens in "Recently Used"
whatever directory it is handed -- Starship passes `--filename=./` and it still
lands there -- so somebody with a controller is left hunting for a file the
plugin chose for them minutes earlier.

So a zenity of our own goes first on PATH for that launch. A file selection is
answered with the game; every other dialog is handed to the real one, because
the questions these ports ask are worth reading.

Every port here is made up.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import launchers  # noqa: E402
from emulator_catalog import schema  # noqa: E402

_PORT = {
    "id": "asking-port",
    "name": "Asking Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/asking",
               "asset": "^Asking\\.AppImage$"},
    "args": "",
    "port": True,
    "root": ".local/share/SomeStudio/Asking",
    "platform": "Nintendo GameCube",
    "game_picker": True,
}

_GAME = "/home/deck/deckyemu/roms/n64/Some Game.z64"


section("a port that takes a path gets no shim")

check("nothing for an entry that declares none",
      launchers.picker_shim({"id": "plain"}, _GAME), "")
check("and nothing without a game", launchers.picker_shim(_PORT, ""), "")


section("the picker is answered with the game")

_real_which = launchers.shutil.which
launchers.shutil.which = lambda name: "/usr/bin/zenity"
try:
    _shell = launchers.picker_shim(_PORT, _GAME)
finally:
    launchers.shutil.which = _real_which

_shim = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "pickers", "asking-port", "zenity")
check("the launcher puts it first on PATH and names the game",
      "PATH=" in _shell and _GAME in _shell, True)
check("and the shim is written where PATH points", os.path.isfile(_shim), True)


def _ran(args, game=_GAME):
    """What the shim prints, and its exit status, for one dialog."""
    done = subprocess.run(["sh", _shim] + args, capture_output=True, text=True,
                          env=dict(os.environ, DECKYEMU_GAME=game))
    return done.stdout.strip(), done.returncode


# Exactly the arguments Starship's picker was seen running with.
_picker = ["--file-selection", "--filename=./", "--title", "Select a file",
           "--separator=", "--file-filter", "N64 Roms|*.z64", "--confirm-overwrite"]
check("a file selection answers with the game", _ran(_picker), (_GAME, 0))

# The port's own questions are readable and worth reading, so they are passed
# through -- which here means the real zenity is reached and fails for want of
# a display, rather than being answered by us.
_question = ["--question", "--text", "Please provide a ROM."]
check("a question is not answered here", _ran(_question)[0], "")

# No game in the environment is the launcher not having set one, and then the
# picker must open rather than answer with nothing.
check("and nothing is claimed when no game was passed", _ran(_picker, "")[0], "")


section("only a port answers its own picker")

_emulator = dict(_PORT)
del _emulator["port"]
check("an emulator declaring one is refused",
      any("is handed a path" in problem
          for problem in schema.validate(_emulator, known_platforms=(), imported=True)),
      True)


if __name__ == "__main__":
    summary()
