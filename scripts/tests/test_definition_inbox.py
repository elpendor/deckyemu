#!/usr/bin/env python3
"""A definition already on the device can be imported without sending it again.

    python scripts/tests/test_definition_inbox.py

The only route in was the transfer dialog's received list, and that list holds
what *this session* took delivery of. It does not survive a reload and it is
empty on a Deck that was sent a file yesterday -- so a definition sitting in the
transfer folder had no route into the plugin at all, and the refusal said it was
"not in the transfer folder" while it sat there. Reading the folder is what
makes the Import button on the Emulators tab possible.

The name reaching a filesystem path is the part worth checking hardest. A
definition names software to install and directories to write into, so which
file is read must not be a choice the frontend gets to make: it names one of the
files in the inbox, and anything else is refused.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, REPO_ROOT  # noqa: E402  -- decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emulator_catalog  # noqa: E402
import fileserver  # noqa: E402
from emulator_catalog import imported  # noqa: E402

INBOX = fileserver.default_dir()


def _write(name, text="{}"):
    path = os.path.join(INBOX, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


section("what is waiting is read off the folder, not off this session")

# Nothing was received by this process, so the old route sees none of these.
check("this session took delivery of nothing", fileserver.received_files(), [])

_write("first%s" % imported.SUFFIX)
_write("second%s" % imported.SUFFIX)
_write("Some Game.iso")
_write("notes.txt")

_names = [item["name"] for item in fileserver.inbox_files(imported.SUFFIX)]
check("both definitions are found", sorted(_names),
      ["first%s" % imported.SUFFIX, "second%s" % imported.SUFFIX])
check("and nothing that is not one", any(n.endswith(".iso") for n in _names), False)

# The suffix is optional, so the same helper answers "what is in the inbox".
check("without a suffix it lists everything",
      len(fileserver.inbox_files()) >= 4, True)

# Newest first: the file somebody just sent is the one they are looking for.
_recent = _write("newest%s" % imported.SUFFIX)
os.utime(_recent, (2 ** 31 - 1, 2 ** 31 - 1))
check("newest first", fileserver.inbox_files(imported.SUFFIX)[0]["name"],
      "newest%s" % imported.SUFFIX)


section("a name reaches one of those files, and nothing else")

check("a file that is there resolves",
      os.path.basename(fileserver.inbox_path("first%s" % imported.SUFFIX)),
      "first%s" % imported.SUFFIX)
check("and it resolves inside the inbox",
      os.path.dirname(fileserver.inbox_path("first%s" % imported.SUFFIX)),
      os.path.normpath(INBOX))

check("a file that is not there resolves to nothing",
      fileserver.inbox_path("never-sent%s" % imported.SUFFIX), "")

# The name arrives from the frontend and decides which file is read and acted
# on. A name that is not already its own basename is refused rather than reduced
# to one -- `subdir/first.deckyemu.json` would otherwise resolve to a real file
# nobody asked for, which is worse than not finding it.
for _escape in ("../../etc/passwd", "..\\..\\windows\\win.ini",
                "/etc/passwd", "subdir/first%s" % imported.SUFFIX):
    check("%r cannot escape the inbox" % _escape, fileserver.inbox_path(_escape), "")

# An empty or absent name must not resolve to the folder itself, or to the
# fallback `safe_name` gives anything unusable.
for _empty in ("", None, ".", ".."):
    check("%r resolves to nothing" % (_empty,), fileserver.inbox_path(_empty), "")


section("a directory in the inbox is not a definition")

os.makedirs(os.path.join(INBOX, "a-folder%s" % imported.SUFFIX), exist_ok=True)
check("a directory named like one is not listed",
      any(item["name"].startswith("a-folder")
          for item in fileserver.inbox_files(imported.SUFFIX)),
      False)
check("and does not resolve as a file",
      fileserver.inbox_path("a-folder%s" % imported.SUFFIX), "")


section("the partial files an upload leaves are never offered")

# `.uploading` is the real suffix -- see `_partial_path`.
_write("half-sent.iso.abc123.uploading")
_listed = [item["name"] for item in fileserver.inbox_files()]
check("a partial is not in the inbox listing",
      any(name.endswith(".uploading") for name in _listed), False)
# Not vacuous: the file is on disk, so an empty listing would pass this too.
check("though it is there to be excluded",
      os.path.isfile(os.path.join(INBOX, "half-sent.iso.abc123.uploading")), True)
check("and the real files still are listed", "notes.txt" in _listed, True)


section("importing takes the file out of the staging folder")

# The transfer folder is a middle point between sending and importing, not a
# store. A definition that has been imported is a duplicate of the one the
# plugin now keeps under `emulators.d`, so leaving it means the Import list
# grows every time somebody uses it and never shrinks. Firmware settled this the
# same way -- see emu_firmware's module docstring, and note that `install`'s own
# docstring claimed the opposite for a long time while calling `shutil.move`.

import asyncio  # noqa: E402

sys.path.insert(0, REPO_ROOT)
import main  # noqa: E402

_loop = asyncio.new_event_loop()
_plugin = main.Plugin()
# `_main` is what normally sets this, and it does a great deal else besides.
# These endpoints need the loop and nothing more.
_plugin.loop = _loop


def _run(coro):
    return _loop.run_until_complete(coro)


_GOOD = json.dumps({
    "id": "inboxtest",
    "name": "Inbox Test",
    "summary": "A system.",
    "source": {"kind": "byo"},
    "args": "-g {rom}",
    "root": ".config/inboxtest",
    "platform": "Nintendo - Switch",
})

_write("inboxtest%s" % imported.SUFFIX, _GOOD)
check("the file is waiting before anything happens",
      bool(fileserver.inbox_path("inboxtest%s" % imported.SUFFIX)), True)

_result = _run(_plugin.import_emulator_definition("inboxtest%s" % imported.SUFFIX))
check("it imports", _result.get("ok"), True)
check("and the plugin keeps its own copy",
      os.path.isfile(imported.path_for("inboxtest")), True)
check("and the staging copy is gone",
      fileserver.inbox_path("inboxtest%s" % imported.SUFFIX), "")
check("so the Import list no longer offers it",
      [item["name"] for item in fileserver.inbox_files(imported.SUFFIX)
       if item["name"].startswith("inboxtest")],
      [])

# The half with the real cost. A refused definition is still the user's only
# copy on the device, and consuming it would leave them holding the reasons it
# was refused and nothing to fix.
_write("brokentest%s" % imported.SUFFIX, "{ not json at all")
_bad = _run(_plugin.import_emulator_definition("brokentest%s" % imported.SUFFIX))
check("a definition that will not parse is refused", _bad.get("ok"), False)
check("and is left where it was",
      bool(fileserver.inbox_path("brokentest%s" % imported.SUFFIX)), True)

# Refused by a rule rather than by the parser: valid JSON, forbidden content.
_write("nastytest%s" % imported.SUFFIX, json.dumps({
    "id": "nastytest",
    "name": "Nasty",
    "summary": "A system.",
    "source": {"kind": "byo"},
    "args": "-g {rom}",
    "root": ".config/nastytest",
    "platform": "Nintendo - Switch",
    "removes": [".config/something"],
}))
_nasty = _run(_plugin.import_emulator_definition("nastytest%s" % imported.SUFFIX))
check("a definition refused by a rule is refused", _nasty.get("ok"), False)
check("and is also left where it was",
      bool(fileserver.inbox_path("nastytest%s" % imported.SUFFIX)), True)

# Previewing must never consume anything: it is what somebody presses to decide.
_preview = _run(_plugin.preview_emulator_definition("brokentest%s" % imported.SUFFIX))
check("previewing does not remove the file",
      bool(fileserver.inbox_path("brokentest%s" % imported.SUFFIX)), True)

section("a file that was simply not wanted can be deleted")

# The only way to, in Game Mode. Everything else that takes something out of the
# transfer folder does it as a side effect of *using* the file, so a refused
# definition or a ROM thought better of stayed forever and the alternative was
# Desktop Mode and a file manager.

_write("zz-unwanted%s" % imported.SUFFIX, "{ not valid")
check("it is there", bool(fileserver.inbox_path("zz-unwanted%s" % imported.SUFFIX)), True)

_gone = _run(_plugin.discard_transferred_file("zz-unwanted%s" % imported.SUFFIX))
check("deleting it works", (_gone.get("ok"), _gone.get("removed")), (True, True))
check("and it is gone", fileserver.inbox_path("zz-unwanted%s" % imported.SUFFIX), "")

# Pressing twice on a stale list is the ordinary case, not a fault: the folder
# is in the state the caller asked for either way.
_again = _run(_plugin.discard_transferred_file("zz-unwanted%s" % imported.SUFFIX))
check("deleting it twice is not an error",
      (_again.get("ok"), _again.get("removed")), (True, False))

# The name decides which file is deleted, so this is the half worth checking
# hardest. `inbox_path` refuses anything that is not already the basename of a
# real file in the folder, and nothing here should reach a file outside it.
_outside = os.path.join(os.path.dirname(INBOX), "not-a-transfer.txt")
with open(_outside, "w", encoding="utf-8") as _handle:
    _handle.write("keep me")
for _escape in ("../not-a-transfer.txt", "..\not-a-transfer.txt",
                _outside, "subdir/notes.txt", "", "..", "."):
    _refused = _run(_plugin.discard_transferred_file(_escape))
    check("%r deletes nothing" % (_escape,), _refused.get("removed"), False)
check("and the file outside the folder is untouched", os.path.isfile(_outside), True)
os.remove(_outside)

# A file in the folder that is not a definition is still deletable -- the point
# is the folder, not the file type. This is the case of a ROM thought better of.
check("a ROM in the inbox can go too",
      _run(_plugin.discard_transferred_file("Some Game.iso")).get("removed"), True)


# Put it back. `emulators.d` and the transfer folder are shared by the whole
# run, and a definition left imported here changes what the catalog holds for
# every file after this one -- which is how three checks in test_imported.py
# started failing about a bundled count they had nothing to do with. The rule
# the suite works to: derive the expectation from what is there, or set the
# state aside and put it back.
_run(_plugin.remove_imported_emulator("inboxtest"))
check("the imported definition is cleaned up",
      os.path.isfile(imported.path_for("inboxtest")), False)
for _leftover in ("brokentest", "nastytest"):
    _path = fileserver.inbox_path("%s%s" % (_leftover, imported.SUFFIX))
    if _path:
        os.remove(_path)
check("and so are the refused ones",
      [item["name"] for item in fileserver.inbox_files(imported.SUFFIX)
       if item["name"].endswith("test%s" % imported.SUFFIX)],
      [])
check("the catalog is back to what it was",
      any(entry.get("id") == "inboxtest" for entry in emulator_catalog.CATALOG),
      False)

_loop.close()


if __name__ == "__main__":
    summary()
