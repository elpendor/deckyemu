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

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

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


if __name__ == "__main__":
    summary()
