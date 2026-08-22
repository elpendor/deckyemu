#!/usr/bin/env python3
"""The firmware panel reads the install record once, not once per requirement.

    python scripts/tests/test_firmware_state_reads.py

`status` answers one question per requirement -- is this file already in place,
and did we put it there -- and the second half of that comes from
`firmware_installed.json`. Read inside the loop, that is one open-and-parse per
requirement per emulator, and the panel asks about every installed emulator at
once: a dozen entries with several requirements each re-read the same small
file dozens of times to draw one screen, on a device where the whole point of
`self._run` is that filesystem work is the expensive part.

`available()` was already hoisted out of that loop by the caller. This is the
same hoist for the other read, and this file is what keeps it hoisted -- the
cost is invisible in every other way, because the answer is correct either way
and a repeated read of a file that has not changed looks exactly like one read.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emu_firmware  # noqa: E402
import emulator_catalog  # noqa: E402

# Ryujinx, because it carries several requirements of more than one kind -- a
# plain copied file, and firmware it installs itself. Only the copied kind
# reaches the record, so an entry with one requirement would pass this while
# still reading per requirement.
ENTRY = emulator_catalog.find("ryujinx")


def _count_reads(**kwargs):
    """How many times `status` opens the record when called this way."""
    reads = []
    original = emu_firmware.read_state

    def counting():
        reads.append(1)
        return original()

    emu_firmware.read_state = counting
    try:
        emu_firmware.status(ENTRY, **kwargs)
    finally:
        # Restored whatever happens: the suite shares one module namespace, and
        # a stub left in place fails whichever file happens to run next.
        emu_firmware.read_state = original
    return len(reads)


section("the install record is read once per call, not once per requirement")

check("more than one requirement, or this proves nothing",
      len(ENTRY.get("firmware") or []) > 1, True)

# The panel's shape: the caller has already read both, so `status` reads neither.
check("a caller that hands the state down makes status read it no times",
      _count_reads(files=[], state=emu_firmware.read_state()), 0)

# Called on its own it still has to work, and still reads once rather than
# per requirement -- the removal path calls it this way.
check("and called without one it reads it exactly once",
      _count_reads(files=[]), 1)

section("the hoisted answer is the same answer")

_files = emu_firmware.available()
# Compared as a boolean rather than by printing both: a requirement dict is
# twenty fields wide and three of them here, so a passing check would put a
# screen of JSON in the suite output for no reader.
check("state passed in reports what reading it inside would have",
      emu_firmware.status(ENTRY, _files, emu_firmware.read_state())
      == emu_firmware.status(ENTRY, _files),
      True)


if __name__ == "__main__":
    summary()
