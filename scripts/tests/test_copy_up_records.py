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

from harness import TMP, check, section, summary  # noqa: E402  -- installs the stub

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


async def worked(steps, kind=""):
    return True, ""


async def failed(steps, kind=""):
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
check("and the time the panel shows is the time it finished, with what it carried",
      [sorted(one) for one in saved],
      [["cloud_last_ids", "cloud_last_remote", "cloud_last_sync"]])
check("including which storage it went to",
      [one.get("cloud_last_remote") for one in saved], ["dropbox"])
check("which names the emulators the copy actually covered",
      [one.get("cloud_last_ids") for one in saved], [["duckstation", "retroarch"]])
check("with the aged-out safety copies tidied afterwards", pruned, ["dropbox"])

carry(failed)
check("a copy that failed records nothing at all",
      (recorded, saved, pruned), ([], [], []))


section("flatpak's own plumbing is not save data")

# It announced itself in a real backup, three times: "NOTICE: .ld.so/active:
# Can't follow symlink without -L/--copy-links". Nothing behind it is a save.
# Nor is a log, nor a shader cache kept beside the saves rather than under
# `cache`, which is where Azahar keeps both -- and both change on every run, so
# counting them made opening an emulator look like save data to upload.
check("the linker cache, logs and shader caches are skipped like the flatpak cache",
      sorted(savedata._SKIP_TOP), [".ld.so", "cache", "log", "shaders"])

_whole = {"id": "duckstation", "name": "DuckStation", "whole": True,
          "roots": [("duckstation", "/home/deck/.var/app/org.duckstation.DuckStation")]}
_parts = {"id": "retroarch", "name": "RetroArch", "whole": False,
          "roots": [("saves", "/home/deck/ra/saves")]}

check("a whole-directory copy leaves both of them behind",
      [argument for argument in cloudsync._excludes(_whole)
       if argument != "--exclude"],
      ["cache/**", ".ld.so/**", "log/**", "shaders/**"])
# An emulator that says where its saves are contributes only those, so there is
# nothing to exclude and nothing to explain in the command line.
check("while an emulator that names its save folders excludes nothing",
      cloudsync._excludes(_parts), [])


section("saves nothing has sent yet are something the panel can name")

# The gap: a copy after a game covers the emulator that was played, so one that
# failed while the Deck was offline waits for the next game of *that* emulator.
# Playing something else leaves the save nowhere but here, and nothing said so.
_WAITING = os.path.join(TMP, "waiting", "saves")
os.makedirs(_WAITING, exist_ok=True)
with open(os.path.join(_WAITING, "kept.srm"), "wb") as _handle:
    _handle.write(b"x" * 40)

_SOURCES = [
    {"id": "retroarch", "name": "RetroArch", "whole": False,
     "roots": [("saves", _WAITING)]},
    # Installed, never played: no files, so nothing to say about it.
    {"id": "azahar", "name": "Azahar", "whole": False,
     "roots": [("saves", os.path.join(TMP, "waiting", "empty"))]},
]
os.makedirs(os.path.join(TMP, "waiting", "empty"), exist_ok=True)

