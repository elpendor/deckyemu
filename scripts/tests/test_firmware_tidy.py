#!/usr/bin/env python3
"""A firmware file is swept only once the emulator has demonstrably taken it in.

    python scripts/tests/test_firmware_tidy.py

Ryujinx installs Switch firmware through its own window: the plugin writes a
launcher, Steam runs the emulator, the user presses Yes -- or does not -- and
nothing comes back. So the zip stayed in the transfer folder at a few hundred
megabytes and the row grew a "Delete file" button to get rid of it by hand.
Answering the question afterwards removes that step.

**The first version of this was wrong on a real device, and the way it was
wrong is why most of these checks exist.** It compared timestamps: contents
newer than the file meant the file had gone in. But an mtime moves for things
that are not an install -- opening the emulator and closing it again touches
its folders, and removing the firmware empties that folder and stamps it with
the moment it was emptied. Ryujinx was opened and closed without installing
anything, and the zip was deleted anyway. It also never checked the folder held
anything at all, so an *empty* folder that had just been touched read as
"installed".

What only an install does is change which entries are in the folder. So the
rule is a before-and-after of the names, recorded when the file is handed over,
and both halves are required: changed, and not empty.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emu_firmware  # noqa: E402
import emu_install  # noqa: E402
import sysenv  # noqa: E402

HOME = sysenv.user_home()
REGISTERED = "test-ryujinx/bis/system/Contents/registered"

ENTRY = {
    "id": "test-switch",
    "name": "Test Switch Emulator",
    "firmware": [
        {
            "name": "Switch firmware",
            "match": r"(?i)^.*firmware.*\.(zip|xci)$",
            "detect": {"path": REGISTERED, "label": "installed"},
        },
    ],
}
SPEC = ENTRY["firmware"][0]

# A copied requirement, to prove the sweep leaves those alone: `install` copies
# rather than moves on purpose, so a file still there is a spare, not litter.
COPIED = {
    "id": "test-copied",
    "name": "Test Copier",
    "firmware": [
        {"name": "BIOS", "match": r"(?i)^bios\.bin$", "dest": "test-copied/bios"},
    ],
}


def _registered():
    return os.path.join(HOME, *REGISTERED.split("/"))


def _empty():
    """The folder present with nothing in it, which is what a removal leaves."""
    root = _registered()
    if os.path.isdir(root):
        for name in os.listdir(root):
            os.rmdir(os.path.join(root, name))
    os.makedirs(root, exist_ok=True)


def _install(count, salt=""):
    """`count` hash-named entries, as a firmware install leaves behind.

    `salt` changes the names without changing how many there are, which is what
    upgrading firmware does -- and is the case a count alone cannot see.
    """
    _empty()
    root = _registered()
    for index in range(count):
        os.makedirs(os.path.join(root, "%s%030x.nca" % (salt, index)), exist_ok=True)


def _clear():
    """An empty transfer folder and no outstanding handoff."""
    folder = emu_install.firmware_dir()
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))
    emu_firmware._write_handoff({})


def _send(name):
    with open(os.path.join(emu_install.firmware_dir(), name), "w") as handle:
        handle.write("x" * 64)


def _hand_over(name):
    """What `prepare_firmware_gui` does: note the file and the state before it."""
    emu_firmware.record_handoff(ENTRY["id"], SPEC, name)


section("the regression: opened, closed, nothing installed")

# Exactly what happened on the device. The folder is touched -- the emulator
# was started -- but nothing was added, so nothing was installed and the file
# is still the user's to install.
_clear()
_empty()
_send("Firmware 20.1.0.zip")
_hand_over("Firmware 20.1.0.zip")
os.utime(_registered(), None)          # the emulator starting, and nothing more
check("a cancelled install keeps the file", emu_firmware.spent(ENTRY), [])

# The other half of that bug: an empty folder is not an install, however
# recently anything about it moved.
check("an empty install folder is never 'installed'",
      emu_firmware.fingerprint(_registered()), "")


section("a real install sweeps the file")

_clear()
_empty()
_send("Firmware 20.1.0.zip")
_hand_over("Firmware 20.1.0.zip")
_install(238)                          # the user pressed Yes
check("the file it was given is spent", emu_firmware.spent(ENTRY),
      ["Firmware 20.1.0.zip"])


section("an upgrade over existing firmware is seen")

# The case a count cannot see, and the one "is the folder non-empty" gets
# backwards: 238 entries before and 238 after, all with different names.
_clear()
_install(238)
_send("Firmware 21.0.0.zip")
_hand_over("Firmware 21.0.0.zip")
check("before installing it, the file waits", emu_firmware.spent(ENTRY), [])
_install(238, salt="ff")
check("once installed, the same count with new contents is an install",
      emu_firmware.spent(ENTRY), ["Firmware 21.0.0.zip"])


section("only the file that was handed over")

# Another dump in the folder was never offered to the emulator, so nothing has
# been demonstrated about it.
_clear()
_empty()
_send("Firmware 20.1.0.zip")
_send("Firmware 21.0.0.zip")
_hand_over("Firmware 20.1.0.zip")
_install(238)
check("the other file is left alone", emu_firmware.spent(ENTRY),
      ["Firmware 20.1.0.zip"])


section("with no handoff recorded, nothing is ever swept")

# Firmware installed by hand months ago and a file sent today: the plugin
# handed over nothing, so it has no grounds to delete anything.
_clear()
_install(238)
_send("Firmware 21.0.0.zip")
check("an unrelated file survives", emu_firmware.spent(ENTRY), [])


section("a copied requirement is never swept")

_clear()
_send("bios.bin")
_dest = os.path.join(HOME, "test-copied", "bios")
os.makedirs(_dest, exist_ok=True)
with open(os.path.join(_dest, "bios.bin"), "w") as _handle:
    _handle.write("x" * 64)
check("an installed copy leaves its source alone", emu_firmware.spent(COPIED), [])


section("what it names can be deleted, and the record goes with it")

_clear()
_empty()
_send("Firmware 20.1.0.zip")
_hand_over("Firmware 20.1.0.zip")
_install(238)
_done = emu_firmware.spent(ENTRY)
check("named", _done, ["Firmware 20.1.0.zip"])
# `spent` names files and `remove` deletes them; `remove` refuses anything that
# is not a bare basename, so the two have to agree on what a name is.
check("remove accepts it", emu_firmware.remove(_done).get("removed"),
      ["Firmware 20.1.0.zip"])
emu_firmware.forget_handoffs(_done)
# Left behind, the record would answer for the next file to take that name --
# a re-sent zip deleted on the strength of an install it never had.
_send("Firmware 20.1.0.zip")
check("and the record does not answer for a re-sent file",
      emu_firmware.spent(ENTRY), [])

# The suite shares this folder and this home with every file after it.
_clear()

summary()
