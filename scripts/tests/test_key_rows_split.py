#!/usr/bin/env python3
"""prod.keys and title.keys are a row each, and old records follow the split.

    python scripts/tests/test_key_rows_split.py

A row is the only way to send a file. The two Switch key files were one
requirement matching both names -- itself a fix for a row called "prod.keys"
that silently installed a title.keys sent beside it -- and that left the second
file no route at all: a row with anything installed reads as done, and a done
row offers Delete and Remove where the Send button would be. Everybody sends
prod.keys first, because it is the one that matters, so everybody closed the
only door title.keys had.

The half worth testing hardest is not the split, which is data. It is that a
device which already installed its keys under the old name is not then told its
own prod.keys is a stranger's: the record is keyed by requirement name, and
`status` reports anything at the destination it cannot account for as foreign.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emu_firmware  # noqa: E402
import emulator_catalog  # noqa: E402
import sysenv  # noqa: E402

ENTRY = emulator_catalog.find("ryujinx")
DEST = os.path.join(sysenv.user_home(),
                    *".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system".split("/"))


def _requirement(name):
    return next((item for item in ENTRY["firmware"] if item["name"] == name), None)


section("the two key files have a row each")

_names = [item["name"] for item in ENTRY["firmware"]]
check("prod.keys is its own requirement", "prod.keys" in _names, True)
check("and so is title.keys", "title.keys" in _names, True)
check("the merged row is gone", "prod.keys and title.keys" in _names, False)

# Each pattern must accept its own file and refuse the other, or the rows are
# two names for one thing again and sending either fills both.
_prod, _title = _requirement("prod.keys"), _requirement("title.keys")
check("prod.keys matches only prod.keys",
      emu_firmware.matching(_prod, [{"name": "prod.keys"}, {"name": "title.keys"}]),
      ["prod.keys"])
check("title.keys matches only title.keys",
      emu_firmware.matching(_title, [{"name": "prod.keys"}, {"name": "title.keys"}]),
      ["title.keys"])
# Dumps arrive from tools that disagree about case.
check("case is not what decides it",
      emu_firmware.matching(_prod, [{"name": "PROD.KEYS"}]), ["PROD.KEYS"])

# Without this, adding any Switch game reports the emulator as missing
# something, forever, for a file most games never need.
check("title.keys is optional so it is never reported as unmet",
      bool(_title.get("optional")), True)
check("prod.keys is not optional", bool(_prod.get("optional")), False)
check("both land in the same folder", _prod["dest"], _title["dest"])


section("a record written under the old name follows the split")

emu_firmware._write_state({
    "ryujinx": {"prod.keys and title.keys": ["prod.keys"]},
    # A second emulator, to prove the migration keeps to its own entry.
    "pcsx2": {"PS2 BIOS": ["SCPH39004.bin"]},
})
_moved = emu_firmware.resplit_record("ryujinx", "prod.keys and title.keys", ENTRY)
check("the file moves to the row that now matches it", _moved, {"prod.keys": ["prod.keys"]})

_state = emu_firmware.read_state()
check("recorded under the new name", _state["ryujinx"].get("prod.keys"), ["prod.keys"])
check("and the old key is gone", "prod.keys and title.keys" in _state["ryujinx"], False)
check("another emulator's record is untouched",
      _state["pcsx2"], {"PS2 BIOS": ["SCPH39004.bin"]})

# The point of the whole migration: `status` must still call this file ours.
os.makedirs(DEST, exist_ok=True)
with open(os.path.join(DEST, "prod.keys"), "w") as _handle:
    _handle.write("x" * 32)
_row = next(item for item in emu_firmware.status(ENTRY, []) if item["name"] == "prod.keys")
check("the installed key is recognised", _row["installed"], ["prod.keys"])
check("and is not reported as somebody else's file", _row["foreign"], [])


section("both files re-file when both were recorded")

emu_firmware._write_state(
    {"ryujinx": {"prod.keys and title.keys": ["prod.keys", "title.keys"]}}
)
_moved = emu_firmware.resplit_record("ryujinx", "prod.keys and title.keys", ENTRY)
check("each goes to its own row", _moved,
      {"prod.keys": ["prod.keys"], "title.keys": ["title.keys"]})


section("running it twice changes nothing")

# Startup steps run on every start, so the second pass has to be a no-op rather
# than a second copy of every filename.
_before = emu_firmware.read_state()
check("a second pass finds nothing to move",
      emu_firmware.resplit_record("ryujinx", "prod.keys and title.keys", ENTRY), {})
check("and leaves the records alone", emu_firmware.read_state(), _before)


section("a record naming a file no row matches is not lost quietly")

# The old key goes either way -- it names a requirement that no longer exists,
# so leaving it would have it re-examined at every start forever.
emu_firmware._write_state({"ryujinx": {"prod.keys and title.keys": ["mystery.bin"]}})
check("nothing is claimed to have moved",
      emu_firmware.resplit_record("ryujinx", "prod.keys and title.keys", ENTRY), {})
check("and the dead key is still dropped",
      "prod.keys and title.keys" in emu_firmware.read_state().get("ryujinx", {}), False)

# Shared with every file after this one.
emu_firmware._write_state({})
try:
    os.remove(os.path.join(DEST, "prod.keys"))
except OSError:
    pass

summary()
