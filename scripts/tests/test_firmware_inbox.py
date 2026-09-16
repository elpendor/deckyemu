#!/usr/bin/env python3
"""A BIOS sent through the Quick Access transfer is offered Install, not Add.

    python scripts/tests/test_firmware_inbox.py

That transfer saves into the ROM folder, and only the firmware panel's own send
ever asked what an arrival was -- so a PS1 BIOS sent the usual way was offered
the add flow, as a game. Matching it there has one trap: xemu's BIOS rows match
any `.bin` of 256KB, 512KB or 1MB, and a folder of ROMs is full of those.

Every file here is made-up bytes.
"""

import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emu_install  # noqa: E402
import fileserver  # noqa: E402
import main  # noqa: E402

section("firmware -- recognised when it arrives with the ROMs")

plugin = main.Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._install = None


async def _present():
    return {"duckstation", "xemu"}


plugin._present_emulator_ids = _present


def run(coro):
    return plugin.loop.run_until_complete(coro)


_inbox = fileserver.default_dir()
_sent = {
    "SCPH5500.BIN": 524288,
    # A cartridge dump the size of an Xbox BIOS: must stay a game.
    "Made Up Cartridge.bin": 1048576,
    # A licence has its own install in the dialog.
    "UP0000-MADEUP00000_00-0000000000000000.rap": 16,
}
for _name, _size in _sent.items():
    with io.open(os.path.join(_inbox, _name), "wb") as _handle:
        _handle.write(b"\0" * _size)

try:
    _matches = run(plugin.firmware_matches(list(_sent)))
    check("a PS1 BIOS among the ROMs is matched to its emulator",
          (_matches.get("SCPH5500.BIN") or {}).get("entry_id"), "duckstation")
    check("a ROM the size of an Xbox BIOS is not", "Made Up Cartridge.bin" in _matches, False)
    check("a licence is left to its own install",
          any(name.endswith(".rap") for name in _matches), False)
    check("a name not in the folder matches nothing",
          run(plugin.firmware_matches(["not-sent.bin"])), {})

    _moved = run(plugin.move_to_firmware("SCPH5500.BIN"))
    _target = os.path.join(emu_install.firmware_dir(), "SCPH5500.BIN")
    check("moving it hands it to the firmware folder", _moved["ok"], True)
    check("where installing reads from", os.path.isfile(_target), True)
    check("and out of the ROM folder",
          os.path.isfile(os.path.join(_inbox, "SCPH5500.BIN")), False)
    # Sent twice, byte for byte: the spare goes and the install carries on.
    with io.open(os.path.join(_inbox, "SCPH5500.BIN"), "wb") as _handle:
        _handle.write(b"\0" * 524288)
    check("the same file sent again is not a conflict",
          run(plugin.move_to_firmware("SCPH5500.BIN"))["ok"], True)
    check("and the spare copy is gone",
          os.path.isfile(os.path.join(_inbox, "SCPH5500.BIN")), False)
    with io.open(os.path.join(_inbox, "SCPH5500.BIN"), "wb") as _handle:
        _handle.write(b"\1")
    _asked = run(plugin.move_to_firmware("SCPH5500.BIN"))
    check("a different file of the same name is not replaced unasked",
          (_asked["ok"], _asked.get("exists")), (False, True))
    check("and is once the user says so",
          run(plugin.move_to_firmware("SCPH5500.BIN", True))["ok"], True)
    with io.open(_target, "rb") as _handle:
        check("with the file just sent", _handle.read(), bytes([1]))
finally:
    for _name in _sent:
        for _folder in (_inbox, emu_install.firmware_dir()):
            _path = os.path.join(_folder, _name)
            if os.path.isfile(_path):
                os.remove(_path)


if __name__ == "__main__":
    summary()
