#!/usr/bin/env python3
"""A save folder that is a link is named, because nothing backs one up.

    python scripts/tests/test_linked_save_folders.py

`os.walk` does not follow directory symlinks and rclone does not either without
`--copy-links`, so an emulator whose save folder was moved to the SD card and
linked back has its saves in neither the archive nor the storage. Both halves
agree, which is exactly why it never looked broken: the file count matches the
copy, and both are missing the same saves.

Whether to follow them is a real decision with a real cost -- a link pointing
at a ROM library would put the ROM library in somebody's cloud storage -- and
the neighbouring plugin doing this job passes `--copy-links` while rclone's own
default does not. What is not defensible either way is being silent, so this
pins that they are found and named.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import savedata  # noqa: E402

_ROOT = os.path.join(TMP, "linked", "saves")
_AWAY = os.path.join(TMP, "linked", "sdcard", "memcards")
os.makedirs(_ROOT, exist_ok=True)
os.makedirs(_AWAY, exist_ok=True)

with open(os.path.join(_ROOT, "here.srm"), "wb") as _handle:
    _handle.write(b"x" * 8)
with open(os.path.join(_AWAY, "card1.mcd"), "wb") as _handle:
    _handle.write(b"y" * 16)

_LINK = os.path.join(_ROOT, "memcards")
try:
    if not os.path.islink(_LINK):
        os.symlink(_AWAY, _LINK, target_is_directory=True)
    _made = os.path.islink(_LINK)
except (OSError, NotImplementedError):
    # Windows refuses without developer mode or an admin shell. The rule is
    # about a Deck, so the check is skipped rather than faked.
    _made = False


section("a linked save folder is found and named")

if not _made:
    print("SKIP this system would not create a symlink, so there is none to find")
else:
    _walked = [relative for _absolute, relative in savedata._walk(_ROOT)]
    check("the walk goes past what is behind the link",
          sorted(_walked), ["here.srm"])

    _found = savedata.links_skipped(_ROOT)
    check("and the link itself is reported, by name",
          [one["at"] for one in _found], ["memcards"])
    check("with where it points, which is the half that explains it",
          [os.path.basename(one["target"]) for one in _found], ["memcards"])

    # The count beside an emulator is what somebody reads as "this is
    # everything". It is not, when a folder here is a link, and the row has to
    # be able to say so.
    check("what a backup measures does not include it",
          savedata._measure(_ROOT)[0], 1)


section("a save folder with no links says nothing at all")

check("nothing to report is an empty list, not a note about links",
      savedata.links_skipped(_AWAY), [])


if __name__ == "__main__":
    summary()
