#!/usr/bin/env python3
"""A sent file that was never added must still be reachable.

    python scripts/tests/test_waiting_rom_dir.py

The received list in the Transfer dialog is the only route to a transferred
file, and it does not survive: `start()` clears it, so a reload -- or closing
the dialog and coming back -- leaves the file on disk with nothing pointing at
it. The picker then opens at `last_rom_dir`, which could be an SD card three
navigations away.

`waiting_dir()` is what closes that, and the reason it answers conditionally
rather than always is the point of most of these checks. The transfer folder
empties itself as games are added, so it is empty most of the time, and a picker
opening in an empty folder is the miss `ra_detect.default_rom_dir` stopped
guessing to avoid. It must answer when there is something to find and stay quiet
otherwise.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

import fileserver  # noqa: E402
import sysenv  # noqa: E402

section("the ROM picker opens where a sent file is waiting")

_home = sysenv.user_dir("", create=False)
_transfer = os.path.join(_home, "transfer")
_stash = os.path.join(_home, "transfer-set-aside-by-this-file")

# The suite shares one scratch home, and files that ran earlier leave uploads in
# the inbox -- so "nothing has been sent yet" is only true when this file runs
# alone. It passed alone and failed in the suite, which is the confusing way to
# learn that. Set the folder aside rather than empty it: a neighbour may be
# asserting on what is in there, and this file has no business deciding.
if os.path.isdir(_transfer):
    os.rename(_transfer, _stash)

# Nothing has been sent yet, and asking must not be what creates the folder --
# `user_dir` creates on demand, so a question asked carelessly leaves an empty
# transfer folder on a device that has never used the feature.
check("with nothing sent, there is nowhere to point at", fileserver.waiting_dir(), "")
check("and asking did not create the folder", os.path.isdir(_transfer), False)

os.makedirs(_transfer, exist_ok=True)
check("an empty inbox is still nothing to point at", fileserver.waiting_dir(), "")

# A partial upload is not a file anybody can add, and it is what a transfer
# interrupted by a reload leaves behind -- exactly the situation this feature is
# for, so pointing the picker at one would be worse than not pointing at all.
with open(os.path.join(_transfer, "half-sent.zip.uploading"), "w") as handle:
    handle.write("x")
check("a partial upload does not count as something waiting",
      fileserver.waiting_dir(), "")

with open(os.path.join(_transfer, ".hidden"), "w") as handle:
    handle.write("x")
check("nor does a dotfile", fileserver.waiting_dir(), "")

# The case the whole thing exists for.
_rom = os.path.join(_transfer, "Some Game (USA).sfc")
with open(_rom, "w") as handle:
    handle.write("x")
check("a sent ROM points the picker at the inbox",
      fileserver.waiting_dir(), fileserver.default_dir(create=False))

# Adding the game moves the ROM out, which is how the folder empties -- and the
# picker has to go back to behaving normally when it does, or a user whose
# library lives on an SD card is sent to an empty folder for ever.
os.remove(_rom)
check("and stops once the game has been added and its ROM moved out",
      fileserver.waiting_dir(), "")

section("the status payload carries it to the picker")

sys.path.insert(0, REPO_ROOT)
import main as plugin_main  # noqa: E402

_plugin = plugin_main.Plugin()
_plugin.loop = __import__("asyncio").new_event_loop()
_plugin._install = None
_plugin._cores = []
_plugin._emulators = []
_status = _plugin.loop.run_until_complete(_plugin.get_status())

# The frontend reads this by name; a rename here is a picker that silently goes
# back to opening at home, with nothing failing to say so.
check("status reports where the picker should open", "waiting_rom_dir" in _status, True)
check("and says nothing is waiting when nothing is", _status["waiting_rom_dir"], "")

with open(_rom, "w") as handle:
    handle.write("x")
_status = _plugin.loop.run_until_complete(_plugin.get_status())
check("and names the inbox once something is",
      _status["waiting_rom_dir"], fileserver.default_dir(create=False))
# The fallback the picker uses behind it must still be there, since it is what
# answers the rest of the time.
check("without losing the default it falls back to",
      bool(_status["default_rom_dir"]), True)
os.remove(_rom)
_plugin.loop.close()

# Put back exactly what was there, so a file that runs after this one sees the
# inbox it would have seen without it.
shutil.rmtree(_transfer, ignore_errors=True)
if os.path.isdir(_stash):
    os.rename(_stash, _transfer)


if __name__ == "__main__":
    from harness import summary

    summary()
