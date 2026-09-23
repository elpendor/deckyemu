#!/usr/bin/env python3
"""Adding a disc to a game that is already in the library.

    python scripts/tests/test_add_disc.py

The case is ordinary and had no answer in Game Mode: a two-disc game whose
second disc turned up after the first was added. Disc 1 went in on its own, so
there is no playlist, and the only route to one entry was to delete the game and
add it again -- which throws away the Steam app id, and the play time and any
per-game controller layout with it.

What is checked here is the part that touches disk, because that is the part
whose failure is invisible. A playlist naming a file that is not beside it is a
game that does not start; a second playlist written next to the first is a
folder nobody can read afterwards; and a disc left in the transfer folder is the
feature silently doing nothing.

The two shapes are different and both are common. A game added as a **single
disc** has to gain a playlist, which the shortcut is then repointed at. A game
that already **is** a set has to keep the playlist it has -- same filename, so
the shortcut pointing at it goes on working -- with a line added.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import discset  # noqa: E402


def disc(folder, name):
    """A .cue and the .bin it names, so the parser has something real to read."""
    track = os.path.splitext(name)[0] + ".bin"
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n' % track)
    with open(os.path.join(folder, track), "w", encoding="utf-8") as handle:
        handle.write("x")


section("ordering -- a disc picked from a browser arrives last, whatever its number")

check("numbered discs come back in disc order",
      discset.in_disc_order(["Zed (Disc 2).cue", "Zed (Disc 1).cue"]),
      ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])
check("and a three-disc set is not sorted as text",
      discset.in_disc_order(["Zed (Disc 10).cue", "Zed (Disc 2).cue", "Zed (Disc 1).cue"]),
      ["Zed (Disc 1).cue", "Zed (Disc 2).cue", "Zed (Disc 10).cue"])
# A set the naming rules cannot read is one somebody assembled by hand, and the
# order they picked in is the only answer anybody has.
check("names with no marker keep the order they were given",
      discset.in_disc_order(["Zed d2.cue", "Zed d1.cue"]),
      ["Zed d2.cue", "Zed d1.cue"])


section("a single-disc game gains a playlist")

with tempfile.TemporaryDirectory() as folder:
    disc(folder, "Zed (Disc 1).cue")
    disc(folder, "Zed (Disc 2).cue")

    discs = discset.in_disc_order(["Zed (Disc 1).cue", "Zed (Disc 2).cue"])
    path, error = discset.write_playlist(folder, discs)
    check("it is written", error, "")
    check("and named after the discs without their number",
          os.path.basename(path), "Zed.m3u")
    with open(path, encoding="utf-8") as handle:
        check("naming both discs in order", handle.read().splitlines(),
              ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])


section("a game that is already a set keeps the playlist it has")

with tempfile.TemporaryDirectory() as folder:
    disc(folder, "Zed (Disc 1).cue")
    disc(folder, "Zed (Disc 2).cue")
    first, _error = discset.write_playlist(
        folder, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])

    # The third disc turns up later. The shortcut points at the playlist by
    # name, so a new file beside it would leave the game running the old two.
    disc(folder, "Zed (Disc 3).cue")
    three = discset.in_disc_order(
        ["Zed (Disc 1).cue", "Zed (Disc 2).cue", "Zed (Disc 3).cue"])
    again, error = discset.write_playlist(folder, three, os.path.basename(first))
    check("rewriting its own playlist is allowed", error, "")
    check("and it is the same file, so the shortcut still points at it",
          again, first)
    with open(again, encoding="utf-8") as handle:
        check("now naming three discs", handle.read().splitlines(), three)
    check("and no second playlist was left beside it",
          sorted(name for name in os.listdir(folder) if name.endswith(".m3u")),
          ["Zed.m3u"])


section("what it still refuses")

with tempfile.TemporaryDirectory() as folder:
    disc(folder, "Zed (Disc 1).cue")
    disc(folder, "Zed (Disc 2).cue")
    # Somebody else's file of the same name. Overwriting is only ever allowed
    # for the playlist the caller's own game is already pointed at.
    with open(os.path.join(folder, "Zed.m3u"), "w", encoding="utf-8") as handle:
        handle.write("something the user wrote\n")
    _path, error = discset.write_playlist(
        folder, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])
    check("a playlist already there saying something else is not overwritten",
          "already there" in error, True)

    # `replacing` names a file in this folder, never a path out of it.
    _path, error = discset.write_playlist(
        folder, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"], "../../elsewhere.m3u")
    check("and it cannot be pointed out of the folder",
          "not a file in this folder" in error, True)

with tempfile.TemporaryDirectory() as folder:
    disc(folder, "Zed (Disc 1).cue")
    # The disc is named but not there: the game would start and fail to find it.
    _path, error = discset.write_playlist(
        folder, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])
    check("a disc that is not in the folder is refused",
          "not in this folder" in error, True)
