#!/usr/bin/env python3
"""A copy up is written down the same way however it was started.

    python scripts/tests/test_copy_up_records.py

Saves go up two ways -- a game closing, and the button in the panel -- and both
have to leave the same three things behind: a record beside the saves for each
emulator, this Deck's copy of that record, and the time the panel shows as
"Last copied". The button was leaving the time alone, so a backup made by hand
finished and the panel still said hours ago.

And none of it may be written when the copy did not work: a record claiming the
storage holds what the Deck holds is what stops the next copy sending the save
that never arrived.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import cloudsync  # noqa: E402
import savedata  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

STEPS = [{"id": "retroarch", "name": "RetroArch saves", "argv": []},
         {"id": "duckstation", "name": "DuckStation", "argv": []}]

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()

saved = []
recorded = []
pruned = []


async def worked(steps):
    return True, ""


async def failed(steps):
    return False, "connection refused"


def carry(stream):
    """One detached copy up, with everything it writes to recorded instead."""
    del saved[:], recorded[:], pruned[:]
    real = (store.set_settings, cloudsync.record_pushes, cloudsync.prune)
    store.set_settings = lambda values: saved.append(values)
    cloudsync.record_pushes = lambda remote, ids: recorded.append(sorted(ids)) or (True, "")
    cloudsync.prune = lambda remote: pruned.append(remote)
    plugin._stream_cloud = stream
    try:
        plugin.loop.run_until_complete(
            plugin._carry_saves(STEPS, "cloud_sync_done", tidy="dropbox"))
    finally:
        store.set_settings, cloudsync.record_pushes, cloudsync.prune = real


section("a copy made from the panel is written down like any other")

carry(worked)
check("every emulator in the copy gets its record",
      recorded, [["duckstation", "retroarch"]])
check("and the time the panel shows is the time it finished",
      [sorted(one) for one in saved], [["cloud_last_sync"]])
check("with the aged-out safety copies tidied afterwards", pruned, ["dropbox"])

carry(failed)
check("a copy that failed records nothing at all",
      (recorded, saved, pruned), ([], [], []))


section("flatpak's own plumbing is not save data")

# It announced itself in a real backup, three times: "NOTICE: .ld.so/active:
# Can't follow symlink without -L/--copy-links". Nothing behind it is a save.
check("the linker cache is skipped like the flatpak cache",
      sorted(savedata._SKIP_TOP), [".ld.so", "cache"])

_whole = {"id": "duckstation", "name": "DuckStation", "whole": True,
          "roots": [("duckstation", "/home/deck/.var/app/org.duckstation.DuckStation")]}
_parts = {"id": "retroarch", "name": "RetroArch", "whole": False,
          "roots": [("saves", "/home/deck/ra/saves")]}

check("a whole-directory copy leaves both of them behind",
      [argument for argument in cloudsync._excludes(_whole)
       if argument != "--exclude"],
      ["cache/**", ".ld.so/**"])
# An emulator that says where its saves are contributes only those, so there is
# nothing to exclude and nothing to explain in the command line.
check("while an emulator that names its save folders excludes nothing",
      cloudsync._excludes(_parts), [])


if __name__ == "__main__":
    summary()
