#!/usr/bin/env python3
"""What a game in the transfer folder brings with it, so the list shows one row.

    python scripts/tests/test_transfer_brings.py

Switch files are told apart here by the title id in their names: these are
not real packages, and the filename is what identifies a file that is not one.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import plugin_transfers  # noqa: E402

_DIR = os.path.join(TMP, "transfer_brings")
os.makedirs(_DIR, exist_ok=True)


def _write(name):
    path = os.path.join(_DIR, name)
    with open(path, "wb") as handle:
        handle.write(b"x" * 64)
    return path


section("a Switch game brings its update and DLC")

_game = _write("Harbor Dash [01009E2E00000000][v0].nsp")
_write("Harbor Dash [01009E2E00000800][v65536].nsp")
_write("Harbor Dash [01009E2E00001001][v0].nsp")
_write("Other Game [0100AAAA00000800][v65536].nsp")
check("its own update and DLC, and nothing for another game",
      sorted(plugin_transfers.brings(_game)),
      ["Harbor Dash [01009E2E00000800][v65536].nsp", "Harbor Dash [01009E2E00001001][v0].nsp"])
check("an update brings nothing",
      plugin_transfers.brings(os.path.join(_DIR, "Harbor Dash [01009E2E00000800][v65536].nsp")), [])
check("nor does a cartridge", plugin_transfers.brings(_write("Harbor Dash.gba")), [])

if __name__ == "__main__":
    summary()
