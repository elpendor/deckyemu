#!/usr/bin/env python3
"""A file from outside cannot touch what Game Mode holds.

    python scripts/tests/test_imported_input.py

Two fields reach past the game and into Steam's own input, and both cost more
than a game is allowed to cost.

`layout` pins a Steam Input layout. Applying one reconfigures the pad, and on a
Deck that ended with Steam closing the controller after a failed read and never
polling it again: no Steam button, no Quick Access. It was pinned again at every
start, so restarting did not clear it.

The two SDL variables hand the physical pad to the program. Steam reads its own
buttons from that pad, and a grab or a crash there is Game Mode with no input.

A bundled entry may still do both -- Vita3K needs the layout to keep the sensor
powered, and the SDL route is how two emulators read motion -- because those are
tested here and this project answers for them.

Every entry here is made up.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

from emulator_catalog import schema  # noqa: E402

_ENTRY = {
    "id": "outside-port",
    "name": "Outside Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/outside",
               "asset": "^Outside\\.AppImage$"},
    "args": "{rom}",
    "port": True,
    "root": ".local/share/SomeStudio/Outside",
    "platform": "Nintendo GameCube",
}


def _refused(entry, phrase):
    return any(phrase in problem
               for problem in schema.validate(entry, known_platforms=(), imported=True))


section("an imported entry may not pin a layout")

_layout = dict(_ENTRY, layout="template://something.vdf")
check("declaring one is refused", _refused(_layout, "not allowed in an imported entry"), True)
check("and the refusal says what it cost",
      _refused(_layout, "no Steam button"), True)
# The same entry bundled is fine: Vita3K pins one, and its gyro depends on it.
check("a bundled entry may still pin one",
      any("layout" in problem for problem in schema.validate(_layout, known_platforms=())),
      False)


section("nor take the pad Steam reads")

for _name in ("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD",
              "SDL_GAMECONTROLLER_IGNORE_DEVICES"):
    check("env %s is refused" % _name.split("_")[-1].lower(),
          _refused(dict(_ENTRY, env={_name: "0"}), "hands the"), True)

# Everything else an entry may need from the environment still goes through.
check("an ordinary variable is allowed",
      schema.validate(dict(_ENTRY, env={"SDL_VIDEODRIVER": "wayland"}),
                      known_platforms=(), imported=True),
      [])


if __name__ == "__main__":
    summary()