_real_sources = savedata._all_sources
_real_mine = cloudsync.read_mine
savedata._all_sources = lambda empty=False: list(_SOURCES)
try:
    cloudsync.read_mine = lambda source_id: {}
    check("an emulator with saves and no copy behind it is waiting",
          [one["name"] for one in cloudsync.waiting_to_go()], ["RetroArch"])

    # The record the last copy left, matching the file exactly.
    _size = os.path.getsize(os.path.join(_WAITING, "kept.srm"))
    _mtime = int(os.path.getmtime(os.path.join(_WAITING, "kept.srm")))
    cloudsync.read_mine = lambda source_id: {
        "device": "deck", "at": 1,
        "files": {"saves/kept.srm": {"size": _size, "mtime": _mtime}},
    }
    check("and one whose files match what went up is not",
          cloudsync.waiting_to_go(), [])

    # **Switching storages is not the same as having copied to it.** Without
    # the name in the record, choosing another storage -- or a second account
    # of the same service -- left the Deck sure its saves were already up
    # there: the copy after a game found nothing changed and skipped, and the
    # panel said nothing was waiting while that storage sat empty.
    _sent = {"device": "deck", "at": 1, "remote": "dropbox",
             "files": {"saves/kept.srm": {"size": _size, "mtime": _mtime}}}
    cloudsync.read_mine = lambda source_id: dict(_sent)
    check("what went to one storage has not gone to another",
          [one["name"] for one in cloudsync.waiting_to_go(None, "pcloud")],
          ["RetroArch"])
    check("while the storage it did go to has nothing waiting",
          cloudsync.waiting_to_go(None, "dropbox"), [])

    # A record written before the name was kept says nothing about where it
    # went, and re-uploading every save on the Deck the first time somebody
    # updates is a worse answer than trusting it.
    cloudsync.read_mine = lambda source_id: {
        "device": "deck", "at": 1,
        "files": {"saves/kept.srm": {"size": _size, "mtime": _mtime}},
    }
    check("and a record from before the name was kept is left alone",
          cloudsync.waiting_to_go(None, "pcloud"), [])

    # **Waiting is ordinary; waiting through a copy is not.** Between quitting a
    # game and its copy landing, every save is waiting -- so the panel says
    # nothing about that. What it does say is when some later copy has been and
    # gone and this one is still here, because a copy after a game only covers
    # the emulator that was played: nothing is coming back for the rest.
    cloudsync.read_mine = lambda source_id: {
        "device": "deck", "at": 1000, "remote": "dropbox", "files": {},
    }
    check("waiting after a copy that did not carry it is overdue",
          [one["overdue"] for one in
           cloudsync.waiting_to_go(None, "dropbox", ("duckstation",), "dropbox")],
          [True])
    # **Not by comparing times.** The record goes up first and the stamp is
    # written after the rest of the bookkeeping -- four seconds later, measured
    # -- so a rule that compared them made every emulator overdue the instant
    # its files changed, including the one whose copy had just run. On the
    # device that read as the panel announcing uncopied saves seconds after a
    # game was opened.
    check("while one the last copy carried is not, however the clocks fell",
          [one["overdue"] for one in
           cloudsync.waiting_to_go(None, "dropbox", ("retroarch",), "dropbox")],
          [False])
    check("and with no copy ever finished nothing is overdue yet",
          [one["overdue"] for one in cloudsync.waiting_to_go(None, "dropbox")],
          [False])

    # **A storage just set up has received nothing**, so everything is waiting
    # and none of it is a fault -- that is what setting one up looks like. Seen
    # on the device: a storage added, one GBA game played, and the panel called
    # every other emulator a problem.
    check("a storage nothing has been copied to yet is not a fault",
          [one["overdue"] for one in
           cloudsync.waiting_to_go(None, "newdrop", ("duckstation",), "dropbox")],
          [False])
    # And an install updating from a version that recorded no such list has no
    # answer either -- reading that as "carried nothing" flagged everything.
    check("nor is an update that has no record of what the last copy carried",
          [one["overdue"] for one in
           cloudsync.waiting_to_go(None, "dropbox", (), "")],
          [False])
    # The half-answer is the one that actually reached the device: a covered
    # list left over from an older version, and no idea which storage it went
    # to. Trusting the list on its own is what flagged every emulator but the
    # one just played, ten minutes after a storage was added.
    check("and neither is a list with no storage recorded beside it",
          [one["overdue"] for one in
           cloudsync.waiting_to_go(None, "dropbox", ("duckstation",), "")],
          [False])
finally:
    savedata._all_sources = _real_sources
    cloudsync.read_mine = _real_mine


if __name__ == "__main__":
    summary()
