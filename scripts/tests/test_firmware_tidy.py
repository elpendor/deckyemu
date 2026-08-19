#!/usr/bin/env python3
"""A firmware file the emulator has taken in is swept; a newer one is not.

    python scripts/tests/test_firmware_tidy.py

Ryujinx installs Switch firmware through its own window: the plugin writes a
launcher, Steam runs the emulator, the user presses Yes, and nothing comes back
to the plugin at all. So the zip stayed in the transfer folder at a few hundred
megabytes and the row grew a "Delete file" button to get rid of it by hand.
Asking the filesystem afterwards removes that step.

The check that earns its place is the second one. The obvious rule -- "the
registered folder has contents, so the firmware is installed, so the zip can
go" -- deletes somebody's firmware *upgrade* before they ever apply it, because
`detect` cannot tell 6.0-is-installed from 7.0-is-not. The rule is therefore
about the file rather than the folder: contents newer than the file mean the
file went in; contents older mean it is a newer dump still waiting its turn.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emu_firmware  # noqa: E402
import emu_install  # noqa: E402
import sysenv  # noqa: E402

HOME = sysenv.user_home()
REGISTERED = "test-ryujinx/bis/system/Contents/registered"

# Shaped like the catalog's, and only the fields `spent` reads.
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

# A copied requirement, to prove the sweep leaves those alone: `install` copies
# rather than moves on purpose, so a file still sitting there is a second dump
# the user chose to keep, not litter.
COPIED = {
    "id": "test-copied",
    "name": "Test Copier",
    "firmware": [
        {"name": "BIOS", "match": r"(?i)^bios\.bin$", "dest": "test-copied/bios"},
    ],
}


def _registered_dir():
    return os.path.join(HOME, *REGISTERED.split("/"))


def _install_firmware(when):
    """238 hash-named directories, as a real install leaves. Stamped at `when`."""
    root = _registered_dir()
    os.makedirs(root, exist_ok=True)
    for index in range(3):
        entry = os.path.join(root, "%032x.nca" % index)
        os.makedirs(entry, exist_ok=True)
        os.utime(entry, (when, when))
    os.utime(root, (when, when))


def _clear():
    """Start a section from an empty transfer folder.

    Sections here share one folder and one home, and a file left by the section
    above is exactly the kind of thing that makes a check pass alone and fail in
    the suite -- so each section says what it starts from.
    """
    folder = emu_install.firmware_dir()
    for name in os.listdir(folder):
        os.remove(os.path.join(folder, name))


def _send(name, when):
    """A file in the transfer folder, stamped at `when`."""
    path = os.path.join(emu_install.firmware_dir(), name)
    with open(path, "w") as handle:
        handle.write("x" * 64)
    os.utime(path, (when, when))
    return path


NOW = time.time()
HOUR = 3600.0

section("a file the emulator has already taken in is spent")

_clear()
_send("Firmware 20.1.0.zip", NOW - 2 * HOUR)
_install_firmware(NOW - HOUR)          # installed after the file arrived
check("the sent firmware is reported as spent",
      emu_firmware.spent(ENTRY), ["Firmware 20.1.0.zip"])

section("a newer firmware than the one installed is NOT spent")

# The whole reason this is not "is anything installed": a device with firmware
# on it looks identical to one without, to `detect`. Deleting on that basis
# throws away the upgrade the user just spent an afternoon dumping.
_clear()
_send("Firmware 21.0.0.zip", NOW)      # sent after the install
check("a firmware sent after the install is kept", emu_firmware.spent(ENTRY), [])
check("and the folder still has it",
      "Firmware 21.0.0.zip" in os.listdir(emu_install.firmware_dir()), True)

section("nothing installed means nothing is spent")

_gone = _registered_dir()
for _root, _dirs, _files in os.walk(_gone, topdown=False):
    for _d in _dirs:
        os.rmdir(os.path.join(_root, _d))
os.rmdir(_gone)
check("with no firmware installed, the file waits", emu_firmware.spent(ENTRY), [])
_clear()

section("a copied requirement is never swept")

# `install` copies rather than moves, deliberately -- the folder sent to is the
# folder resent from. Sweeping those would delete a spare the user kept.
_clear()
_send("bios.bin", NOW - 2 * HOUR)
_dest = os.path.join(HOME, "test-copied", "bios")
os.makedirs(_dest, exist_ok=True)
with open(os.path.join(_dest, "bios.bin"), "w") as _h:
    _h.write("x" * 64)
check("an installed copy leaves its source alone", emu_firmware.spent(COPIED), [])

section("the file it names can actually be deleted")

# `spent` names files and `remove` deletes them, and the two have to agree on
# what a name is -- `remove` refuses anything that is not a bare basename.
_clear()
_install_firmware(NOW)
_send("Firmware 20.1.0.zip", NOW - HOUR)
_done = emu_firmware.spent(ENTRY)
check("it is named again", _done, ["Firmware 20.1.0.zip"])
_result = emu_firmware.remove(_done)
check("and remove accepts that name", _result.get("ok"), True)
check("with the file gone", _result.get("removed"), ["Firmware 20.1.0.zip"])

# The suite shares this folder and this home with every file after it.
_clear()

summary()
