#!/usr/bin/env python3
"""Filing and deleting a multi-disc game, all the way down to its tracks.

    python scripts/tests/test_disc_filing.py

**The deepest path `romshelf` has, and nothing exercised it until this.** A
two-disc PlayStation game with audio is seven files: an `.m3u` naming two
`.cue` files, each naming two `.bin` tracks. Filing it means walking all three
levels and moving every one; a single file left behind is a game that starts and
then cannot find its second disc, or cannot play its music -- which reads as a
bad dump rather than as a plugin that half-moved something.

Deleting has the same shape and worse consequences, since what is not deleted is
invisible: a `.bin` orphaned in `roms/ps1` is a few hundred megabytes nothing
will ever point at again.

Both are tested here against real directories, because the thing being checked
is what ends up on disk. `file_rom` and `delete_rom` take the inbox and the
library as arguments, so no plugin, no Deck, and no monkeypatching is needed.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import discset  # noqa: E402
import romshelf  # noqa: E402

PS1 = "Sony - PlayStation"


def build_set(inbox, discs=2, tracks=2):
    """A multi-disc rip in `inbox`: one .cue per disc, `tracks` .bin under each.

    Written rather than faked, so the parser this is testing has real sheets to
    read. One byte per track: what matters is the graph of references, not the
    contents.
    """
    for disc in range(1, discs + 1):
        names = ["Zed (Disc %d) (Track %02d).bin" % (disc, track)
                 for track in range(1, tracks + 1)]
        with open(os.path.join(inbox, "Zed (Disc %d).cue" % disc),
                  "w", encoding="utf-8", newline="\n") as handle:
            for index, name in enumerate(names, start=1):
                handle.write('FILE "%s" BINARY\n' % name)
                handle.write("  TRACK %02d %s\n"
                             % (index, "MODE2/2352" if index == 1 else "AUDIO"))
        for name in names:
            with open(os.path.join(inbox, name), "w", encoding="utf-8") as handle:
                handle.write("x")


section("two discs, two tracks each -- seven files that travel together")

with tempfile.TemporaryDirectory() as root:
    inbox = os.path.join(root, "transfer")
    library = os.path.join(root, "roms")
    os.makedirs(inbox)
    os.makedirs(library)
    build_set(inbox)

    # What the panel would offer: the .cue files, and neither of the four
    # tracks. Checked here as well as in test_discset.py because everything
    # below depends on it -- a playlist naming tracks would file the wrong graph.
    found = discset.find_set(os.path.join(inbox, "Zed (Disc 1).cue"))
    check("the set is the two sheets", found, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])

    playlist, error = discset.write_playlist(inbox, found)
    check("the playlist is written", error, "")

    # Three levels: the .m3u names the sheets, each sheet names its tracks.
    group = romshelf.companions(playlist)
    check("everything the playlist reaches is one group", sorted(group), sorted([
        "Zed (Disc 1) (Track 01).bin", "Zed (Disc 1) (Track 02).bin",
        "Zed (Disc 1).cue",
        "Zed (Disc 2) (Track 01).bin", "Zed (Disc 2) (Track 02).bin",
        "Zed (Disc 2).cue",
        "Zed.m3u",
    ]))

    filed = romshelf.file_rom(playlist, PS1, inbox, library)
    check("the playlist is what the caller carries on with",
          os.path.basename(filed), "Zed.m3u")
    check("and it lands in the system's own folder",
          os.path.basename(os.path.dirname(filed)), "ps1")
    check("all seven files moved",
          sorted(os.listdir(os.path.join(library, "ps1"))), sorted(group))
    # The half that is easy to forget: filing is a *move*. A copy leaves the
    # inbox full and the user reporting that nothing was sent anywhere.
    check("and none was left in the inbox", os.listdir(inbox), [])

    # Deleting takes the same graph. This is the one whose failure is invisible:
    # an orphaned .bin is hundreds of megabytes nothing will ever point at.
    check("the filed game is ours to delete", romshelf.owned(filed, library), True)
    freed, error = romshelf.delete_rom(filed, library)
    check("deleting says nothing went wrong", error, "")
    check("and takes all seven with it",
          os.path.isdir(os.path.join(library, "ps1")), False)


section("a disc missing its tracks is not filed at all")

with tempfile.TemporaryDirectory() as root:
    inbox = os.path.join(root, "transfer")
    library = os.path.join(root, "roms")
    os.makedirs(inbox)
    os.makedirs(library)
    build_set(inbox)
    # The commonest half-transfer: one track never arrived. Moving what is here
    # would not make the game work and would make finding the rest harder, so
    # nothing moves -- unfiled and working beats filed and broken.
    os.remove(os.path.join(inbox, "Zed (Disc 2) (Track 02).bin"))

    found = discset.find_set(os.path.join(inbox, "Zed (Disc 1).cue"))
    playlist, _ = discset.write_playlist(inbox, found)
    check("the group cannot be worked out", romshelf.companions(playlist), None)
    filed = romshelf.file_rom(playlist, PS1, inbox, library)
    check("so the path comes back unchanged", filed, playlist)
    check("and nothing was moved", os.path.isdir(os.path.join(library, "ps1")), False)
    check("everything is still where it was", len(os.listdir(inbox)), 6)


section("a four-disc set with one track each -- the shape of Final Fantasy VIII")

with tempfile.TemporaryDirectory() as root:
    inbox = os.path.join(root, "transfer")
    library = os.path.join(root, "roms")
    os.makedirs(inbox)
    os.makedirs(library)
    build_set(inbox, discs=4, tracks=1)

    found = discset.find_set(os.path.join(inbox, "Zed (Disc 3).cue"))
    check("found from any disc, in order", found,
          ["Zed (Disc %d).cue" % n for n in (1, 2, 3, 4)])
    playlist, _ = discset.write_playlist(inbox, found)
    with open(playlist, "r", encoding="utf-8") as handle:
        check("and the playlist lists them in that order",
              handle.read().splitlines(), found)

    filed = romshelf.file_rom(playlist, PS1, inbox, library)
    check("nine files move together",
          len(os.listdir(os.path.join(library, "ps1"))), 9)
    check("with nothing left behind", os.listdir(inbox), [])
    romshelf.delete_rom(filed, library)
    check("and nine go back", os.path.isdir(os.path.join(library, "ps1")), False)


section("bare .bin discs -- Final Fantasy VIII as it actually arrived")

with tempfile.TemporaryDirectory() as root:
    inbox = os.path.join(root, "transfer")
    library = os.path.join(root, "roms")
    os.makedirs(inbox)
    os.makedirs(library)
    # No sheets at all: each disc is one raw track, which is right for a game
    # whose audio is streamed from the data track rather than held in CD-DA.
    for disc in range(1, 5):
        with open(os.path.join(inbox, "Zed (Disc %d).bin" % disc),
                  "w", encoding="utf-8") as handle:
            handle.write("x")

    found = discset.find_set(os.path.join(inbox, "Zed (Disc 1).bin"))
    check("four discs, no sheets needed", len(found), 4)
    playlist, _ = discset.write_playlist(inbox, found)
    filed = romshelf.file_rom(playlist, PS1, inbox, library)
    check("five files move", len(os.listdir(os.path.join(library, "ps1"))), 5)
    check("and the inbox empties", os.listdir(inbox), [])


section("filing only ever touches the top of the inbox")

with tempfile.TemporaryDirectory() as root:
    inbox = os.path.join(root, "transfer")
    library = os.path.join(root, "roms")
    nested = os.path.join(inbox, "somewhere")
    os.makedirs(nested)
    os.makedirs(library)
    build_set(nested)

    # Not a limitation of this feature -- `file_rom` has always worked this way,
    # and the reason is that a ROM the user keeps in a folder of their own is not
    # ours to rearrange. Written down here because a multi-disc set is exactly
    # the thing somebody puts in a folder of its own, and the behaviour reads as
    # a failure the first time it is met.
    found = discset.find_set(os.path.join(nested, "Zed (Disc 1).cue"))
    check("the set is still detected in a subfolder", len(found), 2)
    playlist, error = discset.write_playlist(nested, found)
    check("and the playlist is still written there", error, "")
    filed = romshelf.file_rom(playlist, PS1, inbox, library)
    check("but nothing is filed out of it", filed, playlist)
    check("and the library folder is not created",
          os.path.isdir(os.path.join(library, "ps1")), False)
